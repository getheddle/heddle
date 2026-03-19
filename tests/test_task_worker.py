"""Test TaskWorker base class (unit tests, no infrastructure)."""

from unittest.mock import AsyncMock

import pytest

from loom.core.messages import ModelTier, TaskMessage, TaskResult, TaskStatus
from loom.worker.base import TaskWorker

# --- Mock implementation ---


class EchoWorker(TaskWorker):
    """Simple test worker that echoes payload."""

    async def process(self, payload, metadata):
        return {
            "output": {"echo": payload.get("text", "")},
            "model_used": "echo-v1",
            "token_usage": {},
        }


class FailingWorker(TaskWorker):
    """Worker that always raises."""

    async def process(self, payload, metadata):
        raise RuntimeError("intentional failure")


class BadOutputWorker(TaskWorker):
    """Worker that returns output not matching schema."""

    async def process(self, payload, metadata):
        return {
            "output": {"wrong_field": "oops"},
            "model_used": None,
            "token_usage": None,
        }


# --- Fixtures ---

ECHO_CONFIG = {
    "name": "echo_worker",
    "input_schema": {
        "type": "object",
        "required": ["text"],
        "properties": {"text": {"type": "string"}},
    },
    "output_schema": {
        "type": "object",
        "required": ["echo"],
        "properties": {"echo": {"type": "string"}},
    },
}


def _make_task(payload=None, worker_type="echo_worker"):
    return TaskMessage(
        worker_type=worker_type,
        payload=payload or {"text": "hello"},
        model_tier=ModelTier.LOCAL,
        parent_task_id="goal-123",
    ).model_dump(mode="json")


# --- Tests ---


@pytest.mark.asyncio
async def test_task_worker_valid_input_output(tmp_path):
    """TaskWorker validates input, calls process(), validates output, publishes result."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(_yaml_dump(ECHO_CONFIG))

    worker = EchoWorker("test-worker", str(config_file))
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task({"text": "hello"}))

    worker.publish.assert_called_once()
    call_args = worker.publish.call_args
    subject = call_args[0][0]
    result_data = call_args[0][1]

    assert subject == "loom.results.goal-123"
    result = TaskResult(**result_data)
    assert result.status == TaskStatus.COMPLETED
    assert result.output == {"echo": "hello"}
    assert result.model_used == "echo-v1"
    assert result.processing_time_ms >= 0


@pytest.mark.asyncio
async def test_task_worker_input_validation_failure(tmp_path):
    """TaskWorker rejects invalid input and publishes FAILED result."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(_yaml_dump(ECHO_CONFIG))

    worker = EchoWorker("test-worker", str(config_file))
    worker.publish = AsyncMock()

    # Missing required "text" field
    await worker.handle_message(_make_task({"wrong": "field"}))

    worker.publish.assert_called_once()
    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.FAILED
    assert "Input validation" in result.error


@pytest.mark.asyncio
async def test_task_worker_output_validation_failure(tmp_path):
    """TaskWorker rejects output that doesn't match schema."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(_yaml_dump(ECHO_CONFIG))

    worker = BadOutputWorker("test-worker", str(config_file))
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task({"text": "hello"}))

    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.FAILED
    assert "Output validation" in result.error


@pytest.mark.asyncio
async def test_task_worker_process_exception(tmp_path):
    """TaskWorker catches process() exceptions and publishes FAILED result."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(_yaml_dump(ECHO_CONFIG))

    worker = FailingWorker("test-worker", str(config_file))
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task({"text": "hello"}))

    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.FAILED
    assert "intentional failure" in result.error


@pytest.mark.asyncio
async def test_task_worker_empty_schema(tmp_path):
    """TaskWorker with no schemas skips validation."""
    config = {"name": "permissive_worker"}
    config_file = tmp_path / "config.yaml"
    config_file.write_text(_yaml_dump(config))

    worker = EchoWorker("test-worker", str(config_file))
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task({"anything": "goes"}))

    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_task_worker_result_subject_default(tmp_path):
    """Result published to loom.results.default when no parent_task_id."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(_yaml_dump({"name": "test"}))

    worker = EchoWorker("test-worker", str(config_file))
    worker.publish = AsyncMock()

    task = TaskMessage(
        worker_type="test",
        payload={"text": "hello"},
        parent_task_id=None,
    ).model_dump(mode="json")
    await worker.handle_message(task)

    subject = worker.publish.call_args[0][0]
    assert subject == "loom.results.default"


# --- Helpers ---


def _yaml_dump(data):
    import yaml

    return yaml.dump(data)
