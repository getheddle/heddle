"""Council MCP bridge — execute council tool calls directly (no NATS).

Unlike the main MCPBridge which dispatches through NATS, CouncilBridge
manages council sessions in-process.  Council discussions run as
background tasks; status, transcript, and stop operations query or
control the active session.

Follows the pattern of :class:`heddle.mcp.workshop_bridge.WorkshopBridge`.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from heddle.contrib.council.config import load_council_config
from heddle.contrib.council.schemas import CouncilResult, TranscriptEntry
from heddle.contrib.council.transcript import TranscriptStore

if TYPE_CHECKING:
    from heddle.contrib.council.runner import CouncilRunner

logger = structlog.get_logger()


class CouncilBridgeError(Exception):
    """Raised when a council tool call fails."""


@dataclass
class _ActiveCouncil:
    """Tracks an in-progress council discussion."""

    council_id: str
    topic: str
    config_name: str
    task: asyncio.Task | None = None
    result: CouncilResult | None = None
    transcript: TranscriptStore = field(default_factory=TranscriptStore)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None


class CouncilBridge:
    """Bridge MCP tool calls to :class:`CouncilRunner`.

    Manages active council sessions and provides status, transcript,
    intervention, and stop operations.

    Args:
        runner: A configured :class:`CouncilRunner` with backends.
        configs_dir: Directory containing council YAML configs.
    """

    def __init__(
        self,
        runner: CouncilRunner,
        configs_dir: str = "configs/councils",
    ) -> None:
        self.runner = runner
        self.configs_dir = Path(configs_dir)
        self._active: dict[str, _ActiveCouncil] = {}

    async def dispatch(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch a council tool call by action name.

        Args:
            action: Action name (``start``, ``status``, etc.).
            arguments: Tool arguments from MCP client.

        Returns:
            JSON-serializable result dict.
        """
        handler = _HANDLERS.get(action)
        if handler is None:
            msg = f"Unknown council action: {action}"
            raise CouncilBridgeError(msg)
        return await handler(self, arguments)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _start(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Start a council discussion as a background task."""
        topic = arguments.get("topic", "")
        config_name = arguments.get("config_name", "")

        if not topic:
            raise CouncilBridgeError("'topic' is required")
        if not config_name:
            raise CouncilBridgeError("'config_name' is required")

        # Load config.
        config_path = self.configs_dir / f"{config_name}.yaml"
        if not config_path.exists():
            msg = (
                f"Council config not found: {config_path}. "
                f"Available: {[p.stem for p in self.configs_dir.glob('*.yaml')]}"
            )
            raise CouncilBridgeError(msg)

        config = load_council_config(str(config_path))
        council_id = str(uuid.uuid4())[:8]

        active = _ActiveCouncil(
            council_id=council_id,
            topic=topic,
            config_name=config_name,
        )
        self._active[council_id] = active

        # Run the council in the background.
        async def _run() -> None:
            try:
                # Wire up the on_turn callback to populate transcript.
                def on_turn(entry: TranscriptEntry) -> None:
                    active.transcript.add_entry(entry)

                result = await self.runner.run(topic, config=config, on_turn=on_turn)
                active.result = result
            except Exception as e:
                active.error = str(e)
                logger.error(
                    "council.bridge.run_failed",
                    council_id=council_id,
                    error=str(e),
                )

        active.task = asyncio.create_task(_run())

        return {
            "council_id": council_id,
            "topic": topic,
            "config_name": config_name,
            "status": "started",
        }

    async def _status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Get the current status of a council discussion."""
        council_id = arguments.get("council_id", "")
        active = self._active.get(council_id)

        if active is None:
            return {"error": f"No council with ID '{council_id}'"}

        if active.result is not None:
            return {
                "council_id": council_id,
                "status": "completed",
                "rounds_completed": active.result.rounds_completed,
                "converged": active.result.converged,
                "convergence_score": active.result.convergence_score,
            }

        if active.error is not None:
            return {
                "council_id": council_id,
                "status": "failed",
                "error": active.error,
            }

        return {
            "council_id": council_id,
            "status": "running",
            "rounds_so_far": len(active.transcript.rounds),
            "entries_so_far": active.transcript.total_entries,
        }

    async def _transcript(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Get the transcript of a council discussion."""
        council_id = arguments.get("council_id", "")
        agent_filter = arguments.get("agent_filter")

        active = self._active.get(council_id)
        if active is None:
            return {"error": f"No council with ID '{council_id}'"}

        # Use the completed result's transcript if available.
        if active.result is not None:
            transcript_data = active.result.transcript
        else:
            transcript_data = active.transcript.rounds

        # Apply agent filter if requested.
        rounds_out = []
        for r in transcript_data:
            entries = r.entries if hasattr(r, "entries") else []
            if agent_filter:
                entries = [e for e in entries if e.agent_name == agent_filter]
            rounds_out.append(
                {
                    "round": r.round_num,
                    "entries": [
                        {
                            "agent": e.agent_name,
                            "role": e.role,
                            "content": e.content,
                            "model": e.model_used,
                        }
                        for e in entries
                    ],
                    "convergence_score": r.convergence_score,
                }
            )

        return {
            "council_id": council_id,
            "rounds": rounds_out,
            "total_entries": sum(len(r["entries"]) for r in rounds_out),
        }

    async def _intervene(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Inject a human message into an active council."""
        council_id = arguments.get("council_id", "")
        message = arguments.get("message", "")

        active = self._active.get(council_id)
        if active is None:
            return {"error": f"No council with ID '{council_id}'"}

        if active.result is not None:
            return {"error": "Council has already completed"}

        # Add a human entry to the current round.
        if not active.transcript.rounds:
            active.transcript.start_round(0)

        active.transcript.add_entry(
            TranscriptEntry(
                round_num=active.transcript.rounds[-1].round_num,
                agent_name="human",
                role="Human intervention",
                content=message,
            )
        )

        return {
            "council_id": council_id,
            "status": "intervention_added",
            "message_length": len(message),
        }

    async def _stop(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Stop an active council and return current state."""
        council_id = arguments.get("council_id", "")
        active = self._active.get(council_id)

        if active is None:
            return {"error": f"No council with ID '{council_id}'"}

        if active.task is not None and not active.task.done():
            active.task.cancel()

        if active.result is not None:
            return {
                "council_id": council_id,
                "status": "already_completed",
                "synthesis": active.result.synthesis,
            }

        return {
            "council_id": council_id,
            "status": "stopped",
            "rounds_completed": len(active.transcript.rounds),
            "entries_collected": active.transcript.total_entries,
        }


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Any] = {
    "start": CouncilBridge._start,
    "status": CouncilBridge._status,
    "transcript": CouncilBridge._transcript,
    "intervene": CouncilBridge._intervene,
    "stop": CouncilBridge._stop,
}
