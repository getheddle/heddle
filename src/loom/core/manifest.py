"""
App manifest schema for Loom application bundles.

A Loom app is a ZIP archive containing worker/pipeline/scheduler configs,
optional scripts, and a ``manifest.yaml`` describing the app metadata and
entry points. Apps are deployed via the Workshop UI or CLI.

Manifest format::

    name: "myapp"
    version: "1.0.0"
    description: "My Loom application"
    loom_version: ">=0.4.0"
    required_extras: [duckdb, mcp]
    python_package:          # optional — for apps with Python code
      name: "myapp"
      install_path: "src/"
    entry_configs:
      workers:
        - config: "configs/workers/my_worker.yaml"
          tier: "standard"
      pipelines:
        - config: "configs/orchestrators/my_pipeline.yaml"
      schedulers:
        - config: "configs/schedulers/my_schedule.yaml"
      mcp:
        - config: "configs/mcp/my_mcp.yaml"
    scripts:
      - path: "scripts/setup.py"
        description: "Initial setup script"
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
import yaml
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()

# Known loom extras (from pyproject.toml optional-dependencies).
KNOWN_EXTRAS = frozenset(
    {"redis", "local", "docproc", "duckdb", "rag", "scheduler", "mcp", "workshop", "mdns"}
)


class PythonPackage(BaseModel):
    """Optional Python package included in the app bundle."""

    name: str
    install_path: str = "src/"


class EntryConfigRef(BaseModel):
    """Reference to a config file within the app bundle."""

    config: str
    tier: str | None = None
    name: str | None = None
    description: str | None = None


class EntryConfigs(BaseModel):
    """Entry point configurations that the app exposes."""

    workers: list[EntryConfigRef] = Field(default_factory=list)
    pipelines: list[EntryConfigRef] = Field(default_factory=list)
    schedulers: list[EntryConfigRef] = Field(default_factory=list)
    mcp: list[EntryConfigRef] = Field(default_factory=list)


class ScriptRef(BaseModel):
    """Reference to a script included in the app bundle."""

    path: str
    description: str = ""


class AppManifest(BaseModel):
    """Loom application manifest.

    Describes the contents and metadata of a Loom app bundle (ZIP archive).
    The manifest is stored as ``manifest.yaml`` at the root of the ZIP.
    """

    name: str
    version: str
    description: str
    loom_version: str = ">=0.4.0"
    required_extras: list[str] = Field(default_factory=list)
    python_package: PythonPackage | None = None
    entry_configs: EntryConfigs = Field(default_factory=EntryConfigs)
    scripts: list[ScriptRef] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """App name must be a valid identifier (lowercase, hyphens, underscores)."""
        import re

        if not re.match(r"^[a-z][a-z0-9_-]*$", v):
            msg = (
                f"App name '{v}' must start with a lowercase letter and contain "
                "only lowercase letters, digits, hyphens, and underscores"
            )
            raise ValueError(msg)
        return v

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Version must be semantic (major.minor.patch, optional pre-release)."""
        import re

        if not re.match(r"^\d+\.\d+\.\d+", v):
            msg = f"Version '{v}' must follow semantic versioning (e.g., '1.0.0')"
            raise ValueError(msg)
        return v


def _check_yaml_extension(
    refs: list[EntryConfigRef],
    kind: str,
    errors: list[str],
) -> None:
    """Check that all config refs end with .yaml."""
    errors.extend(
        f"{kind} config must be a .yaml file: {ref.config}"
        for ref in refs
        if not ref.config.endswith(".yaml")
    )


def validate_app_manifest(data: dict[str, Any]) -> list[str]:
    """Validate a manifest dict.

    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = [
        f"Missing required field: {f}" for f in ("name", "version", "description") if f not in data
    ]

    if errors:
        return errors

    # Try parsing with Pydantic
    try:
        manifest = AppManifest(**data)
    except Exception as e:
        errors.append(f"Manifest validation error: {e}")
        return errors

    # Warn about unknown extras (non-fatal)
    for extra in manifest.required_extras:
        if extra not in KNOWN_EXTRAS:
            logger.warning("manifest.unknown_extra", extra=extra, app=manifest.name)

    # Verify config file extensions
    _check_yaml_extension(manifest.entry_configs.workers, "Worker", errors)
    _check_yaml_extension(manifest.entry_configs.pipelines, "Pipeline", errors)
    _check_yaml_extension(manifest.entry_configs.schedulers, "Scheduler", errors)
    _check_yaml_extension(manifest.entry_configs.mcp, "MCP", errors)

    return errors


def load_manifest(path: Path) -> AppManifest:
    """Load and validate a manifest from a YAML file.

    Raises:
        FileNotFoundError: If the manifest file doesn't exist.
        ValueError: If the manifest is invalid.
    """
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        msg = f"Manifest must be a YAML mapping, got {type(data).__name__}"
        raise ValueError(msg)

    errors = validate_app_manifest(data)
    if errors:
        msg = f"Invalid manifest: {'; '.join(errors)}"
        raise ValueError(msg)

    return AppManifest(**data)
