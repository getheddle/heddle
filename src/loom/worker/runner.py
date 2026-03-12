"""
LLM worker actor. Processes a single task via an LLM backend and resets.
No state carries between tasks — this is enforced, not optional.

Supports tool-use: when knowledge_silos include tool-type entries, the worker
offers those tools to the LLM and executes a multi-turn loop until the LLM
produces a final text answer.
"""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from loom.worker.backends import LLMBackend
from loom.worker.base import TaskWorker
from loom.worker.tools import MAX_TOOL_ROUNDS, ToolProvider, load_tool_provider

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
    - Loads knowledge silos (folder content → system prompt, tools → function-calling)
    - Calls the appropriate LLM backend by model tier
    - Executes multi-turn tool-use loop when tools are available
    - Parses JSON output from the LLM response (with fence-stripping fallback)
    - Applies silo_updates for writable folder silos
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

        # 1a. Knowledge silo injection — load folder silos into system prompt
        silos = self.config.get("knowledge_silos", [])
        if silos:
            from loom.worker.knowledge import load_knowledge_silos
            silo_text = load_knowledge_silos(silos)
            if silo_text:
                system_prompt = silo_text + "\n\n" + system_prompt

        # 1b. Legacy knowledge injection — prepend loaded knowledge to system prompt
        knowledge_sources = self.config.get("knowledge_sources", [])
        if knowledge_sources:
            from loom.worker.knowledge import load_knowledge_sources
            knowledge_text = load_knowledge_sources(knowledge_sources)
            if knowledge_text:
                system_prompt = knowledge_text + "\n\n" + system_prompt

        # 1c. File-ref resolution — read workspace files and inject content
        workspace_dir = self.config.get("workspace_dir")
        file_ref_fields = self.config.get("resolve_file_refs", [])
        if workspace_dir and file_ref_fields:
            from loom.core.workspace import WorkspaceManager
            ws = WorkspaceManager(workspace_dir)
            for field in file_ref_fields:
                if field in payload:
                    try:
                        content = ws.read_json(payload[field])
                        payload[f"{field}_content"] = content
                    except (ValueError, FileNotFoundError, json.JSONDecodeError) as e:
                        logger.warning(
                            "worker.file_ref_resolution_failed",
                            field=field, error=str(e),
                        )

        user_message = json.dumps(payload, indent=2)

        # 2. Load tool providers from knowledge_silos
        tool_providers = _load_tool_providers(silos)
        tool_defs = [p.get_definition() for p in tool_providers.values()] or None

        # 3. Resolve backend from task metadata or config default
        tier = metadata.get("model_tier", self.config.get("default_model_tier", "standard"))
        backend = self.backends.get(tier)
        if not backend:
            raise RuntimeError(f"No backend for tier: {tier}")

        # 4. Call LLM (with tools if available)
        logger.info("worker.calling_llm", tier=tier, tools=len(tool_providers))
        result = await backend.complete(
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=self.config.get("max_output_tokens", 2000),
            tools=tool_defs,
        )

        # 5. Tool execution loop — multi-turn until LLM gives a final answer
        total_prompt_tokens = result.get("prompt_tokens", 0)
        total_completion_tokens = result.get("completion_tokens", 0)
        messages: list[dict[str, Any]] | None = None
        rounds = 0

        while result.get("tool_calls") and rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            logger.info("worker.tool_round", round=rounds, calls=len(result["tool_calls"]))

            # Build message history on first tool round
            if messages is None:
                messages = [{"role": "user", "content": user_message}]

            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {"role": "assistant", "tool_calls": result["tool_calls"]}
            if result.get("content"):
                assistant_msg["content"] = result["content"]
            messages.append(assistant_msg)

            # Execute each tool call
            for call in result["tool_calls"]:
                tool_name = call["name"]
                provider = tool_providers.get(tool_name)
                if provider is None:
                    tool_result = json.dumps({"error": f"Unknown tool: {tool_name}"})
                    logger.warning("worker.unknown_tool", tool=tool_name)
                else:
                    try:
                        tool_result = await provider.execute(call["arguments"])
                    except Exception as e:
                        tool_result = json.dumps({"error": str(e)})
                        logger.error("worker.tool_execution_failed", tool=tool_name, error=str(e))

                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": tool_result,
                })

            # Call LLM again with updated message history
            result = await backend.complete(
                system_prompt=system_prompt,
                user_message=user_message,
                messages=messages,
                max_tokens=self.config.get("max_output_tokens", 2000),
                tools=tool_defs,
            )
            total_prompt_tokens += result.get("prompt_tokens", 0)
            total_completion_tokens += result.get("completion_tokens", 0)

        if rounds >= MAX_TOOL_ROUNDS:
            logger.warning("worker.max_tool_rounds_reached", rounds=rounds)

        # 6. Parse JSON output — handles markdown fences and preamble text
        if result.get("content") is None:
            raise ValueError("LLM did not produce a text response after tool-use loop")

        output = _extract_json(result["content"])

        # 7. Process silo_updates — apply write-back to writable folder silos
        silo_updates = output.pop("silo_updates", None)
        if silo_updates:
            from loom.worker.knowledge import apply_silo_updates
            apply_silo_updates(silo_updates, silos)

        return {
            "output": output,
            "model_used": result["model"],
            "token_usage": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
            },
        }


def _load_tool_providers(silos: list[dict[str, Any]]) -> dict[str, ToolProvider]:
    """Load tool providers from tool-type knowledge silos.

    Returns a dict mapping tool name → ToolProvider instance.
    """
    providers: dict[str, ToolProvider] = {}
    for silo in silos:
        if silo.get("type") != "tool":
            continue
        class_path = silo.get("provider", "")
        config = silo.get("config", {})
        try:
            provider = load_tool_provider(class_path, config)
            definition = provider.get_definition()
            name = definition["name"]
            providers[name] = provider
            logger.info("worker.tool_loaded", tool=name, provider=class_path)
        except Exception as e:
            logger.error("worker.tool_load_failed", provider=class_path, error=str(e))
    return providers
