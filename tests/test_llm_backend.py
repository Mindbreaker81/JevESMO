"""Backend LLM alternativo: opt-in estricto y sin certeza fabricada (adaptador simulado)."""
import sys
import types

import pytest

from jevesmo.jev_client import Question, make_client


def _install_fake_adapter(monkeypatch, answers):
    mod = types.ModuleType("system_one_adapter")

    class _Q:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class Adapter:
        def __init__(self, **kw):
            pass

        def system_one(self, state, mapped):
            return types.SimpleNamespace(model="fake-1", answers={k: answers[k] for k in mapped})

    mod.SystemOneAdapterClient, mod.Choice, mod.Score, mod.Noul = Adapter, _Q, _Q, _Q
    monkeypatch.setitem(sys.modules, "system_one_adapter", mod)


def _a(**kw):
    return types.SimpleNamespace(**kw)


@pytest.mark.parametrize("valor", ["", "  ", "typesafe", "OpenAi2", "jev2"])
def test_make_client_rejects_invalid_backend(monkeypatch, valor):
    monkeypatch.setenv("JEVESMO_BACKEND", valor)
    with pytest.raises(RuntimeError):
        make_client()


def test_llm_requires_model(monkeypatch):
    _install_fake_adapter(monkeypatch, {})
    monkeypatch.setenv("JEVESMO_BACKEND", "llm")
    monkeypatch.delenv("JEVESMO_LLM_MODEL", raising=False)
    with pytest.raises(RuntimeError):
        make_client()


def test_llm_without_sdk_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "system_one_adapter", None)  # import -> ImportError
    monkeypatch.setenv("JEVESMO_BACKEND", "llm")
    monkeypatch.setenv("JEVESMO_LLM_MODEL", "x")
    with pytest.raises(RuntimeError):
        make_client()


QS = {
    "c2": Question("c2", "choice", "?", {"a": "A", "b": "B"}),
    "c1": Question("c1", "choice", "?", {"solo": "S"}),
    "n": Question("n", "noul", "?"),
}


def test_probabilities_mode_keeps_model_confidence(monkeypatch):
    _install_fake_adapter(monkeypatch, {
        "c2": _a(choice="a", confidence=0.4, probabilities={"a": 0.7, "b": 0.3}, noul=None, score=None),
        "n": _a(noul=0.35, choice=None, score=None, confidence=None, probabilities=None)})
    monkeypatch.setenv("JEVESMO_BACKEND", "llm")
    monkeypatch.setenv("JEVESMO_LLM_MODEL", "x")
    ans = make_client().system_one("s", QS).answers
    assert ans["c2"].confidence == 0.4 and ans["n"].noul == 0.35
    # choice degenerado: eleccion local, sin confianza ni probabilidades inventadas
    assert ans["c1"].choice == "solo" and ans["c1"].confidence is None and ans["c1"].probabilities is None


def test_discrete_mode_drops_fabricated_certainty(monkeypatch):
    _install_fake_adapter(monkeypatch, {
        "c2": _a(choice="a", confidence=1.0, probabilities={"a": 1.0, "b": 0.0}, noul=None, score=None),
        "n": _a(noul=0.0, choice=None, score=None, confidence=None, probabilities=None)})
    monkeypatch.setenv("JEVESMO_BACKEND", "llm")
    monkeypatch.setenv("JEVESMO_LLM_MODEL", "x")
    monkeypatch.setenv("JEVESMO_LLM_ANSWER_MODE", "discrete")
    ans = make_client().system_one("s", QS).answers
    assert ans["c2"].choice == "a" and ans["c2"].confidence is None and ans["c2"].probabilities is None
    assert "n" not in ans  # noul binario: sin respuesta (seguridad falla cerrado)
