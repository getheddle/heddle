"""Tests for loom.mcp.workshop_bridge — Workshop MCP tool execution."""

import os
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from loom.mcp.workshop_bridge import WorkshopBridge, WorkshopBridgeError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(dir_path: str, filename: str, data: dict) -> str:
    path = os.path.join(dir_path, filename)
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


def _make_config_manager(tmp_path, workers=None):
    """Create a ConfigManager with optional worker configs."""
    from loom.workshop.config_manager import ConfigManager

    workers_dir = tmp_path / "workers"
    workers_dir.mkdir(exist_ok=True)
    orch_dir = tmp_path / "orchestrators"
    orch_dir.mkdir(exist_ok=True)

    for name, cfg in (workers or {}).items():
        _write_yaml(str(workers_dir), f"{name}.yaml", cfg)

    return ConfigManager(configs_dir=str(tmp_path))


SAMPLE_WORKER = {
    "name": "summarizer",
    "system_prompt": "Summarize the input text.",
    "input_schema": {
        "type": "object",
        "required": ["text"],
        "properties": {"text": {"type": "string"}},
    },
    "output_schema": {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
    },
    "default_model_tier": "local",
}


# ---------------------------------------------------------------------------
# Worker config tools
# ---------------------------------------------------------------------------


class TestWorkerList:
    @pytest.mark.asyncio
    async def test_list_workers(self, tmp_path):
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        bridge = WorkshopBridge(config_manager=cm)

        result = await bridge.dispatch("worker.list", {})
        assert result["count"] >= 1
        names = [w["name"] for w in result["workers"]]
        assert "summarizer" in names

    @pytest.mark.asyncio
    async def test_list_no_config_manager(self):
        bridge = WorkshopBridge()
        with pytest.raises(WorkshopBridgeError, match="ConfigManager"):
            await bridge.dispatch("worker.list", {})


class TestWorkerGet:
    @pytest.mark.asyncio
    async def test_get_worker(self, tmp_path):
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        bridge = WorkshopBridge(config_manager=cm)

        result = await bridge.dispatch("worker.get", {"name": "summarizer"})
        assert result["name"] == "summarizer"
        assert result["config"]["name"] == "summarizer"
        assert "yaml" in result

    @pytest.mark.asyncio
    async def test_get_worker_not_found(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        bridge = WorkshopBridge(config_manager=cm)

        with pytest.raises(WorkshopBridgeError, match="not found"):
            await bridge.dispatch("worker.get", {"name": "nonexistent"})

    @pytest.mark.asyncio
    async def test_get_worker_missing_name(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        bridge = WorkshopBridge(config_manager=cm)

        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("worker.get", {})


class TestWorkerUpdate:
    @pytest.mark.asyncio
    async def test_update_worker(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        bridge = WorkshopBridge(config_manager=cm)

        config_yaml = yaml.dump(SAMPLE_WORKER)
        result = await bridge.dispatch(
            "worker.update",
            {"name": "summarizer", "config_yaml": config_yaml},
        )
        assert result["success"] is True
        assert result["name"] == "summarizer"

        # Verify it was saved.
        saved = cm.get_worker("summarizer")
        assert saved["name"] == "summarizer"

    @pytest.mark.asyncio
    async def test_update_invalid_yaml(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        bridge = WorkshopBridge(config_manager=cm)

        with pytest.raises(WorkshopBridgeError, match="Invalid YAML"):
            await bridge.dispatch(
                "worker.update",
                {"name": "bad", "config_yaml": ":\n  :\n  - [invalid"},
            )

    @pytest.mark.asyncio
    async def test_update_non_dict_yaml(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        bridge = WorkshopBridge(config_manager=cm)

        with pytest.raises(WorkshopBridgeError, match="YAML mapping"):
            await bridge.dispatch(
                "worker.update",
                {"name": "bad", "config_yaml": "- list\n- items"},
            )


# ---------------------------------------------------------------------------
# Test bench
# ---------------------------------------------------------------------------


@dataclass
class MockTestResult:
    output: dict[str, Any] | None = None
    raw_response: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    input_validation_errors: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 42
    model_used: str | None = "mock-model"
    error: str | None = None

    @property
    def success(self):
        return self.error is None and self.output is not None


class TestWorkerTest:
    @pytest.mark.asyncio
    async def test_run_test(self, tmp_path):
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        mock_runner = AsyncMock()
        mock_runner.run.return_value = MockTestResult(
            output={"summary": "A brief summary."},
            raw_response='{"summary": "A brief summary."}',
        )
        bridge = WorkshopBridge(config_manager=cm, test_runner=mock_runner)

        result = await bridge.dispatch(
            "worker.test",
            {"name": "summarizer", "payload": {"text": "Hello world"}},
        )
        assert result["output"] == {"summary": "A brief summary."}
        assert result["latency_ms"] == 42
        mock_runner.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_test_runner(self, tmp_path):
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        bridge = WorkshopBridge(config_manager=cm)

        with pytest.raises(WorkshopBridgeError, match="WorkerTestRunner"):
            await bridge.dispatch(
                "worker.test",
                {"name": "summarizer", "payload": {"text": "Hello"}},
            )


# ---------------------------------------------------------------------------
# Eval
# ---------------------------------------------------------------------------


class TestEvalRun:
    @pytest.mark.asyncio
    async def test_run_eval_no_runner(self, tmp_path):
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        bridge = WorkshopBridge(config_manager=cm)

        with pytest.raises(WorkshopBridgeError, match="EvalRunner"):
            await bridge.dispatch(
                "eval.run",
                {
                    "name": "summarizer",
                    "test_suite": [
                        {
                            "name": "t1",
                            "input": {"text": "hi"},
                            "expected_output": {"summary": "hi"},
                        }
                    ],
                },
            )

    @pytest.mark.asyncio
    async def test_run_eval_worker_not_found(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        mock_eval = AsyncMock()
        bridge = WorkshopBridge(config_manager=cm, eval_runner=mock_eval)

        with pytest.raises(WorkshopBridgeError, match="not found"):
            await bridge.dispatch(
                "eval.run",
                {
                    "name": "nonexistent",
                    "test_suite": [{"name": "t1", "input": {}, "expected_output": {}}],
                },
            )


class TestEvalCompare:
    @pytest.mark.asyncio
    async def test_compare_no_db(self):
        bridge = WorkshopBridge()
        with pytest.raises(WorkshopBridgeError, match="WorkshopDB"):
            await bridge.dispatch("eval.compare", {"name": "summarizer", "run_id": "abc"})

    @pytest.mark.asyncio
    async def test_compare_no_baseline(self):
        mock_db = MagicMock()
        mock_db.compare_against_baseline.return_value = None
        bridge = WorkshopBridge(db=mock_db)

        result = await bridge.dispatch("eval.compare", {"name": "summarizer", "run_id": "abc"})
        assert "error" in result
        assert "No baseline" in result["error"]

    @pytest.mark.asyncio
    async def test_compare_with_baseline(self):
        mock_db = MagicMock()
        mock_db.compare_against_baseline.return_value = {
            "baseline_run_id": "base-1",
            "current_run_id": "abc",
            "regressions": [],
            "improvements": [],
        }
        bridge = WorkshopBridge(db=mock_db)

        result = await bridge.dispatch("eval.compare", {"name": "summarizer", "run_id": "abc"})
        assert result["baseline_run_id"] == "base-1"


# ---------------------------------------------------------------------------
# Impact analysis
# ---------------------------------------------------------------------------


class TestImpactAnalyze:
    @pytest.mark.asyncio
    async def test_analyze_impact(self, tmp_path):
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        bridge = WorkshopBridge(config_manager=cm)

        result = await bridge.dispatch("impact.analyze", {"name": "summarizer"})
        assert result["worker_name"] == "summarizer"
        assert "pipelines" in result
        assert "risk" in result

    @pytest.mark.asyncio
    async def test_analyze_missing_name(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        bridge = WorkshopBridge(config_manager=cm)

        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("impact.analyze", {})


# ---------------------------------------------------------------------------
# Dead-letter
# ---------------------------------------------------------------------------


class TestDeadletterList:
    @pytest.mark.asyncio
    async def test_list_entries(self):
        mock_dl = MagicMock()
        mock_dl.list_entries.return_value = [
            {"id": "1", "reason": "unroutable", "worker_type": "foo"}
        ]
        mock_dl.count.return_value = 1
        bridge = WorkshopBridge(dead_letter=mock_dl)

        result = await bridge.dispatch("deadletter.list", {"limit": 10})
        assert result["count"] == 1
        assert result["total"] == 1
        mock_dl.list_entries.assert_called_once_with(limit=10, offset=0)

    @pytest.mark.asyncio
    async def test_list_no_consumer(self):
        bridge = WorkshopBridge()
        with pytest.raises(WorkshopBridgeError, match="DeadLetterConsumer"):
            await bridge.dispatch("deadletter.list", {})


class TestDeadletterReplay:
    @pytest.mark.asyncio
    async def test_replay_no_consumer(self):
        bridge = WorkshopBridge()
        with pytest.raises(WorkshopBridgeError, match="DeadLetterConsumer"):
            await bridge.dispatch("deadletter.replay", {"entry_id": "1"})

    @pytest.mark.asyncio
    async def test_replay_no_bus(self):
        mock_dl = MagicMock()
        bridge = WorkshopBridge(dead_letter=mock_dl)

        with pytest.raises(WorkshopBridgeError, match="message bus"):
            await bridge.dispatch("deadletter.replay", {"entry_id": "1"})

    @pytest.mark.asyncio
    async def test_replay_uses_replay_bus(self):
        mock_dl = MagicMock()
        mock_dl.replay = AsyncMock(return_value=True)
        replay_bus = object()
        bridge = WorkshopBridge(dead_letter=mock_dl, replay_bus=replay_bus)

        result = await bridge.dispatch("deadletter.replay", {"entry_id": "1"})
        assert result == {"success": True, "entry_id": "1"}
        mock_dl.replay.assert_awaited_once_with("1", replay_bus)


# ---------------------------------------------------------------------------
# Unknown action
# ---------------------------------------------------------------------------


class TestWorkerGetVersionHistory:
    @pytest.mark.asyncio
    async def test_get_worker_with_version_history(self, tmp_path):
        """version_history is included when db is available."""
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        mock_db = MagicMock()
        bridge = WorkshopBridge(config_manager=cm, db=mock_db)

        # ConfigManager.get_worker_version_history may not exist — mock it.
        cm.get_worker_version_history = MagicMock(return_value=[{"version": 1, "hash": "abc"}])

        result = await bridge.dispatch("worker.get", {"name": "summarizer"})
        assert result["name"] == "summarizer"
        assert result["version_history"] == [{"version": 1, "hash": "abc"}]

    @pytest.mark.asyncio
    async def test_get_worker_without_db_no_version_history(self, tmp_path):
        """version_history is absent when db is None."""
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        bridge = WorkshopBridge(config_manager=cm)

        result = await bridge.dispatch("worker.get", {"name": "summarizer"})
        assert "version_history" not in result


class TestWorkerUpdateValidationErrors:
    @pytest.mark.asyncio
    async def test_update_returns_validation_errors(self, tmp_path):
        """save_worker returning errors results in success=False."""
        cm = _make_config_manager(tmp_path)
        cm.save_worker = MagicMock(return_value=["missing system_prompt"])
        bridge = WorkshopBridge(config_manager=cm)

        result = await bridge.dispatch(
            "worker.update",
            {"name": "bad", "config_yaml": yaml.dump({"name": "bad"})},
        )
        assert result["success"] is False
        assert "missing system_prompt" in result["validation_errors"]

    @pytest.mark.asyncio
    async def test_update_missing_required_fields(self, tmp_path):
        """Missing name or config_yaml raises error."""
        cm = _make_config_manager(tmp_path)
        bridge = WorkshopBridge(config_manager=cm)

        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("worker.update", {"name": "x"})

        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("worker.update", {"config_yaml": "name: x"})


class TestWorkerTestMissingArgs:
    @pytest.mark.asyncio
    async def test_missing_name(self, tmp_path):
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        mock_runner = AsyncMock()
        bridge = WorkshopBridge(config_manager=cm, test_runner=mock_runner)

        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("worker.test", {"payload": {"text": "hi"}})

    @pytest.mark.asyncio
    async def test_missing_payload(self, tmp_path):
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        mock_runner = AsyncMock()
        bridge = WorkshopBridge(config_manager=cm, test_runner=mock_runner)

        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("worker.test", {"name": "summarizer"})

    @pytest.mark.asyncio
    async def test_worker_not_found(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        mock_runner = AsyncMock()
        bridge = WorkshopBridge(config_manager=cm, test_runner=mock_runner)

        with pytest.raises(WorkshopBridgeError, match="not found"):
            await bridge.dispatch("worker.test", {"name": "nonexistent", "payload": {"text": "hi"}})


class TestEvalRunWithDB:
    @pytest.mark.asyncio
    async def test_eval_run_returns_avg_score_with_db(self, tmp_path):
        """When db is available, returns avg_score in result."""
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        mock_eval = AsyncMock()
        mock_eval.run_suite.return_value = "run-123"
        mock_db = MagicMock()
        mock_db.get_eval_results.return_value = [
            {"score": 0.8, "case": "t1"},
            {"score": 0.6, "case": "t2"},
        ]
        bridge = WorkshopBridge(config_manager=cm, eval_runner=mock_eval, db=mock_db)

        result = await bridge.dispatch(
            "eval.run",
            {
                "name": "summarizer",
                "test_suite": [
                    {"name": "t1", "input": {"text": "a"}, "expected_output": {"summary": "a"}},
                    {"name": "t2", "input": {"text": "b"}, "expected_output": {"summary": "b"}},
                ],
            },
        )
        assert result["run_id"] == "run-123"
        assert result["avg_score"] == 0.7
        assert result["scoring"] == "field_match"

    @pytest.mark.asyncio
    async def test_eval_run_without_db_minimal_result(self, tmp_path):
        """Without db, returns minimal result (no avg_score)."""
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        mock_eval = AsyncMock()
        mock_eval.run_suite.return_value = "run-456"
        bridge = WorkshopBridge(config_manager=cm, eval_runner=mock_eval)

        result = await bridge.dispatch(
            "eval.run",
            {
                "name": "summarizer",
                "test_suite": [
                    {"name": "t1", "input": {"text": "a"}, "expected_output": {"summary": "a"}},
                ],
            },
        )
        assert result["run_id"] == "run-456"
        assert "avg_score" not in result

    @pytest.mark.asyncio
    async def test_eval_run_empty_scores(self, tmp_path):
        """DB returns results with no scores → avg_score is 0.0."""
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        mock_eval = AsyncMock()
        mock_eval.run_suite.return_value = "run-789"
        mock_db = MagicMock()
        mock_db.get_eval_results.return_value = [{"case": "t1"}]  # no score key
        bridge = WorkshopBridge(config_manager=cm, eval_runner=mock_eval, db=mock_db)

        result = await bridge.dispatch(
            "eval.run",
            {
                "name": "summarizer",
                "test_suite": [
                    {"name": "t1", "input": {"text": "a"}, "expected_output": {"summary": "a"}},
                ],
            },
        )
        assert result["avg_score"] == 0.0

    @pytest.mark.asyncio
    async def test_eval_run_missing_args(self, tmp_path):
        """Missing name or test_suite raises error."""
        cm = _make_config_manager(tmp_path, {"summarizer": SAMPLE_WORKER})
        mock_eval = AsyncMock()
        bridge = WorkshopBridge(config_manager=cm, eval_runner=mock_eval)

        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("eval.run", {"name": "summarizer"})

        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("eval.run", {"test_suite": []})


class TestEvalCompareMissingArgs:
    @pytest.mark.asyncio
    async def test_missing_name(self):
        mock_db = MagicMock()
        bridge = WorkshopBridge(db=mock_db)
        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("eval.compare", {"run_id": "abc"})

    @pytest.mark.asyncio
    async def test_missing_run_id(self):
        mock_db = MagicMock()
        bridge = WorkshopBridge(db=mock_db)
        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("eval.compare", {"name": "summarizer"})

    @pytest.mark.asyncio
    async def test_both_missing(self):
        mock_db = MagicMock()
        bridge = WorkshopBridge(db=mock_db)
        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("eval.compare", {})


class TestDeadletterReplayMissingArgs:
    @pytest.mark.asyncio
    async def test_missing_entry_id(self):
        mock_dl = MagicMock()
        bridge = WorkshopBridge(dead_letter=mock_dl)
        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("deadletter.replay", {})

    @pytest.mark.asyncio
    async def test_empty_entry_id(self):
        mock_dl = MagicMock()
        bridge = WorkshopBridge(dead_letter=mock_dl)
        with pytest.raises(WorkshopBridgeError, match="required"):
            await bridge.dispatch("deadletter.replay", {"entry_id": ""})


class TestImpactAnalyzeNoConfigManager:
    @pytest.mark.asyncio
    async def test_no_config_manager(self):
        bridge = WorkshopBridge()
        with pytest.raises(WorkshopBridgeError, match="ConfigManager"):
            await bridge.dispatch("impact.analyze", {"name": "foo"})


class TestUnknownAction:
    @pytest.mark.asyncio
    async def test_unknown_action(self):
        bridge = WorkshopBridge()
        with pytest.raises(WorkshopBridgeError, match="Unknown workshop action"):
            await bridge.dispatch("nonexistent.action", {})
