"""Tests for council MCP bridge."""

import os
import tempfile
from unittest.mock import AsyncMock

import pytest
import yaml

from heddle.contrib.council.runner import CouncilRunner
from heddle.mcp.council_bridge import CouncilBridge, CouncilBridgeError


def _write_council_config(dir_path: str, name: str = "test"):
    """Write a minimal council config YAML to a directory."""
    config = {
        "name": name,
        "protocol": "round_robin",
        "max_rounds": 1,
        "convergence": {"method": "none"},
        "agents": [
            {"name": "a1", "worker_type": "w1", "tier": "standard"},
            {"name": "a2", "worker_type": "w2", "tier": "standard"},
        ],
        "facilitator": {"tier": "standard"},
    }
    path = os.path.join(dir_path, f"{name}.yaml")
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


def _mock_backend():
    backend = AsyncMock()
    backend.complete.return_value = {
        "content": "Mock response",
        "model": "mock",
        "prompt_tokens": 50,
        "completion_tokens": 20,
    }
    return backend


class TestCouncilBridge:
    async def test_start_returns_council_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_council_config(tmpdir, "mycouncil")
            backend = _mock_backend()
            runner = CouncilRunner(backends={"standard": backend})
            bridge = CouncilBridge(runner=runner, configs_dir=tmpdir)

            result = await bridge.dispatch(
                "start",
                {
                    "topic": "Test topic",
                    "config_name": "mycouncil",
                },
            )

            assert "council_id" in result
            assert result["status"] == "started"
            assert result["topic"] == "Test topic"

    async def test_start_missing_config_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = CouncilRunner(backends={})
            bridge = CouncilBridge(runner=runner, configs_dir=tmpdir)

            with pytest.raises(CouncilBridgeError, match="not found"):
                await bridge.dispatch(
                    "start",
                    {
                        "topic": "Test",
                        "config_name": "nonexistent",
                    },
                )

    async def test_start_missing_topic_raises(self):
        runner = CouncilRunner(backends={})
        bridge = CouncilBridge(runner=runner)

        with pytest.raises(CouncilBridgeError, match="topic"):
            await bridge.dispatch("start", {"config_name": "x"})

    async def test_status_unknown_id(self):
        runner = CouncilRunner(backends={})
        bridge = CouncilBridge(runner=runner)

        result = await bridge.dispatch("status", {"council_id": "unknown"})
        assert "error" in result

    async def test_transcript_unknown_id(self):
        runner = CouncilRunner(backends={})
        bridge = CouncilBridge(runner=runner)

        result = await bridge.dispatch("transcript", {"council_id": "unknown"})
        assert "error" in result

    async def test_intervene_unknown_id(self):
        runner = CouncilRunner(backends={})
        bridge = CouncilBridge(runner=runner)

        result = await bridge.dispatch(
            "intervene",
            {"council_id": "unknown", "message": "Hello"},
        )
        assert "error" in result

    async def test_stop_unknown_id(self):
        runner = CouncilRunner(backends={})
        bridge = CouncilBridge(runner=runner)

        result = await bridge.dispatch("stop", {"council_id": "unknown"})
        assert "error" in result

    async def test_unknown_action_raises(self):
        runner = CouncilRunner(backends={})
        bridge = CouncilBridge(runner=runner)

        with pytest.raises(CouncilBridgeError, match="Unknown"):
            await bridge.dispatch("bogus", {})
