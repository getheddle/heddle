"""Tests for JudgePanelScorer and scorer data models."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from heddle.contrib.chatbridge.base import ChatResponse
from heddle.contrib.council.schemas import (
    CouncilResult,
    RoundEntry,
    TranscriptEntry,
)
from heddle.contrib.council.scorer import (
    AgentScore,
    JudgePanelScorer,
    JudgeVerdict,
    ScoringResult,
)

# -- Helpers ---------------------------------------------------------------


def _verdict_response(winner: str, margin: float = 0.7, **rubric: float) -> ChatResponse:
    """Build a ChatResponse with a JSON verdict."""
    rubric_str = ", ".join(f'"{k}": {v}' for k, v in rubric.items())
    body = (
        '{"winner": "' + winner + '", "margin": ' + str(margin) + ", "
        '"rubric": {' + rubric_str + "}, "
        '"reasoning": "test"}'
    )
    return ChatResponse(content=body, model=f"judge-{winner}")


def _mock_judge(response: ChatResponse) -> AsyncMock:
    """Create a ChatBridge mock that returns the given response."""
    judge = AsyncMock()
    judge.send_turn.return_value = response
    return judge


def _council_result(
    topic: str = "Topic",
    agents: tuple[str, ...] = ("pro", "con"),
    rounds: int = 1,
) -> CouncilResult:
    transcript = [
        RoundEntry(
            round_num=r + 1,
            entries=[
                TranscriptEntry(
                    round_num=r + 1,
                    agent_name=a,
                    role=f"role-{a}",
                    content=f"{a} content round {r + 1}",
                )
                for a in agents
            ],
        )
        for r in range(rounds)
    ]
    return CouncilResult(
        topic=topic,
        rounds_completed=rounds,
        converged=False,
        synthesis="Facilitator summary.",
        transcript=transcript,
    )


# -- Models ---------------------------------------------------------------


class TestModels:
    def test_judge_verdict_defaults(self) -> None:
        v = JudgeVerdict(judge_model="m", winner="pro")
        assert v.margin == 0.0
        assert v.rubric == {}
        assert v.reasoning == ""

    def test_scoring_result_defaults(self) -> None:
        s = ScoringResult(council_topic="t")
        assert s.winner is None
        assert s.win_margin == 0.0
        assert s.agent_scores == []
        assert s.verdicts == []
        assert s.metadata == {}

    def test_agent_score_defaults(self) -> None:
        a = AgentScore(agent_name="pro")
        assert a.score == 0.0
        assert a.rubric == {}
        assert a.notes == ""


# -- _parse_verdict --------------------------------------------------------


class TestParseVerdict:
    def test_bare_json(self) -> None:
        v = JudgePanelScorer._parse_verdict(
            '{"winner": "pro", "margin": 0.6, "rubric": {"q": 0.7}, "reasoning": "ok"}',
            judge_model="judge-1",
        )
        assert v is not None
        assert v.winner == "pro"
        assert v.margin == 0.6
        assert v.rubric == {"q": 0.7}
        assert v.reasoning == "ok"
        assert v.judge_model == "judge-1"

    def test_markdown_fenced_json(self) -> None:
        body = '```json\n{"winner": "con", "margin": 0.4}\n```'
        v = JudgePanelScorer._parse_verdict(body, "j")
        assert v is not None
        assert v.winner == "con"
        assert v.margin == 0.4

    def test_unfenced_with_surrounding_prose(self) -> None:
        body = 'Here is my verdict:\n{"winner": "pro", "margin": 0.5}\nThanks.'
        v = JudgePanelScorer._parse_verdict(body, "j")
        assert v is not None
        assert v.winner == "pro"

    def test_invalid_json_returns_none(self) -> None:
        assert JudgePanelScorer._parse_verdict("not json at all", "j") is None

    def test_empty_returns_none(self) -> None:
        assert JudgePanelScorer._parse_verdict("", "j") is None

    def test_missing_winner_returns_none(self) -> None:
        assert JudgePanelScorer._parse_verdict('{"margin": 0.5}', "j") is None

    def test_non_object_returns_none(self) -> None:
        assert JudgePanelScorer._parse_verdict("[1, 2, 3]", "j") is None


# -- _aggregate_verdicts ---------------------------------------------------


class TestAggregateVerdicts:
    def test_unanimous(self) -> None:
        verdicts = [
            JudgeVerdict(judge_model=f"j{i}", winner="pro", margin=0.7 + 0.1 * i) for i in range(3)
        ]
        winner, margin = JudgePanelScorer._aggregate_verdicts(verdicts)
        assert winner == "pro"
        assert margin == pytest.approx((0.7 + 0.8 + 0.9) / 3)

    def test_split_2_1(self) -> None:
        verdicts = [
            JudgeVerdict(judge_model="j1", winner="pro", margin=0.6),
            JudgeVerdict(judge_model="j2", winner="pro", margin=0.5),
            JudgeVerdict(judge_model="j3", winner="con", margin=0.4),
        ]
        winner, margin = JudgePanelScorer._aggregate_verdicts(verdicts)
        assert winner == "pro"
        assert margin == pytest.approx(0.55)

    def test_three_way_tie_is_draw(self) -> None:
        verdicts = [
            JudgeVerdict(judge_model="j1", winner="pro"),
            JudgeVerdict(judge_model="j2", winner="con"),
            JudgeVerdict(judge_model="j3", winner="other"),
        ]
        winner, margin = JudgePanelScorer._aggregate_verdicts(verdicts)
        assert winner is None
        assert margin == 0.0

    def test_even_split_is_draw(self) -> None:
        verdicts = [
            JudgeVerdict(judge_model="j1", winner="pro", margin=0.9),
            JudgeVerdict(judge_model="j2", winner="con", margin=0.9),
        ]
        winner, margin = JudgePanelScorer._aggregate_verdicts(verdicts)
        assert winner is None
        assert margin == 0.0

    def test_empty_returns_draw(self) -> None:
        winner, margin = JudgePanelScorer._aggregate_verdicts([])
        assert winner is None
        assert margin == 0.0


# -- _format_transcript ----------------------------------------------------


class TestFormatTranscript:
    def test_includes_turns_and_interjections(self) -> None:
        rounds = [
            RoundEntry(
                round_num=1,
                entries=[
                    TranscriptEntry(round_num=1, agent_name="pro", content="Pro round 1."),
                    TranscriptEntry(
                        round_num=1,
                        agent_name="hooman",
                        content="Hey what about cost?",
                        entry_type="interjection",
                    ),
                    TranscriptEntry(round_num=1, agent_name="con", content="Con round 1."),
                ],
            ),
        ]
        text = JudgePanelScorer._format_transcript(rounds)
        assert "Round 1" in text
        assert "[PRO]" in text
        assert "[CON]" in text
        assert "[AUDIENCE: hooman]" in text
        assert "Pro round 1." in text
        assert "Hey what about cost?" in text


# -- _compute_agent_scores -------------------------------------------------


class TestComputeAgentScores:
    def test_unanimous_win(self) -> None:
        verdicts = [
            JudgeVerdict(judge_model=f"j{i}", winner="pro", rubric={"q": 0.7}) for i in range(3)
        ]
        scores = JudgePanelScorer._compute_agent_scores(verdicts, ["pro", "con"])
        by_name = {s.agent_name: s for s in scores}
        assert by_name["pro"].score == pytest.approx(1.0)
        assert by_name["con"].score == pytest.approx(0.0)
        assert by_name["pro"].rubric == {"q": pytest.approx(0.7)}
        assert by_name["con"].rubric == {}

    def test_split_2_1(self) -> None:
        verdicts = [
            JudgeVerdict(judge_model="j1", winner="pro", rubric={"q": 0.6}),
            JudgeVerdict(judge_model="j2", winner="pro", rubric={"q": 0.8}),
            JudgeVerdict(judge_model="j3", winner="con", rubric={"q": 0.5}),
        ]
        scores = JudgePanelScorer._compute_agent_scores(verdicts, ["pro", "con"])
        by_name = {s.agent_name: s for s in scores}
        assert by_name["pro"].score == pytest.approx(2 / 3)
        assert by_name["con"].score == pytest.approx(1 / 3)
        assert by_name["pro"].rubric["q"] == pytest.approx(0.7)
        assert by_name["con"].rubric["q"] == pytest.approx(0.5)

    def test_no_verdicts(self) -> None:
        scores = JudgePanelScorer._compute_agent_scores([], ["pro", "con"])
        assert all(s.score == 0.0 for s in scores)
        assert all(s.rubric == {} for s in scores)


# -- score() end-to-end -----------------------------------------------------


class TestScoreEndToEnd:
    async def test_score_full_loop(self) -> None:
        judges = [
            _mock_judge(_verdict_response("pro", 0.8, argument_quality=0.9)),
            _mock_judge(_verdict_response("pro", 0.7, argument_quality=0.8)),
            _mock_judge(_verdict_response("con", 0.6, argument_quality=0.7)),
        ]
        scorer = JudgePanelScorer(judges=judges)
        result = await scorer.score(_council_result())

        assert result.council_topic == "Topic"
        assert len(result.verdicts) == 3
        assert result.winner == "pro"
        assert result.win_margin == pytest.approx(0.75)
        assert result.metadata["judge_count"] == 3
        assert result.metadata["verdict_count"] == 3

        by_name = {s.agent_name: s for s in result.agent_scores}
        assert by_name["pro"].score == pytest.approx(2 / 3)
        assert by_name["con"].score == pytest.approx(1 / 3)

        # Verify each judge was actually called.
        for j in judges:
            j.send_turn.assert_awaited_once()

    async def test_score_handles_judge_failures(self) -> None:
        good = _mock_judge(_verdict_response("pro", 0.8))
        bad = AsyncMock()
        bad.send_turn.side_effect = RuntimeError("network down")
        scorer = JudgePanelScorer(judges=[good, bad])

        result = await scorer.score(_council_result())
        assert len(result.verdicts) == 1
        assert result.winner == "pro"
        assert result.metadata["verdict_count"] == 1

    async def test_score_handles_unparsable_judge(self) -> None:
        good = _mock_judge(_verdict_response("pro", 0.8))
        garbage = _mock_judge(ChatResponse(content="not JSON", model="bad-judge"))
        scorer = JudgePanelScorer(judges=[good, garbage])

        result = await scorer.score(_council_result())
        assert len(result.verdicts) == 1
        assert result.winner == "pro"

    async def test_score_all_judges_fail(self) -> None:
        judges = [_mock_judge(ChatResponse(content="garbage", model="x")) for _ in range(3)]
        scorer = JudgePanelScorer(judges=judges)

        result = await scorer.score(_council_result())
        assert result.verdicts == []
        assert result.winner is None
        assert result.win_margin == 0.0


# -- Constructor validation ------------------------------------------------


class TestConstructor:
    def test_empty_judges_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one judge"):
            JudgePanelScorer(judges=[])

    def test_default_rubric(self) -> None:
        scorer = JudgePanelScorer(judges=[AsyncMock()])
        assert "argument_quality" in scorer.rubric_fields
        assert "rebuttal_strength" in scorer.rubric_fields

    def test_custom_rubric(self) -> None:
        scorer = JudgePanelScorer(
            judges=[AsyncMock()],
            rubric_fields=["a", "b"],
        )
        assert scorer.rubric_fields == ["a", "b"]

    def test_custom_prompt(self) -> None:
        prompt = "topic={topic} agents={agents} rubric={rubric_fields} t={transcript}"
        scorer = JudgePanelScorer(judges=[AsyncMock()], scoring_prompt=prompt)
        assert scorer.scoring_prompt == prompt
