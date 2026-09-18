"""Tests for Event / Command wire bodies (wire-envelope S3a)."""

import pytest
from pydantic import ValidationError

from heddle.contrib.events.envelopes import (
    Command,
    CommandMetadata,
    Event,
    EventMetadata,
)


def _event_kwargs(**overrides):
    base = {
        "aggregate_type": "Job",
        "aggregate_id": "39174-004",
        "aggregate_version": 1,
        "event_type": "JobClockedIn",
        "metadata": EventMetadata(issued_by="user:badge:206"),
    }
    base.update(overrides)
    return base


def _command_kwargs(**overrides):
    base = {
        "aggregate_type": "Job",
        "aggregate_id": "39174-004",
        "command_type": "JobClockIn",
        "metadata": CommandMetadata(issued_by="user:badge:206"),
    }
    base.update(overrides)
    return base


def test_event_round_trip():
    env = Event(**_event_kwargs(payload={"badge": "206"}))
    restored = Event.model_validate_json(env.model_dump_json())
    assert restored == env


def test_event_requires_issued_by():
    with pytest.raises(ValidationError):
        EventMetadata()  # type: ignore[call-arg]


def test_event_event_id_defaults_to_uuid7():
    e1 = Event(**_event_kwargs())
    e2 = Event(**_event_kwargs())
    assert e1.event_id != e2.event_id
    # UUIDv7 is time-ordered — second id should sort >= first lexically.
    assert e2.event_id >= e1.event_id


def test_event_aggregate_version_minimum():
    with pytest.raises(ValidationError):
        Event(**_event_kwargs(aggregate_version=0))


def test_command_round_trip():
    cmd = Command(**_command_kwargs(payload={"badge": "206"}))
    restored = Command.model_validate_json(cmd.model_dump_json())
    assert restored == cmd


def test_command_expected_aggregate_version_optional():
    cmd = Command(**_command_kwargs(expected_aggregate_version=None))
    assert cmd.expected_aggregate_version is None
    cmd_with_cas = Command(**_command_kwargs(expected_aggregate_version=7))
    assert cmd_with_cas.expected_aggregate_version == 7


def test_command_metadata_issued_by_legacy_reserved():
    meta = CommandMetadata(issued_by="user:badge:206", issued_by_legacy="anything")
    assert meta.issued_by_legacy == "anything"
    # Default is None — reserved slot, no business logic.
    bare = CommandMetadata(issued_by="user:badge:206")
    assert bare.issued_by_legacy is None
