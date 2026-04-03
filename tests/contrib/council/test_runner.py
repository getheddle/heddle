"""Tests for CouncilRunner."""

from unittest.mock import AsyncMock

import pytest

from heddle.contrib.council.config import CouncilConfig
from heddle.contrib.council.runner import CouncilRunner


def _mock_backend(content="I think we should proceed.", model="mock-model"):
    """Create a mock LLMBackend that returns fixed content."""
    backend = AsyncMock()
    backend.complete.return_value = {
        "content": content,
        "model": model,
        "prompt_tokens": 50,
        "completion_tokens": 30,
    }
    return backend


def _minimal_config(**overrides):
    cfg = {
        "name": "test_council",
        "protocol": "round_robin",
        "max_rounds": 2,
        "convergence": {"method": "none"},
        "agents": [
            {"name": "analyst", "worker_type": "w1", "tier": "standard", "role": "Analyst"},
            {"name": "critic", "worker_type": "w2", "tier": "standard", "role": "Critic"},
        ],
        "facilitator": {
            "tier": "standard",
            "synthesis_prompt": "Synthesize the discussion.",
        },
    }
    cfg.update(overrides)
    return CouncilConfig(**cfg)


class TestCouncilRunner:
    async def test_basic_two_round_discussion(self):
        backend = _mock_backend()
        runner = CouncilRunner(backends={"standard": backend})
        config = _minimal_config()

        result = await runner.run("Should we refactor?", config=config)

        assert result.topic == "Should we refactor?"
        assert result.rounds_completed == 2
        assert result.converged is False  # method=none
        assert result.synthesis != ""
        assert len(result.transcript) == 2
        # 2 agents per round * 2 rounds = 4 agent turns + 1 synthesis
        assert backend.complete.call_count == 5  # 4 turns + 1 synthesis

    async def test_convergence_stops_early(self):
        agent_backend = _mock_backend(content="We all agree on X.")
        # Use position_stability with threshold=0 so it converges on round 2
        config = _minimal_config(
            max_rounds=5,
            convergence={"method": "position_stability", "threshold": 0.5},
        )
        runner = CouncilRunner(backends={"standard": agent_backend})
        result = await runner.run("Test topic", config=config)

        # Position stability needs 2 rounds minimum, but identical responses
        # mean it converges on round 2.
        assert result.rounds_completed == 2
        assert result.converged is True

    async def test_max_rounds_enforced(self):
        backend = _mock_backend()
        config = _minimal_config(max_rounds=3, convergence={"method": "none"})
        runner = CouncilRunner(backends={"standard": backend})
        result = await runner.run("Topic", config=config)
        assert result.rounds_completed == 3

    async def test_on_turn_callback(self):
        backend = _mock_backend()
        config = _minimal_config(max_rounds=1)
        runner = CouncilRunner(backends={"standard": backend})

        entries: list = []
        await runner.run(
            "Topic",
            config=config,
            on_turn=entries.append,
        )

        # 2 agents, 1 round = 2 callbacks
        assert len(entries) == 2
        assert entries[0].agent_name == "analyst"
        assert entries[1].agent_name == "critic"

    async def test_async_on_turn_callback(self):
        backend = _mock_backend()
        config = _minimal_config(max_rounds=1)
        runner = CouncilRunner(backends={"standard": backend})

        entries: list = []

        async def async_callback(e):
            entries.append(e)

        await runner.run("Topic", config=config, on_turn=async_callback)
        assert len(entries) == 2

    async def test_missing_backend_produces_error_entry(self):
        # Only provide "local" backend, but agents need "standard"
        backend = _mock_backend()
        runner = CouncilRunner(backends={"local": backend})
        config = _minimal_config(max_rounds=1)

        result = await runner.run("Topic", config=config)

        # Agent entries should contain error messages
        assert result.rounds_completed == 1
        round_entries = result.transcript[0].entries
        assert all("[ERROR" in e.content for e in round_entries)

    async def test_token_usage_accumulated(self):
        backend = _mock_backend()
        config = _minimal_config(max_rounds=1)
        runner = CouncilRunner(backends={"standard": backend})

        result = await runner.run("Topic", config=config)
        assert result.total_token_usage["prompt_tokens"] > 0

    async def test_agent_summaries(self):
        backend = _mock_backend()
        config = _minimal_config(max_rounds=1)
        runner = CouncilRunner(backends={"standard": backend})

        result = await runner.run("Topic", config=config)
        assert "analyst" in result.agent_summaries
        assert "critic" in result.agent_summaries

    async def test_no_config_raises(self):
        runner = CouncilRunner(backends={"standard": _mock_backend()})
        with pytest.raises(ValueError, match="No council config"):
            await runner.run("Topic")

    async def test_constructor_config_used(self):
        config = _minimal_config(max_rounds=1)
        backend = _mock_backend()
        runner = CouncilRunner(backends={"standard": backend}, config=config)

        result = await runner.run("Topic")
        assert result.rounds_completed == 1

    async def test_backend_exception_produces_error_entry(self):
        backend = AsyncMock()
        backend.complete.side_effect = RuntimeError("LLM API down")
        runner = CouncilRunner(backends={"standard": backend})
        config = _minimal_config(max_rounds=1)

        result = await runner.run("Topic", config=config)
        entries = result.transcript[0].entries
        assert any("[ERROR" in e.content for e in entries)

    async def test_elapsed_ms_populated(self):
        backend = _mock_backend()
        config = _minimal_config(max_rounds=1)
        runner = CouncilRunner(backends={"standard": backend})

        result = await runner.run("Topic", config=config)
        assert result.elapsed_ms >= 0  # May be 0 with mock backends

    async def test_different_tiers_per_agent(self):
        local_backend = _mock_backend(content="Local view", model="ollama")
        frontier_backend = _mock_backend(content="Frontier view", model="opus")

        config = CouncilConfig(
            name="multi_tier",
            max_rounds=1,
            convergence={"method": "none"},
            agents=[
                {"name": "local_agent", "worker_type": "w1", "tier": "local"},
                {"name": "frontier_agent", "worker_type": "w2", "tier": "frontier"},
            ],
            facilitator={"tier": "local"},
        )
        runner = CouncilRunner(backends={"local": local_backend, "frontier": frontier_backend})

        result = await runner.run("Topic", config=config)
        assert result.rounds_completed == 1
        entries = result.transcript[0].entries
        assert entries[0].content == "Local view"
        assert entries[1].content == "Frontier view"
