"""Tests for RejectionLog ABC + InMemoryRejectionLog (wire-envelope S3a)."""

from __future__ import annotations

import json

import pytest

from heddle.contrib.events.envelopes import Command, CommandMetadata
from heddle.contrib.events.rejection_log import (
    InMemoryRejectionLog,
    Rejection,
)
from heddle.core.envelope import WireEnvelope, unwrap, wrap


def _cmd(
    *,
    aggregate_type: str = "Job",
    aggregate_id: str = "39174-004",
    command_type: str = "ClockIn",
) -> Command:
    return Command(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        command_type=command_type,
        payload={"badge": "206"},
        metadata=CommandMetadata(issued_by="user:badge:206"),
    )


def _rej(cmd: Command, *, reason: str = "INVALID", detail: str = "") -> WireEnvelope:
    body = Rejection(command=cmd, reason=reason, detail=detail)
    return wrap("events.Rejection", body)


def _body(envelope: WireEnvelope) -> Rejection:
    body = unwrap(envelope)
    assert isinstance(body, Rejection)
    return body


@pytest.mark.asyncio
async def test_append_then_load_round_trip() -> None:
    log = InMemoryRejectionLog()
    cmd = _cmd()
    await log.append(_rej(cmd, reason="INVALID", detail="phase=finalized"))

    loaded = [_body(r) async for r in log.load("Job")]
    assert len(loaded) == 1
    assert loaded[0].reason == "INVALID"
    assert loaded[0].detail == "phase=finalized"
    assert loaded[0].command.command_id == cmd.command_id


@pytest.mark.asyncio
async def test_filter_by_aggregate_type() -> None:
    log = InMemoryRejectionLog()
    await log.append(_rej(_cmd(aggregate_type="Job")))
    await log.append(_rej(_cmd(aggregate_type="Operation")))

    jobs = [_body(r) async for r in log.load("Job")]
    ops = [_body(r) async for r in log.load("Operation")]
    assert len(jobs) == 1
    assert len(ops) == 1
    assert jobs[0].command.aggregate_type == "Job"
    assert ops[0].command.aggregate_type == "Operation"


@pytest.mark.asyncio
async def test_filter_by_aggregate_id_when_supplied() -> None:
    log = InMemoryRejectionLog()
    await log.append(_rej(_cmd(aggregate_id="a-1")))
    await log.append(_rej(_cmd(aggregate_id="a-2")))

    a1 = [_body(r) async for r in log.load("Job", "a-1")]
    a2 = [_body(r) async for r in log.load("Job", "a-2")]
    assert [r.command.aggregate_id for r in a1] == ["a-1"]
    assert [r.command.aggregate_id for r in a2] == ["a-2"]


@pytest.mark.asyncio
async def test_aggregate_id_none_returns_all_of_type() -> None:
    log = InMemoryRejectionLog()
    await log.append(_rej(_cmd(aggregate_id="a-1")))
    await log.append(_rej(_cmd(aggregate_id="a-2")))

    rows = [_body(r) async for r in log.load("Job", None)]
    assert {r.command.aggregate_id for r in rows} == {"a-1", "a-2"}


def test_envelope_serialises_to_json() -> None:
    env = _rej(_cmd(), reason="X", detail="y")
    blob = env.model_dump_json()
    parsed = json.loads(blob)
    body_parsed = parsed["payload"]
    assert body_parsed["reason"] == "X"
    assert body_parsed["detail"] == "y"
    assert body_parsed["command"]["aggregate_type"] == "Job"

    # Round-trip via Pydantic preserves equality at the model level.
    restored = WireEnvelope.model_validate_json(blob)
    restored_body = _body(restored)
    original_body = _body(env)
    assert restored_body.reason == original_body.reason
    assert restored_body.command.command_id == original_body.command.command_id
