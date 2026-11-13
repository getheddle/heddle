"""Tests for ``tools/check_release_cadence.py`` (docs/RELEASING.md cadence)."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "tools/check_release_cadence.py"
_spec = importlib.util.spec_from_file_location("check_release_cadence", _PATH)
assert _spec is not None
assert _spec.loader is not None
cadence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cadence)

T0 = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
TAGS = [("v0.12.0", T0 - timedelta(days=1)), ("v0.13.0", T0)]

CHANGELOG = """# Changelog

## [Unreleased]

## [0.13.1] — 2026-11-10

Urgent release: security fix for the router.

### Fixed

- Something.

## [0.14.0] — 2026-11-10

### Added

- Something.

## [0.13.0] — 2026-11-08
"""


def test_release_after_two_weeks_passes() -> None:
    ok, message = cadence.check("v0.14.0", TAGS, CHANGELOG, T0 + timedelta(days=14))
    assert ok
    assert "v0.13.0" in message


def test_early_release_without_marker_fails() -> None:
    ok, message = cadence.check("v0.14.0", TAGS, CHANGELOG, T0 + timedelta(days=2))
    assert not ok
    assert "Urgent release:" in message


def test_early_release_with_marker_passes() -> None:
    ok, message = cadence.check("v0.13.1", TAGS, CHANGELOG, T0 + timedelta(days=2))
    assert ok
    assert "security fix" in message


def test_existing_tag_is_measured_against_the_one_before_it() -> None:
    tags = [*TAGS, ("v0.14.0", T0 + timedelta(days=20))]
    ok, _ = cadence.check("v0.14.0", tags, CHANGELOG, T0 + timedelta(days=20))
    assert ok


def test_empty_marker_does_not_count() -> None:
    changelog = "## [0.14.0] — 2026-11-10\n\nUrgent release:\n"
    ok, _ = cadence.check("v0.14.0", TAGS, changelog, T0 + timedelta(days=2))
    assert not ok


def test_marker_in_another_section_does_not_count() -> None:
    # 0.13.1 carries the marker; 0.14.0 does not.
    ok, _ = cadence.check("v0.14.0", TAGS, CHANGELOG, T0 + timedelta(days=2))
    assert not ok


def test_first_release_passes() -> None:
    ok, _ = cadence.check("v0.1.0", [], "", T0)
    assert ok
