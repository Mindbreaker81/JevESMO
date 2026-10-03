"""Estadistica de evaluacion (JES-5): Wilson, McNemar, Brier/ECE, comparador
pareado y reintento de filas con error."""
import json

import pytest

from jevesmo.evaluation.compare import compare_rows, metric_value
from jevesmo.evaluation.runner import _kept_rows, _run_meta, _summary, evaluate_tumor
from jevesmo.evaluation.stats import (
    brier_score, expected_calibration_error, mcnemar_exact_p, wilson_ci,
)
from jevesmo.jev_client import JevClient


def mock():
    c = JevClient(api_key=None)
    c._mock_mode = True
    return c


def test_wilson_bounds():
    ci = wilson_ci(48, 50)
    assert ci["n"] == 50 and ci["aciertos"] == 48
    assert 0.0 <= ci["lo"] < ci["estimado"] < ci["hi"] <= 1.0
    assert ci["estimado"] == pytest.approx(0.96)
    assert wilson_ci(0, 0) is None


def test_mcnemar_exact():
    assert mcnemar_exact_p(0, 0) is None
    assert mcnemar_exact_p(5, 5) == 1.0
    assert mcnemar_exact_p(10, 0) < 0.01


def test_brier_and_ece():
    assert brier_score([(1.0, True), (0.0, False)]) == 0.0
    assert brier_score([(0.5, True), (0.5, False)]) == pytest.approx(0.25)
    assert brier_score([]) is None
    assert expected_calibration_error([(1.0, True), (0.0, False)]) == pytest.approx(0.0)
    assert expected_calibration_error([(0.9, True)]) == pytest.approx(0.1)
    assert expected_calibration_error([(0.9, False)]) == pytest.approx(0.9)
    assert expected_calibration_error([]) is None


def test_compare_rows_pairs_on_key():
    a = [{"id": "1", "acierto": True}, {"id": "2", "acierto": False},
         {"id": "3", "acierto": True}, {"id": "4", "acierto": True}]
    b = [{"id": "1", "acierto": True}, {"id": "2", "acierto": True},
         {"id": "3", "acierto": False}, {"id": "9", "acierto": True}]
    res = compare_rows(a, b, key="id")
    assert res["pareados"] == 3
    assert res["solo_en_a"] == 1 and res["solo_en_b"] == 1
    assert res["solo_acierta_a"] == 1 and res["solo_acierta_b"] == 1
    assert res["aciertos_a"] == 2 and res["aciertos_b"] == 2
    assert res["mcnemar_p"] == pytest.approx(1.0)  # b=1, c=1 -> exacto
    assert res["ic95_a"]["lo"] <= res["ic95_a"]["hi"]


def test_metric_value_derived():
    assert metric_value({"pred_quimio": True, "real_quimio": True}, "quimio") is True
    assert metric_value({"pred_quimio": True, "real_quimio": False}, "quimio") is False
    assert metric_value({"compatible": False}, "compatible") is False
    assert metric_value({}, "compatible") is None


def test_summary_excludes_error_rows():
    rows = [
        {"esperado_tipo": "recomendacion", "acierto": True, "acierto_preferida": True,
         "revision": False, "confianza": 0.9, "n_candidatos": 2},
        {"esperado_tipo": "recomendacion", "acierto": False, "acierto_preferida": False,
         "revision": True, "confianza": 0.4, "n_candidatos": 1,
         "error": "Timeout"},
    ]
    s = _summary(rows)
    assert s["n"] == 1 and s["errores"] == 1
    assert s["acierto_global"] == 1.0
    assert s["acierto_tratamiento"] == 1.0


def test_run_meta_manifest_fields():
    meta = _run_meta(mock(), [{"modelo_jev": ["jev-x-mock"]}], ["mama"])
    assert meta["host"]
    assert meta["specs"]["mama"]["version"]
    assert len(meta["specs"]["mama"]["sha256"]) == 16
    assert meta["modelos_resueltos"] == ["jev-x-mock"]
    assert meta["mock"] is True


def test_retry_errors_keeps_good_rows(tmp_path, monkeypatch):
    import jevesmo.evaluation.runner as runner

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    keep_row = {"id": "MAMA-V01", "esperado_tipo": "recomendacion", "acierto": True,
                "acierto_preferida": True, "revision": False, "confianza": 0.9,
                "n_candidatos": 2, "marca": "guardada"}
    error_row = {"id": "MAMA-V02", "esperado_tipo": "recomendacion", "acierto": False,
                 "revision": False, "confianza": None, "n_candidatos": 0,
                 "error": "Timeout"}
    (tmp_path / "mama.json").write_text(
        json.dumps({"casos": [keep_row, error_row]}), encoding="utf-8")

    res = evaluate_tumor("mama", client=mock(), save=False, retry_errors=True)
    by_id = {x["id"]: x for x in res["casos"]}
    assert by_id["MAMA-V01"].get("marca") == "guardada"      # conservada, no repite
    assert by_id["MAMA-V02"].get("error") is None            # repetida con exito
    assert len(res["casos"]) == 22                           # todas las vinetas del spec
    kept = _kept_rows(tmp_path / "mama.json", "id")
    assert list(kept) == ["MAMA-V01"]
