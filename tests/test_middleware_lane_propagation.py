"""Middleware-Lane keys travel across hops (DESIGN_INVARIANTS #22).

Every actor must preserve and propagate top-level ``_``-prefixed frame keys.
These tests pin the two shapes of hop:

- **Forward** (the router): the same message moves one hop, so the whole
  inbound frame is republished unchanged.
- **Respond** (a worker, or an orchestrator finishing a goal): a new message
  caused by an inbound one carries the inbound ``_`` keys on its frame.

Tracing is not active in these tests, so ``inject_trace_context`` is a no-op
and an inbound ``_trace_context`` must pass through untouched.
"""

from __future__ import annotations

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

    # Identity, causation, timestamps, every `_` key, and the body as
    # received (including a body key this version does not know).
    assert forwarded == data


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
    assert {k: v for k, v in published.items() if k.startswith("_")} == LANE


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
        assert {k: v for k, v in result.items() if k.startswith("_")} == LANE
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
    assert {k: v for k, v in result.items() if k.startswith("_")} == LANE


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
        assert {k: v for k, v in published.items() if k.startswith("_")} == LANE
    finally:
        os.unlink(fh.name)
