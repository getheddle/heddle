"""
LLM backend adapters — uniform interface for local and API models.

Each backend wraps a specific LLM provider's API and normalizes the response
into a consistent dict format. Workers never call APIs directly; they always
go through a backend.

To add a new backend:
    1. Subclass LLMBackend
    2. Implement complete() returning the standard response dict
    3. Register it in cli/main.py's worker command (backend resolution by tier)

All backends use httpx with a 120s timeout. Adjust if your models are slow.

Tool-use support:
    Backends accept optional ``tools`` and ``messages`` parameters. When
    ``tools`` is provided, the LLM may return tool_calls instead of content.
    When ``messages`` is provided, it replaces the single user_message for
    multi-turn conversations (tool execution loop).
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any

import httpx


class LLMBackend(ABC):
    """Common interface all model backends implement."""

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2000,
        temperature: float = 0.0,
        *,
        tools: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Complete an LLM request and return a normalized response dict.

        Args:
            system_prompt: System instructions for the LLM.
            user_message: User message (ignored when ``messages`` is provided).
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature.
            tools: Optional list of tool definitions for function-calling.
            messages: Optional full message history for multi-turn. When
                provided, overrides ``user_message``.

        Returns:
            A dict with the following structure::

                {
                    "content": str | None,      # Text response (None if tool_calls)
                    "model": str,               # Model identifier
                    "prompt_tokens": int,
                    "completion_tokens": int,
                    "tool_calls": list | None,  # [{"id": str, "name": str, "arguments": dict}]
                    "stop_reason": str | None,  # "end_turn" | "tool_use"
                }
        """
        ...


class AnthropicBackend(LLMBackend):
    """Claude API via httpx (Messages API).

    Uses the Anthropic Messages API directly via httpx rather than the
    anthropic Python SDK — this keeps dependencies minimal and avoids
    version coupling.
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            headers={
                "x-api-key": api_key,
                # Anthropic API version — pinned for reproducibility.
                # See: https://docs.anthropic.com/en/api/versioning
                "anthropic-version": "2024-10-22",
                "content-type": "application/json",
            },
            timeout=120.0,
        )

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2000,
        temperature: float = 0.0,
        *,
        tools: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Complete an LLM request via the Anthropic Messages API."""
        # Build messages array
        if messages is not None:
            api_messages = _anthropic_messages(messages)
        else:
            api_messages = [{"role": "user", "content": user_message}]

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": api_messages,
        }

        # Add tool definitions if provided
        if tools:
            body["tools"] = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {"type": "object"}),
                }
                for t in tools
            ]

        resp = await self.client.post("/v1/messages", json=body)
        resp.raise_for_status()
        data = resp.json()

        # Parse response — may contain text blocks, tool_use blocks, or both
        content = None
        tool_calls = None

        for block in data.get("content", []):
            if block["type"] == "text":
                content = block["text"]
            elif block["type"] == "tool_use":
                if tool_calls is None:
                    tool_calls = []
                tool_calls.append(
                    {
                        "id": block["id"],
                        "name": block["name"],
                        "arguments": block["input"],
                    }
                )

        return {
            "content": content,
            "model": data["model"],
            "prompt_tokens": data["usage"]["input_tokens"],
            "completion_tokens": data["usage"]["output_tokens"],
            "tool_calls": tool_calls,
            "stop_reason": data.get("stop_reason"),
            # OTel GenAI semantic convention metadata
            "gen_ai_system": "anthropic",
            "gen_ai_request_model": self.model,
            "gen_ai_response_model": data["model"],
            "gen_ai_request_temperature": temperature,
            "gen_ai_request_max_tokens": max_tokens,
        }


class OllamaBackend(LLMBackend):
    """Local models via Ollama HTTP API.

    Default base_url points to K8s service name "ollama". For local dev,
    override with http://localhost:11434 (set OLLAMA_URL env var).

    Note: Ollama's token counts (prompt_eval_count, eval_count) may be
    absent for some models; we default to 0 in that case.
    """

    def __init__(self, model: str = "llama3.2:3b", base_url: str = "http://ollama:11434") -> None:
        self.model = model
        self.client = httpx.AsyncClient(base_url=base_url, timeout=120.0)

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2000,
        temperature: float = 0.0,
        *,
        tools: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Complete an LLM request via the Ollama HTTP API."""
        # Build messages array
        if messages is not None:
            api_messages = [
                {"role": "system", "content": system_prompt},
                *_ollama_messages(messages),
            ]
        else:
            api_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

        body: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

        # Add tool definitions if provided (OpenAI-compatible format)
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object"}),
                    },
                }
                for t in tools
            ]

        resp = await self.client.post("/api/chat", json=body)
        resp.raise_for_status()
        data = resp.json()

        # Parse tool calls from Ollama response
        message = data.get("message", {})
        content = message.get("content") or None
        tool_calls = None

        raw_calls = message.get("tool_calls")
        if raw_calls:
            tool_calls = []
            for i, call in enumerate(raw_calls):
                func = call.get("function", {})
                tool_calls.append(
                    {
                        "id": f"call_{i}",
                        "name": func.get("name", ""),
                        "arguments": func.get("arguments", {}),
                    }
                )

        stop_reason = "tool_use" if tool_calls else "end_turn"

        return {
            "content": content,
            "model": self.model,
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
            "tool_calls": tool_calls,
            "stop_reason": stop_reason,
            # OTel GenAI semantic convention metadata
            "gen_ai_system": "ollama",
            "gen_ai_request_model": self.model,
            "gen_ai_response_model": self.model,
            "gen_ai_request_temperature": temperature,
            "gen_ai_request_max_tokens": max_tokens,
        }


class OpenAICompatibleBackend(LLMBackend):
    """Any OpenAI-compatible API (vLLM, llama.cpp server, LiteLLM, etc.)."""

    def __init__(self, base_url: str, api_key: str = "not-needed", model: str = "default") -> None:
        self.model = model
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120.0,
        )

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2000,
        temperature: float = 0.0,
        *,
        tools: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Complete an LLM request via an OpenAI-compatible API."""
        # Build messages array
        if messages is not None:
            api_messages = [
                {"role": "system", "content": system_prompt},
                *_openai_messages(messages),
            ]
        else:
            api_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

        body: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Add tool definitions if provided
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object"}),
                    },
                }
                for t in tools
            ]

        resp = await self.client.post("/v1/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})

        # Parse response
        choice = data["choices"][0]
        message = choice.get("message", {})
        content = message.get("content")
        tool_calls = None

        raw_calls = message.get("tool_calls")
        if raw_calls:
            tool_calls = []
            for call in raw_calls:
                func = call.get("function", {})
                args = func.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"_raw": args}
                tool_calls.append(
                    {
                        "id": call.get("id", ""),
                        "name": func.get("name", ""),
                        "arguments": args,
                    }
                )

        finish_reason = choice.get("finish_reason", "stop")
        stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"

        return {
            "content": content,
            "model": data.get("model", self.model),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "tool_calls": tool_calls,
            "stop_reason": stop_reason,
            # OTel GenAI semantic convention metadata
            "gen_ai_system": "openai",
            "gen_ai_request_model": self.model,
            "gen_ai_response_model": data.get("model", self.model),
            "gen_ai_request_temperature": temperature,
            "gen_ai_request_max_tokens": max_tokens,
        }


# ---------------------------------------------------------------------------
# Message format helpers
# ---------------------------------------------------------------------------


def _anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert internal message format to Anthropic Messages API format."""
    result = []
    for msg in messages:
        role = msg["role"]

        if role == "user":
            result.append({"role": "user", "content": msg["content"]})

        elif role == "assistant":
            # May contain text and/or tool_calls
            content_blocks = []
            if msg.get("content"):
                content_blocks.append({"type": "text", "text": msg["content"]})
            content_blocks.extend(
                {
                    "type": "tool_use",
                    "id": call["id"],
                    "name": call["name"],
                    "input": call["arguments"],
                }
                for call in msg.get("tool_calls", [])
            )
            result.append({"role": "assistant", "content": content_blocks})

        elif role == "tool":
            result.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg["tool_call_id"],
                            "content": msg["content"],
                        }
                    ],
                }
            )

    return result


def _ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert internal message format to Ollama /api/chat format."""
    result = []
    for msg in messages:
        role = msg["role"]

        if role == "user":
            result.append({"role": "user", "content": msg["content"]})

        elif role == "assistant":
            entry: dict[str, Any] = {"role": "assistant"}
            if msg.get("content"):
                entry["content"] = msg["content"]
            if msg.get("tool_calls"):
                entry["tool_calls"] = [
                    {
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments"],
                        },
                    }
                    for call in msg["tool_calls"]
                ]
            result.append(entry)

        elif role == "tool":
            result.append(
                {
                    "role": "tool",
                    "content": msg["content"],
                }
            )

    return result


def _openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert internal message format to OpenAI /v1/chat/completions format."""
    result = []
    for msg in messages:
        role = msg["role"]

        if role == "user":
            result.append({"role": "user", "content": msg["content"]})

        elif role == "assistant":
            entry: dict[str, Any] = {"role": "assistant"}
            if msg.get("content"):
                entry["content"] = msg["content"]
            if msg.get("tool_calls"):
                entry["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"]),
                        },
                    }
                    for call in msg["tool_calls"]
                ]
            result.append(entry)

        elif role == "tool":
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": msg["tool_call_id"],
                    "content": msg["content"],
                }
            )

    return result


def build_backends_from_env() -> dict[str, LLMBackend]:
    """Build LLM backends from environment variables and ``~/.loom/config.yaml``.

    Resolution priority: env vars > config.yaml > built-in defaults.

    Resolves available backends based on which env vars are set:

    - ``OLLAMA_URL`` → OllamaBackend for the ``local`` tier
    - ``OLLAMA_MODEL`` → Override Ollama model (default: ``llama3.2:3b``)
    - ``ANTHROPIC_API_KEY`` → AnthropicBackend for ``standard`` + ``frontier``
    - ``FRONTIER_MODEL`` → Override frontier model (default: ``claude-opus-4-20250514``)

    Returns:
        Dict mapping tier name → LLMBackend instance. May be empty if no
        environment variables are set.
    """
    # Load config.yaml defaults (best-effort; env vars still override)
    try:
        from loom.cli.config import apply_config_to_env, load_config

        config = load_config()
        apply_config_to_env(config)
    except Exception:
        pass

    backends: dict[str, LLMBackend] = {}

    if os.getenv("OLLAMA_URL"):
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        backends["local"] = OllamaBackend(model=ollama_model, base_url=os.getenv("OLLAMA_URL"))

    if os.getenv("ANTHROPIC_API_KEY"):
        backends["standard"] = AnthropicBackend(api_key=os.getenv("ANTHROPIC_API_KEY"))
        backends["frontier"] = AnthropicBackend(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model=os.getenv("FRONTIER_MODEL", "claude-opus-4-20250514"),
        )

    return backends
