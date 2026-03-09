"""Test LLMWorker (unit tests, no infrastructure)."""
import json
from unittest.mock import AsyncMock

import pytest
import yaml

from loom.core.messages import ModelTier, TaskMessage, TaskResult, TaskStatus
from loom.worker.runner import LLMWorker


# --- Mock LLM backend ---

class MockLLMBackend:
    """Fake LLM backend that returns a fixed JSON response."""

    def __init__(self, response_output=None, model="mock-llm"):
        self._output = response_output or {"summary": "test summary", "key_points": ["a"]}
        self._model = model

    async def complete(self, system_prompt, user_message, max_tokens=2000, temperature=0.0):
        return {
            "content": json.dumps(self._output),
            "model": self._model,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }


class BadJsonBackend:
    """Backend that returns non-JSON content."""

    async def complete(self, system_prompt, user_message, max_tokens=2000, temperature=0.0):
        return {
            "content": "This is not JSON at all",
            "model": "bad-model",
            "prompt_tokens": 10,
            "completion_tokens": 5,
        }


# --- Config ---

LLM_CONFIG = {
    "name": "test_llm_worker",
    "system_prompt": "You are a test worker. Return JSON.",
    "default_model_tier": "local",
    "max_output_tokens": 500,
    "input_schema": {
        "type": "object",
        "required": ["text"],
        "properties": {"text": {"type": "string"}},
    },
    "output_schema": {
        "type": "object",
        "required": ["summary", "key_points"],
        "properties": {
            "summary": {"type": "string"},
            "key_points": {"type": "array"},
        },
    },
}


def _make_task(payload=None):
    return TaskMessage(
        worker_type="test_llm_worker",
        payload=payload or {"text": "hello world"},
        model_tier=ModelTier.LOCAL,
        parent_task_id="goal-789",
    ).model_dump(mode="json")


# --- Tests ---

@pytest.mark.asyncio
async def test_llm_worker_processes_task(tmp_path):
    """LLMWorker calls backend and publishes valid result."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(LLM_CONFIG))

    backends = {"local": MockLLMBackend()}
    worker = LLMWorker("llm-1", str(config_file), backends)
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task())

    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.COMPLETED
    assert result.output == {"summary": "test summary", "key_points": ["a"]}
    assert result.model_used == "mock-llm"
    assert result.token_usage["prompt_tokens"] == 100
    assert result.token_usage["completion_tokens"] == 50


@pytest.mark.asyncio
async def test_llm_worker_no_backend_for_tier(tmp_path):
    """LLMWorker fails when no backend available for the requested tier."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(LLM_CONFIG))

    backends = {"standard": MockLLMBackend()}  # No "local" backend
    worker = LLMWorker("llm-1", str(config_file), backends)
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task())

    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.FAILED
    assert "No backend for tier" in result.error


@pytest.mark.asyncio
async def test_llm_worker_non_json_response(tmp_path):
    """LLMWorker fails when backend returns non-JSON."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(LLM_CONFIG))

    backends = {"local": BadJsonBackend()}
    worker = LLMWorker("llm-1", str(config_file), backends)
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task())

    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.FAILED
    assert "non-JSON" in result.error


@pytest.mark.asyncio
async def test_llm_worker_input_validation(tmp_path):
    """LLMWorker validates input before calling backend."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(LLM_CONFIG))

    backends = {"local": MockLLMBackend()}
    worker = LLMWorker("llm-1", str(config_file), backends)
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task({"wrong": "field"}))

    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.FAILED
    assert "Input validation" in result.error


@pytest.mark.asyncio
async def test_llm_worker_output_validation(tmp_path):
    """LLMWorker validates LLM output against schema."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(LLM_CONFIG))

    # Backend returns valid JSON but wrong schema
    backends = {"local": MockLLMBackend(response_output={"bad": "schema"})}
    worker = LLMWorker("llm-1", str(config_file), backends)
    worker.publish = AsyncMock()

    await worker.handle_message(_make_task())

    result = TaskResult(**worker.publish.call_args[0][1])
    assert result.status == TaskStatus.FAILED
    assert "Output validation" in result.error
