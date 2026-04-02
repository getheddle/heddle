"""Discussion protocols — pluggable turn-ordering and context-building.

Each protocol defines *who speaks when* and *what they see*.  The
:class:`CouncilRunner` and :class:`CouncilOrchestrator` delegate to
the active protocol every round.

Built-in protocols:
    - ``round_robin`` — all agents speak every round in config order
    - ``structured_debate`` — positions -> rebuttals -> closing (Phase 5)
    - ``delphi`` — anonymized positions with convergence feedback (Phase 5)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from loom.contrib.council.schemas import AgentConfig, AgentTurn

if TYPE_CHECKING:
    from loom.contrib.council.transcript import TranscriptStore


class DiscussionProtocol(ABC):
    """Abstract base for discussion protocols."""

    @abstractmethod
    def get_turn_order(
        self,
        round_num: int,
        agents: list[AgentConfig],
        transcript: TranscriptStore,
    ) -> list[AgentTurn]:
        """Determine who speaks this round and in what order."""

    @abstractmethod
    def build_agent_context(
        self,
        agent: AgentConfig,
        transcript: TranscriptStore,
        round_num: int,
        topic: str,
    ) -> dict[str, Any]:
        """Build the payload context for one agent's turn."""


class RoundRobinProtocol(DiscussionProtocol):
    """All agents speak every round, in config order.

    Round 1: each agent states their initial position (no prior transcript).
    Round 2+: each agent sees the (filtered) transcript and responds.
    """

    def get_turn_order(  # noqa: D102  # noqa: D102
        self,
        round_num: int,
        agents: list[AgentConfig],
        transcript: TranscriptStore,
    ) -> list[AgentTurn]:
        return [AgentTurn(agent=a, round_num=round_num) for a in agents]

    def build_agent_context(  # noqa: D102  # noqa: D102
        self,
        agent: AgentConfig,
        transcript: TranscriptStore,
        round_num: int,
        topic: str,
    ) -> dict[str, Any]:
        # Get entries visible to this agent, up to previous round.
        prior_round = round_num - 1 if round_num > 1 else None
        visible = transcript.get_visible_transcript(agent, up_to_round=prior_round)
        round_context = transcript.format_for_payload(visible, max_chars=transcript._max_chars)

        if round_num == 1:
            instructions = (
                "This is Round 1 of a team discussion.  State your initial "
                "position on the topic.  Be specific and substantive."
            )
        else:
            instructions = (
                f"This is Round {round_num}.  Review the discussion so far "
                f"and refine your position.  Address points raised by other "
                f"participants.  Note agreements and remaining disagreements."
            )

        return {
            "topic": topic,
            "round_num": round_num,
            "role": agent.role,
            "round_context": round_context,
            "instructions": instructions,
        }


class StructuredDebateProtocol(DiscussionProtocol):
    """Three-phase structured debate: positions -> rebuttals -> closing.

    Round 1: Initial positions (no transcript).
    Round 2..N-1: Rebuttals — agents respond to specific points.
    Round N (final): Closing statements summarizing final position.
    """

    def get_turn_order(  # noqa: D102
        self,
        round_num: int,
        agents: list[AgentConfig],
        transcript: TranscriptStore,
    ) -> list[AgentTurn]:
        return [AgentTurn(agent=a, round_num=round_num) for a in agents]

    def build_agent_context(  # noqa: D102
        self,
        agent: AgentConfig,
        transcript: TranscriptStore,
        round_num: int,
        topic: str,
    ) -> dict[str, Any]:
        visible = transcript.get_visible_transcript(
            agent, up_to_round=round_num - 1 if round_num > 1 else None
        )
        round_context = transcript.format_for_payload(visible, max_chars=transcript._max_chars)

        if round_num == 1:
            instructions = (
                "OPENING STATEMENT: Present your initial position on the "
                "topic.  Be clear, specific, and well-reasoned.  This is "
                "the foundation others will respond to."
            )
        else:
            # Check if this is likely the final round by examining
            # whether convergence is close or max_rounds is near.
            instructions = (
                f"REBUTTAL (Round {round_num}): Review the discussion so "
                f"far.  Directly address specific points raised by other "
                f"participants.  Concede where appropriate, challenge where "
                f"you disagree, and propose synthesis where possible."
            )

        return {
            "topic": topic,
            "round_num": round_num,
            "role": agent.role,
            "round_context": round_context,
            "instructions": instructions,
        }


class DelphiProtocol(DiscussionProtocol):
    """Delphi method — anonymized positions with convergence feedback.

    Agent identities are hidden in the transcript shown to participants.
    Each round includes the previous round's convergence score as feedback.
    """

    def get_turn_order(  # noqa: D102
        self,
        round_num: int,
        agents: list[AgentConfig],
        transcript: TranscriptStore,
    ) -> list[AgentTurn]:
        return [AgentTurn(agent=a, round_num=round_num) for a in agents]

    def build_agent_context(  # noqa: D102
        self,
        agent: AgentConfig,
        transcript: TranscriptStore,
        round_num: int,
        topic: str,
    ) -> dict[str, Any]:
        # Build anonymized transcript.
        visible = transcript.get_visible_transcript(
            agent, up_to_round=round_num - 1 if round_num > 1 else None
        )
        anon_context = self._anonymize_transcript(visible, agent.name)

        # Include convergence feedback from prior round.
        convergence_feedback = ""
        if round_num > 1:
            rounds = transcript.rounds
            for r in rounds:
                if r.round_num == round_num - 1 and r.convergence_score is not None:
                    convergence_feedback = (
                        f"\nPrior round agreement score: "
                        f"{r.convergence_score:.2f} (0=total disagreement, "
                        f"1=full consensus)"
                    )
                    break

        if round_num == 1:
            instructions = (
                "This is a Delphi-method discussion.  State your position "
                "independently.  Other participants' identities are hidden "
                "to reduce anchoring bias."
            )
        else:
            instructions = (
                f"Round {round_num} of Delphi discussion.  Review the "
                f"anonymized positions below and revise yours if persuaded.  "
                f"Focus on the arguments, not who made them."
                f"{convergence_feedback}"
            )

        return {
            "topic": topic,
            "round_num": round_num,
            "role": agent.role,
            "round_context": anon_context,
            "instructions": instructions,
        }

    @staticmethod
    def _anonymize_transcript(
        entries: list,
        self_name: str,
    ) -> str:
        """Replace agent names with Participant A/B/C labels."""
        name_map: dict[str, str] = {}
        label_idx = 0

        blocks: list[str] = []
        for e in entries:
            if e.agent_name == self_name:
                label = "You"
            elif e.agent_name not in name_map:
                label = f"Participant {chr(65 + label_idx)}"
                name_map[e.agent_name] = label
                label_idx += 1
            else:
                label = name_map[e.agent_name]

            blocks.append(f"[Round {e.round_num}] {label}:\n{e.content}")

        return "\n\n".join(blocks)


# -- Protocol registry -------------------------------------------------

PROTOCOL_REGISTRY: dict[str, type[DiscussionProtocol]] = {
    "round_robin": RoundRobinProtocol,
    "structured_debate": StructuredDebateProtocol,
    "delphi": DelphiProtocol,
}


def get_protocol(name: str) -> DiscussionProtocol:
    """Instantiate a protocol by name.

    Raises :class:`ValueError` if *name* is not in the registry.
    """
    cls = PROTOCOL_REGISTRY.get(name)
    if cls is None:
        msg = f"Unknown protocol: '{name}'. Available: {sorted(PROTOCOL_REGISTRY)}"
        raise ValueError(msg)
    return cls()
