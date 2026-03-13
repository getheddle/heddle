"""
Unit tests for OrchestratorActor (orchestrator/runner.py).

Tests cover:
- GoalState: all_collected, pending_count properties
- OrchestratorActor lifecycle: decompose → dispatch → collect → synthesize
- Timeout and partial collection behaviour
- Checkpoint triggering
- Error handling (parse errors, decomposition failure)
- Concurrent goal processing (max_concurrent_goals)

All tests use InMemoryBus -- no NATS or external infrastructure required.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from typing import Any

import pytest
import yaml

from loom.bus.memory import InMemoryBus
from loom.core.messages import (
    ModelTier,
    OrchestratorGoal,
    TaskMessage,
    TaskResult,
    TaskStatus,
)
from loom.orchestrator.runner import GoalState, OrchestratorActor
from loom.orchestrator.store import InMemoryCheckpointStore
from loom.worker.backends import LLMBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockOrchestratorBackend(LLMBackend):
    """Returns configurable responses depending on system prompt content."""

    def __init__(self, decompose_response: str, synthesis_response: str = "{}"):
        self._decompose = decompose_response
        self._synthesis = synthesis_response

    async def complete(self, system_prompt, user_message, max_tokens, temperature, **kw):
        # Route to decomposition or synthesis based on system prompt
        if "task decomposition" in system_prompt.lower():
            content = self._decompose
        else:
            content = self._synthesis
        return {
            "content": content,
            "model": "mock-orch",
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }


def _write_config(
    available_workers: list[dict] | None = None,
    timeout_seconds: int = 5,
    max_concurrent_goals: int | None = None,
) -> str:
    """Write a minimal orchestrator config to a temp file."""
    config = {
        "name": "test-orchestrator",
        "timeout_seconds": timeout_seconds,
        "max_concurrent_tasks": 5,
        "available_workers": available_workers or [
            {
                "name": "summarizer",
                "description": "Summarizes text",
                "input_schema": {"type": "object", "required": ["text"]},
                "default_model_tier": "local",
            },
        ],
    }
    if max_concurrent_goals is not None:
        config["max_concurrent_goals"] = max_concurrent_goals
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump(config, f)
    return path


def _make_goal_data(instruction: str = "Summarize this document") -> dict[str, Any]:
    goal = OrchestratorGoal(instruction=instruction, context={"text": "Hello world"})
    return goal.model_dump(mode="json")


def _make_result_data(
    task_id: str,
    worker_type: str = "summarizer",
    status: TaskStatus = TaskStatus.COMPLETED,
    output: dict | None = None,
) -> dict[str, Any]:
    result = TaskResult(
        task_id=task_id,
        worker_type=worker_type,
        status=status,
        output=output or {"summary": "Test summary"},
        model_used="mock",
        processing_time_ms=100,
        token_usage={"prompt_tokens": 50, "completion_tokens": 30},
    )
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# GoalState tests
# ---------------------------------------------------------------------------


class TestGoalState:
    def test_all_collected_false_when_empty(self):
        goal = OrchestratorGoal(instruction="test")
        state = GoalState(goal=goal)
        assert state.all_collected is False

    def test_all_collected_false_when_partial(self):
        goal = OrchestratorGoal(instruction="test")
        state = GoalState(goal=goal)
        task = TaskMessage(worker_type="summarizer", payload={})
        state.dispatched_tasks[task.task_id] = task
        assert state.all_collected is False

    def test_all_collected_true_when_complete(self):
        goal = OrchestratorGoal(instruction="test")
        state = GoalState(goal=goal)

        task = TaskMessage(worker_type="summarizer", payload={})
        state.dispatched_tasks[task.task_id] = task

        result = TaskResult(
            task_id=task.task_id,
            worker_type="summarizer",
            status=TaskStatus.COMPLETED,
            output={"data": "test"},
        )
        state.collected_results[task.task_id] = result

        assert state.all_collected is True

    def test_pending_count(self):
        goal = OrchestratorGoal(instruction="test")
        state = GoalState(goal=goal)

        for i in range(3):
            task = TaskMessage(worker_type="summarizer", payload={})
            state.dispatched_tasks[task.task_id] = task

        assert state.pending_count == 3

        # Collect one result
        first_id = list(state.dispatched_tasks.keys())[0]
        state.collected_results[first_id] = TaskResult(
            task_id=first_id,
            worker_type="summarizer",
            status=TaskStatus.COMPLETED,
            output={},
        )
        assert state.pending_count == 2

    def test_start_time_is_set(self):
        goal = OrchestratorGoal(instruction="test")
        before = time.monotonic()
        state = GoalState(goal=goal)
        after = time.monotonic()
        assert before <= state.start_time <= after


# ---------------------------------------------------------------------------
# OrchestratorActor handle_message tests
# ---------------------------------------------------------------------------


class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_invalid_goal_data_does_not_crash(self):
        """Malformed goal data is handled gracefully."""
        config_path = _write_config()
        try:
            backend = MockOrchestratorBackend("[]")
            bus = InMemoryBus()
            actor = OrchestratorActor(
                actor_id="test-orch",
                config_path=config_path,
                backend=backend,
                nats_url="nats://localhost:4222",
            )
            actor._bus = bus
            await bus.connect()

            # Pass garbage -- should not raise
            await actor.handle_message({"invalid": True})
        finally:
            os.unlink(config_path)

    @pytest.mark.asyncio
    async def test_empty_decomposition_publishes_failure(self):
        """When decomposition produces no subtasks, a FAILED result is published."""
        config_path = _write_config()
        try:
            backend = MockOrchestratorBackend("[]")  # Empty plan
            bus = InMemoryBus()
            actor = OrchestratorActor(
                actor_id="test-orch",
                config_path=config_path,
                backend=backend,
            )
            actor._bus = bus
            await bus.connect()

            goal_data = _make_goal_data()
            goal_id = goal_data["goal_id"]
            sub = await bus.subscribe(f"loom.results.{goal_id}")

            await actor.handle_message(goal_data)

            result = await sub.__anext__()
            assert result["status"] == TaskStatus.FAILED.value
            assert "no subtasks" in result["error"].lower()
        finally:
            os.unlink(config_path)

    @pytest.mark.asyncio
    async def test_goal_state_cleaned_up_after_completion(self):
        """Goal state is removed from _active_goals after processing."""
        config_path = _write_config(timeout_seconds=1)
        try:
            # Return a valid subtask plan
            plan = json.dumps([{
                "worker_type": "summarizer",
                "payload": {"text": "test"},
            }])
            backend = MockOrchestratorBackend(plan)
            bus = InMemoryBus()
            actor = OrchestratorActor(
                actor_id="test-orch",
                config_path=config_path,
                backend=backend,
            )
            actor._bus = bus
            await bus.connect()

            goal_data = _make_goal_data()
            # Will timeout on collection since no worker responds, but state
            # should be cleaned up regardless
            await actor.handle_message(goal_data)

            assert len(actor._active_goals) == 0
        finally:
            os.unlink(config_path)


# ---------------------------------------------------------------------------
# _record_in_history tests
# ---------------------------------------------------------------------------


class TestRecordInHistory:
    @pytest.mark.asyncio
    async def test_history_accumulates(self):
        config_path = _write_config()
        try:
            backend = MockOrchestratorBackend("[]")
            actor = OrchestratorActor(
                actor_id="test-orch",
                config_path=config_path,
                backend=backend,
            )

            goal = OrchestratorGoal(instruction="Test goal")
            results = [
                TaskResult(
                    task_id="t1",
                    worker_type="summarizer",
                    status=TaskStatus.COMPLETED,
                    output={"summary": "done"},
                    processing_time_ms=100,
                ),
            ]
            synthesis = {"confidence": "high"}

            await actor._record_in_history(goal, results, synthesis)
            assert len(actor._conversation_history) == 1

            entry = actor._conversation_history[0]
            assert entry["goal_id"] == goal.goal_id
            assert entry["subtask_count"] == 1
            assert entry["synthesis_confidence"] == "high"
        finally:
            os.unlink(config_path)

    @pytest.mark.asyncio
    async def test_history_records_failures(self):
        config_path = _write_config()
        try:
            backend = MockOrchestratorBackend("[]")
            actor = OrchestratorActor(
                actor_id="test-orch",
                config_path=config_path,
                backend=backend,
            )

            goal = OrchestratorGoal(instruction="Test")
            results = [
                TaskResult(
                    task_id="t1",
                    worker_type="summarizer",
                    status=TaskStatus.FAILED,
                    error="timeout",
                    processing_time_ms=0,
                ),
            ]
            await actor._record_in_history(goal, results, {})

            entry = actor._conversation_history[0]
            assert entry["results"][0]["error"] == "timeout"
        finally:
            os.unlink(config_path)


# ---------------------------------------------------------------------------
# Concurrent goal processing tests
# ---------------------------------------------------------------------------


class TestConcurrentGoals:
    @pytest.mark.asyncio
    async def test_default_max_concurrent_goals_is_one(self):
        """Without config, max_concurrent_goals defaults to 1."""
        config_path = _write_config()
        try:
            backend = MockOrchestratorBackend("[]")
            actor = OrchestratorActor(
                actor_id="test-orch",
                config_path=config_path,
                backend=backend,
            )
            assert actor.max_concurrent == 1
        finally:
            os.unlink(config_path)

    @pytest.mark.asyncio
    async def test_max_concurrent_goals_from_config(self):
        """Config value is passed through to BaseActor.max_concurrent."""
        config_path = _write_config(max_concurrent_goals=4)
        try:
            backend = MockOrchestratorBackend("[]")
            actor = OrchestratorActor(
                actor_id="test-orch",
                config_path=config_path,
                backend=backend,
            )
            assert actor.max_concurrent == 4
        finally:
            os.unlink(config_path)

    @pytest.mark.asyncio
    async def test_concurrent_record_in_history_no_lost_writes(self):
        """Concurrent _record_in_history calls produce no lost writes."""
        config_path = _write_config(max_concurrent_goals=4)
        try:
            backend = MockOrchestratorBackend("[]")
            actor = OrchestratorActor(
                actor_id="test-orch",
                config_path=config_path,
                backend=backend,
            )

            async def record_one(i: int):
                goal = OrchestratorGoal(instruction=f"Goal {i}")
                results = [
                    TaskResult(
                        task_id=f"t{i}",
                        worker_type="summarizer",
                        status=TaskStatus.COMPLETED,
                        output={"n": i},
                        processing_time_ms=10,
                    ),
                ]
                await actor._record_in_history(goal, results, {"confidence": "high"})

            # Fire 20 concurrent writes
            await asyncio.gather(*(record_one(i) for i in range(20)))

            assert len(actor._conversation_history) == 20
        finally:
            os.unlink(config_path)

    @pytest.mark.asyncio
    async def test_bus_injection_via_constructor(self):
        """The bus= keyword argument is forwarded to BaseActor."""
        config_path = _write_config()
        try:
            backend = MockOrchestratorBackend("[]")
            bus = InMemoryBus()
            actor = OrchestratorActor(
                actor_id="test-orch",
                config_path=config_path,
                backend=backend,
                bus=bus,
            )
            assert actor._bus is bus
        finally:
            os.unlink(config_path)
