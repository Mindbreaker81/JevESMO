"""Pipeline generico JevESMO: recorre el arbol ESMO de cualquier tumor.

Flujo (identico para todos los tumores, lo que cambia es el spec JSON):
0. Normaliza la entrada y comprueba los datos imprescindibles. Si falta
   alguno, se detiene y devuelve las preguntas ("si no sabe algo, pregunta").
1-2. Capas de interpretacion: preguntas atomicas a Jev definidas en el spec.
   Sus respuestas quedan disponibles como `jev.<key>` para las reglas.
3. Opciones permitidas por ESMO (reglas deterministas) -> Jev elige la mas
   adecuada (Choice) y estima el beneficio (Score).
4. Seguridad: reglas del spec + reglas comunes; pueden bloquear opciones.
5. Gate de confianza: por debajo del umbral, revision humana obligatoria.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ..jev_client import Answer, JevClient, Question
from .conditions import evaluate, is_missing
from .spec import Campo, TumorSpec, get_spec

CONFIDENCE_THRESHOLD = 0.6


@dataclass
class LayerTrace:
    name: str
    questions: dict[str, Question]
    answers: dict[str, Answer]


# ------------------------------------------------------------------ entrada
def _coerce(c: Campo, v: Any) -> Any:
    if is_missing(v):
        return None
    if c.tipo == "number":
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return int(f) if f.is_integer() else f
    if c.tipo == "bool":
        if isinstance(v, bool):
            return v
        return {"si": True, "sí": True, "true": True, "yes": True, "no": False, "false": False}.get(str(v).strip().lower())
    if c.tipo == "choice":
        s = str(v)
        return s if s in {o.id for o in c.opciones} else None
    if c.tipo == "list":
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return [str(x) for x in v if str(x).strip()]
    return str(v)


def normalize(spec: TumorSpec, raw: dict[str, Any]) -> dict[str, Any]:
    return {c.id: _coerce(c, raw.get(c.id)) for c in spec.all_campos()}


def missing_required(spec: TumorSpec, data: dict[str, Any]) -> list[str]:
    preguntas = []
    for c in spec.all_campos():
        needed = c.requerido or (c.requerido_si is not None and evaluate(c.requerido_si, data))
        if needed and is_missing(data.get(c.id)):
            preguntas.append(c.pregunta or f"¿Cual es el valor de '{c.label}'?")
    return preguntas


def _fmt(c: Campo, v: Any) -> str:
    if v is None:
        return "no disponible / no testado"
    if isinstance(v, bool):
        return "si" if v else "no"
    if isinstance(v, list):
        return ", ".join(v) or "ninguno"
    if c.tipo == "choice":
        return next((o.label for o in c.opciones if o.id == v), str(v))
    return f"{v} {c.unidad}" if c.unidad else str(v)


def build_state(spec: TumorSpec, data: dict[str, Any], derived: dict[str, Any], interp: dict[str, Any]) -> str:
    lines = [f"Tumor: {spec.nombre}."]
    for c in spec.all_campos():
        if c.id == "descripcion_libre":
            continue
        lines.append(f"{c.label}: {_fmt(c, data.get(c.id))}.")
    for d in spec.derivados:
        lines.append(f"{d.label} (derivado): {derived.get(d.id) or 'no determinable'}.")
    if data.get("descripcion_libre"):
        lines.append(f"Notas clinicas: {data['descripcion_libre']}")
    if interp:
        lines.append("Valoraciones clinicas previas: " + "; ".join(f"{k} = {v}" for k, v in interp.items()) + ".")
    return "\n".join(lines)


# ------------------------------------------------------------------ helpers
def _ask(client: JevClient, state: str, questions: dict[str, Question]) -> dict[str, Answer]:
    return client.system_one(state, questions).answers if questions else {}


def _value(a: Answer) -> Any:
    return a.choice if a.choice is not None else (a.score if a.score is not None else a.noul)


def _derive(spec: TumorSpec, ctx: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for d in spec.derivados:
        out[d.id] = next((r.valor for r in d.reglas if evaluate(r.cuando, {**ctx, **out})), d.defecto)
    return out


# ------------------------------------------------------------------ pipeline
def run(tumor_id: str, raw: dict[str, Any], client: Optional[JevClient] = None) -> dict[str, Any]:
    spec = get_spec(tumor_id)
    data = normalize(spec, raw)
    base = {"tumor": spec.id, "tumor_nombre": spec.nombre, "grupo": spec.grupo, "esmo_tree_version": spec.version}

    faltan = missing_required(spec, data)
    if faltan:
        return {**base, "status": "necesita_datos", "preguntas": faltan}

    client = client or JevClient()
    ctx: dict[str, Any] = dict(data)
    derived = _derive(spec, ctx)
    ctx.update(derived)
    traces: list[LayerTrace] = []
    interp: dict[str, Any] = {}

    for capa, name in ((1, "Capa 1 - Interpretacion clinica"), (2, "Capa 2 - Biomarcadores y riesgo")):
        qs = {
            q.key: Question(q.key, q.tipo, q.instrucciones, q.criterios)
            for q in spec.preguntas if q.capa == capa and evaluate(q.cuando, ctx)
        }
        ans = _ask(client, build_state(spec, data, derived, interp), qs)
        for k, a in ans.items():
            ctx[f"jev.{k}"] = _value(a)
            interp[k] = _value(a) if a.type != "noul" else f"{_value(a):.2f} (probabilidad)"
        traces.append(LayerTrace(name, qs, ans))
        derived = _derive(spec, ctx)  # los derivados pueden depender de jev.*
        ctx.update(derived)

    state = build_state(spec, data, derived, interp)
    candidatos = [o for o in spec.opciones if evaluate(o.cuando, ctx)]
    avisos = [a.texto for a in spec.avisos if evaluate(a.cuando, ctx)]

    # Capa 3: eleccion entre opciones ESMO validas
    qs3: dict[str, Question] = {}
    if candidatos:
        qs3 = {
            "mejor_opcion": Question(
                "mejor_opcion", "choice",
                "Entre las opciones de tratamiento permitidas por la guia ESMO para este paciente, "
                "¿cual es la mas adecuada dado el contexto clinico completo?",
                {o.id: f"{o.label} — {o.nota}" for o in candidatos},
            ),
            "beneficio_esperado": Question(
                "beneficio_esperado", "score",
                "Beneficio clinico esperado de la opcion mas adecuada para este paciente",
                ["Bajo", "Moderado", "Alto"],
            ),
        }
    ans3 = _ask(client, state, qs3)
    traces.append(LayerTrace("Capa 3 - Eleccion de tratamiento (ESMO)", qs3, ans3))

    # Capa 4: seguridad
    cand_ids = {o.id for o in candidatos}
    cand_comp = {c for o in candidatos for c in o.componentes}
    reglas = [
        s for s in spec.seguridad
        if evaluate(s.cuando, ctx) and (set(s.bloquea) & cand_ids or set(s.bloquea_componentes) & cand_comp
                                        or not (s.bloquea or s.bloquea_componentes))
    ]
    qs4 = {s.key: Question(s.key, "noul", s.instrucciones) for s in reglas}
    if candidatos and (data.get("insuficiencia_renal") or data.get("insuficiencia_hepatica")):
        qs4["ajuste_dosis"] = Question(
            "ajuste_dosis", "noul",
            "Dada la insuficiencia renal/hepatica del paciente, ¿es necesario un ajuste de dosis o cambio "
            "de esquema que limite las opciones disponibles?",
        )
    if candidatos and data.get("ecog") in ("3", "4"):
        qs4["candidato_tratamiento_activo"] = Question(
            "candidato_tratamiento_activo", "noul",
            "Con este estado funcional, comorbilidades y situacion oncologica, ¿es el paciente candidato a "
            "tratamiento oncologico activo (frente a tratamiento de soporte exclusivo)?",
        )
    ans4 = _ask(client, state, qs4)
    traces.append(LayerTrace("Capa 4 - Seguridad y contraindicaciones", qs4, ans4))

    bloqueos: dict[str, str] = {}
    for s in reglas:
        a = ans4.get(s.key)
        if a is not None and a.noul is not None and a.noul >= s.umbral:
            for o in candidatos:
                if o.id in s.bloquea or set(o.componentes) & set(s.bloquea_componentes):
                    bloqueos.setdefault(o.id, s.motivo)

    fitness = ans4.get("candidato_tratamiento_activo")
    no_fit = fitness is not None and fitness.noul is not None and fitness.noul < 0.5
    if no_fit:
        avisos.append("Jev considera que el paciente probablemente NO es candidato a tratamiento activo: valorar soporte exclusivo.")

    probs = (ans3.get("mejor_opcion").probabilities or {}) if "mejor_opcion" in ans3 else {}
    ranked = sorted(candidatos, key=lambda o: -float(probs.get(o.id, 0) or 0))
    lista = [
        {
            "id": o.id, "label": o.label, "esmo_note": o.nota, "evidencia": o.evidencia,
            "componentes": o.componentes, "probabilidad": probs.get(o.id),
            "contraindicado": o.id in bloqueos, "motivo_contraindicacion": bloqueos.get(o.id),
        }
        for o in ranked
    ]

    elegido_id = ans3["mejor_opcion"].choice if "mejor_opcion" in ans3 else None
    confianza = ans3["mejor_opcion"].confidence if "mejor_opcion" in ans3 else None
    rec = next((c for c in lista if c["id"] == elegido_id), None)
    if rec and rec["contraindicado"]:
        avisos.append(f"La opcion preferida ('{rec['label']}') se descarto por seguridad: {rec['motivo_contraindicacion']}.")
        rec = next((c for c in lista if not c["contraindicado"]), None)
        confianza = min(float(rec["probabilidad"] or 0), 0.3) if rec else 0.0
    if not candidatos:
        avisos.append("Ninguna opcion del arbol ESMO aplica a esta combinacion de datos: caso fuera del arbol.")

    requiere_revision = rec is None or confianza is None or confianza < CONFIDENCE_THRESHOLD or no_fit

    explicabilidad = [
        {
            "capa": t.name,
            "preguntas": {k: {"tipo": q.type, "instrucciones": q.instructions} for k, q in t.questions.items()},
            "respuestas": {
                k: {"valor": _value(a), "confianza": a.confidence, "probabilidades": a.probabilities, "simulado": a.mock}
                for k, a in t.answers.items()
            },
        }
        for t in traces
    ]
    derived_labels = {d.label: derived.get(d.id) for d in spec.derivados}
    return {
        **base,
        "status": "ok",
        "derivados": derived_labels,
        "subtipo": " · ".join(str(v) for v in derived_labels.values() if v) or spec.nombre,
        "candidatos": lista,
        "recomendacion_principal": rec,
        "confianza": confianza,
        "requiere_revision_humana": requiere_revision,
        "avisos_datos_faltantes": avisos,
        "explicabilidad": explicabilidad,
    }
