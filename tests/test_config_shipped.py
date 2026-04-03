"""Validate all shipped config files at build time.

This test ensures that every YAML config file shipped in configs/ is
structurally valid according to its config type's validator. It runs
as part of the standard test suite — no infrastructure needed.

If a config file is added or modified and fails validation, this test
will catch it before CI merges the change.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from heddle.core.config import (
    validate_orchestrator_config,
    validate_pipeline_config,
    validate_router_rules,
    validate_worker_config,
)
from heddle.scheduler.config import validate_scheduler_config

# Root of the configs directory (relative to repo root).
CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def _load_yaml(path: Path) -> dict:
    """Load a YAML file and return as dict."""
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Worker configs
# ---------------------------------------------------------------------------

_WORKER_CONFIGS = sorted(CONFIGS_DIR.glob("workers/*.yaml"))
# Exclude template — it has placeholder values that won't validate as a real worker.
_WORKER_CONFIGS = [p for p in _WORKER_CONFIGS if p.name != "_template.yaml"]


@pytest.mark.parametrize(
    "config_path",
    _WORKER_CONFIGS,
    ids=[p.name for p in _WORKER_CONFIGS],
)
def test_worker_config_valid(config_path: Path):
    """Every shipped worker config must pass validation."""
    cfg = _load_yaml(config_path)
    errors = validate_worker_config(cfg, config_path)
    assert errors == [], f"Validation errors in {config_path.name}:\n" + "\n".join(
        f"  - {e}" for e in errors
    )


# ---------------------------------------------------------------------------
# Pipeline configs
# ---------------------------------------------------------------------------


def _is_pipeline_config(path: Path) -> bool:
    """Check if a config file is a pipeline config (has pipeline_stages)."""
    try:
        cfg = _load_yaml(path)
        return isinstance(cfg, dict) and "pipeline_stages" in cfg
    except Exception:
        return False


_PIPELINE_CONFIGS = [
    p
    for p in sorted(CONFIGS_DIR.glob("orchestrators/*.yaml"))
    if "pipeline" in p.name.lower() or _is_pipeline_config(p)
]


@pytest.mark.parametrize(
    "config_path",
    _PIPELINE_CONFIGS,
    ids=[p.name for p in _PIPELINE_CONFIGS],
)
def test_pipeline_config_valid(config_path: Path):
    """Every shipped pipeline config must pass validation."""
    cfg = _load_yaml(config_path)
    errors = validate_pipeline_config(cfg, config_path)
    assert errors == [], f"Validation errors in {config_path.name}:\n" + "\n".join(
        f"  - {e}" for e in errors
    )


# ---------------------------------------------------------------------------
# Orchestrator configs (non-pipeline)
# ---------------------------------------------------------------------------

_ORCHESTRATOR_CONFIGS = [
    p for p in sorted(CONFIGS_DIR.glob("orchestrators/*.yaml")) if p not in _PIPELINE_CONFIGS
]


@pytest.mark.parametrize(
    "config_path",
    _ORCHESTRATOR_CONFIGS,
    ids=[p.name for p in _ORCHESTRATOR_CONFIGS],
)
def test_orchestrator_config_valid(config_path: Path):
    """Every shipped orchestrator config must pass validation."""
    cfg = _load_yaml(config_path)
    errors = validate_orchestrator_config(cfg, config_path)
    assert errors == [], f"Validation errors in {config_path.name}:\n" + "\n".join(
        f"  - {e}" for e in errors
    )


# ---------------------------------------------------------------------------
# Scheduler configs
# ---------------------------------------------------------------------------

_SCHEDULER_CONFIGS = sorted(CONFIGS_DIR.glob("schedulers/*.yaml"))


@pytest.mark.parametrize(
    "config_path",
    _SCHEDULER_CONFIGS,
    ids=[p.name for p in _SCHEDULER_CONFIGS],
)
def test_scheduler_config_valid(config_path: Path):
    """Every shipped scheduler config must pass validation."""
    cfg = _load_yaml(config_path)
    errors = validate_scheduler_config(cfg, config_path)
    assert errors == [], f"Validation errors in {config_path.name}:\n" + "\n".join(
        f"  - {e}" for e in errors
    )


# ---------------------------------------------------------------------------
# Router rules
# ---------------------------------------------------------------------------


def test_router_rules_valid():
    """The shipped router_rules.yaml must pass validation."""
    path = CONFIGS_DIR / "router_rules.yaml"
    if not path.exists():
        pytest.skip("No router_rules.yaml shipped")
    cfg = _load_yaml(path)
    errors = validate_router_rules(cfg, path)
    assert errors == [], "Validation errors in router_rules.yaml:\n" + "\n".join(
        f"  - {e}" for e in errors
    )


# ---------------------------------------------------------------------------
# MCP configs
# ---------------------------------------------------------------------------

_MCP_CONFIGS = sorted(CONFIGS_DIR.glob("mcp/*.yaml"))


@pytest.mark.parametrize(
    "config_path",
    _MCP_CONFIGS,
    ids=[p.name for p in _MCP_CONFIGS],
)
def test_mcp_config_valid(config_path: Path):
    """Every shipped MCP config must pass validation."""
    from heddle.mcp.config import validate_mcp_config

    cfg = _load_yaml(config_path)
    errors = validate_mcp_config(cfg, config_path)
    assert errors == [], f"Validation errors in {config_path.name}:\n" + "\n".join(
        f"  - {e}" for e in errors
    )


# ---------------------------------------------------------------------------
# YAML parse safety
# ---------------------------------------------------------------------------


def test_all_configs_are_valid_yaml():
    """Every .yaml file in configs/ must be parseable YAML."""
    all_yamls = sorted(CONFIGS_DIR.rglob("*.yaml"))
    assert len(all_yamls) > 0, "No YAML files found in configs/"

    for path in all_yamls:
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            assert isinstance(data, dict), f"{path.name}: expected dict, got {type(data).__name__}"
        except yaml.YAMLError as e:
            pytest.fail(f"{path.name}: invalid YAML — {e}")
