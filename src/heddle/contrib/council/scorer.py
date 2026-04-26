"""Post-council evaluation framework.

Scorers consume a :class:`CouncilResult` and produce a
:class:`ScoringResult` with per-agent scores, judge verdicts, and an
aggregate winner.  This is the post-debate analogue of the in-loop
:class:`heddle.contrib.council.convergence.ConvergenceDetector` —
convergence detection happens during the discussion, scoring happens
after it ends.

The reference implementation is :class:`JudgePanelScorer`, which sends
the full transcript to a panel of LLM judges (typically from different
model families to reduce family-bias, mirroring Lech Mazur's debate
benchmark methodology) and aggregates their verdicts by majority vote.
"""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from collections import Counter
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from heddle.contrib.chatbridge.base import ChatBridge
    from heddle.contrib.council.schemas import CouncilResult, RoundEntry

logger = structlog.get_logger()


DEFAULT_RUBRIC_FIELDS = (
    "argument_quality",
    "rebuttal_strength",
    "evidence_use",
    "rhetorical_skill",
    "responsiveness",
)


class AgentScore(BaseModel):
    """Aggregate score for one agent across the judge panel."""

    agent_name: str
    score: float = 0.0  # win rate across judges, 0..1
    rubric: dict[str, float] = Field(default_factory=dict)
    notes: str = ""


class JudgeVerdict(BaseModel):
    """One judge's verdict on a single debate."""

    judge_model: str
    winner: str  # agent name
    margin: float = 0.0  # 0..1, how decisive
    rubric: dict[str, float] = Field(default_factory=dict)
    reasoning: str = ""


class ScoringResult(BaseModel):
    """Aggregated scoring across all judges."""

    council_topic: str
    agent_scores: list[AgentScore] = Field(default_factory=list)
    verdicts: list[JudgeVerdict] = Field(default_factory=list)
    winner: str | None = None  # None means draw
    win_margin: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class Scorer(ABC):
    """Abstract base for council post-hoc scorers."""

    @abstractmethod
    async def score(self, result: CouncilResult) -> ScoringResult:
        """Score a finished council deliberation."""


class JudgePanelScorer(Scorer):
    """Send a transcript to N judges and aggregate verdicts by majority vote.

    Each judge is a :class:`ChatBridge` — typically from a different
    model family than the debaters, to reduce family-bias in scoring.
    Judges return JSON with ``winner`` / ``margin`` / ``rubric`` /
    ``reasoning``.  The panel aggregates by majority vote; ties (equal
    top-vote count, or 1-1-1 splits) are recorded as draws.

    Args:
        judges: List of :class:`ChatBridge` instances (one per judge).
        rubric_fields: Rubric dimensions for the judge to score.
            Defaults to ``DEFAULT_RUBRIC_FIELDS``.
        scoring_prompt: Override the default judge system prompt.
            Must contain ``{transcript}``, ``{topic}``, ``{agents}``,
            and ``{rubric_fields}`` placeholders.
    """

    def __init__(
        self,
        judges: list[ChatBridge],
        rubric_fields: list[str] | None = None,
        scoring_prompt: str | None = None,
    ) -> None:
        if not judges:
            msg = "JudgePanelScorer requires at least one judge"
            raise ValueError(msg)
        self.judges = judges
        self.rubric_fields = list(rubric_fields) if rubric_fields else list(DEFAULT_RUBRIC_FIELDS)
        self.scoring_prompt = scoring_prompt or self._default_prompt()

    async def score(self, result: CouncilResult) -> ScoringResult:
        """Score a finished council via the judge panel."""
        agent_names = sorted({e.agent_name for r in result.transcript for e in r.entries})

        transcript_text = self._format_transcript(result.transcript)
        prompt = self.scoring_prompt.format(
            transcript=transcript_text,
            topic=result.topic,
            agents=", ".join(agent_names),
            rubric_fields=", ".join(self.rubric_fields),
        )

        verdicts = await self._collect_verdicts(prompt)
        winner, win_margin = self._aggregate_verdicts(verdicts)
        agent_scores = self._compute_agent_scores(verdicts, agent_names)

        return ScoringResult(
            council_topic=result.topic,
            agent_scores=agent_scores,
            verdicts=verdicts,
            winner=winner,
            win_margin=win_margin,
            metadata={
                "judge_count": len(self.judges),
                "verdict_count": len(verdicts),
                "rubric_fields": list(self.rubric_fields),
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _collect_verdicts(self, prompt: str) -> list[JudgeVerdict]:
        """Send the scoring prompt to all judges concurrently."""

        async def _one(judge: ChatBridge, idx: int) -> JudgeVerdict | None:
            try:
                response = await judge.send_turn(
                    message=prompt,
                    context={},
                    session_id=f"score-{idx}",
                )
            except Exception as e:
                logger.warning("scorer.judge.failed", judge_index=idx, error=str(e))
                return None
            return self._parse_verdict(response.content, response.model or f"judge-{idx}")

        results = await asyncio.gather(*[_one(j, i) for i, j in enumerate(self.judges)])
        return [v for v in results if v is not None]

    @staticmethod
    def _format_transcript(rounds: list[RoundEntry]) -> str:
        """Convert :class:`RoundEntry` list into readable text.

        Distinguishes panelist turns from audience interjections.
        """
        lines: list[str] = []
        for round_entry in rounds:
            lines.append(f"--- Round {round_entry.round_num} ---")
            for entry in round_entry.entries:
                if entry.entry_type == "interjection":
                    label = f"[AUDIENCE: {entry.agent_name}]"
                else:
                    label = f"[{entry.agent_name.upper()}]"
                lines.append(f"{label}\n{entry.content.strip()}\n")
        return "\n".join(lines)

    @staticmethod
    def _parse_verdict(content: str, judge_model: str) -> JudgeVerdict | None:
        """Extract JSON verdict from a judge response.

        Handles bare JSON and markdown-wrapped (```json ... ```) JSON.
        Returns ``None`` if parsing fails or required fields are missing.
        """
        if not content:
            return None

        text = content.strip()

        # Strip markdown code fence if present.
        fence = re.search(r"```(?:json)?\s*\n(.+?)\n```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()

        # If there's still surrounding text, try to extract the first JSON object.
        if not text.startswith("{"):
            obj = re.search(r"\{.*\}", text, re.DOTALL)
            if obj:
                text = obj.group(0)

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            logger.warning("scorer.verdict.parse_failed", preview=content[:200])
            return None

        if not isinstance(data, dict) or "winner" not in data:
            return None

        try:
            return JudgeVerdict(
                judge_model=judge_model,
                winner=str(data["winner"]),
                margin=float(data.get("margin", 0.0)),
                rubric={k: float(v) for k, v in (data.get("rubric") or {}).items()},
                reasoning=str(data.get("reasoning", "")),
            )
        except (TypeError, ValueError):
            logger.warning("scorer.verdict.coerce_failed", preview=content[:200])
            return None

    @staticmethod
    def _aggregate_verdicts(verdicts: list[JudgeVerdict]) -> tuple[str | None, float]:
        """Majority vote on winner; ties are draws.

        Returns ``(winner_name, avg_margin)``.  ``winner_name`` is
        ``None`` for an empty verdict list, an even split, or a
        three-way (or worse) tie at the top.  ``avg_margin`` averages
        the margins of verdicts that voted for the winner; ``0.0`` for
        draws.
        """
        if not verdicts:
            return None, 0.0

        counts = Counter(v.winner for v in verdicts)
        ranking = counts.most_common()
        top_count = ranking[0][1]
        tied = [name for name, c in ranking if c == top_count]
        if len(tied) > 1:
            return None, 0.0

        winner = ranking[0][0]
        winning_margins = [v.margin for v in verdicts if v.winner == winner]
        avg_margin = sum(winning_margins) / len(winning_margins) if winning_margins else 0.0
        return winner, avg_margin

    @staticmethod
    def _compute_agent_scores(
        verdicts: list[JudgeVerdict],
        agent_names: list[str],
    ) -> list[AgentScore]:
        """Per-agent win rate across judges.

        Each agent's ``score`` is the fraction of judges that picked
        them as winner.  ``rubric`` is the average of rubric scores
        from verdicts where the agent won (empty if the agent never
        won, since judges report rubric for the winner).
        """
        if not verdicts:
            return [AgentScore(agent_name=n) for n in agent_names]

        n_judges = len(verdicts)
        scores: list[AgentScore] = []
        for name in agent_names:
            winning = [v for v in verdicts if v.winner == name]
            wins = len(winning)
            avg_rubric: dict[str, float] = {}
            if winning:
                fields: set[str] = set()
                for v in winning:
                    fields.update(v.rubric)
                for field in fields:
                    vals = [v.rubric.get(field, 0.0) for v in winning]
                    avg_rubric[field] = sum(vals) / len(vals)
            scores.append(
                AgentScore(
                    agent_name=name,
                    score=wins / n_judges,
                    rubric=avg_rubric,
                )
            )
        return scores

    def _default_prompt(self) -> str:
        return (
            "You are a fair, substantive judge of a structured debate.\n"
            "Judge on argument quality, not rhetorical style.  Reward "
            "concrete evidence, sharp rebuttals, and direct engagement "
            "with the opponent.  Penalize evasion, ad hominem, and "
            "unsupported claims.\n\n"
            "TOPIC: {topic}\n"
            "DEBATERS: {agents}\n\n"
            "TRANSCRIPT:\n{transcript}\n\n"
            "Score each rubric dimension from 0.0 to 1.0 for the WINNER:\n"
            "{rubric_fields}\n\n"
            "Return JSON ONLY (no prose, no markdown fence) with this shape:\n"
            "{{\n"
            '  "winner": "<exact agent name>",\n'
            '  "margin": <0.0..1.0 — how decisive>,\n'
            '  "rubric": {{"argument_quality": 0.0, ...}},\n'
            '  "reasoning": "<one or two sentences>"\n'
            "}}"
        )
