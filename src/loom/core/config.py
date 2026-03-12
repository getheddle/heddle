"""
Configuration loading and validation utilities.

All Loom configs are YAML files. Worker configs define system prompts,
I/O schemas, timeouts, and backend settings. See configs/workers/_template.yaml
for the canonical config structure.

This module provides basic structural validation for worker and pipeline
configs: it checks that required keys are present and that types are correct.
This catches common mistakes (typos, missing fields) at startup rather than
at first-message time.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger()

# Required top-level keys for each config type and their expected Python types.
# None means any type is accepted (the key just needs to exist).
_WORKER_REQUIRED: dict[str, type | None] = {
    "name": str,
    "system_prompt": str,
}

_PIPELINE_REQUIRED: dict[str, type | None] = {
    "name": str,
    "pipeline_stages": list,
}


class ConfigValidationError(Exception):
    """Raised when a config file fails structural validation."""


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML config file and return as a dict.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        yaml.YAMLError: If the file contains invalid YAML.
    """
    with open(path) as f:
        return yaml.safe_load(f)


def validate_worker_config(config: dict[str, Any], path: str | Path = "<unknown>") -> list[str]:
    """Validate a worker config dict against expected structure.

    Checks for required keys and correct types. Returns a list of error
    strings (empty = valid). Does NOT raise — callers decide what to do
    with validation errors.

    This catches the most common config mistakes:
    - Missing 'name' or 'system_prompt'
    - Wrong type for schema fields (e.g., input_schema as a string)
    """
    return _validate_config(config, _WORKER_REQUIRED, "worker", path)


def validate_pipeline_config(config: dict[str, Any], path: str | Path = "<unknown>") -> list[str]:
    """Validate a pipeline orchestrator config."""
    errors = _validate_config(config, _PIPELINE_REQUIRED, "pipeline", path)
    # Check that each stage has required fields
    for i, stage in enumerate(config.get("pipeline_stages", [])):
        if not isinstance(stage, dict):
            errors.append(f"pipeline_stages[{i}]: expected dict, got {type(stage).__name__}")
            continue
        if "name" not in stage:
            errors.append(f"pipeline_stages[{i}]: missing required key 'name'")
        if "worker_type" not in stage:
            errors.append(f"pipeline_stages[{i}]: missing required key 'worker_type'")
    return errors


def _validate_config(
    config: dict[str, Any],
    required: dict[str, type | None],
    config_type: str,
    path: str | Path,
) -> list[str]:
    """Check that required keys exist and have correct types."""
    errors = []
    if not isinstance(config, dict):
        return [f"{config_type} config at {path}: expected dict, got {type(config).__name__}"]

    for key, expected_type in required.items():
        if key not in config:
            errors.append(f"{config_type} config at {path}: missing required key '{key}'")
        elif expected_type is not None and not isinstance(config[key], expected_type):
            errors.append(
                f"{config_type} config at {path}: key '{key}' expected {expected_type.__name__}, "
                f"got {type(config[key]).__name__}"
            )

    # Warn about schema fields that should be dicts
    for schema_key in ("input_schema", "output_schema"):
        if schema_key in config and not isinstance(config[schema_key], dict):
            errors.append(
                f"{config_type} config at {path}: '{schema_key}' should be a dict "
                f"(JSON Schema object), got {type(config[schema_key]).__name__}"
            )

    # Validate knowledge_silos if present
    if "knowledge_silos" in config:
        errors.extend(_validate_knowledge_silos(config["knowledge_silos"], path))

    return errors


def _validate_knowledge_silos(
    silos: Any,
    path: str | Path,
) -> list[str]:
    """Validate the knowledge_silos config section.

    Each silo must have ``name`` (str) and ``type`` (str).
    Folder silos must have ``path`` (str).
    Tool silos must have ``provider`` (str) and ``config`` (dict).
    """
    errors: list[str] = []

    if not isinstance(silos, list):
        return [f"config at {path}: 'knowledge_silos' should be a list, got {type(silos).__name__}"]

    for i, silo in enumerate(silos):
        prefix = f"config at {path}: knowledge_silos[{i}]"

        if not isinstance(silo, dict):
            errors.append(f"{prefix}: expected dict, got {type(silo).__name__}")
            continue

        # Required fields for all silo types
        if "name" not in silo:
            errors.append(f"{prefix}: missing required key 'name'")
        elif not isinstance(silo["name"], str):
            errors.append(f"{prefix}: 'name' must be a string")

        if "type" not in silo:
            errors.append(f"{prefix}: missing required key 'type'")
            continue
        elif not isinstance(silo["type"], str):
            errors.append(f"{prefix}: 'type' must be a string")
            continue

        silo_type = silo["type"]

        if silo_type == "folder":
            if "path" not in silo:
                errors.append(f"{prefix}: folder silo missing required key 'path'")
            elif not isinstance(silo["path"], str):
                errors.append(f"{prefix}: 'path' must be a string")

            permissions = silo.get("permissions", "read")
            if permissions not in ("read", "read_write"):
                errors.append(f"{prefix}: 'permissions' must be 'read' or 'read_write', got '{permissions}'")

        elif silo_type == "tool":
            if "provider" not in silo:
                errors.append(f"{prefix}: tool silo missing required key 'provider'")
            elif not isinstance(silo["provider"], str):
                errors.append(f"{prefix}: 'provider' must be a string")

            if "config" in silo and not isinstance(silo["config"], dict):
                errors.append(f"{prefix}: 'config' must be a dict")

        else:
            errors.append(f"{prefix}: unknown silo type '{silo_type}' (expected 'folder' or 'tool')")

    return errors
