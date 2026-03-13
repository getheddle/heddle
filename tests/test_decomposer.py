"""
Unit tests for GoalDecomposer (orchestrator/decomposer.py).

Tests cover:
- _extract_json_array: all parsing paths (clean JSON, fences, preamble, single object)
- WorkerDescriptor: to_prompt_block formatting
- GoalDecomposer.decompose: end-to-end with mock backend
- _parse_subtask: validation (missing worker, unknown worker, missing/bad payload)
- _resolve_tier / _resolve_priority: fallback chains
- from_worker_configs: factory method
"""
from __future__ import annotations

import json

import pytest

from loom.core.messages import ModelTier, TaskMessage, TaskPriority
from loom.orchestrator.decomposer import (
    GoalDecomposer,
    WorkerDescriptor,
    _build_system_prompt,
    _build_user_message,
    _extract_json_array,
)
from loom.worker.backends import LLMBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockBackend(LLMBackend):
    """Mock LLM backend returning a fixed response."""

    def __init__(self, content: str, model: str = "mock-model"):
        self._content = content
        self._model = model

    async def complete(self, system_prompt, user_message, max_tokens, temperature, **kw):
        return {
            "content": self._content,
            "model": self._model,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }


class FailingBackend(LLMBackend):
    """Backend that always raises."""

    async def complete(self, *args, **kwargs):
        raise RuntimeError("LLM unavailable")


WORKERS = [
    WorkerDescriptor(
        name="summarizer",
        description="Summarizes text",
        input_schema={"type": "object", "required": ["text"]},
        default_tier="local",
    ),
    WorkerDescriptor(
        name="classifier",
        description="Classifies documents",
        input_schema={"type": "object", "required": ["text"]},
        default_tier="standard",
    ),
]


# ---------------------------------------------------------------------------
# _extract_json_array tests
# ---------------------------------------------------------------------------


class TestExtractJsonArray:
    """Test the JSON extraction helper for various LLM response formats."""

    def test_clean_json_array(self):
        raw = '[{"worker_type": "summarizer", "payload": {"text": "hello"}}]'
        result = _extract_json_array(raw)
        assert len(result) == 1
        assert result[0]["worker_type"] == "summarizer"

    def test_clean_json_single_object(self):
        """Single JSON object is wrapped in a list."""
        raw = '{"worker_type": "summarizer", "payload": {"text": "hello"}}'
        result = _extract_json_array(raw)
        assert len(result) == 1

    def test_markdown_fenced_array(self):
        raw = '```json\n[{"worker_type": "summarizer", "payload": {}}]\n```'
        result = _extract_json_array(raw)
        assert len(result) == 1

    def test_markdown_fenced_single_object(self):
        raw = '```json\n{"worker_type": "summarizer", "payload": {}}\n```'
        result = _extract_json_array(raw)
        assert len(result) == 1

    def test_preamble_and_postamble(self):
        """Array buried in explanatory text is still extracted."""
        raw = (
            'Here is the decomposition:\n'
            '[{"worker_type": "summarizer", "payload": {"text": "hi"}}]\n'
            'Let me know if you need changes.'
        )
        result = _extract_json_array(raw)
        assert len(result) == 1

    def test_preamble_single_object_fallback(self):
        """Single object buried in text uses last-resort extraction."""
        raw = 'Sure: {"worker_type": "summarizer", "payload": {}}'
        result = _extract_json_array(raw)
        assert len(result) == 1

    def test_empty_array(self):
        result = _extract_json_array("[]")
        assert result == []

    def test_non_json_raises(self):
        with pytest.raises(ValueError, match="non-JSON"):
            _extract_json_array("This is not JSON at all")

    def test_whitespace_stripped(self):
        raw = '  \n  [{"a": 1}]  \n  '
        result = _extract_json_array(raw)
        assert result == [{"a": 1}]


# ---------------------------------------------------------------------------
# WorkerDescriptor tests
# ---------------------------------------------------------------------------


class TestWorkerDescriptor:
    def test_to_prompt_block_with_schema(self):
        w = WorkerDescriptor(
            name="summarizer",
            description="Summarizes text",
            input_schema={"type": "object"},
            default_tier="local",
        )
        block = w.to_prompt_block()
        assert "Worker: summarizer" in block
        assert "Description: Summarizes text" in block
        assert "Default tier: local" in block
        assert "Input payload schema:" in block

    def test_to_prompt_block_without_schema(self):
        w = WorkerDescriptor(name="basic", description="Does stuff")
        block = w.to_prompt_block()
        assert "Input payload schema" not in block

    def test_frozen(self):
        w = WorkerDescriptor(name="a", description="b")
        with pytest.raises(AttributeError):
            w.name = "c"


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


class TestPromptBuilders:
    def test_build_system_prompt_with_workers(self):
        prompt = _build_system_prompt(WORKERS)
        assert "summarizer" in prompt
        assert "classifier" in prompt
        assert "AVAILABLE WORKERS" in prompt

    def test_build_system_prompt_no_workers(self):
        prompt = _build_system_prompt([])
        assert "(none configured)" in prompt

    def test_build_user_message_with_context(self):
        msg = _build_user_message("Do stuff", {"file": "test.pdf"})
        assert "GOAL:" in msg
        assert "Do stuff" in msg
        assert "CONTEXT:" in msg
        assert "test.pdf" in msg

    def test_build_user_message_without_context(self):
        msg = _build_user_message("Do stuff", None)
        assert "GOAL:" in msg
        assert "CONTEXT:" not in msg


# ---------------------------------------------------------------------------
# GoalDecomposer.decompose tests
# ---------------------------------------------------------------------------


class TestDecompose:
    @pytest.mark.asyncio
    async def test_decompose_valid_response(self):
        plan = json.dumps([
            {"worker_type": "summarizer", "payload": {"text": "hello"}, "model_tier": "local"},
            {"worker_type": "classifier", "payload": {"text": "world"}, "priority": "high"},
        ])
        decomposer = GoalDecomposer(backend=MockBackend(plan), workers=WORKERS)
        tasks = await decomposer.decompose("Summarize and classify", parent_task_id="goal-1")

        assert len(tasks) == 2
        assert all(isinstance(t, TaskMessage) for t in tasks)
        assert tasks[0].worker_type == "summarizer"
        assert tasks[0].model_tier == ModelTier.LOCAL
        assert tasks[0].parent_task_id == "goal-1"
        assert tasks[1].worker_type == "classifier"
        assert tasks[1].priority == TaskPriority.HIGH

    @pytest.mark.asyncio
    async def test_decompose_backend_failure_returns_empty(self):
        decomposer = GoalDecomposer(backend=FailingBackend(), workers=WORKERS)
        tasks = await decomposer.decompose("Do something")
        assert tasks == []

    @pytest.mark.asyncio
    async def test_decompose_unparseable_response_returns_empty(self):
        decomposer = GoalDecomposer(backend=MockBackend("Not JSON at all"), workers=WORKERS)
        tasks = await decomposer.decompose("Do something")
        assert tasks == []

    @pytest.mark.asyncio
    async def test_decompose_empty_plan_returns_empty(self):
        decomposer = GoalDecomposer(backend=MockBackend("[]"), workers=WORKERS)
        tasks = await decomposer.decompose("Do something")
        assert tasks == []

    @pytest.mark.asyncio
    async def test_decompose_skips_invalid_subtasks(self):
        """Unknown worker types are skipped, valid ones kept."""
        plan = json.dumps([
            {"worker_type": "unknown_worker", "payload": {"text": "a"}},
            {"worker_type": "summarizer", "payload": {"text": "b"}},
        ])
        decomposer = GoalDecomposer(backend=MockBackend(plan), workers=WORKERS)
        tasks = await decomposer.decompose("Mixed plan")
        assert len(tasks) == 1
        assert tasks[0].worker_type == "summarizer"

    @pytest.mark.asyncio
    async def test_decompose_fenced_json(self):
        plan = '```json\n[{"worker_type": "summarizer", "payload": {"text": "x"}}]\n```'
        decomposer = GoalDecomposer(backend=MockBackend(plan), workers=WORKERS)
        tasks = await decomposer.decompose("Test")
        assert len(tasks) == 1

    @pytest.mark.asyncio
    async def test_decompose_with_context(self):
        plan = json.dumps([{"worker_type": "summarizer", "payload": {"text": "hi"}}])
        decomposer = GoalDecomposer(backend=MockBackend(plan), workers=WORKERS)
        tasks = await decomposer.decompose("Test", context={"file_ref": "doc.pdf"})
        assert len(tasks) == 1


# ---------------------------------------------------------------------------
# _parse_subtask validation
# ---------------------------------------------------------------------------


class TestParseSubtask:
    """Test individual subtask parsing and validation."""

    def _make_decomposer(self):
        return GoalDecomposer(backend=MockBackend("[]"), workers=WORKERS)

    def test_missing_worker_type(self):
        d = self._make_decomposer()
        result = d._parse_subtask({"payload": {"text": "hi"}}, index=0, parent_task_id=None, default_priority=TaskPriority.NORMAL)
        assert result is None

    def test_unknown_worker_type(self):
        d = self._make_decomposer()
        result = d._parse_subtask({"worker_type": "nonexistent", "payload": {}}, index=0, parent_task_id=None, default_priority=TaskPriority.NORMAL)
        assert result is None

    def test_missing_payload(self):
        d = self._make_decomposer()
        result = d._parse_subtask({"worker_type": "summarizer"}, index=0, parent_task_id=None, default_priority=TaskPriority.NORMAL)
        assert result is None

    def test_non_dict_payload(self):
        d = self._make_decomposer()
        result = d._parse_subtask({"worker_type": "summarizer", "payload": "string"}, index=0, parent_task_id=None, default_priority=TaskPriority.NORMAL)
        assert result is None

    def test_valid_subtask_returns_task_message(self):
        d = self._make_decomposer()
        result = d._parse_subtask(
            {"worker_type": "summarizer", "payload": {"text": "hi"}, "rationale": "Testing"},
            index=0,
            parent_task_id="goal-1",
            default_priority=TaskPriority.NORMAL,
        )
        assert isinstance(result, TaskMessage)
        assert result.worker_type == "summarizer"
        assert result.parent_task_id == "goal-1"
        assert result.metadata["decomposer_rationale"] == "Testing"


# ---------------------------------------------------------------------------
# Tier and priority resolution
# ---------------------------------------------------------------------------


class TestResolveTier:
    def _make_decomposer(self):
        return GoalDecomposer(backend=MockBackend("[]"), workers=WORKERS)

    def test_explicit_valid_tier(self):
        d = self._make_decomposer()
        assert d._resolve_tier("frontier", "summarizer") == ModelTier.FRONTIER

    def test_invalid_tier_falls_back_to_worker_default(self):
        d = self._make_decomposer()
        # summarizer has default_tier="local"
        assert d._resolve_tier("invalid_tier", "summarizer") == ModelTier.LOCAL

    def test_none_tier_uses_worker_default(self):
        d = self._make_decomposer()
        assert d._resolve_tier(None, "summarizer") == ModelTier.LOCAL

    def test_none_tier_unknown_worker_uses_standard(self):
        d = self._make_decomposer()
        # Worker not in the list → global fallback
        assert d._resolve_tier(None, "nonexistent") == ModelTier.STANDARD


class TestResolvePriority:
    def test_explicit_valid_priority(self):
        result = GoalDecomposer._resolve_priority("high", TaskPriority.NORMAL)
        assert result == TaskPriority.HIGH

    def test_invalid_priority_falls_back(self):
        result = GoalDecomposer._resolve_priority("ultra", TaskPriority.LOW)
        assert result == TaskPriority.LOW

    def test_none_priority_uses_default(self):
        result = GoalDecomposer._resolve_priority(None, TaskPriority.CRITICAL)
        assert result == TaskPriority.CRITICAL


# ---------------------------------------------------------------------------
# Factory method
# ---------------------------------------------------------------------------


class TestFromWorkerConfigs:
    def test_builds_from_yaml_style_dicts(self):
        configs = [
            {
                "name": "summarizer",
                "description": "Summarizes text",
                "input_schema": {"type": "object"},
                "default_model_tier": "local",
            },
            {
                "name": "classifier",
                "description": "Classifies docs",
            },
        ]
        decomposer = GoalDecomposer.from_worker_configs(
            backend=MockBackend("[]"),
            configs=configs,
        )
        assert len(decomposer._workers) == 2
        assert decomposer._workers[0].name == "summarizer"
        assert decomposer._workers[0].default_tier == "local"
        # Missing fields get defaults
        assert decomposer._workers[1].description == "Classifies docs"
        assert decomposer._workers[1].default_tier == "standard"
