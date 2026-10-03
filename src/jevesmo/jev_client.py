"""Cliente de Jev (TypeSafe AI System One) con fallback a modo mock.

En produccion, este modulo delega en el SDK oficial `typesafe_sdk`
(https://docs.typesafe.ai). Como durante el desarrollo no siempre hay una
TYPESAFE_API_KEY disponible (y los datos clinicos no deben salir del entorno
sin control), se ofrece un modo "mock" deterministico que permite construir y
probar todo el pipeline de capas sin depender de la red.

El modo se selecciona automaticamente:
- Si existe TYPESAFE_API_KEY -> modo real (usa typesafe_sdk).
- Si no -> modo mock (respuestas heuristicas, marcadas explicitamente como
  no reales en el campo `mock=True` de cada respuesta).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

QuestionType = Literal["choice", "score", "noul"]


@dataclass
class Question:
    """Una pregunta atomica que se envia a Jev junto al `state`."""

    key: str
    type: QuestionType
    instructions: str
    criteria: Optional[Any] = None  # dict para choice, list para score, None para noul


@dataclass
class Answer:
    type: QuestionType
    choice: Optional[str] = None
    score: Optional[float] = None
    noul: Optional[float] = None
    confidence: Optional[float] = None
    probabilities: Optional[dict] = None
    mock: bool = False


@dataclass
class SystemOneResponse:
    model: str
    answers: dict[str, Answer] = field(default_factory=dict)


class JevClient:
    """Envuelve la llamada a Jev: `system_one(state, questions) -> respuestas tipadas`."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY")
        # Modelo solicitado (puede ser un alias flotante como "jev-latest"). La version que
        # realmente responde viene en SystemOneResponse.model y se registra en la traza.
        self.model = model or os.environ.get("JEV_MODEL") or "jev-latest"
        self.backend = "typesafe"
        self._mock_mode = not bool(self.api_key)
        self._sdk_client = None
        if not self._mock_mode:
            try:
                from typesafe_sdk import TypeSafeClient  # type: ignore

                self._sdk_client = TypeSafeClient(api_key=self.api_key)
            except ImportError as exc:
                # Hay clave pero no SDK: fallar explicitamente. Degradar en silencio a respuestas
                # simuladas cambiaria el comportamiento clinico sin que el usuario lo sepa.
                raise RuntimeError(
                    "TYPESAFE_API_KEY configurada pero el paquete 'typesafe-sdk' no esta instalado. "
                    "Instalalo (pip install typesafe-sdk) o elimina la clave para usar el modo simulado."
                ) from exc

    @property
    def is_mock(self) -> bool:
        return self._mock_mode

    def system_one(self, state: str, questions: dict[str, Question]) -> SystemOneResponse:
        if self._mock_mode:
            return self._mock_system_one(state, questions)
        return self._real_system_one(state, questions)

    # -- Real ---------------------------------------------------------
    def _real_system_one(self, state: str, questions: dict[str, Question]) -> SystemOneResponse:
        from typesafe_sdk import Choice, Noul, Score  # type: ignore

        sdk_questions = {}
        for key, q in questions.items():
            if q.type == "choice":
                sdk_questions[key] = Choice(instructions=q.instructions, criteria=q.criteria)
            elif q.type == "score":
                sdk_questions[key] = Score(instructions=q.instructions, criteria=q.criteria)
            else:
                sdk_questions[key] = Noul(instructions=q.instructions)

        raw = self._sdk_client.system_one(state=state, questions=sdk_questions, model=self.model)  # type: ignore
        answers = {}
        for key, a in raw.answers.items():
            answers[key] = Answer(
                type=a.type,
                choice=getattr(a, "choice", None),
                score=getattr(a, "score", None),
                noul=getattr(a, "noul", None),
                confidence=getattr(a, "confidence", None),
                probabilities=getattr(a, "probabilities", None),
                mock=False,
            )
        return SystemOneResponse(model=raw.model, answers=answers)

    # -- Mock -----------------------------------------------------------
    def _mock_system_one(self, state: str, questions: dict[str, Question]) -> SystemOneResponse:
        """Genera respuestas deterministicas (hash-based) para desarrollo/tests.

        IMPORTANTE: esto NO es una simulacion clinica valida. Solo permite
        ejercitar el pipeline (orquestacion de capas, logging, ranking) sin
        una API key real. Nunca usar estas respuestas para decisiones reales.
        """
        answers: dict[str, Answer] = {}
        for key, q in questions.items():
            seed = int(hashlib.sha256(f"{state}|{key}|{q.instructions}".encode()).hexdigest(), 16)
            if q.type == "noul":
                val = (seed % 100) / 100.0
                answers[key] = Answer(type="noul", noul=round(val, 2), mock=True)
            elif q.type == "score":
                n = len(q.criteria) if q.criteria else 3
                idx = seed % n
                probs = {str(i): (1.0 if i == idx else 0.0) for i in range(n)}
                answers[key] = Answer(
                    type="score",
                    score=float(idx),
                    confidence=0.5,
                    probabilities=probs,
                    mock=True,
                )
            else:  # choice
                options = list(q.criteria.keys()) if isinstance(q.criteria, dict) else []
                if not options:
                    options = ["opcion_a"]
                idx = seed % len(options)
                probs = {opt: (1.0 if i == idx else 0.0) for i, opt in enumerate(options)}
                answers[key] = Answer(
                    type="choice",
                    choice=options[idx],
                    confidence=0.5,
                    probabilities=probs,
                    mock=True,
                )
        return SystemOneResponse(model=f"{self.model}-mock", answers=answers)


def make_client(api_key: Optional[str] = None, model: Optional[str] = None):
    """Cliente segun JEVESMO_BACKEND:

    - "jev" (default) -> JevClient (real si hay TYPESAFE_API_KEY, mock si no).
    - "llm" o un proveedor ("openai"|"anthropic"|"gemini") -> LlmClient via
      system-one-adapter. NUNCA es un fallback silencioso: exige opt-in
      explicito y cada caso queda marcado con el motivo `backend_alternativo`.
    """
    backend = os.environ.get("JEVESMO_BACKEND", "jev").strip().lower()
    if backend == "jev":
        return JevClient(api_key=api_key, model=model)
    # Lista blanca estricta: un valor vacio o mal escrito no puede activar el backend LLM.
    if backend not in ("llm", "openai", "anthropic", "gemini"):
        raise RuntimeError(
            f"JEVESMO_BACKEND={backend!r} no valido: usa 'jev' (default) o 'llm'|'openai'|'anthropic'|'gemini'. "
            "Si no quieres el backend alternativo, borra la variable.")
    from .llm_client import LlmClient  # import perezoso: dependencia opcional
    provider = backend if backend != "llm" else None
    return LlmClient(provider=provider, model=model)
