"""Tests for _extract_json() YAML parsing paths."""

import pytest

from loom.worker.runner import _extract_json

# --- JSON (existing behavior, regression check) ---


def test_extract_json_prefers_json():
    """JSON is preferred over YAML when both could parse."""
    raw = '{"key": "value"}'
    result = _extract_json(raw)
    assert result == {"key": "value"}


# --- Clean YAML (no fences) ---


def test_extract_json_clean_yaml():
    raw = "integration_result:\n  status: PASS\n  count: 3"
    result = _extract_json(raw)
    assert result["integration_result"]["status"] == "PASS"
    assert result["integration_result"]["count"] == 3


# --- Fenced YAML variants ---


def test_extract_json_fenced_yaml():
    raw = "```yaml\nintegration_result:\n  status: PASS\n```"
    result = _extract_json(raw)
    assert result["integration_result"]["status"] == "PASS"


def test_extract_json_fenced_yml():
    raw = "```yml\nclaims:\n  - text: hello\n```"
    result = _extract_json(raw)
    assert "claims" in result


# --- YAML with preamble text ---


def test_extract_json_yaml_with_preamble():
    raw = "Here is the output:\n\n```yaml\nresult:\n  ok: true\n```"
    result = _extract_json(raw)
    assert result["result"]["ok"] is True


# --- Non-dict YAML raises ValueError ---


def test_extract_json_yaml_list_raises():
    raw = "- item1\n- item2"
    with pytest.raises(ValueError):
        _extract_json(raw)
