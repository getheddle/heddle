"""LM Studio chat bridge — session-aware adapter for LM Studio's local server.

LM Studio's HTTP server speaks the OpenAI Chat Completions schema, so
this bridge is a thin specialization of :class:`OpenAIChatBridge` with
LM Studio-friendly defaults (no API key required, port 1234, accepts
either ``/v1`` or non-``/v1`` base URLs).
"""

from __future__ import annotations

import os

from heddle.contrib.chatbridge.openai import OpenAIChatBridge


class LMStudioChatBridge(OpenAIChatBridge):
    """OpenAI-compatible chat bridge pointed at an LM Studio server.

    LM Studio runs locally (default port 1234) and exposes
    ``/v1/chat/completions`` for any model loaded in its UI.  Use this
    bridge anywhere :class:`OllamaChatBridge` would normally appear —
    e.g., as a council agent — when you want the MLX runtime or any of
    LM Studio's GUI-loaded models.

    Args:
        model: Model identifier as listed by ``GET /v1/models``, or
            ``"default"`` to let LM Studio route to the loaded model.
        base_url: LM Studio server URL.  Both ``http://localhost:1234``
            and ``http://localhost:1234/v1`` are accepted; the trailing
            ``/v1`` is normalized away.  Falls back to ``LM_STUDIO_URL``
            env var, then ``http://localhost:1234``.
        api_key: Sent as a Bearer token (LM Studio ignores it).
        system_prompt: System instructions applied to all sessions.
        max_tokens: Default max tokens per turn.
    """

    bridge_type = "lmstudio"

    def __init__(
        self,
        model: str = "default",
        base_url: str | None = None,
        api_key: str = "not-needed",
        system_prompt: str = "",
        max_tokens: int = 2000,
    ) -> None:
        raw = base_url or os.environ.get("LM_STUDIO_URL") or "http://localhost:1234"
        normalized = raw.rstrip("/")
        if normalized.endswith("/v1"):
            normalized = normalized[: -len("/v1")]
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=normalized,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )
