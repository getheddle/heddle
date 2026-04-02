"""Tests for council Pydantic models."""

import pytest
from pydantic import ValidationError

from loom.contrib.council.schemas import (
    AgentConfig,
    AgentTurn,
    ConvergenceConfig,
    ConvergenceResult,
    CouncilResult,
    FacilitatorConfig,
    RoundEntry,
    TranscriptEntry,
)
from loom.core.messages import ModelTier


class TestAgentConfig:
    def test_valid_worker_type(self):
        a = AgentConfig(name="analyst", worker_type="summarizer")
        assert a.worker_type == "summarizer"
        assert a.bridge is None

    def test_valid_bridge(self):
        a = AgentConfig(
            name="gpt",
            bridge="loom.contrib.chatbridge.openai.OpenAIChatBridge",
            bridge_config={"model": "gpt-4o"},
        )
        assert a.bridge is not None
        assert a.worker_type is None

    def test_neither_set_raises(self):
        with pytest.raises(ValidationError, match="Exactly one"):
            AgentConfig(name="bad")

    def test_both_set_raises(self):
        with pytest.raises(ValidationError, match="Exactly one"):
            AgentConfig(
                name="bad",
                worker_type="summarizer",
                bridge="some.Bridge",
            )

    def test_defaults(self):
        a = AgentConfig(name="x", worker_type="w")
        assert a.tier == ModelTier.STANDARD
        assert a.role == ""
        assert a.sees_transcript_from == ["all"]
        assert a.max_tokens_per_turn == 2000


class TestConvergenceConfig:
    def test_valid_methods(self):
        for m in ("none", "llm_judge", "position_stability"):
            c = ConvergenceConfig(method=m)
            assert c.method == m

    def test_invalid_method(self):
        with pytest.raises(ValidationError, match=r"convergence\.method"):
            ConvergenceConfig(method="invalid")

    def test_defaults(self):
        c = ConvergenceConfig()
        assert c.method == "none"
        assert c.threshold == 0.8


class TestFacilitatorConfig:
    def test_defaults(self):
        f = FacilitatorConfig()
        assert f.tier == ModelTier.STANDARD
        assert "facilitator" in f.synthesis_prompt.lower()


class TestTranscriptEntry:
    def test_construction(self):
        e = TranscriptEntry(
            round_num=1,
            agent_name="analyst",
            content="I think we should...",
        )
        assert e.round_num == 1
        assert e.token_count == 0
        assert e.model_used is None


class TestRoundEntry:
    def test_empty_round(self):
        r = RoundEntry(round_num=1)
        assert r.entries == []
        assert r.convergence_score is None


class TestAgentTurn:
    def test_construction(self):
        agent = AgentConfig(name="a", worker_type="w")
        turn = AgentTurn(agent=agent, round_num=1, context={"topic": "test"})
        assert turn.round_num == 1


class TestConvergenceResult:
    def test_converged(self):
        r = ConvergenceResult(converged=True, score=0.9, round_num=3)
        assert r.converged is True

    def test_not_converged(self):
        r = ConvergenceResult(converged=False, score=0.3, round_num=1)
        assert r.converged is False


class TestCouncilResult:
    def test_minimal(self):
        r = CouncilResult(
            topic="test",
            rounds_completed=2,
            converged=True,
            synthesis="We agree on X.",
        )
        assert r.converged is True
        assert r.transcript == []
        assert r.total_token_usage == {}

    def test_serialization_roundtrip(self):
        r = CouncilResult(
            topic="test",
            rounds_completed=1,
            converged=False,
            synthesis="no consensus",
            agent_summaries={"a": "pos A", "b": "pos B"},
            total_token_usage={"prompt_tokens": 100},
            elapsed_ms=500,
        )
        data = r.model_dump(mode="json")
        restored = CouncilResult(**data)
        assert restored.topic == r.topic
        assert restored.agent_summaries == r.agent_summaries
