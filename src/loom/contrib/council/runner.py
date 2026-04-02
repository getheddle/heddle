"""CouncilRunner — NATS-free council execution.

Runs a multi-round deliberation directly against LLM backends without
requiring NATS, actors, or running infrastructure.  This is the council
equivalent of :class:`loom.workshop.test_runner.WorkerTestRunner`.

Usage::

    from loom.worker.backends import build_backends_from_env
    from loom.contrib.council.config import load_council_config
    from loom.contrib.council.runner import CouncilRunner

    config = load_council_config("configs/councils/example.yaml")
    runner = CouncilRunner(build_backends_from_env())
    result = await runner.run("Should we adopt microservices?", config=config)
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from loom.contrib.council.convergence import ConvergenceDetector
from loom.contrib.council.protocol import get_protocol
from loom.contrib.council.schemas import (
    CouncilResult,
    TranscriptEntry,
)
from loom.contrib.council.transcript import TranscriptStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from loom.contrib.council.config import CouncilConfig
    from loom.contrib.council.schemas import AgentConfig
    from loom.worker.backends import LLMBackend

logger = structlog.get_logger()


class CouncilRunner:
    """Execute a council discussion directly against LLM backends.

    This replicates the multi-round deliberation loop without NATS.
    Each agent turn calls ``backend.complete()`` directly, builds a
    transcript entry, and feeds it into the next round.

    Args:
        backends: Dict mapping tier name (``"local"``, ``"standard"``,
            ``"frontier"``) to :class:`LLMBackend` instances.
        config: Optional default :class:`CouncilConfig`.  Can be
            overridden per-call in :meth:`run`.
    """

    def __init__(
        self,
        backends: dict[str, LLMBackend],
        config: CouncilConfig | None = None,
    ) -> None:
        self.backends = backends
        self._default_config = config

    async def run(
        self,
        topic: str,
        config: CouncilConfig | None = None,
        on_turn: Callable | None = None,
    ) -> CouncilResult:
        """Run a full council deliberation.

        Args:
            topic: The discussion topic / question.
            config: Council config (overrides the constructor default).
            on_turn: Optional callback invoked after each agent's turn
                with the :class:`TranscriptEntry`.  May be sync or async.

        Returns:
            :class:`CouncilResult` with the full transcript, synthesis,
            convergence info, and token usage.
        """
        cfg = config or self._default_config
        if cfg is None:
            msg = "No council config provided"
            raise ValueError(msg)

        start = time.monotonic()
        log = logger.bind(council=cfg.name, topic=topic[:80])
        log.info("council.start", agents=len(cfg.agents), max_rounds=cfg.max_rounds)

        protocol = get_protocol(cfg.protocol)
        transcript = TranscriptStore()
        convergence_backend = self.backends.get(cfg.convergence.backend_tier.value)
        detector = ConvergenceDetector(cfg.convergence, backend=convergence_backend)

        total_tokens: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
        converged = False
        convergence_score: float | None = None
        rounds_completed = 0

        for round_num in range(1, cfg.max_rounds + 1):
            round_log = log.bind(round=round_num)
            round_log.info("council.round.start")

            transcript.start_round(round_num)
            turns = protocol.get_turn_order(round_num, cfg.agents, transcript)

            for turn in turns:
                agent = turn.agent
                context = protocol.build_agent_context(
                    agent, transcript, round_num, topic
                )

                entry = await self._execute_agent_turn(
                    agent=agent,
                    context=context,
                    round_num=round_num,
                    topic=topic,
                    config=cfg,
                )

                transcript.add_entry(entry)

                # Accumulate tokens.
                total_tokens["prompt_tokens"] += entry.token_count
                # token_count tracks prompt tokens; we don't have a
                # separate completion count from backend.complete()
                # in this simplified path.

                if on_turn is not None:
                    result = on_turn(entry)
                    if hasattr(result, "__await__"):
                        await result

                round_log.info(
                    "council.agent_turn.done",
                    agent=agent.name,
                    model=entry.model_used,
                    tokens=entry.token_count,
                )

            # Check convergence.
            conv_result = await detector.check(transcript, round_num, topic)
            transcript.set_convergence_score(round_num, conv_result.score)
            convergence_score = conv_result.score
            rounds_completed = round_num

            round_log.info(
                "council.round.done",
                convergence_score=conv_result.score,
                converged=conv_result.converged,
            )

            if conv_result.converged:
                converged = True
                log.info("council.converged", round=round_num, score=conv_result.score)
                break

        # Facilitator synthesis.
        synthesis = await self._synthesize(cfg, transcript, topic, total_tokens)

        # Build agent summaries (latest position per agent).
        agent_summaries = transcript.get_latest_positions()

        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "council.done",
            rounds=rounds_completed,
            converged=converged,
            elapsed_ms=elapsed_ms,
        )

        return CouncilResult(
            topic=topic,
            rounds_completed=rounds_completed,
            converged=converged,
            convergence_score=convergence_score,
            synthesis=synthesis,
            transcript=transcript.rounds,
            agent_summaries=agent_summaries,
            total_token_usage=total_tokens,
            elapsed_ms=elapsed_ms,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _execute_agent_turn(
        self,
        agent: AgentConfig,
        context: dict[str, Any],
        round_num: int,
        topic: str,
        config: CouncilConfig,
    ) -> TranscriptEntry:
        """Execute a single agent's turn via direct backend call."""
        tier = agent.tier.value
        backend = self.backends.get(tier)

        if backend is None:
            available = list(self.backends.keys())
            return TranscriptEntry(
                round_num=round_num,
                agent_name=agent.name,
                role=agent.role,
                content=f"[ERROR: No backend for tier '{tier}'. Available: {available}]",
                timestamp=datetime.now(UTC),
            )

        system_prompt = self._build_agent_prompt(agent, config)
        user_message = json.dumps(context, ensure_ascii=False, indent=2)

        try:
            response = await backend.complete(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=agent.max_tokens_per_turn,
                temperature=0.3,
            )
        except Exception as e:
            logger.error(
                "council.agent_turn.failed",
                agent=agent.name,
                error=str(e),
            )
            return TranscriptEntry(
                round_num=round_num,
                agent_name=agent.name,
                role=agent.role,
                content=f"[ERROR: {e}]",
                timestamp=datetime.now(UTC),
            )

        content = response.get("content") or ""
        prompt_tokens = response.get("prompt_tokens", 0)
        completion_tokens = response.get("completion_tokens", 0)

        return TranscriptEntry(
            round_num=round_num,
            agent_name=agent.name,
            role=agent.role,
            content=content,
            token_count=prompt_tokens + completion_tokens,
            model_used=response.get("model"),
            timestamp=datetime.now(UTC),
        )

    @staticmethod
    def _build_agent_prompt(
        agent: AgentConfig,
        config: CouncilConfig,
    ) -> str:
        """Build the system prompt for an agent's turn."""
        parts: list[str] = []

        parts.append(
            f"You are participating in a structured team discussion "
            f"(council: {config.name})."
        )

        if agent.role:
            parts.append(f"Your role: {agent.role}")

        parts.append(
            "Respond substantively to the topic and context provided.  "
            "Be specific, cite evidence where applicable, and clearly "
            "state your position.  Do NOT wrap your response in JSON — "
            "respond in natural prose."
        )

        return "\n\n".join(parts)

    async def _synthesize(
        self,
        config: CouncilConfig,
        transcript: TranscriptStore,
        topic: str,
        total_tokens: dict[str, int],
    ) -> str:
        """Produce the facilitator's final synthesis."""
        tier = config.facilitator.tier.value
        backend = self.backends.get(tier)

        if backend is None:
            return "[Synthesis unavailable: no backend for facilitator tier]"

        entries = transcript.get_full_transcript_entries()
        formatted = TranscriptStore.format_for_payload(entries)

        user_message = (
            f"TOPIC: {topic}\n\n"
            f"FULL DISCUSSION TRANSCRIPT:\n\n{formatted}\n\n"
            f"Produce your synthesis now."
        )

        try:
            response = await backend.complete(
                system_prompt=config.facilitator.synthesis_prompt,
                user_message=user_message,
                max_tokens=4000,
                temperature=0.2,
            )
        except Exception as e:
            logger.error("council.synthesis.failed", error=str(e))
            return f"[Synthesis failed: {e}]"

        total_tokens["prompt_tokens"] += response.get("prompt_tokens", 0)
        total_tokens["completion_tokens"] += response.get("completion_tokens", 0)

        return response.get("content") or "[Empty synthesis]"
