"""Esquema de las especificaciones de tumor (src/jevesmo/tumors/*.json).

Cada tumor es un JSON auto-contenido y auditable con:
- campos clinicos especificos (ademas de los comunes a todos los tumores),
- derivados (p.ej. subtipo molecular) calculados con reglas deterministas,
- opciones de tratamiento permitidas por ESMO, cada una con su condicion,
- preguntas a Jev (capas 1-2) para juicio clinico sobre el caso,
- reglas de seguridad (capa 4) que pueden bloquear opciones,
- avisos por datos que mejorarian la decision,
- viñetas de referencia para la evaluacion.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from .conditions import referenced_fields

TUMORS_DIR = Path(__file__).resolve().parents[1] / "tumors"

Cond = Any  # ver conditions.py


class ChoiceOption(BaseModel):
    id: str
    label: str


class Campo(BaseModel):
    id: str
    label: str
    tipo: Literal["choice", "bool", "number", "text", "list"]
    seccion: str = "Tumor"
    opciones: list[ChoiceOption] = Field(default_factory=list)
    min: Optional[float] = None
    max: Optional[float] = None
    unidad: Optional[str] = None
    requerido: bool = False
    requerido_si: Optional[Cond] = None
    pregunta: Optional[str] = None
    ayuda: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _opciones_str(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("opciones"):
            data["opciones"] = [
                {"id": o, "label": o} if isinstance(o, str) else o for o in data["opciones"]
            ]
        return data

    @model_validator(mode="after")
    def _check(self) -> "Campo":
        if self.tipo == "choice" and not self.opciones:
            raise ValueError(f"Campo choice '{self.id}' sin opciones")
        return self


class ReglaDerivado(BaseModel):
    cuando: Cond = None
    valor: Any


class Derivado(BaseModel):
    id: str
    label: str
    reglas: list[ReglaDerivado]
    defecto: Any = None


class Opcion(BaseModel):
    id: str
    label: str
    nota: str
    cuando: Cond = None
    componentes: list[str] = Field(default_factory=list)
    evidencia: Optional[str] = None


class PreguntaJev(BaseModel):
    key: str
    tipo: Literal["choice", "score", "noul"]
    instrucciones: str
    criterios: Optional[Union[dict[str, str], list[str]]] = None
    cuando: Cond = None
    capa: Literal[1, 2] = 1

    @model_validator(mode="after")
    def _check(self) -> "PreguntaJev":
        if self.tipo == "choice" and not isinstance(self.criterios, dict):
            raise ValueError(f"Pregunta choice '{self.key}' necesita criterios dict")
        if self.tipo == "score" and not isinstance(self.criterios, list):
            raise ValueError(f"Pregunta score '{self.key}' necesita criterios lista")
        return self


class Seguridad(BaseModel):
    """Regla de seguridad (capa 4).

    tipo:
      - "duro": contraindicacion explicita -> bloqueo determinista, sin preguntar a Jev.
      - "jev" (defecto): contraindicacion relativa. Jev estima si aplica al caso; bloquea si
        noul >= umbral. Falla cerrado: sin respuesta valida o en zona dudosa -> revision obligatoria.
      - "revision": nunca bloquea, pero obliga a revision por especialista si se activa.
    """

    key: str
    instrucciones: str = ""
    tipo: Literal["jev", "duro", "revision"] = "jev"
    cuando: Cond = None
    bloquea: list[str] = Field(default_factory=list, description="ids de opcion")
    bloquea_componentes: list[str] = Field(default_factory=list)
    umbral: float = 0.5
    motivo: str


class Aviso(BaseModel):
    cuando: Cond = None
    texto: str


class Esperado(BaseModel):
    tipo: Literal["recomendacion", "revision_humana", "necesita_datos"]
    preferida: Optional[str] = None
    aceptables: list[str] = Field(default_factory=list)


class Vineta(BaseModel):
    id: str
    titulo: str
    fuente: str
    payload: dict[str, Any]
    esperado: Esperado


class Guia(BaseModel):
    titulo: str
    anio: Optional[int] = None
    url: Optional[str] = None


class TumorSpec(BaseModel):
    id: str
    nombre: str
    grupo: str
    version: str
    guias: list[Guia]
    descripcion: str = ""
    campos: list[Campo]
    derivados: list[Derivado] = Field(default_factory=list)
    opciones: list[Opcion]
    preguntas: list[PreguntaJev] = Field(default_factory=list)
    seguridad: list[Seguridad] = Field(default_factory=list)
    avisos: list[Aviso] = Field(default_factory=list)
    vinetas: list[Vineta] = Field(default_factory=list)

    def all_campos(self) -> list[Campo]:
        return COMMON_FIELDS + self.campos

    def campo(self, cid: str) -> Optional[Campo]:
        return next((c for c in self.all_campos() if c.id == cid), None)


# Campos comunes a todos los tumores. Los specs NO deben redefinirlos.
COMMON_FIELDS: list[Campo] = [
    Campo(id="edad", label="Edad", tipo="number", seccion="Paciente", min=0, max=120, unidad="anios",
          requerido=True, pregunta="¿Cual es la edad del paciente?"),
    Campo(id="sexo", label="Sexo", tipo="choice", seccion="Paciente",
          opciones=[ChoiceOption(id="mujer", label="mujer"), ChoiceOption(id="hombre", label="hombre")]),
    Campo(id="ecog", label="ECOG performance status", tipo="choice", seccion="Paciente",
          opciones=[ChoiceOption(id=str(i), label=str(i)) for i in range(5)],
          requerido=True, pregunta="¿Cual es el ECOG performance status del paciente (0-4)?"),
    Campo(id="insuficiencia_renal", label="Insuficiencia renal", tipo="bool", seccion="Seguridad"),
    Campo(id="insuficiencia_hepatica", label="Insuficiencia hepatica", tipo="bool", seccion="Seguridad"),
    Campo(id="comorbilidades_relevantes", label="Comorbilidades relevantes", tipo="list", seccion="Seguridad"),
    Campo(id="lineas_previas", label="Lineas previas de tratamiento sistemico en enfermedad avanzada",
          tipo="number", seccion="Historial", min=0, max=15),
    Campo(id="tratamientos_previos", label="Tratamientos previos", tipo="list", seccion="Historial"),
    Campo(id="descripcion_libre", label="Notas clinicas (texto libre)", tipo="text", seccion="Notas"),
]
COMMON_IDS = {c.id for c in COMMON_FIELDS}


def validate_spec(spec: TumorSpec) -> list[str]:
    """Comprobaciones de integridad referencial. Devuelve la lista de errores."""
    errs: list[str] = []
    ids = [c.id for c in spec.campos]
    if dup := {i for i in ids if ids.count(i) > 1}:
        errs.append(f"campos duplicados: {dup}")
    if clash := set(ids) & COMMON_IDS:
        errs.append(f"campos que redefinen campos comunes: {clash}")
    known = COMMON_IDS | set(ids) | {d.id for d in spec.derivados} | {f"jev.{q.key}" for q in spec.preguntas}
    opt_ids = [o.id for o in spec.opciones]
    if dup := {i for i in opt_ids if opt_ids.count(i) > 1}:
        errs.append(f"opciones duplicadas: {dup}")

    def chk(where: str, cond: Any) -> None:
        try:
            for f in referenced_fields(cond):
                if f not in known:
                    errs.append(f"{where}: campo desconocido '{f}'")
        except ValueError as ex:
            errs.append(f"{where}: {ex}")

    for c in spec.campos:
        chk(f"campo {c.id}.requerido_si", c.requerido_si)
        if (c.requerido or c.requerido_si) and not c.pregunta:
            errs.append(f"campo {c.id} requerido sin 'pregunta'")
    for d in spec.derivados:
        for r in d.reglas:
            chk(f"derivado {d.id}", r.cuando)
    for o in spec.opciones:
        chk(f"opcion {o.id}", o.cuando)
    for q in spec.preguntas:
        chk(f"pregunta {q.key}", q.cuando)
    for s in spec.seguridad:
        chk(f"seguridad {s.key}", s.cuando)
        for b in s.bloquea:
            if b not in opt_ids:
                errs.append(f"seguridad {s.key}: bloquea opcion inexistente '{b}'")
        if s.tipo == "jev" and not s.instrucciones:
            errs.append(f"seguridad {s.key}: tipo 'jev' sin instrucciones")
    for a in spec.avisos:
        chk("aviso", a.cuando)

    # Coherencia texto <-> regla: si la etiqueta/nota exige linea previa, la regla debe comprobarlo.
    import re
    linea_re = re.compile(r"(\b[2-9]\s?[aª]?\s?l(inea|ínea)?\b|\b[2-9]L\b|segunda l|tercera l|tras progres|post-?progres|>=\s?1 l)", re.I)
    for o in spec.opciones:
        refs = set(referenced_fields(o.cuando))
        if linea_re.search(o.label) and not any(
                r in ("lineas_previas", "tratamientos_previos") or "situacion" in r or "linea" in r or "recaida" in r
                for r in refs):
            errs.append(f"opcion {o.id}: la etiqueta indica linea >=2 pero 'cuando' no comprueba lineas_previas/tratamientos_previos")

    vids = [v.id for v in spec.vinetas]
    if dup := {i for i in vids if vids.count(i) > 1}:
        errs.append(f"viñetas duplicadas: {dup}")
    field_ids = COMMON_IDS | set(ids)
    for v in spec.vinetas:
        if extra := set(v.payload) - field_ids:
            errs.append(f"viñeta {v.id}: campos desconocidos {extra}")
        for f, val in v.payload.items():
            c = spec.campo(f)
            if c and c.tipo == "choice" and val is not None and val not in {o.id for o in c.opciones}:
                errs.append(f"viñeta {v.id}: valor '{val}' no valido para {f}")
        e = v.esperado
        if e.tipo == "recomendacion":
            if not e.preferida or e.preferida not in opt_ids:
                errs.append(f"viñeta {v.id}: preferida '{e.preferida}' no es una opcion")
            for a in e.aceptables:
                if a not in opt_ids:
                    errs.append(f"viñeta {v.id}: aceptable '{a}' no es una opcion")
            if e.preferida and e.preferida not in e.aceptables:
                errs.append(f"viñeta {v.id}: la preferida debe estar en aceptables")
    return errs


def load_spec_file(path: Path) -> TumorSpec:
    return TumorSpec.model_validate(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def load_all() -> dict[str, TumorSpec]:
    specs = {}
    for p in sorted(TUMORS_DIR.glob("*.json")):
        s = load_spec_file(p)
        specs[s.id] = s
    return specs


def get_spec(tumor_id: str) -> TumorSpec:
    return load_all()[tumor_id]
