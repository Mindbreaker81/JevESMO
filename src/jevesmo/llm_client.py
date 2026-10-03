"""Backend LLM alternativo (opt-in) via system-one-adapter (JES-4).

Implementa la misma frontera que `JevClient` (`system_one(state, questions)`)
traduciendo las preguntas al formato del adaptador, que a su vez llama a
OpenAI/Anthropic/Gemini o a un endpoint OpenAI-compatible (Ollama, vLLM...).

Garantias de seguridad:
- NUNCA se selecciona en silencio: solo `JEVESMO_BACKEND` distinto de "jev".
- Todo caso evaluado con este backend lleva el motivo permanente
  `backend_alternativo` (revision humana obligatoria), porque es un backend
  no validado clinicamente. Ver engine/pipeline.py.
- Los resultados guardan `backend` + modelo resuelto en el manifiesto.

Configuracion por entorno:
    JEVESMO_BACKEND=llm|openai|anthropic|gemini
    JEVESMO_LLM_MODEL          (obligatorio con backend llm)
    JEVESMO_LLM_PROVIDER       (openai|anthropic|gemini; default openai)
    JEVESMO_LLM_BASE_URL       (endpoint OpenAI-compatible; opcional)
    JEVESMO_LLM_API_KEY        (si el SDK nativo no la resuelve ya)
    JEVESMO_LLM_ANSWER_MODE    (probabilities|discrete; default probabilities)
    JEVESMO_LLM_STRUCTURED     (0|1; default 1 = salida estructurada nativa)

Nota del banco (JEV-32): un revisor no-Jev NO hereda la alerta de manipulacion
de Jev — si se usa este backend, la capa 4.5 la ejecuta tambien el LLM
alternativo y su calidad debe medirse con la bateria adversarial propia.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .jev_client import Answer, Question, SystemOneResponse

_PROVIDERS = ("openai", "anthropic", "gemini")


class LlmClient:
    """Cliente compatible con `JevClient` que delega en system-one-adapter."""

    def __init__(self, model: Optional[str] = None, provider: Optional[str] = None,
                 base_url: Optional[str] = None, api_key: Optional[str] = None,
                 answer_mode: Optional[str] = None) -> None:
        try:
            from system_one_adapter import SystemOneAdapterClient  # type: ignore
        except ImportError as exc:
            # Hay backend alternativo configurado pero el adaptador no esta: fallar
            # explicitamente, no degradar en silencio a mock ni a otro backend.
            raise RuntimeError(
                "Backend LLM seleccionado pero 'system-one-adapter' no esta instalado. "
                "Instalalo (pip install system-one-adapter) o vuelve a JEVESMO_BACKEND=jev."
            ) from exc
        self.model = model or os.environ.get("JEVESMO_LLM_MODEL")
        if not self.model:
            raise RuntimeError("Backend LLM seleccionado pero falta JEVESMO_LLM_MODEL.")
        self.provider = (provider or os.environ.get("JEVESMO_LLM_PROVIDER") or "openai").lower()
        if self.provider not in _PROVIDERS:
            raise RuntimeError(f"JEVESMO_LLM_PROVIDER={self.provider!r} no soportado: {_PROVIDERS}")
        self.base_url = base_url or os.environ.get("JEVESMO_LLM_BASE_URL")
        self.api_key = api_key or os.environ.get("JEVESMO_LLM_API_KEY")
        self.answer_mode = (answer_mode or os.environ.get("JEVESMO_LLM_ANSWER_MODE")
                            or "probabilities").lower()
        if self.answer_mode not in ("probabilities", "discrete"):
            raise RuntimeError("JEVESMO_LLM_ANSWER_MODE debe ser 'probabilities' o 'discrete'.")
        structured = os.environ.get("JEVESMO_LLM_STRUCTURED", "1").strip().lower() not in ("0", "no", "false")
        self._mock_mode = False
        self.backend = f"llm:{self.provider}"

        # El adaptador acepta un provider ya construido como `model`: lo usamos cuando
        # hay base_url/api_key explicitos (endpoint OpenAI-compatible). Sin ellos el
        # SDK del proveedor resuelve las credenciales por sus propias env vars.
        provider_obj: Optional[Any] = None
        if self.provider == "openai" and (self.base_url or self.api_key):
            from system_one_adapter.providers.openai import OpenAIProvider  # type: ignore

            provider_obj = OpenAIProvider(self.model, base_url=self.base_url, api_key=self.api_key)
        self._adapter = SystemOneAdapterClient(
            structured_outputs=structured,
            llm_answer_mode=self.answer_mode,
            normalize_probabilities=True,
            n_retry_malformed_structure=1,
            provider=None if provider_obj else self.provider,
            model=provider_obj or self.model,
        )

    @property
    def is_mock(self) -> bool:
        return self._mock_mode

    def system_one(self, state: str, questions: dict[str, Question]) -> SystemOneResponse:
        from system_one_adapter import Choice, Noul, Score  # type: ignore

        # El adaptador exige >=2 criterios en choice/score (Jev tolera 1). Las
        # preguntas degeneradas no se envian al modelo:
        # - choice con 1 criterio: la respuesta es forzosa -> se resuelve en
        #   local con confianza ausente (no es una decision del modelo).
        # - choice/score con <2 criterios: sin respuesta (confianza ausente ->
        #   revision), mejor que fabricar un numero que el modelo no dio.
        mapped: dict[str, Any] = {}
        answers: dict[str, Answer] = {}
        for key, q in questions.items():
            if q.type == "choice":
                crit = q.criteria or {}
                if len(crit) >= 2:
                    mapped[key] = Choice(type="choice", instructions=q.instructions, criteria=crit)
                elif len(crit) == 1:
                    only = next(iter(crit))
                    answers[key] = Answer(type="choice", choice=only, probabilities={only: 1.0})
            elif q.type == "score":
                if q.criteria and len(q.criteria) >= 2:
                    mapped[key] = Score(type="score", instructions=q.instructions, criteria=q.criteria)
            else:
                mapped[key] = Noul(type="noul", instructions=q.instructions)
        model = self.model
        if mapped:
            resp = self._adapter.system_one(state, mapped)
            model = resp.model or self.model
            for key, a in (resp.answers or {}).items():
                answers[key] = Answer(
                    type=questions[key].type if key in questions else getattr(a, "type", "noul"),
                    choice=getattr(a, "choice", None),
                    score=getattr(a, "score", None),
                    noul=getattr(a, "noul", None),
                    confidence=getattr(a, "confidence", None),
                    probabilities=getattr(a, "probabilities", None),
                    mock=False,
                )
        return SystemOneResponse(model=model, answers=answers)
