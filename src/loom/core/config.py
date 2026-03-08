"""
Configuration loading utilities.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML config file."""
    with open(path) as f:
        return yaml.safe_load(f)
