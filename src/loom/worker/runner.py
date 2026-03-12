"""
LLM worker actor. Processes a single task via an LLM backend and resets.
No state carries between tasks — this is enforced, not optional.
"""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from loom.worker.backends import LLMBackend
from loom.worker.base import TaskWorker

logger = structlog.get_logger()

# Regex to strip markdown code fences that LLMs commonly wrap JSON in.
# Matches ```json ... ``` or ``` ... ``` with optional whitespace.
_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?\s*```$", re.DOTALL)


def _extract_json(raw: str) -> dict:
    """Extract a JSON object from an LLM response, handling common quirks.

    LLMs frequently wrap valid JSON in markdown code fences (```json ... ```)
    or add explanatory text before/after the JSON object. This function
    handles those cases in order of preference:

    1. Direct parse (ideal — model returned clean JSON)
    2. Strip markdown fences and parse
    3. Extract the first { ... } block via regex (fallback for preamble/postamble)

    Raises ValueError if no valid JSON object can be extracted.
    """
    # 1. Try direct parse
    stripped = raw.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # 2. Try stripping markdown fences
    fence_match = _FENCE_RE.match(stripped)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Fallback: extract the first JSON object from anywhere in the response.
    # This handles cases where the LLM adds prose before/after the JSON.
    obj_match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"LLM returned non-JSON: {raw[:200]}")


class LLMWorker(TaskWorker):
    """
    LLM-backed stateless worker.

    Extends TaskWorker with LLM-specific logic:
    - Builds prompt from system_prompt + JSON payload
    - Calls the appropriate LLM backend by model tier
    - Parses JSON output from the LLM response (with fence-stripping fallback)
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

        # 4. Parse JSON output — handles markdown fences and preamble text
        output = _extract_json(result["content"])

        return {
            "output": output,
            "model_used": result["model"],
            "token_usage": {
                "prompt_tokens": result.get("prompt_tokens", 0),
                "completion_tokens": result.get("completion_tokens", 0),
            },
        }
