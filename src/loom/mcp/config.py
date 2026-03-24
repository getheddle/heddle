"""
MCP gateway configuration loading and validation.

Defines the YAML config structure for exposing LOOM workers, pipelines,
query backends, and Workshop operations as MCP tools. Follows the same
validation pattern as ``loom.core.config``.

Example config::

    name: "docman"
    description: "Document processing and querying"
    nats_url: "nats://localhost:4222"

    tools:
      workers:
        - config: "configs/workers/doc_classifier.yaml"
          name: "classify_document"
          description: "Classify a document by type"
          tier: "local"

      pipelines:
        - config: "configs/orchestrators/doc_pipeline.yaml"
          name: "process_document"
          description: "Full document processing pipeline"

      queries:
        - backend: "docman.backends.duckdb_query.DocmanQueryBackend"
          backend_config:
            db_path: "/tmp/workspace/docman.duckdb"
          actions: ["search", "filter", "stats", "get"]
          name_prefix: "docman"

    resources:
      workspace_dir: "/tmp/workspace"
      patterns: ["*.pdf", "*.json"]
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from loom.core.config import load_config


def load_mcp_config(path: str | Path) -> dict[str, Any]:
    """Load and validate an MCP gateway config YAML.

    Raises:
        ConfigValidationError: If the config has structural errors.
        FileNotFoundError: If the config file doesn't exist.
        yaml.YAMLError: If the file contains invalid YAML.
    """
    from loom.core.config import ConfigValidationError

    config = load_config(path)
    errors = validate_mcp_config(config, path)
    if errors:
        raise ConfigValidationError(
            f"MCP config at {path} has {len(errors)} error(s):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
    return config


def validate_mcp_config(  # noqa: PLR0912
    config: dict[str, Any],
    path: str | Path = "<unknown>",
) -> list[str]:
    """Validate an MCP gateway config dict.

    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []

    if not isinstance(config, dict):
        return [f"MCP config at {path}: expected dict, got {type(config).__name__}"]

    # Required top-level keys.
    if "name" not in config:
        errors.append("missing required key 'name'")
    elif not isinstance(config["name"], str):
        errors.append("'name' must be a string")

    # Optional but typed.
    if "description" in config and not isinstance(config["description"], str):
        errors.append("'description' must be a string")
    if "nats_url" in config and not isinstance(config["nats_url"], str):
        errors.append("'nats_url' must be a string")

    # Tools section.
    tools = config.get("tools", {})
    if not isinstance(tools, dict):
        errors.append("'tools' must be a dict")
    else:
        errors.extend(_validate_worker_entries(tools.get("workers", [])))
        errors.extend(_validate_pipeline_entries(tools.get("pipelines", [])))
        errors.extend(_validate_query_entries(tools.get("queries", [])))
        errors.extend(_validate_workshop_config(tools.get("workshop")))
        errors.extend(_validate_session_config(tools.get("session")))

    # Resources section.
    resources = config.get("resources")
    if resources is not None:
        if not isinstance(resources, dict):
            errors.append("'resources' must be a dict")
        else:
            if "workspace_dir" not in resources:
                errors.append("resources: missing required key 'workspace_dir'")
            elif not isinstance(resources["workspace_dir"], str):
                errors.append("resources: 'workspace_dir' must be a string")
            patterns = resources.get("patterns")
            if patterns is not None and not isinstance(patterns, list):
                errors.append("resources: 'patterns' must be a list")

    return errors


def _validate_worker_entries(entries: Any) -> list[str]:
    """Validate the tools.workers list."""
    errors: list[str] = []
    if not isinstance(entries, list):
        return ["tools.workers must be a list"]

    for i, entry in enumerate(entries):
        prefix = f"tools.workers[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: expected dict")
            continue
        if "config" not in entry:
            errors.append(f"{prefix}: missing required key 'config'")
        elif not isinstance(entry["config"], str):
            errors.append(f"{prefix}: 'config' must be a string")
        # name, description, tier are all optional overrides.
        errors.extend(
            f"{prefix}: '{key}' must be a string"
            for key in ("name", "description", "tier")
            if key in entry and not isinstance(entry[key], str)
        )

    return errors


def _validate_pipeline_entries(entries: Any) -> list[str]:
    """Validate the tools.pipelines list."""
    errors: list[str] = []
    if not isinstance(entries, list):
        return ["tools.pipelines must be a list"]

    for i, entry in enumerate(entries):
        prefix = f"tools.pipelines[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: expected dict")
            continue
        if "config" not in entry:
            errors.append(f"{prefix}: missing required key 'config'")
        elif not isinstance(entry["config"], str):
            errors.append(f"{prefix}: 'config' must be a string")
        if "name" not in entry:
            errors.append(f"{prefix}: missing required key 'name'")
        elif not isinstance(entry["name"], str):
            errors.append(f"{prefix}: 'name' must be a string")
        if "description" in entry and not isinstance(entry["description"], str):
            errors.append(f"{prefix}: 'description' must be a string")

    return errors


def _validate_workshop_config(workshop: Any) -> list[str]:
    """Validate the tools.workshop section."""
    if workshop is None:
        return []
    errors: list[str] = []
    if not isinstance(workshop, dict):
        return ["tools.workshop must be a dict"]
    if "configs_dir" in workshop and not isinstance(workshop["configs_dir"], str):
        errors.append("tools.workshop: 'configs_dir' must be a string")
    if "apps_dir" in workshop and not isinstance(workshop["apps_dir"], str):
        errors.append("tools.workshop: 'apps_dir' must be a string")
    if "enable" in workshop:
        if not isinstance(workshop["enable"], list):
            errors.append("tools.workshop: 'enable' must be a list")
        else:
            valid_groups = {"worker", "test", "eval", "impact", "deadletter"}
            errors.extend(
                f"tools.workshop: unknown group '{item}' in 'enable' "
                f"(valid: {', '.join(sorted(valid_groups))})"
                for item in workshop["enable"]
                if item not in valid_groups
            )
    return errors


def _validate_session_config(session: Any) -> list[str]:
    """Validate the tools.session section."""
    if session is None:
        return []
    errors: list[str] = []
    if not isinstance(session, dict):
        return ["tools.session must be a dict"]
    errors.extend(
        f"tools.session: '{key}' must be a string"
        for key in ("framework_dir", "workspace_dir", "baft_dir", "nats_url", "ollama_url")
        if key in session and not isinstance(session[key], str)
    )
    if "enable" in session:
        if not isinstance(session["enable"], list):
            errors.append("tools.session: 'enable' must be a list")
        else:
            valid_actions = {"start", "end", "status", "sync_check", "sync"}
            errors.extend(
                f"tools.session: unknown action '{item}' in 'enable' "
                f"(valid: {', '.join(sorted(valid_actions))})"
                for item in session["enable"]
                if item not in valid_actions
            )
    return errors


def _validate_query_entries(entries: Any) -> list[str]:
    """Validate the tools.queries list."""
    errors: list[str] = []
    if not isinstance(entries, list):
        return ["tools.queries must be a list"]

    for i, entry in enumerate(entries):
        prefix = f"tools.queries[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: expected dict")
            continue
        if "backend" not in entry:
            errors.append(f"{prefix}: missing required key 'backend'")
        elif not isinstance(entry["backend"], str):
            errors.append(f"{prefix}: 'backend' must be a string")
        if "actions" not in entry:
            errors.append(f"{prefix}: missing required key 'actions'")
        elif not isinstance(entry["actions"], list):
            errors.append(f"{prefix}: 'actions' must be a list")
        if "name_prefix" not in entry:
            errors.append(f"{prefix}: missing required key 'name_prefix'")
        elif not isinstance(entry["name_prefix"], str):
            errors.append(f"{prefix}: 'name_prefix' must be a string")
        if "backend_config" in entry and not isinstance(entry["backend_config"], dict):
            errors.append(f"{prefix}: 'backend_config' must be a dict")

    return errors
