"""Pick a :class:`ChatBridge` class + kwargs from a model identifier.

Used by examples (debate arena, blind taste test) and any application
that wants zero-config provider routing based on a model name like
``claude-sonnet-4-20250514`` or ``lmstudio/google/gemma-3-4b``.

Routing rules (first prefix match wins, case-insensitive):

    claude*          → :class:`AnthropicChatBridge`
    anthropic/<id>   → :class:`AnthropicChatBridge`
    gpt*             → :class:`OpenAIChatBridge`
    openai/<id>      → :class:`OpenAIChatBridge`
    lmstudio/<id>    → :class:`LMStudioChatBridge`
    <anything else>  → :class:`OllamaChatBridge`

The fallthrough is Ollama because (a) it is the most common local
runtime and (b) Ollama tags follow ``family:tag`` (e.g. ``llama3.2:3b``)
which would otherwise need a long allowlist.  Use ``lmstudio/<id>`` to
explicitly route a local model name to LM Studio instead.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from heddle.contrib.chatbridge.base import ChatBridge


# (lower-cased prefix, dotted bridge path) — first match wins.
_PROVIDER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "heddle.contrib.chatbridge.anthropic.AnthropicChatBridge"),
    ("anthropic/", "heddle.contrib.chatbridge.anthropic.AnthropicChatBridge"),
    ("gpt", "heddle.contrib.chatbridge.openai.OpenAIChatBridge"),
    ("openai/", "heddle.contrib.chatbridge.openai.OpenAIChatBridge"),
    ("lmstudio/", "heddle.contrib.chatbridge.lmstudio.LMStudioChatBridge"),
)

# Bridge for unrecognized names (locally-loaded model tags etc.).
_DEFAULT_BRIDGE = "heddle.contrib.chatbridge.ollama.OllamaChatBridge"


def chatbridge_spec(model_name: str) -> tuple[str, dict[str, Any]]:
    """Pick a bridge class + kwargs for *model_name*.

    Returns ``(dotted_path, kwargs)``.  ``kwargs`` always contains the
    bridge's ``model=`` argument with the provider prefix stripped, so
    e.g. ``"openai/gpt-4o-mini"`` returns
    ``("heddle.contrib.chatbridge.openai.OpenAIChatBridge",
       {"model": "gpt-4o-mini"})``.
    """
    name = model_name.strip()
    lower = name.lower()
    for prefix, dotted in _PROVIDER_PREFIXES:
        if lower.startswith(prefix):
            stripped = name.split("/", 1)[1] if "/" in name else name
            return dotted, {"model": stripped}
    return _DEFAULT_BRIDGE, {"model": name}


def make_chatbridge(model_name: str, **extra_kwargs: Any) -> ChatBridge:
    """Construct and return a :class:`ChatBridge` for *model_name*.

    Convenience wrapper around :func:`chatbridge_spec` that imports the
    class and instantiates it.  Any ``extra_kwargs`` override the
    auto-derived ``model=`` (handy for setting ``base_url``,
    ``api_key``, ``system_prompt``, etc).
    """
    dotted, kwargs = chatbridge_spec(model_name)
    kwargs.update(extra_kwargs)
    module_path, _, class_name = dotted.rpartition(".")
    cls = getattr(importlib.import_module(module_path), class_name)
    return cls(**kwargs)
