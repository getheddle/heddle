"""
Tests for CLI pre-flight checks (heddle.cli.preflight).

All NATS connectivity tests use mocks — no infrastructure needed.
Environment variable tests use monkeypatch for isolation.
Config readability tests use tmp_path for real file I/O.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from heddle.cli.preflight import check_config_readable, check_env_vars, check_nats_connectivity

# ---------------------------------------------------------------------------
# check_nats_connectivity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nats_connectivity_success():
    """Successful NATS connection returns (True, message)."""
    mock_nc = AsyncMock()
    mock_nc.drain = AsyncMock()

    with patch("heddle.cli.preflight.nats_lib") as mock_nats:
        mock_nats.connect = AsyncMock(return_value=mock_nc)
        ok, msg = await check_nats_connectivity("nats://localhost:4222")

    assert ok is True
    assert "Connected to NATS" in msg
    assert "localhost:4222" in msg


@pytest.mark.asyncio
async def test_nats_connectivity_failure():
    """Failed NATS connection returns (False, message with fix suggestion)."""
    with patch("heddle.cli.preflight.nats_lib") as mock_nats:
        mock_nats.connect = AsyncMock(side_effect=ConnectionRefusedError("refused"))
        ok, msg = await check_nats_connectivity("nats://localhost:4222", timeout=1.0)

    assert ok is False
    assert "Cannot connect to NATS" in msg
    assert "docker run" in msg
    assert "refused" in msg


# ---------------------------------------------------------------------------
# check_env_vars
# ---------------------------------------------------------------------------


def test_env_vars_local_missing_ollama(monkeypatch):
    """Local tier without OLLAMA_URL returns a warning."""
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    warnings = check_env_vars("local")
    assert len(warnings) == 1
    assert "OLLAMA_URL" in warnings[0]


def test_env_vars_local_with_ollama(monkeypatch):
    """Local tier with OLLAMA_URL set returns no warnings."""
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
    warnings = check_env_vars("local")
    assert warnings == []


def test_env_vars_standard_missing_anthropic(monkeypatch):
    """Standard tier without ANTHROPIC_API_KEY returns a warning."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    warnings = check_env_vars("standard")
    assert len(warnings) == 1
    assert "ANTHROPIC_API_KEY" in warnings[0]
    assert "standard" in warnings[0]


def test_env_vars_frontier_missing_anthropic(monkeypatch):
    """Frontier tier without ANTHROPIC_API_KEY returns a warning."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    warnings = check_env_vars("frontier")
    assert len(warnings) == 1
    assert "ANTHROPIC_API_KEY" in warnings[0]
    assert "frontier" in warnings[0]


def test_env_vars_standard_with_anthropic(monkeypatch):
    """Standard tier with ANTHROPIC_API_KEY set returns no warnings."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    warnings = check_env_vars("standard")
    assert warnings == []


def test_env_vars_unknown_tier():
    """Unknown tier returns no warnings (no env vars to check)."""
    warnings = check_env_vars("unknown-tier")
    assert warnings == []


# ---------------------------------------------------------------------------
# check_config_readable
# ---------------------------------------------------------------------------


def test_config_readable_nonexistent():
    """Nonexistent file returns (False, message)."""
    ok, msg = check_config_readable("/nonexistent/path/config.yaml")
    assert ok is False
    assert "not found" in msg


def test_config_readable_valid_yaml(tmp_path):
    """Valid YAML file returns (True, message)."""
    config = tmp_path / "good.yaml"
    config.write_text("name: test\ntier: local\n")
    ok, msg = check_config_readable(str(config))
    assert ok is True
    assert "valid YAML" in msg


def test_config_readable_invalid_yaml(tmp_path):
    """Invalid YAML file returns (False, message)."""
    config = tmp_path / "bad.yaml"
    config.write_text("name: test\n  bad indent: [unclosed\n")
    ok, msg = check_config_readable(str(config))
    assert ok is False
    assert "invalid YAML" in msg


def test_config_readable_empty_file(tmp_path):
    """Empty YAML file returns (False, message)."""
    config = tmp_path / "empty.yaml"
    config.write_text("")
    ok, msg = check_config_readable(str(config))
    assert ok is False
    assert "empty" in msg
