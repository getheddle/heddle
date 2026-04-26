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
from heddle.cli.setup import (  # noqa: E402
    _detect_lm_studio,
    _detect_ollama,
    _find_telegram_exports,
    setup,
)

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


def test_detect_lm_studio_success():
    """_detect_lm_studio returns (True, model_ids) when LM Studio responds."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {"id": "qwen/qwen2.5-7b"},
            {"id": "text-embedding-nomic-embed-text-v1.5"},
        ]
    }
    with patch("httpx.get", return_value=mock_resp):
        found, models = _detect_lm_studio("http://localhost:1234/v1")
    assert found is True
    assert "qwen/qwen2.5-7b" in models
    assert "text-embedding-nomic-embed-text-v1.5" in models


def test_detect_lm_studio_strips_v1_then_re_appends():
    """Both http://host:port and http://host:port/v1 work."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "model-a"}]}
    with patch("httpx.get", return_value=mock_resp) as mock_get:
        _detect_lm_studio("http://localhost:1234")
    mock_get.assert_called_once()
    args, _ = mock_get.call_args
    assert args[0].endswith("/v1/models")


def test_detect_lm_studio_unreachable():
    """_detect_lm_studio returns (False, []) when connection fails."""
    import httpx

    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        found, models = _detect_lm_studio("http://localhost:1234/v1")
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


def _patch_detectors(lm_studio: tuple[bool, list[str]], ollama: tuple[bool, list[str]]):
    """Patch both detectors at once so the wizard's local-LLM section is hermetic."""
    return (
        patch("heddle.cli.setup._detect_lm_studio", return_value=lm_studio),
        patch("heddle.cli.setup._detect_ollama", return_value=ollama),
    )


def test_setup_non_interactive_no_local(tmp_path):
    """Non-interactive mode with no local LLMs still writes config."""
    cfg_path = str(tmp_path / "config.yaml")
    p1, p2 = _patch_detectors((False, []), (False, []))
    with p1, p2:
        runner = CliRunner()
        result = runner.invoke(setup, ["--non-interactive", "--config-path", cfg_path])
    assert result.exit_code == 0
    assert "Config saved" in result.output
    assert Path(cfg_path).exists()


def test_setup_non_interactive_with_ollama_only(tmp_path):
    """Non-interactive mode detects Ollama (no LM Studio) and saves URL."""
    cfg_path = str(tmp_path / "config.yaml")
    p1, p2 = _patch_detectors(
        (False, []),
        (True, ["llama3.2:3b", "nomic-embed-text"]),
    )
    with p1, p2:
        runner = CliRunner()
        result = runner.invoke(setup, ["--non-interactive", "--config-path", cfg_path])
    assert result.exit_code == 0
    assert "Ollama detected" in result.output
    assert "nomic-embed-text available" in result.output

    from heddle.cli.config import load_config

    config = load_config(cfg_path)
    assert config.ollama_url == "http://localhost:11434"
    assert config.local_backend == "ollama"


def test_setup_non_interactive_with_lm_studio_only(tmp_path):
    """Non-interactive mode detects LM Studio (no Ollama) and saves URL."""
    cfg_path = str(tmp_path / "config.yaml")
    p1, p2 = _patch_detectors(
        (True, ["qwen/qwen2.5-7b", "text-embedding-nomic-embed-text-v1.5"]),
        (False, []),
    )
    with p1, p2:
        runner = CliRunner()
        result = runner.invoke(setup, ["--non-interactive", "--config-path", cfg_path])
    assert result.exit_code == 0
    assert "LM Studio detected" in result.output

    from heddle.cli.config import load_config

    config = load_config(cfg_path)
    assert config.lm_studio_url == "http://localhost:1234/v1"
    assert config.local_backend == "lmstudio"
    assert config.embedding_backend == "openai-compatible"


def test_setup_non_interactive_both_runtimes(tmp_path):
    """Non-interactive with both runtimes — LM Studio wins by default."""
    cfg_path = str(tmp_path / "config.yaml")
    p1, p2 = _patch_detectors(
        (True, ["qwen/qwen2.5-7b"]),
        (True, ["llama3.2:3b"]),
    )
    with p1, p2:
        runner = CliRunner()
        result = runner.invoke(setup, ["--non-interactive", "--config-path", cfg_path])
    assert result.exit_code == 0

    from heddle.cli.config import load_config

    config = load_config(cfg_path)
    assert config.lm_studio_url == "http://localhost:1234/v1"
    assert config.ollama_url == "http://localhost:11434"
    # Wizard does not prompt in non-interactive mode and leaves
    # local_backend as auto/None when both are present (resolution
    # happens at runtime via build_backends_from_env).


def test_setup_interactive_skips_prompts(tmp_path):
    """Interactive mode with empty inputs skips optional fields."""
    cfg_path = str(tmp_path / "config.yaml")
    p1, p2 = _patch_detectors((False, []), (False, []))
    with p1, p2:
        runner = CliRunner()
        # Inputs in order: lm-studio url, ollama url, anthropic key, data dir
        result = runner.invoke(
            setup,
            ["--config-path", cfg_path],
            input="\n\n\n\n",
        )
    assert result.exit_code == 0
    assert "Config saved" in result.output


def test_setup_interactive_with_anthropic_key(tmp_path):
    """Interactive mode accepts and validates an Anthropic API key."""
    cfg_path = str(tmp_path / "config.yaml")
    p1, p2 = _patch_detectors((False, []), (False, []))
    with (
        p1,
        p2,
        patch("heddle.cli.setup._test_anthropic_key", return_value=True),
    ):
        runner = CliRunner()
        # Inputs: skip lm-studio, skip ollama, enter API key, skip data dir
        result = runner.invoke(
            setup,
            ["--config-path", cfg_path],
            input="\n\nsk-ant-test-key\n\n",
        )
    assert result.exit_code == 0
    assert "Key validated" in result.output

    from heddle.cli.config import load_config

    config = load_config(cfg_path)
    assert config.anthropic_api_key == "sk-ant-test-key"


def test_setup_rerun_preserves_existing(tmp_path):
    """Re-running setup loads existing config as defaults."""
    cfg_path = str(tmp_path / "config.yaml")

    from heddle.cli.config import HeddleConfig, save_config

    save_config(HeddleConfig(ollama_url="http://saved:11434"), cfg_path)

    p1, p2 = _patch_detectors(
        (False, []),
        (True, ["llama3.2:3b"]),
    )
    with p1, p2:
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

    p1, p2 = _patch_detectors((False, []), (False, []))
    with p1, p2:
        runner = CliRunner()
        # Inputs: skip lm-studio url, skip ollama url, skip API key, data dir
        result = runner.invoke(
            setup,
            ["--config-path", cfg_path],
            input=f"\n\n\n{data_dir}\n",
        )
    assert result.exit_code == 0
    assert "Found 2 export file(s)" in result.output
