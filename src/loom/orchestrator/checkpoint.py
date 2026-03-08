"""
Self-summarization checkpoint system for orchestrators.

The orchestrator's context is precious. This module compresses
conversation history into structured state snapshots at defined intervals,
allowing the orchestrator to "reboot" with a clean, compact understanding
of where things stand.

Checkpoint trigger: when estimated token count exceeds threshold.
"""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis
import structlog
import tiktoken

from loom.core.messages import CheckpointState

logger = structlog.get_logger()


class CheckpointManager:
    """
    Manages orchestrator state compression.

    Workflow:
    1. After each worker result, estimate_tokens() checks context size
    2. If threshold exceeded, create_checkpoint() asks a summarizer
       to compress the current state
    3. The orchestrator restarts with: system_prompt + checkpoint + recent_window
    """

    def __init__(
        self,
        redis_url: str = "redis://redis:6379",
        token_threshold: int = 50_000,     # Trigger checkpoint at this count
        recent_window_size: int = 5,       # Keep last N interactions in detail
        encoding_name: str = "cl100k_base",
    ):
        self.redis = redis.from_url(redis_url)
        self.token_threshold = token_threshold
        self.recent_window_size = recent_window_size
        self.encoder = tiktoken.get_encoding(encoding_name)

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for a string."""
        return len(self.encoder.encode(text))

    def should_checkpoint(self, conversation_history: list[dict]) -> bool:
        """Check if context has grown enough to trigger compression."""
        total = sum(
            self.estimate_tokens(json.dumps(msg))
            for msg in conversation_history
        )
        return total > self.token_threshold

    async def create_checkpoint(
        self,
        goal_id: str,
        original_instruction: str,
        completed_tasks: list[dict[str, Any]],
        pending_tasks: list[dict[str, Any]],
        open_issues: list[str],
        decisions_made: list[str],
        checkpoint_number: int,
    ) -> CheckpointState:
        """
        Build a checkpoint. The orchestrator or a dedicated summarizer
        compresses current state into this structure.
        """
        # Build executive summary from completed task outcomes
        outcomes = []
        for t in completed_tasks[-20:]:  # Last 20 for summary
            status = t.get("status", "unknown")
            summary = t.get("summary", t.get("worker_type", "task"))
            outcomes.append(f"- [{status}] {summary}")

        executive_summary = (
            f"Goal: {original_instruction}\n"
            f"Progress: {len(completed_tasks)} completed, {len(pending_tasks)} pending.\n"
            f"Recent outcomes:\n" + "\n".join(outcomes[-10:])
        )

        total_tokens = self.estimate_tokens(executive_summary)

        checkpoint = CheckpointState(
            goal_id=goal_id,
            original_instruction=original_instruction,
            executive_summary=executive_summary,
            completed_tasks=[
                {"task_id": t["task_id"], "worker_type": t.get("worker_type"), "summary": t.get("summary", "")}
                for t in completed_tasks
            ],
            pending_tasks=pending_tasks,
            open_issues=open_issues,
            decisions_made=decisions_made,
            context_token_count=total_tokens,
            checkpoint_number=checkpoint_number,
        )

        # Persist to Redis
        key = f"loom:checkpoint:{goal_id}:{checkpoint_number}"
        await self.redis.set(key, checkpoint.model_dump_json(), ex=86400)  # 24h TTL

        # Also maintain a "latest" pointer
        await self.redis.set(f"loom:checkpoint:{goal_id}:latest", key, ex=86400)

        logger.info(
            "checkpoint.created",
            goal_id=goal_id,
            checkpoint_number=checkpoint_number,
            token_count=total_tokens,
        )
        return checkpoint

    async def load_latest(self, goal_id: str) -> CheckpointState | None:
        """Load the most recent checkpoint for a goal."""
        latest_key = await self.redis.get(f"loom:checkpoint:{goal_id}:latest")
        if not latest_key:
            return None
        data = await self.redis.get(latest_key)
        if not data:
            return None
        return CheckpointState.model_validate_json(data)

    def format_for_injection(self, checkpoint: CheckpointState) -> str:
        """
        Format checkpoint as context to inject into a fresh orchestrator session.
        This is what the orchestrator sees when it "wakes up" after a checkpoint.
        """
        sections = [
            f"=== CHECKPOINT #{checkpoint.checkpoint_number} ===",
            f"Original Goal: {checkpoint.original_instruction}",
            "",
            "--- Executive Summary ---",
            checkpoint.executive_summary,
            "",
            f"--- Decisions Made ({len(checkpoint.decisions_made)}) ---",
        ]
        for d in checkpoint.decisions_made:
            sections.append(f"  * {d}")

        if checkpoint.open_issues:
            sections.append(f"\n--- Open Issues ({len(checkpoint.open_issues)}) ---")
            for issue in checkpoint.open_issues:
                sections.append(f"  ! {issue}")

        sections.append(f"\n--- Pending Tasks ({len(checkpoint.pending_tasks)}) ---")
        for t in checkpoint.pending_tasks:
            sections.append(f"  -> {t}")

        sections.append("\n=== END CHECKPOINT ===")
        return "\n".join(sections)
