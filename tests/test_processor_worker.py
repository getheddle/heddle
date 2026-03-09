"""Test ProcessorWorker and ProcessingBackend (unit tests, no infrastructure)."""
from unittest.mock import AsyncMock

import pytest
import yaml

from loom.core.messages import ModelTier, TaskMessage, TaskResult, TaskStatus
from loom.worker.processor import ProcessingBackend, ProcessorWorker


# --- Mock backend ---

class MockBackend(ProcessingBackend):
    """Backend that returns a fixed output."""

    def __init__(self, output=None, model_used="mock-v1"):
        self._output = output or {"result": "processed"}
        self._model_used = model_used

    async def process(self, payload, config):
        return {
            "output": self._output,
            "model_used": self._model_used,
        }


class ErrorBackend(ProcessingBackend):
    """Backend that always raises."""

    async def process(self, payload, config):
        raise RuntimeError("backend exploded")


# --- Fixtures ---

PROCESSOR_CONFIG = {
    "name": "test_processor",
    "processing_backend": "test.MockBackend",
    "input_schema": {
        "type": "object",
        "required": ["file_ref"],
        "properties": {"file_ref": {"type": "string"}},
    },
    "output_schema": {
        "type": "object",
        "required": ["result"],
        "properties": {"result": {"type": "string"}},
    },
}


def _make_task(payload=None):
    return TaskMessage(
        worker_type="test_processor",
        payload=payload or {"file_ref": "doc.pdf"},
        model_tier=ModelTier.LOCAL,
        parent_task_id="goal-456",
    ).model_dump(mode="json")


# --- Tests ---

@pytest.mark.asyncio
async def test_processor_worker_delegates_to_backend(tmp_path):
    """ProcessorWorker delegates to its ProcessingBackend."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(PROCESSOR_CONFIG))

    backend = MockBackend(output={"result": "done"}, model_used="docling-v2")
    worker = ProcessorWorker("proc-1", str(config_file), backend)
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task({"file_ref": "report.pdf"}))

    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.COMPLETED
    assert result.output == {"result": "done"}
    assert result.model_used == "docling-v2"
    assert result.token_usage == {"prompt_tokens": 0, "completion_tokens": 0}


@pytest.mark.asyncio
async def test_processor_worker_input_validation(tmp_path):
    """ProcessorWorker validates input against schema before calling backend."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(PROCESSOR_CONFIG))

    backend = MockBackend()
    worker = ProcessorWorker("proc-1", str(config_file), backend)
    worker.publish = AsyncMock()

    # Missing required "file_ref"
    await worker.handle_message(_make_task({"wrong": "field"}))

    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.FAILED
    assert "Input validation" in result.error


@pytest.mark.asyncio
async def test_processor_worker_backend_exception(tmp_path):
    """ProcessorWorker handles backend exceptions gracefully."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(PROCESSOR_CONFIG))

    backend = ErrorBackend()
    worker = ProcessorWorker("proc-1", str(config_file), backend)
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task({"file_ref": "doc.pdf"}))

    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.FAILED
    assert "backend exploded" in result.error


@pytest.mark.asyncio
async def test_processor_worker_output_validation(tmp_path):
    """ProcessorWorker validates backend output against schema."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(PROCESSOR_CONFIG))

    # Backend returns output that doesn't match required "result" field
    backend = MockBackend(output={"unexpected": "data"})
    worker = ProcessorWorker("proc-1", str(config_file), backend)
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task({"file_ref": "doc.pdf"}))

    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.FAILED
    assert "Output validation" in result.error


@pytest.mark.asyncio
async def test_processor_worker_passes_config_to_backend(tmp_path):
    """ProcessorWorker passes its full config dict to the backend."""
    config = {**PROCESSOR_CONFIG, "custom_setting": "value123"}
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))

    received_config = {}

    class SpyBackend(ProcessingBackend):
        async def process(self, payload, config):
            received_config.update(config)
            return {"output": {"result": "ok"}, "model_used": None}

    worker = ProcessorWorker("proc-1", str(config_file), SpyBackend())
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task({"file_ref": "doc.pdf"}))

    assert received_config.get("custom_setting") == "value123"
