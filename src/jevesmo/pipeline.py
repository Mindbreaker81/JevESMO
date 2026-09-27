"""Compatibilidad: el pipeline ahora es generico (engine.pipeline)."""

from .engine.pipeline import CONFIDENCE_THRESHOLD, run  # noqa: F401


def run_pipeline(raw, client=None, tumor: str = "mama"):
    return run(tumor, raw, client)
