"""
LLM worker actor. Processes a single task via an LLM backend and resets.
No state carries between tasks — this is enforced, not optional.
"""
from __future__ import annotations

import json
from typing import Any

import structlog

from loom.worker.backends import LLMBackend
from loom.worker.base import TaskWorker

logger = structlog.get_logger()


class LLMWorker(TaskWorker):
    """
    LLM-backed stateless worker.

    Extends TaskWorker with LLM-specific logic:
    - Builds prompt from system_prompt + JSON payload
    - Calls the appropriate LLM backend by model tier
    - Parses JSON output from the LLM response
    """

    def __init__(
        self,
        actor_id: str,
        config_path: str,
        backends: dict[str, LLMBackend],
        nats_url: str = "nats://nats:4222",
    ):
        super().__init__(actor_id, config_path, nats_url)
        self.backends = backends

    async def process(self, payload: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        # 1. Build prompt
        system_prompt = self.config["system_prompt"]
        user_message = json.dumps(payload, indent=2)

        # 2. Resolve backend from task metadata or config default
        tier = metadata.get("model_tier", self.config.get("default_model_tier", "standard"))
        backend = self.backends.get(tier)
        if not backend:
            raise RuntimeError(f"No backend for tier: {tier}")

        # 3. Call LLM
        logger.info("worker.calling_llm", tier=tier)
        result = await backend.complete(
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=self.config.get("max_output_tokens", 2000),
        )

        # 4. Parse JSON output
        try:
            output = json.loads(result["content"])
        except json.JSONDecodeError:
            raise ValueError(f"LLM returned non-JSON: {result['content'][:200]}")

        return {
            "output": output,
            "model_used": result["model"],
            "token_usage": {
                "prompt_tokens": result.get("prompt_tokens", 0),
                "completion_tokens": result.get("completion_tokens", 0),
            },
        }
