"""ChatBridge — external chat/LLM session adapters for Heddle.

Wraps external chat APIs (Claude, OpenAI, Ollama, LM Studio,
human-in-loop) as Heddle-compatible participants.  Each adapter
maintains per-session conversation history, enabling multi-turn
interactions in council discussions or standalone use.

Requires: ``pip install heddle-ai[chatbridge]``
"""

from heddle.contrib.chatbridge.base import ChatBridge, ChatResponse, SessionInfo
from heddle.contrib.chatbridge.discover import chatbridge_spec, make_chatbridge

__all__ = [
    "ChatBridge",
    "ChatResponse",
    "SessionInfo",
    "chatbridge_spec",
    "make_chatbridge",
]
