"""Shared test fixtures and markers."""

import os

import pytest

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")


def _ollama_available() -> bool:
    try:
        import httpx

        r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _deepeval_available() -> bool:
    try:
        import deepeval  # noqa: F401

        return True
    except ImportError:
        return False


skip_no_deepeval = pytest.mark.skipif(
    not _deepeval_available() or not _ollama_available(),
    reason="DeepEval or Ollama not available",
)
