"""
Configuration loading utilities.

All Loom configs are YAML files. Worker configs define system prompts,
I/O schemas, timeouts, and backend settings. See configs/workers/_template.yaml
for the canonical config structure.

TODO: Add schema validation for config files themselves (currently any YAML
      is accepted, and missing keys only surface at runtime).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML config file and return as a dict.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        yaml.YAMLError: If the file contains invalid YAML.
    """
    with open(path) as f:
        return yaml.safe_load(f)
