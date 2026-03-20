"""Tests for config reload mechanism in BaseActor and subclasses."""

import asyncio
from typing import Any

import pytest
import yaml

from loom.bus.memory import InMemoryBus
from loom.core.actor import BaseActor

# ---------------------------------------------------------------------------
# Test actor with reload tracking
# ---------------------------------------------------------------------------


class ReloadTrackingActor(BaseActor):
    """Minimal actor that tracks reload calls."""

    def __init__(self, actor_id: str, *, bus: InMemoryBus) -> None:
        super().__init__(actor_id, bus=bus)
        self.reload_count = 0
        self.messages_processed: list[dict] = []

    async def handle_message(self, data: dict[str, Any]) -> None:
        self.messages_processed.append(data)

    async def on_reload(self) -> None:
        self.reload_count += 1


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBaseActorReload:
    @pytest.mark.asyncio
    async def test_on_reload_default_noop(self):
        """BaseActor.on_reload() is a no-op by default."""
        bus = InMemoryBus()
        await bus.connect()

        class MinimalActor(BaseActor):
            async def handle_message(self, data):
                pass

        actor = MinimalActor("test", bus=bus)
        await actor.on_reload()  # should not raise
        await bus.close()

    @pytest.mark.asyncio
    async def test_control_listener_receives_reload(self):
        """Publishing to loom.control.reload triggers on_reload()."""
        bus = InMemoryBus()
        await bus.connect()

        actor = ReloadTrackingActor("test-actor", bus=bus)

        # Start actor in background
        task = asyncio.create_task(actor.run("loom.test.subject"))
        await asyncio.sleep(0.05)  # let it subscribe

        # Publish reload message
        await bus.publish("loom.control.reload", {"action": "reload"})
        await asyncio.sleep(0.05)  # let it process

        assert actor.reload_count == 1

        # Cleanup
        actor._running = False
        if actor._sub:
            await actor._sub.unsubscribe()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await bus.close()

    @pytest.mark.asyncio
    async def test_control_listener_ignores_non_reload(self):
        """Non-reload control messages are ignored."""
        bus = InMemoryBus()
        await bus.connect()

        actor = ReloadTrackingActor("test-actor", bus=bus)

        task = asyncio.create_task(actor.run("loom.test.subject"))
        await asyncio.sleep(0.05)

        await bus.publish("loom.control.reload", {"action": "status"})
        await asyncio.sleep(0.05)

        assert actor.reload_count == 0

        actor._running = False
        if actor._sub:
            await actor._sub.unsubscribe()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await bus.close()


class TestTaskWorkerReload:
    @pytest.mark.asyncio
    async def test_worker_reloads_config(self, tmp_path):
        """TaskWorker.on_reload() re-reads config from disk."""
        from loom.worker.base import TaskWorker

        # Create a worker config
        config_path = tmp_path / "worker.yaml"
        config_path.write_text(yaml.dump({
            "name": "test_worker",
            "system_prompt": "Original prompt",
            "input_schema": {"text": "string"},
            "output_schema": {"result": "string"},
        }))

        class TestWorker(TaskWorker):
            async def process(self, payload, metadata):
                return {"output": {}, "model_used": None, "token_usage": None}

        worker = TestWorker(
            actor_id="test-worker",
            config_path=str(config_path),
            nats_url="nats://localhost:4222",
        )

        assert worker.config["system_prompt"] == "Original prompt"

        # Update config on disk
        config_path.write_text(yaml.dump({
            "name": "test_worker",
            "system_prompt": "Updated prompt",
            "input_schema": {"text": "string"},
            "output_schema": {"result": "string"},
        }))

        await worker.on_reload()
        assert worker.config["system_prompt"] == "Updated prompt"


class TestPipelineOrchestratorReload:
    @pytest.mark.asyncio
    async def test_pipeline_reloads_config(self, tmp_path):
        """PipelineOrchestrator.on_reload() re-reads config from disk."""
        from loom.orchestrator.pipeline import PipelineOrchestrator

        config_path = tmp_path / "pipeline.yaml"
        config_path.write_text(yaml.dump({
            "name": "test_pipeline",
            "pipeline_stages": [
                {
                    "name": "stage1",
                    "worker_type": "summarizer",
                    "model_tier": "local",
                    "input_mapping": {"text": "goal.context.text"},
                },
            ],
        }))

        orch = PipelineOrchestrator(
            actor_id="test-pipeline",
            config_path=str(config_path),
            nats_url="nats://localhost:4222",
        )

        assert len(orch.config["pipeline_stages"]) == 1

        # Update config on disk
        config_path.write_text(yaml.dump({
            "name": "test_pipeline",
            "pipeline_stages": [
                {
                    "name": "stage1",
                    "worker_type": "summarizer",
                    "model_tier": "local",
                    "input_mapping": {"text": "goal.context.text"},
                },
                {
                    "name": "stage2",
                    "worker_type": "classifier",
                    "model_tier": "local",
                    "input_mapping": {"text": "stage1.output.summary"},
                },
            ],
        }))

        await orch.on_reload()
        assert len(orch.config["pipeline_stages"]) == 2
