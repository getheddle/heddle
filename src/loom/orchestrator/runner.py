"""
Orchestrator actor lifecycle — the "thinking" layer above workers.

The orchestrator is a longer-lived LLM actor that:
- Receives high-level goals (OrchestratorGoal messages)
- Decomposes them into subtasks for workers (via decomposer.py)
- Dispatches subtasks through the router and collects results
- Synthesizes worker outputs into a coherent final answer (via synthesizer.py)
- Performs periodic self-summarization checkpoints (via checkpoint.py)

This differs from PipelineOrchestrator in that it uses an LLM to dynamically
decide which workers to invoke, rather than following a fixed stage sequence.

Message flow:
    loom.goals.incoming → OrchestratorActor.handle_message()
        → LLM decomposes goal into subtasks
        → Publishes TaskMessages to loom.tasks.incoming (one per subtask)
        → Subscribes to loom.results.{goal_id} for worker responses
        → LLM synthesizes final answer from collected results
        → Publishes final TaskResult to loom.results.{goal_id}

TODO: This is a stub. To implement the full orchestrator loop:
      1. Load an LLM backend (same as LLMWorker) for decomposition/synthesis
      2. Maintain a conversation_history list for multi-turn reasoning
      3. On each goal: call decomposer to break into subtasks, dispatch each
         to loom.tasks.incoming, collect results from loom.results.{goal_id}
      4. After collecting, call synthesizer to produce final answer
      5. Use CheckpointManager to compress context when tokens exceed threshold
      6. Consider: should the orchestrator retry failed subtasks? How many times?
"""
from __future__ import annotations

from typing import Any

import structlog

from loom.core.actor import BaseActor

logger = structlog.get_logger()


class OrchestratorActor(BaseActor):
    """
    Dynamic orchestrator actor (stub — not yet functional).

    Unlike PipelineOrchestrator which follows a fixed stage sequence,
    this actor uses an LLM to dynamically reason about which workers
    to invoke and how to combine their results.

    Expected implementation pattern:
        1. Receive OrchestratorGoal
        2. LLM call: "Given this goal, what subtasks are needed?"
        3. Dispatch subtasks as TaskMessages
        4. Collect TaskResults
        5. LLM call: "Given these results, what's the final answer?"
        6. Publish synthesized result
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
        # TODO: Initialize LLM backend, CheckpointManager, conversation_history here

    async def handle_message(self, data: dict[str, Any]) -> None:
        """Handle an incoming OrchestratorGoal.

        TODO: Implement the full loop:
              1. Parse data as OrchestratorGoal
              2. Call decomposer to generate subtask list
              3. Dispatch each subtask via self.publish("loom.tasks.incoming", ...)
              4. Wait for results on loom.results.{goal_id}
              5. Call synthesizer to combine results
              6. Publish final result
              7. Check if checkpoint is needed (token threshold)
        """
        logger.info("orchestrator.received", data_keys=list(data.keys()))
