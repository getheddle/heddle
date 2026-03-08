"""
LLM backend adapters. Uniform interface for local and API models.
Add new backends by subclassing LLMBackend.
"""
from __future__ import annotations

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
    ) -> dict[str, Any]:
        """
        Returns:
            {
                "content": str,          # Raw model output
                "model": str,            # Model identifier
                "prompt_tokens": int,
                "completion_tokens": int,
            }
        """
        ...


class AnthropicBackend(LLMBackend):
    """Claude API via httpx."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=120.0,
        )

    async def complete(self, system_prompt, user_message, max_tokens=2000, temperature=0.0):
        resp = await self.client.post(
            "/v1/messages",
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "content": data["content"][0]["text"],
            "model": data["model"],
            "prompt_tokens": data["usage"]["input_tokens"],
            "completion_tokens": data["usage"]["output_tokens"],
        }


class OllamaBackend(LLMBackend):
    """Local models via Ollama API."""

    def __init__(self, model: str = "llama3.2:3b", base_url: str = "http://ollama:11434"):
        self.model = model
        self.client = httpx.AsyncClient(base_url=base_url, timeout=120.0)

    async def complete(self, system_prompt, user_message, max_tokens=2000, temperature=0.0):
        resp = await self.client.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "content": data["message"]["content"],
            "model": self.model,
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
        }


class OpenAICompatibleBackend(LLMBackend):
    """Any OpenAI-compatible API (vLLM, llama.cpp server, LiteLLM, etc.)."""

    def __init__(self, base_url: str, api_key: str = "not-needed", model: str = "default"):
        self.model = model
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120.0,
        )

    async def complete(self, system_prompt, user_message, max_tokens=2000, temperature=0.0):
        resp = await self.client.post(
            "/v1/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return {
            "content": data["choices"][0]["message"]["content"],
            "model": data.get("model", self.model),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        }
