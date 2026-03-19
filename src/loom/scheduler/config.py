"""
Scheduler configuration validation.

Validates the YAML config structure at startup to catch common mistakes
(missing fields, mutually exclusive options, invalid values) before the
scheduler begins its timer loop.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

_SCHEDULER_REQUIRED: dict[str, type | None] = {
    "name": str,
    "schedules": list,
}

_VALID_DISPATCH_TYPES = {"goal", "task"}
_VALID_PRIORITIES = {"low", "normal", "high", "critical"}
_VALID_TIERS = {"local", "standard", "frontier"}


def validate_scheduler_config(
    config: dict[str, Any],
    path: str = "<unknown>",
) -> list[str]:
    """Validate a scheduler config dict.  Returns list of error strings."""
    errors: list[str] = []

    if not isinstance(config, dict):
        return [f"scheduler config at {path}: expected dict, got {type(config).__name__}"]

    for key, expected_type in _SCHEDULER_REQUIRED.items():
        if key not in config:
            errors.append(f"scheduler config at {path}: missing required key '{key}'")
        elif expected_type is not None and not isinstance(config[key], expected_type):
            errors.append(
                f"scheduler config at {path}: key '{key}' expected "
                f"{expected_type.__name__}, got {type(config[key]).__name__}"
            )

    for i, entry in enumerate(config.get("schedules", [])):
        errors.extend(_validate_schedule_entry(entry, i, path))

    return errors


def _validate_schedule_entry(  # noqa: PLR0912
    entry: Any,
    index: int,
    path: str,
) -> list[str]:
    """Validate a single schedule entry."""
    errors: list[str] = []
    prefix = f"scheduler config at {path}: schedules[{index}]"

    if not isinstance(entry, dict):
        return [f"{prefix}: expected dict, got {type(entry).__name__}"]

    # Required fields
    if "name" not in entry:
        errors.append(f"{prefix}: missing required key 'name'")
    if "dispatch_type" not in entry:
        errors.append(f"{prefix}: missing required key 'dispatch_type'")

    # Timing: exactly one of cron or interval_seconds
    has_cron = "cron" in entry
    has_interval = "interval_seconds" in entry
    if has_cron and has_interval:
        errors.append(f"{prefix}: cannot specify both 'cron' and 'interval_seconds'")
    elif not has_cron and not has_interval:
        errors.append(f"{prefix}: must specify either 'cron' or 'interval_seconds'")

    if has_cron:
        try:
            from croniter import croniter

            croniter(entry["cron"])
        except (ValueError, KeyError) as exc:
            errors.append(f"{prefix}: invalid cron expression '{entry.get('cron')}': {exc}")
        except ImportError:
            errors.append(
                f"{prefix}: 'cron' requires the croniter package. "
                f"Install with: pip install loom[scheduler]"
            )

    if has_interval:
        val = entry["interval_seconds"]
        if not isinstance(val, (int, float)) or val <= 0:
            errors.append(f"{prefix}: 'interval_seconds' must be a positive number")

    # Dispatch type
    dispatch_type = entry.get("dispatch_type")
    if dispatch_type and dispatch_type not in _VALID_DISPATCH_TYPES:
        errors.append(f"{prefix}: 'dispatch_type' must be 'goal' or 'task', got '{dispatch_type}'")

    # Dispatch-specific validation
    if dispatch_type == "goal":
        goal_cfg = entry.get("goal")
        if not goal_cfg or not isinstance(goal_cfg, dict):
            errors.append(f"{prefix}: dispatch_type 'goal' requires a 'goal' dict")
        elif "instruction" not in goal_cfg:
            errors.append(f"{prefix}: goal config missing 'instruction'")

    if dispatch_type == "task":
        task_cfg = entry.get("task")
        if not task_cfg or not isinstance(task_cfg, dict):
            errors.append(f"{prefix}: dispatch_type 'task' requires a 'task' dict")
        elif "worker_type" not in task_cfg:
            errors.append(f"{prefix}: task config missing 'worker_type'")

    return errors
