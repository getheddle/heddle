"""Tests for CouncilOrchestrator with InMemoryBus.

Exercises the full NATS-connected council flow using an in-memory bus
so no infrastructure is needed. Follows the pattern of
tests/test_e2e_operations.py.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import yaml

from loom.bus.memory import InMemoryBus
from loom.contrib.council.orchestrator import CouncilOrchestrator
from loom.core.messages import (
    OrchestratorGoal,
    TaskResult,
    TaskStatus,
)
from loom.worker.backends import LLMBackend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(data: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump(data, f)
    return path


def _council_config(max_rounds=2, convergence_method="none"):
    return {
        "name": "test_council",
        "protocol": "round_robin",
        "max_rounds": max_rounds,
        "timeout_seconds": 10,
        "convergence": {"method": convergence_method, "threshold": 0.9},
        "agents": [
            {"name": "analyst", "worker_type": "test_worker",
             "tier": "standard", "role": "Analyst"},
            {"name": "critic", "worker_type": "test_worker",
             "tier": "standard", "role": "Critic"},
        ],
        "facilitator": {
            "tier": "standard",
            "synthesis_prompt": "Synthesize.",
        },
    }


class MockFacilitatorBackend(LLMBackend):
    """Mock backend used by the facilitator for synthesis and convergence."""

    async def complete(self, system_prompt, user_message, max_tokens=2000, temperature=0.0, **kw):
        if "score" in system_prompt.lower() or "agreement" in system_prompt.lower():
            return {
                "content": '{"score": 0.95, "reason": "Everyone agrees"}',
                "model": "mock",
                "prompt_tokens": 50,
                "completion_tokens": 20,
            }
        return {
            "content": "The team reached consensus on the approach.",
            "model": "mock",
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }


async def _simulate_worker(bus: InMemoryBus, respond_to_n: int = 10) -> None:
    """Subscribe to loom.tasks.incoming and respond with mock results.

    Simulates the router+worker path: reads TaskMessage from incoming,
    publishes TaskResult to the appropriate result subject.
    """
    sub = await bus.subscribe("loom.tasks.incoming")
    count = 0
    async for data in sub:
        parent_id = data.get("parent_task_id", "default")
        task_id = data.get("task_id")
        worker_type = data.get("worker_type", "unknown")
        agent = data.get("metadata", {}).get("agent", "unknown")

        result = TaskResult(
            task_id=task_id,
            parent_task_id=parent_id,
            worker_type=worker_type,
            status=TaskStatus.COMPLETED,
            output={"content": f"Position from {agent}: I think we should proceed."},
            model_used="mock-worker",
            token_usage={"prompt_tokens": 30, "completion_tokens": 20},
            processing_time_ms=10,
        )
        await bus.publish(
            f"loom.results.{parent_id}",
            result.model_dump(mode="json"),
        )

        count += 1
        if count >= respond_to_n:
            break


async def _get_final_result(sub, goal_id: str, timeout: float = 5.0) -> dict:
    """Wait for the final council result on the result subject."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            msg = f"Final result for {goal_id} not received within {timeout}s"
            raise TimeoutError(msg)
        data = await asyncio.wait_for(sub.__anext__(), timeout=remaining)
        if data.get("task_id") == goal_id:
            return data


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCouncilOrchestrator:
    async def test_basic_two_round_discussion(self):
        """Full 2-round council with mock workers and facilitator."""
        bus = InMemoryBus()
        await bus.connect()

        config_path = _write_yaml(_council_config(max_rounds=2))
        backend = MockFacilitatorBackend()

        orch = CouncilOrchestrator(
            actor_id="test-council-orch",
            config_path=config_path,
            backend=backend,
            bus=bus,
        )

        goal = OrchestratorGoal(instruction="Should we adopt microservices?")
        goal_data = goal.model_dump(mode="json")

        # Subscribe to result subject before starting.
        result_sub = await bus.subscribe(f"loom.results.{goal.goal_id}")

        # 2 agents * 2 rounds = 4 worker responses needed.
        worker_task = asyncio.create_task(_simulate_worker(bus, respond_to_n=4))

        # Run the orchestrator's message handler directly.
        await orch.handle_message(goal_data)

        # Get the final result.
        final = await _get_final_result(result_sub, goal.goal_id)

        assert final["status"] == "completed"
        assert final["output"]["rounds_completed"] == 2
        assert final["output"]["converged"] is False  # method=none
        assert "consensus" in final["output"]["synthesis"].lower()
        assert "analyst" in final["output"]["agent_summaries"]
        assert "critic" in final["output"]["agent_summaries"]

        worker_task.cancel()
        await bus.close()

    async def test_convergence_stops_early(self):
        """Council with llm_judge convergence that stops on round 1."""
        bus = InMemoryBus()
        await bus.connect()

        config = _council_config(max_rounds=5, convergence_method="llm_judge")
        config["convergence"]["threshold"] = 0.5  # Low threshold
        config_path = _write_yaml(config)
        backend = MockFacilitatorBackend()

        orch = CouncilOrchestrator(
            actor_id="test-council-conv",
            config_path=config_path,
            backend=backend,
            bus=bus,
        )

        goal = OrchestratorGoal(instruction="Test convergence")
        result_sub = await bus.subscribe(f"loom.results.{goal.goal_id}")

        # Provide enough responses for up to 5 rounds (but expect early stop).
        worker_task = asyncio.create_task(_simulate_worker(bus, respond_to_n=10))

        await orch.handle_message(goal.model_dump(mode="json"))

        final = await _get_final_result(result_sub, goal.goal_id)

        assert final["status"] == "completed"
        # Should converge after round 1 since mock returns score 0.95 > 0.5.
        assert final["output"]["rounds_completed"] == 1
        assert final["output"]["converged"] is True

        worker_task.cancel()
        await bus.close()

    async def test_worker_timeout_produces_error_entry(self):
        """When a worker doesn't respond, the transcript notes the timeout."""
        bus = InMemoryBus()
        await bus.connect()

        config = _council_config(max_rounds=1)
        config["timeout_seconds"] = 1  # Very short timeout
        config_path = _write_yaml(config)
        backend = MockFacilitatorBackend()

        orch = CouncilOrchestrator(
            actor_id="test-council-timeout",
            config_path=config_path,
            backend=backend,
            bus=bus,
        )

        goal = OrchestratorGoal(instruction="Test timeout")
        result_sub = await bus.subscribe(f"loom.results.{goal.goal_id}")

        # Don't start any workers — all dispatches will timeout.
        await orch.handle_message(goal.model_dump(mode="json"))

        final = await _get_final_result(result_sub, goal.goal_id)

        assert final["status"] == "completed"
        # Timeouts are not fatal — the council still produces a result.
        assert final["output"]["rounds_completed"] == 1

        await bus.close()

    async def test_worker_failure_noted_in_transcript(self):
        """When a worker returns FAILED, the transcript notes the error."""
        bus = InMemoryBus()
        await bus.connect()

        config_path = _write_yaml(_council_config(max_rounds=1))
        backend = MockFacilitatorBackend()

        orch = CouncilOrchestrator(
            actor_id="test-council-fail",
            config_path=config_path,
            backend=backend,
            bus=bus,
        )

        goal = OrchestratorGoal(instruction="Test failure")
        result_sub = await bus.subscribe(f"loom.results.{goal.goal_id}")

        # Simulate a worker that returns FAILED.
        async def _failing_worker():
            sub = await bus.subscribe("loom.tasks.incoming")
            count = 0
            async for data in sub:
                parent_id = data.get("parent_task_id", "default")
                task_id = data.get("task_id")
                result = TaskResult(
                    task_id=task_id,
                    parent_task_id=parent_id,
                    worker_type=data.get("worker_type", "unknown"),
                    status=TaskStatus.FAILED,
                    output=None,
                    error="Worker crashed",
                    token_usage={},
                    processing_time_ms=5,
                )
                await bus.publish(
                    f"loom.results.{parent_id}",
                    result.model_dump(mode="json"),
                )
                count += 1
                if count >= 2:
                    break

        worker_task = asyncio.create_task(_failing_worker())
        await orch.handle_message(goal.model_dump(mode="json"))

        final = await _get_final_result(result_sub, goal.goal_id)
        assert final["status"] == "completed"

        worker_task.cancel()
        await bus.close()

    async def test_final_result_on_correct_subject(self):
        """The final result is published to loom.results.{goal_id}."""
        bus = InMemoryBus()
        await bus.connect()

        config_path = _write_yaml(_council_config(max_rounds=1))
        backend = MockFacilitatorBackend()

        orch = CouncilOrchestrator(
            actor_id="test-council-subject",
            config_path=config_path,
            backend=backend,
            bus=bus,
        )

        goal = OrchestratorGoal(instruction="Test subject")
        result_sub = await bus.subscribe(f"loom.results.{goal.goal_id}")
        worker_task = asyncio.create_task(_simulate_worker(bus, respond_to_n=2))

        await orch.handle_message(goal.model_dump(mode="json"))

        final = await _get_final_result(result_sub, goal.goal_id)
        assert final["task_id"] == goal.goal_id
        assert final["worker_type"] == "council:test_council"

        worker_task.cancel()
        await bus.close()
