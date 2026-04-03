"""
Tests for heddle.cli.config — config file load/save/merge.

All tests use tmp_path for isolation. No external services needed.
"""

from __future__ import annotations

import os

from heddle.cli.config import (
    HeddleConfig,
    apply_config_to_env,
    load_config,
    resolve_config,
    save_config,
)

# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def test_load_config_missing_file_returns_defaults(tmp_path):
    """A non-existent file returns all-default HeddleConfig."""
    config = load_config(str(tmp_path / "nonexistent.yaml"))
    assert config.ollama_url is None
    assert config.ollama_model == "llama3.2:3b"
    assert config.anthropic_api_key is None
    assert config.embedding_model == "nomic-embed-text"
    assert config.rag_vector_store == "duckdb"
    assert config.rag_db_path == "~/.heddle/rag.duckdb"
    assert config.workshop_port == 8080


def test_load_config_reads_yaml(tmp_path):
    """Config values are loaded from a structured YAML file."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "backends:\n"
        "  ollama_url: http://myhost:11434\n"
        "  anthropic_api_key: sk-test-key\n"
        "rag:\n"
        "  rag_vector_store: lancedb\n"
        "  rag_data_dir: /data/exports\n"
        "workshop:\n"
        "  workshop_port: 9090\n"
    )
    config = load_config(str(cfg_path))
    assert config.ollama_url == "http://myhost:11434"
    assert config.anthropic_api_key == "sk-test-key"
    assert config.rag_vector_store == "lancedb"
    assert config.rag_data_dir == "/data/exports"
    assert config.workshop_port == 9090


def test_load_config_partial_yaml_fills_defaults(tmp_path):
    """A partial config file fills in defaults for missing fields."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("backends:\n  ollama_url: http://localhost:11434\n")
    config = load_config(str(cfg_path))
    assert config.ollama_url == "http://localhost:11434"
    # Defaults for everything else
    assert config.ollama_model == "llama3.2:3b"
    assert config.rag_vector_store == "duckdb"
    assert config.workshop_port == 8080


def test_load_config_flat_keys(tmp_path):
    """Top-level keys (not nested under sections) are also accepted."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("ollama_url: http://flat:11434\nworkshop_port: 7070\n")
    config = load_config(str(cfg_path))
    assert config.ollama_url == "http://flat:11434"
    assert config.workshop_port == 7070


def test_load_config_empty_yaml(tmp_path):
    """An empty file returns defaults."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("")
    config = load_config(str(cfg_path))
    assert config.ollama_url is None
    assert config.rag_vector_store == "duckdb"


# ---------------------------------------------------------------------------
# save_config
# ---------------------------------------------------------------------------


def test_save_config_creates_parent_dirs(tmp_path):
    """save_config creates intermediate directories."""
    cfg_path = tmp_path / "deep" / "nested" / "config.yaml"
    config = HeddleConfig(ollama_url="http://localhost:11434")
    save_config(config, str(cfg_path))
    assert cfg_path.exists()
    # Check file permissions (owner read/write only)
    mode = cfg_path.stat().st_mode
    assert mode & 0o777 == 0o600


def test_save_config_roundtrip(tmp_path):
    """Values survive a save → load roundtrip."""
    cfg_path = str(tmp_path / "config.yaml")
    original = HeddleConfig(
        ollama_url="http://localhost:11434",
        anthropic_api_key="sk-ant-test",
        rag_vector_store="lancedb",
        rag_data_dir="/data",
        workshop_port=9999,
    )
    save_config(original, cfg_path)
    loaded = load_config(cfg_path)
    assert loaded.ollama_url == original.ollama_url
    assert loaded.anthropic_api_key == original.anthropic_api_key
    assert loaded.rag_vector_store == original.rag_vector_store
    assert loaded.rag_data_dir == original.rag_data_dir
    assert loaded.workshop_port == original.workshop_port


def test_save_config_defaults_produce_minimal_file(tmp_path):
    """A default config produces a mostly-empty file."""
    cfg_path = tmp_path / "config.yaml"
    save_config(HeddleConfig(), str(cfg_path))
    content = cfg_path.read_text()
    assert "No non-default values" in content


# ---------------------------------------------------------------------------
# resolve_config
# ---------------------------------------------------------------------------


def test_resolve_config_env_overrides_file(tmp_path, monkeypatch):
    """Environment variables override values from config.yaml."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("backends:\n  ollama_url: http://from-file:11434\n")
    monkeypatch.setenv("OLLAMA_URL", "http://from-env:11434")

    config = resolve_config(config_path=str(cfg_path))
    assert config.ollama_url == "http://from-env:11434"


def test_resolve_config_cli_overrides_env(tmp_path, monkeypatch):
    """CLI overrides win over env vars."""
    monkeypatch.setenv("OLLAMA_URL", "http://from-env:11434")
    config = resolve_config(
        cli_overrides={"ollama_url": "http://from-cli:11434"},
        config_path=str(tmp_path / "nonexistent.yaml"),
    )
    assert config.ollama_url == "http://from-cli:11434"


def test_resolve_config_priority_chain(tmp_path, monkeypatch):
    """Full chain: defaults ← file ← env ← CLI."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "backends:\n"
        "  ollama_url: http://file:11434\n"
        "  ollama_model: file-model\n"
        "  anthropic_api_key: file-key\n"
    )
    monkeypatch.setenv("OLLAMA_MODEL", "env-model")

    config = resolve_config(
        cli_overrides={"anthropic_api_key": "cli-key"},
        config_path=str(cfg_path),
    )
    # ollama_url: from file (no env override)
    assert config.ollama_url == "http://file:11434"
    # ollama_model: env wins over file
    assert config.ollama_model == "env-model"
    # anthropic_api_key: CLI wins over file
    assert config.anthropic_api_key == "cli-key"
    # embedding_model: default (not in file, env, or CLI)
    assert config.embedding_model == "nomic-embed-text"


# ---------------------------------------------------------------------------
# apply_config_to_env
# ---------------------------------------------------------------------------


def test_apply_config_to_env_sets_missing_vars(monkeypatch):
    """apply_config_to_env sets env vars that are not already set."""
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    config = HeddleConfig(
        ollama_url="http://config:11434",
        anthropic_api_key="sk-from-config",
    )
    apply_config_to_env(config)

    assert os.environ["OLLAMA_URL"] == "http://config:11434"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-from-config"


def test_apply_config_to_env_does_not_overwrite_existing(monkeypatch):
    """Explicit env vars are preserved — config values don't overwrite."""
    monkeypatch.setenv("OLLAMA_URL", "http://existing:11434")

    config = HeddleConfig(ollama_url="http://config:11434")
    apply_config_to_env(config)

    assert os.environ["OLLAMA_URL"] == "http://existing:11434"


def test_apply_config_to_env_skips_none_values(monkeypatch):
    """None values in config don't set env vars."""
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    config = HeddleConfig()  # ollama_url is None
    apply_config_to_env(config)
    assert "OLLAMA_URL" not in os.environ
