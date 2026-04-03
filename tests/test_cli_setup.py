"""
Tests for heddle setup command — interactive wizard.

All tests use Click's CliRunner and mock HTTP calls.
No external services needed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import structlog
from click.testing import CliRunner

_saved_structlog_config = structlog.get_config()
from heddle.cli.setup import _detect_ollama, _find_telegram_exports, setup  # noqa: E402

structlog.configure(**_saved_structlog_config)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def test_detect_ollama_success():
    """_detect_ollama returns (True, models) when Ollama responds."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [{"name": "llama3.2:3b"}, {"name": "nomic-embed-text"}]
    }
    with patch("httpx.get", return_value=mock_resp):
        found, models = _detect_ollama("http://localhost:11434")
    assert found is True
    assert "llama3.2:3b" in models
    assert "nomic-embed-text" in models


def test_detect_ollama_unreachable():
    """_detect_ollama returns (False, []) when connection fails."""
    import httpx

    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        found, models = _detect_ollama("http://localhost:11434")
    assert found is False
    assert models == []


def test_find_telegram_exports(tmp_path):
    """_find_telegram_exports finds result*.json files in a directory."""
    (tmp_path / "result-1.json").write_text("{}")
    (tmp_path / "result-2.json").write_text("{}")
    (tmp_path / "other.txt").write_text("")
    exports = _find_telegram_exports(str(tmp_path))
    assert len(exports) == 2
    assert all("result" in e for e in exports)


def test_find_telegram_exports_nonexistent():
    """_find_telegram_exports returns [] for non-existent directory."""
    assert _find_telegram_exports("/nonexistent/path") == []


# ---------------------------------------------------------------------------
# Setup command
# ---------------------------------------------------------------------------


def test_setup_help():
    """--help prints usage and exits 0."""
    runner = CliRunner()
    result = runner.invoke(setup, ["--help"])
    assert result.exit_code == 0
    assert "Interactive setup wizard" in result.output


def test_setup_non_interactive_no_ollama(tmp_path):
    """Non-interactive mode skips prompts and writes config."""
    cfg_path = str(tmp_path / "config.yaml")
    with patch("heddle.cli.setup._detect_ollama", return_value=(False, [])):
        runner = CliRunner()
        result = runner.invoke(setup, ["--non-interactive", "--config-path", cfg_path])
    assert result.exit_code == 0
    assert "Config saved" in result.output
    assert Path(cfg_path).exists()


def test_setup_non_interactive_with_ollama(tmp_path):
    """Non-interactive mode detects Ollama and saves URL."""
    cfg_path = str(tmp_path / "config.yaml")
    with patch(
        "heddle.cli.setup._detect_ollama",
        return_value=(True, ["llama3.2:3b", "nomic-embed-text"]),
    ):
        runner = CliRunner()
        result = runner.invoke(setup, ["--non-interactive", "--config-path", cfg_path])
    assert result.exit_code == 0
    assert "Ollama detected" in result.output
    assert "nomic-embed-text available" in result.output

    # Verify saved config
    from heddle.cli.config import load_config

    config = load_config(cfg_path)
    assert config.ollama_url == "http://localhost:11434"


def test_setup_interactive_skips_prompts(tmp_path):
    """Interactive mode with Enter (empty) inputs skips optional fields."""
    cfg_path = str(tmp_path / "config.yaml")
    with patch("heddle.cli.setup._detect_ollama", return_value=(False, [])):
        runner = CliRunner()
        # Provide empty inputs for: ollama url, anthropic key, data dir
        result = runner.invoke(
            setup,
            ["--config-path", cfg_path],
            input="\n\n\n",
        )
    assert result.exit_code == 0
    assert "Config saved" in result.output


def test_setup_interactive_with_anthropic_key(tmp_path):
    """Interactive mode accepts and validates an Anthropic API key."""
    cfg_path = str(tmp_path / "config.yaml")
    with (
        patch("heddle.cli.setup._detect_ollama", return_value=(False, [])),
        patch("heddle.cli.setup._test_anthropic_key", return_value=True),
    ):
        runner = CliRunner()
        # Inputs: skip ollama url, enter API key, skip data dir
        result = runner.invoke(
            setup,
            ["--config-path", cfg_path],
            input="\nsk-ant-test-key\n\n",
        )
    assert result.exit_code == 0
    assert "Key validated" in result.output

    from heddle.cli.config import load_config

    config = load_config(cfg_path)
    assert config.anthropic_api_key == "sk-ant-test-key"


def test_setup_rerun_preserves_existing(tmp_path):
    """Re-running setup loads existing config as defaults."""
    cfg_path = str(tmp_path / "config.yaml")

    # First run: save an Ollama URL
    from heddle.cli.config import HeddleConfig, save_config

    save_config(HeddleConfig(ollama_url="http://saved:11434"), cfg_path)

    # Second run: non-interactive, Ollama at saved URL
    with patch(
        "heddle.cli.setup._detect_ollama",
        return_value=(True, ["llama3.2:3b"]),
    ):
        runner = CliRunner()
        result = runner.invoke(setup, ["--non-interactive", "--config-path", cfg_path])

    assert result.exit_code == 0
    assert "Existing config found" in result.output


def test_setup_data_dir_with_exports(tmp_path):
    """Setup finds and reports Telegram export files."""
    cfg_path = str(tmp_path / "config.yaml")
    data_dir = tmp_path / "exports"
    data_dir.mkdir()
    (data_dir / "result-1.json").write_text("{}")
    (data_dir / "result-2.json").write_text("{}")

    with patch("heddle.cli.setup._detect_ollama", return_value=(False, [])):
        runner = CliRunner()
        # Inputs: skip ollama url, skip API key, enter data dir
        result = runner.invoke(
            setup,
            ["--config-path", cfg_path],
            input=f"\n\n{data_dir}\n",
        )
    assert result.exit_code == 0
    assert "Found 2 export file(s)" in result.output
