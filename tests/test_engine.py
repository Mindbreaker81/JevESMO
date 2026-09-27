"""Regresiones de la revision adversaria: seguridad, datos ausentes y logica trivalente."""
import pytest

from jevesmo.engine.conditions import evaluate
from jevesmo.engine.pipeline import run
from jevesmo.engine.spec import load_all
from jevesmo.jev_client import JevClient


class FakeClient(JevClient):
    """Usa las respuestas simuladas pero se presenta como cliente real; puede omitir respuestas."""

    def __init__(self, drop=lambda key: False):
        super().__init__(api_key=None)
        self._mock_mode = True
        self._drop = drop

    @property
    def is_mock(self) -> bool:
        return False

    def system_one(self, state, questions):
        resp = self._mock_system_one(state, questions)
        resp.answers = {k: v for k, v in resp.answers.items() if not self._drop(k)}
        return resp


def mock():
    c = JevClient(api_key=None)
    c._mock_mode = True
    return c


HER2_IV = {
    "edad": 68, "sexo": "mujer", "estadio": "IV", "tipo_histologico": "ductal_invasivo", "ecog": "1",
    "premenopausica": False, "her2": "positivo", "re": "negativo", "rp": "negativo",
    "fraccion_eyeccion_ventricular": 60, "lineas_previas": 0, "tratamientos_previos": [],
    "comorbilidades_relevantes": [],
}


def codes(res):
    return {m["codigo"] for m in res.get("motivos_revision") or []}


def test_ne_nin_false_on_missing():
    assert evaluate({"campo": "x", "ne": "a"}, {}) is False
    assert evaluate({"campo": "x", "nin": ["a"]}, {}) is False
    assert evaluate({"campo": "x", "ne": "a"}, {"x": "b"}) is True


def test_hard_block_low_lvef():
    res = run("mama", {**HER2_IV, "fraccion_eyeccion_ventricular": 35}, client=FakeClient())
    assert res["status"] != "necesita_datos"
    blocked = [c for c in res["candidatos"] if c["contraindicado"]]
    assert blocked, "FEVI 35% debe bloquear anti-HER2"
    assert any(s["tipo"] == "duro" and s["bloquea"] for s in res["seguridad"])
    rec = res["recomendacion_principal"]
    assert rec is None or rec["id"] not in {c["id"] for c in blocked}
    assert res["requiere_revision_humana"]


def test_missing_lvef_asks_for_data():
    raw = {k: v for k, v in HER2_IV.items() if k != "fraccion_eyeccion_ventricular"}
    res = run("mama", raw, client=FakeClient())
    assert res["status"] == "necesita_datos"


def test_safety_fails_closed_when_answer_missing():
    raw = {**HER2_IV, "fraccion_eyeccion_ventricular": 52}  # franja de riesgo -> regla tipo jev
    res = run("mama", raw, client=FakeClient(drop=lambda k: k.startswith("seg_") or "riesgo_cardiaco" in k))
    assert "seguridad_sin_respuesta" in codes(res)
    assert res["requiere_revision_humana"]


def test_out_of_range_value_requests_data():
    res = run("mama", {**HER2_IV, "edad": 400}, client=FakeClient())
    assert res["status"] == "necesita_datos"


def test_missing_prior_lines_flags_critical():
    raw = {k: v for k, v in HER2_IV.items() if k != "lineas_previas"}
    res = run("mama", raw, client=FakeClient())
    if res["status"] != "necesita_datos":
        assert "datos_criticos_ausentes" in codes(res)


def test_mock_mode_always_requires_review():
    res = run("mama", HER2_IV, client=mock())
    assert "modo_simulado" in codes(res)
    assert res["requiere_revision_humana"]


def test_unknown_tumor_raises():
    with pytest.raises(KeyError):
        run("tumor_inexistente", {}, client=mock())


@pytest.mark.parametrize("spec", list(load_all().values()), ids=lambda s: s.id)
def test_vignettes_preferred_option_is_candidate(spec):
    for v in spec.vinetas:
        if v.esperado.tipo != "recomendacion" or not v.esperado.preferida:
            continue
        res = run(spec.id, v.payload, client=mock())
        if res["status"] == "necesita_datos":
            continue
        ids = {c["id"] for c in res["candidatos"]}
        assert v.esperado.preferida in ids, f"{spec.id}/{v.id}"
