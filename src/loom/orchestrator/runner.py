"""
Orchestrator actor lifecycle.

The orchestrator is a longer-lived LLM actor that:
- Receives high-level goals
- Decomposes them into subtasks for workers
- Collects and synthesizes results
- Performs periodic self-summarization checkpoints
"""
from __future__ import annotations

from typing import Any

import structlog

from loom.core.actor import BaseActor

logger = structlog.get_logger()


class OrchestratorActor(BaseActor):
    """
    Orchestrator actor stub.

    TODO: Implement the full decomposition/synthesis loop.
    This is the first real extension point after scaffolding.
    """

    def __init__(
        self,
        actor_id: str,
        config_path: str,
        nats_url: str = "nats://nats:4222",
        redis_url: str = "redis://redis:6379",
    ):
        super().__init__(actor_id, nats_url)
        self.config_path = config_path
        self.redis_url = redis_url

    async def handle_message(self, data: dict[str, Any]) -> None:
        logger.info("orchestrator.received", data_keys=list(data.keys()))
        # TODO: Implement goal decomposition, task dispatch, result synthesis
