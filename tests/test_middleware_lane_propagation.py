"""Middleware-Lane keys travel across hops (DESIGN_INVARIANTS #22).

Every actor must preserve and propagate top-level ``_``-prefixed frame keys.
These tests pin the two shapes of hop:

- **Forward** (the router): the same message moves one hop, so the whole
  inbound frame is republished unchanged.
- **Respond** (a worker, or an orchestrator finishing a goal): a new message
  caused by an inbound one carries the inbound ``_`` keys on its frame.

An earlier test may leave an OpenTelemetry provider installed, in which case
``inject_trace_context`` legitimately replaces ``_trace_context`` with the
current span. Assertions on ``_trace_context`` therefore check only that the
trace id survives (the span id may change); every other ``_`` key must match
exactly.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml

from heddle.bus.memory import InMemoryBus
from heddle.contrib.council.orchestrator import CouncilOrchestrator
from heddle.core.envelope import WireEnvelope, middleware_lane, wrap
from heddle.core.messages import (
    ModelTier,
    OrchestratorGoal,
    TaskMessage,
    TaskResult,
    TaskStatus,
)
from heddle.orchestrator.pipeline import PipelineOrchestrator
from heddle.orchestrator.runner import OrchestratorActor
from heddle.router.router import TaskRouter
from heddle.worker.processor import ProcessorWorker, SyncProcessingBackend

LANE: dict[str, Any] = {
    "_trace_context": {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
    "_x_custom": {"tenant": "acme"},
}


def _frame(payload_type: str, body: Any, **frame: Any) -> dict[str, Any]:
    return wrap(payload_type, body, **LANE, **frame).model_dump(mode="json")


def _trace_id(trace_context: dict[str, str]) -> str:
    return trace_context["traceparent"].split("-")[1]


def _assert_lane(published: dict[str, Any], *, same_trace: bool = True) -> None:
    """Every inbound `_` key is on ``published``; non-trace keys exactly.

    ``same_trace=False`` is for subtasks an orchestrator dispatches from its
    own dispatch/stage/turn span: called directly (no actor span extracting
    the inbound context), an installed provider gives that span a new trace.
    """
    lane = {k: v for k, v in published.items() if k.startswith("_")}
    assert set(lane) == set(LANE)
    assert {k: v for k, v in lane.items() if k != "_trace_context"} == {
        k: v for k, v in LANE.items() if k != "_trace_context"
    }
    if same_trace:
        assert _trace_id(lane["_trace_context"]) == _trace_id(LANE["_trace_context"])


def _write(tmp_path, name: str, config: dict[str, Any]) -> str:
    path = tmp_path / name
    path.write_text(yaml.dump(config))
    return str(path)


# --- helper ----------------------------------------------------------------


def test_middleware_lane_returns_only_underscore_keys_as_a_copy() -> None:
    envelope = WireEnvelope.model_validate(
        _frame("core.TaskMessage", TaskMessage(worker_type="w", input={}), origin="cli")
    )
    lane = middleware_lane(envelope)
    assert lane == LANE
    lane["_x_custom"] = "changed"
    assert envelope.model_extra is not None
    assert envelope.model_extra["_x_custom"] == {"tenant": "acme"}


# --- forward: router -------------------------------------------------------


@pytest.mark.asyncio
async def test_router_forwards_the_inbound_frame_unchanged(tmp_path) -> None:
    rules = _write(tmp_path, "rules.yaml", {"rate_limits": {"local": {"max_concurrent": 10}}})
    bus = InMemoryBus()
    router = TaskRouter(rules, bus)
    await bus.connect()
    sub = await bus.subscribe("heddle.tasks.summarizer.local")

    data = _frame(
        "core.TaskMessage",
        TaskMessage(worker_type="summarizer", input={"text": "hi"}, model_tier=ModelTier.LOCAL),
        origin="cli:test",
        correlation_id="corr-1",
        causation_id="cause-1",
    )
    data["payload"]["x_future_field"] = "kept by a forwarder"

    await router.route(data)
    forwarded = await sub.__anext__()

    # Identity, causation, timestamps and the body (including a body key this
    # version does not know) are unchanged; every `_` key travels.
    _assert_lane(forwarded)
    strip = lambda d: {k: v for k, v in d.items() if k != "_trace_context"}  # noqa: E731
    assert strip(forwarded) == strip(data)


@pytest.mark.asyncio
async def test_router_forwards_the_task_id_parse_generated(tmp_path) -> None:
    rules = _write(tmp_path, "rules.yaml", {"rate_limits": {"local": {"max_concurrent": 10}}})
    bus = InMemoryBus()
    router = TaskRouter(rules, bus)
    await bus.connect()
    sub = await bus.subscribe("heddle.tasks.summarizer.local")

    data = _frame(
        "core.TaskMessage",
        TaskMessage(worker_type="summarizer", input={}, model_tier=ModelTier.LOCAL),
    )
    del data["payload"]["task_id"]  # a producer that left it to the receiver

    await router.route(data)
    forwarded = await sub.__anext__()

    assert forwarded["payload"]["task_id"]  # filled, so router and worker agree


# --- respond: worker -------------------------------------------------------


class _Echo(SyncProcessingBackend):
    def process_sync(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        return {"output": {"echo": payload["text"]}, "model_used": None}


def _processor(tmp_path) -> ProcessorWorker:
    config = _write(
        tmp_path,
        "worker.yaml",
        {
            "name": "echo",
            "input_schema": {"type": "object", "required": ["text"]},
            "output_schema": {"type": "object"},
        },
    )
    worker = ProcessorWorker("echo-1", config, _Echo())
    worker.publish = AsyncMock()
    return worker


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("task_input", "status"),
    [({"text": "hi"}, TaskStatus.COMPLETED), ({}, TaskStatus.FAILED)],
    ids=["completed", "input-validation-failure"],
)
async def test_worker_result_carries_inbound_lane(tmp_path, task_input, status) -> None:
    worker = _processor(tmp_path)
    task = TaskMessage(worker_type="echo", input=task_input, model_tier=ModelTier.LOCAL)

    await worker.handle_message(_frame("core.TaskMessage", task))

    published = worker.publish.call_args[0][1]
    assert TaskResult(**published["payload"]).status == status
    _assert_lane(published)


@pytest.mark.asyncio
async def test_worker_without_lane_publishes_no_lane_keys(tmp_path) -> None:
    worker = _processor(tmp_path)
    task = TaskMessage(worker_type="echo", input={"text": "hi"}, model_tier=ModelTier.LOCAL)

    await worker.handle_message(wrap("core.TaskMessage", task).model_dump(mode="json"))

    published = worker.publish.call_args[0][1]
    assert not [k for k in published if k.startswith("_")]


# --- respond: orchestrators finishing a goal -------------------------------


@pytest.mark.asyncio
async def test_orchestrator_final_result_carries_goal_lane() -> None:
    from tests.test_orchestrator import MockOrchestratorBackend, _write_config

    config_path = _write_config()
    try:
        bus = InMemoryBus()
        actor = OrchestratorActor(
            actor_id="orch", config_path=config_path, backend=MockOrchestratorBackend("[]")
        )
        actor._bus = bus
        await bus.connect()
        goal = OrchestratorGoal(instruction="summarize")
        sub = await bus.subscribe(f"heddle.results.{goal.goal_id}")

        await actor.handle_message(_frame("core.OrchestratorGoal", goal))

        result = await sub.__anext__()
        assert result["payload"]["status"] == TaskStatus.FAILED.value
        _assert_lane(result)
    finally:
        os.unlink(config_path)


@pytest.mark.asyncio
async def test_pipeline_final_result_carries_goal_lane(tmp_path) -> None:
    # A stage whose input mapping points at a missing path fails fast and
    # publishes the pipeline's FAILED result.
    stages = [
        {
            "name": "A",
            "worker_type": "workerA",
            "tier": "local",
            "input_mapping": {"x": "goal.context.missing"},
        }
    ]
    config = _write(
        tmp_path, "pipeline.yaml", {"name": "p", "pipeline_stages": stages, "timeout_seconds": 2}
    )
    bus = InMemoryBus()
    orch = PipelineOrchestrator("pipe", config, bus=bus)
    await bus.connect()
    goal = OrchestratorGoal(instruction="run", context={})
    sub = await bus.subscribe(f"heddle.results.{goal.goal_id}")

    await orch.handle_message(_frame("core.OrchestratorGoal", goal))

    result = await sub.__anext__()
    assert result["payload"]["status"] == TaskStatus.FAILED.value
    _assert_lane(result)


@pytest.mark.asyncio
async def test_council_publish_result_carries_lane() -> None:
    from tests.contrib.council.test_orchestrator import MockFacilitatorBackend, _council_config

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        yaml.dump(_council_config(), fh)
    try:
        orch = CouncilOrchestrator(
            actor_id="council", config_path=fh.name, backend=MockFacilitatorBackend()
        )
        orch.publish = AsyncMock()
        goal = OrchestratorGoal(instruction="debate")

        await orch._publish_council_result(goal, TaskStatus.FAILED, error="x", lane=dict(LANE))

        published = orch.publish.call_args[0][1]
        _assert_lane(published)
    finally:
        os.unlink(fh.name)


# --- originate-from-goal: subtasks an orchestrator dispatches for a goal ---


async def _first_dispatched(bus: InMemoryBus, start: Any) -> dict[str, Any]:
    """Run ``start()`` in the background and return the first published task."""
    import asyncio

    sub = await bus.subscribe("heddle.tasks.incoming")
    runner = asyncio.create_task(start())
    try:
        return await asyncio.wait_for(sub.__anext__(), timeout=5)
    finally:
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await runner


@pytest.mark.asyncio
async def test_orchestrator_subtasks_carry_goal_lane() -> None:
    import json

    from tests.test_orchestrator import MockOrchestratorBackend, _write_config

    plan = json.dumps([{"worker_type": "summarizer", "payload": {"text": "t"}}])
    config_path = _write_config(timeout_seconds=2)
    try:
        bus = InMemoryBus()
        actor = OrchestratorActor(
            actor_id="orch", config_path=config_path, backend=MockOrchestratorBackend(plan)
        )
        actor._bus = bus
        await bus.connect()
        goal = OrchestratorGoal(instruction="summarize")

        task = await _first_dispatched(
            bus, lambda: actor.handle_message(_frame("core.OrchestratorGoal", goal))
        )

        assert task["payload_type"] == "core.TaskMessage"
        _assert_lane(task, same_trace=False)
    finally:
        os.unlink(config_path)


@pytest.mark.asyncio
async def test_pipeline_stage_tasks_carry_goal_lane(tmp_path) -> None:
    stages = [
        {
            "name": "A",
            "worker_type": "workerA",
            "tier": "local",
            "input_mapping": {"x": "goal.context.x"},
        }
    ]
    config = _write(
        tmp_path, "pipeline.yaml", {"name": "p", "pipeline_stages": stages, "timeout_seconds": 2}
    )
    bus = InMemoryBus()
    orch = PipelineOrchestrator("pipe", config, bus=bus)
    await bus.connect()
    goal = OrchestratorGoal(instruction="run", context={"x": "v"})

    task = await _first_dispatched(
        bus, lambda: orch.handle_message(_frame("core.OrchestratorGoal", goal))
    )

    assert task["payload"]["worker_type"] == "workerA"
    _assert_lane(task, same_trace=False)


@pytest.mark.asyncio
async def test_council_agent_turns_carry_goal_lane() -> None:
    from tests.contrib.council.test_orchestrator import MockFacilitatorBackend, _council_config

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        yaml.dump(_council_config(), fh)
    try:
        bus = InMemoryBus()
        await bus.connect()
        orch = CouncilOrchestrator(
            actor_id="council", config_path=fh.name, backend=MockFacilitatorBackend(), bus=bus
        )
        goal = OrchestratorGoal(instruction="debate")

        task = await _first_dispatched(
            bus, lambda: orch.handle_message(_frame("core.OrchestratorGoal", goal))
        )

        assert task["payload"]["metadata"]["council"]
        _assert_lane(task, same_trace=False)
    finally:
        os.unlink(fh.name)
