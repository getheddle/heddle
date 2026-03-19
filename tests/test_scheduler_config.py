"""Tests for scheduler configuration validation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from loom.scheduler.config import _validate_schedule_entry, validate_scheduler_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_config(**overrides):
    """Return a minimal valid scheduler config, merging any overrides."""
    cfg = {
        "name": "test-scheduler",
        "schedules": [],
    }
    cfg.update(overrides)
    return cfg


def _cron_entry(**overrides):
    """Return a minimal valid cron-based schedule entry."""
    entry = {
        "name": "every-minute",
        "dispatch_type": "goal",
        "cron": "* * * * *",
        "goal": {"instruction": "do something"},
    }
    entry.update(overrides)
    return entry


def _interval_entry(**overrides):
    """Return a minimal valid interval-based schedule entry."""
    entry = {
        "name": "every-30s",
        "dispatch_type": "task",
        "interval_seconds": 30,
        "task": {"worker_type": "summarizer"},
    }
    entry.update(overrides)
    return entry


# ---------------------------------------------------------------------------
# Top-level validation
# ---------------------------------------------------------------------------


class TestValidateSchedulerConfig:
    """Tests for validate_scheduler_config()."""

    def test_valid_config_with_cron(self):
        cfg = _base_config(schedules=[_cron_entry()])
        errors = validate_scheduler_config(cfg, "test.yaml")
        assert errors == []

    def test_valid_config_with_interval(self):
        cfg = _base_config(schedules=[_interval_entry()])
        errors = validate_scheduler_config(cfg, "test.yaml")
        assert errors == []

    def test_non_dict_top_level(self):
        errors = validate_scheduler_config("not-a-dict", "test.yaml")
        assert len(errors) == 1
        assert "expected dict" in errors[0]
        assert "str" in errors[0]

    def test_missing_top_level_name_and_schedules(self):
        errors = validate_scheduler_config({}, "test.yaml")
        assert len(errors) == 2
        keys_mentioned = {e.split("'")[1] for e in errors}
        assert keys_mentioned == {"name", "schedules"}

    def test_wrong_type_for_name(self):
        cfg = _base_config(name=123)
        errors = validate_scheduler_config(cfg, "test.yaml")
        assert any("'name' expected str" in e for e in errors)

    def test_wrong_type_for_schedules(self):
        cfg = _base_config(schedules="not-a-list")
        errors = validate_scheduler_config(cfg, "test.yaml")
        assert any("'schedules' expected list" in e for e in errors)


# ---------------------------------------------------------------------------
# Timing mutual exclusivity — parametrized
# ---------------------------------------------------------------------------


class TestTimingMutualExclusivity:
    """Exactly one of 'cron' or 'interval_seconds' must be present."""

    @pytest.mark.parametrize(
        ("extra_keys", "should_error", "snippet"),
        [
            pytest.param(
                {"cron": "* * * * *"},
                False,
                None,
                id="cron-only-ok",
            ),
            pytest.param(
                {"interval_seconds": 60},
                False,
                None,
                id="interval-only-ok",
            ),
            pytest.param(
                {"cron": "* * * * *", "interval_seconds": 60},
                True,
                "cannot specify both",
                id="both-error",
            ),
            pytest.param(
                {},
                True,
                "must specify either",
                id="neither-error",
            ),
        ],
    )
    def test_timing_combinations(self, extra_keys, should_error, snippet):
        entry = {
            "name": "t",
            "dispatch_type": "goal",
            "goal": {"instruction": "x"},
            **extra_keys,
        }
        errors = _validate_schedule_entry(entry, 0, "test.yaml")
        timing_errors = [e for e in errors if "cron" in e or "interval" in e]
        if should_error:
            assert any(snippet in e for e in timing_errors)
        else:
            assert timing_errors == []


# ---------------------------------------------------------------------------
# Entry-level validation
# ---------------------------------------------------------------------------


class TestValidateScheduleEntry:
    """Tests for _validate_schedule_entry()."""

    def test_non_dict_entry(self):
        errors = _validate_schedule_entry("not-a-dict", 0, "test.yaml")
        assert len(errors) == 1
        assert "expected dict" in errors[0]

    def test_missing_name_in_entry(self):
        entry = _cron_entry()
        del entry["name"]
        errors = _validate_schedule_entry(entry, 0, "test.yaml")
        assert any("missing required key 'name'" in e for e in errors)

    def test_missing_dispatch_type(self):
        entry = _cron_entry()
        del entry["dispatch_type"]
        errors = _validate_schedule_entry(entry, 0, "test.yaml")
        assert any("missing required key 'dispatch_type'" in e for e in errors)

    def test_invalid_dispatch_type(self):
        entry = _cron_entry(dispatch_type="invalid")
        errors = _validate_schedule_entry(entry, 0, "test.yaml")
        assert any("'dispatch_type' must be 'goal' or 'task'" in e for e in errors)

    def test_invalid_cron_expression(self):
        entry = _cron_entry(cron="not-a-cron")
        errors = _validate_schedule_entry(entry, 0, "test.yaml")
        assert any("invalid cron expression" in e for e in errors)

    def test_negative_interval(self):
        entry = _interval_entry(interval_seconds=-5)
        errors = _validate_schedule_entry(entry, 0, "test.yaml")
        assert any("'interval_seconds' must be a positive number" in e for e in errors)

    def test_string_interval(self):
        entry = _interval_entry(interval_seconds="sixty")
        errors = _validate_schedule_entry(entry, 0, "test.yaml")
        assert any("'interval_seconds' must be a positive number" in e for e in errors)

    def test_zero_interval(self):
        entry = _interval_entry(interval_seconds=0)
        errors = _validate_schedule_entry(entry, 0, "test.yaml")
        assert any("'interval_seconds' must be a positive number" in e for e in errors)

    # -- dispatch-specific: goal ------------------------------------------------

    def test_goal_missing_goal_dict(self):
        entry = _cron_entry(dispatch_type="goal")
        del entry["goal"]
        errors = _validate_schedule_entry(entry, 0, "test.yaml")
        assert any("requires a 'goal' dict" in e for e in errors)

    def test_goal_missing_instruction(self):
        entry = _cron_entry(dispatch_type="goal", goal={"context": {}})
        errors = _validate_schedule_entry(entry, 0, "test.yaml")
        assert any("goal config missing 'instruction'" in e for e in errors)

    # -- dispatch-specific: task ------------------------------------------------

    def test_task_missing_task_dict(self):
        entry = _interval_entry(dispatch_type="task")
        del entry["task"]
        errors = _validate_schedule_entry(entry, 0, "test.yaml")
        assert any("requires a 'task' dict" in e for e in errors)

    def test_task_missing_worker_type(self):
        entry = _interval_entry(dispatch_type="task", task={"timeout": 30})
        errors = _validate_schedule_entry(entry, 0, "test.yaml")
        assert any("task config missing 'worker_type'" in e for e in errors)

    # -- croniter import failure ------------------------------------------------

    def test_cron_without_croniter(self):
        entry = _cron_entry()
        with (
            patch.dict("sys.modules", {"croniter": None}),
            # Force ImportError on `from croniter import croniter`
            patch(
                "loom.scheduler.config.croniter",
                side_effect=ImportError,
                create=True,
            ),
        ):
            # Reimport isn't needed; the function does a local import.
            # We patch builtins __import__ to raise for croniter.
            original_import = (
                __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
            )

            def _fake_import(name, *args, **kwargs):
                if name == "croniter":
                    raise ImportError("no croniter")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=_fake_import):
                errors = _validate_schedule_entry(entry, 0, "test.yaml")

        assert any("croniter package" in e for e in errors)

    def test_error_prefix_includes_index(self):
        """Error messages include the schedule index for debugging."""
        entry = _cron_entry()
        del entry["name"]
        errors = _validate_schedule_entry(entry, 3, "test.yaml")
        assert any("schedules[3]" in e for e in errors)
