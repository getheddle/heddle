"""
User config (~/.heddle/config.yaml) — load, save, and merge with env vars.

The config file stores defaults for LLM backends, RAG settings, and Workshop
preferences. Values can be overridden by environment variables or CLI flags.

Priority (highest wins): CLI flags > env vars > config.yaml > built-in defaults.
"""

from __future__ import annotations

import os
import stat
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = "~/.heddle/config.yaml"


@dataclass
class HeddleConfig:
    """Parsed representation of ~/.heddle/config.yaml.

    TODO(local-runtime-registry): the per-runtime ``*_url`` / ``*_model``
    fields below (and the matching entries in ``_ENV_MAP``) should be
    generated from the planned ``LocalRuntime`` registry rather than
    hand-maintained in lockstep with ``cli/setup.py``,
    ``cli/preflight.py``, ``workshop/app.py``, ``cli/rag.py``, and
    ``mcp/session_bridge.py``.  See
    ``heddle.worker.backends._select_local_backend`` for the design.
    """

    # LLM backends
    ollama_url: str | None = None
    ollama_model: str = "llama3.2:3b"
    lm_studio_url: str | None = None
    lm_studio_model: str = "default"
    # Which local backend wins when both ``ollama_url`` and
    # ``lm_studio_url`` are configured.  Accepts ``"lmstudio"`` or
    # ``"ollama"``.  When unset, LM Studio is preferred (newer default).
    local_backend: str | None = None
    anthropic_api_key: str | None = None
    frontier_model: str = "claude-opus-4-20250514"
    embedding_model: str = "nomic-embed-text"
    # Which embedding backend the RAG pipeline should use.  Accepts
    # ``"ollama"`` or ``"openai-compatible"`` (LM Studio etc.).  When
    # unset, follows ``local_backend`` and then falls back to whichever
    # URL is configured.
    embedding_backend: str | None = None

    # RAG pipeline
    rag_data_dir: str | None = None
    rag_vector_store: str = "duckdb"
    rag_db_path: str = "~/.heddle/rag.duckdb"

    # Workshop
    workshop_port: int = 8080


# ---------------------------------------------------------------------------
# Env-var mapping: config field → env var name
# ---------------------------------------------------------------------------

_ENV_MAP: dict[str, str] = {
    "ollama_url": "OLLAMA_URL",
    "ollama_model": "OLLAMA_MODEL",
    "lm_studio_url": "LM_STUDIO_URL",
    "lm_studio_model": "LM_STUDIO_MODEL",
    "local_backend": "HEDDLE_LOCAL_BACKEND",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "frontier_model": "FRONTIER_MODEL",
    "embedding_backend": "HEDDLE_EMBEDDING_BACKEND",
}


def load_config(path: str = DEFAULT_CONFIG_PATH) -> HeddleConfig:
    """Load config from YAML file. Returns defaults if file is missing."""
    expanded = Path(path).expanduser()
    if not expanded.exists():
        return HeddleConfig()

    import yaml

    with expanded.open() as f:
        data = yaml.safe_load(f) or {}

    # Flatten nested sections into flat dict
    flat: dict[str, Any] = {}
    for section_key in ("backends", "rag", "workshop"):
        section = data.get(section_key, {})
        if isinstance(section, dict):
            flat.update(section)

    # Also accept top-level keys
    valid_fields = {f.name for f in fields(HeddleConfig)}
    flat.update({k: v for k, v in data.items() if k in valid_fields})

    # Build config with only recognized fields
    kwargs = {k: v for k, v in flat.items() if k in valid_fields and v is not None}
    return HeddleConfig(**kwargs)


def save_config(config: HeddleConfig, path: str = DEFAULT_CONFIG_PATH) -> None:  # noqa: PLR0912
    """Write config to YAML file, creating parent dirs as needed.

    Sets file permissions to 0o600 (owner read/write only) since the file
    may contain API keys.
    """
    import yaml

    expanded = Path(path).expanduser()
    expanded.parent.mkdir(parents=True, exist_ok=True)

    # Organize into sections for readability
    data: dict[str, Any] = {}

    backends: dict[str, Any] = {}
    if config.ollama_url:
        backends["ollama_url"] = config.ollama_url
    if config.ollama_model != "llama3.2:3b":
        backends["ollama_model"] = config.ollama_model
    if config.lm_studio_url:
        backends["lm_studio_url"] = config.lm_studio_url
    if config.lm_studio_model != "default":
        backends["lm_studio_model"] = config.lm_studio_model
    if config.local_backend:
        backends["local_backend"] = config.local_backend
    if config.anthropic_api_key:
        backends["anthropic_api_key"] = config.anthropic_api_key
    if config.frontier_model != "claude-opus-4-20250514":
        backends["frontier_model"] = config.frontier_model
    if config.embedding_model != "nomic-embed-text":
        backends["embedding_model"] = config.embedding_model
    if config.embedding_backend:
        backends["embedding_backend"] = config.embedding_backend
    if backends:
        data["backends"] = backends

    rag: dict[str, Any] = {}
    if config.rag_data_dir:
        rag["rag_data_dir"] = config.rag_data_dir
    if config.rag_vector_store != "duckdb":
        rag["rag_vector_store"] = config.rag_vector_store
    if config.rag_db_path != "~/.heddle/rag.duckdb":
        rag["rag_db_path"] = config.rag_db_path
    if rag:
        data["rag"] = rag

    workshop: dict[str, Any] = {}
    if config.workshop_port != 8080:
        workshop["workshop_port"] = config.workshop_port
    if workshop:
        data["workshop"] = workshop

    content = "# Heddle configuration — generated by `heddle setup`\n"
    content += "# This file may contain API keys. Keep it private.\n\n"
    if data:
        content += yaml.dump(data, default_flow_style=False, sort_keys=False)
    else:
        content += "# No non-default values configured.\n"

    expanded.write_text(content)
    expanded.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600


def resolve_config(
    cli_overrides: dict[str, Any] | None = None,
    config_path: str = DEFAULT_CONFIG_PATH,
) -> HeddleConfig:
    """Merge: built-in defaults ← config.yaml ← env vars ← cli_overrides.

    Args:
        cli_overrides: Dict of field_name → value from CLI flags.
        config_path: Path to the YAML config file.

    Returns:
        Fully resolved HeddleConfig.
    """
    # Start from config file (includes built-in defaults for missing fields)
    config = load_config(config_path)
    config_dict = asdict(config)

    # Layer 2: env vars override config file
    for field_name, env_var in _ENV_MAP.items():
        env_val = os.environ.get(env_var)
        if env_val is not None:
            config_dict[field_name] = env_val

    # Layer 3: CLI overrides win
    if cli_overrides:
        for k, v in cli_overrides.items():
            if v is not None and k in config_dict:
                config_dict[k] = v

    return HeddleConfig(**config_dict)


def apply_config_to_env(config: HeddleConfig) -> None:
    """Set env vars from config for backwards compat with ``build_backends_from_env``.

    Only sets variables that are NOT already present in the environment,
    so explicit ``export OLLAMA_URL=...`` always wins.
    """
    for field_name, env_var in _ENV_MAP.items():
        value = getattr(config, field_name, None)
        if value is not None:
            os.environ.setdefault(env_var, str(value))
