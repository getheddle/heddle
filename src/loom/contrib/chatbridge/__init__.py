"""ChatBridge — external chat/LLM session adapters for Loom.

Wraps external chat APIs (Claude, OpenAI, Ollama, human-in-loop) as
Loom-compatible participants.  Each adapter maintains per-session
conversation history, enabling multi-turn interactions in council
discussions or standalone use.

Requires: ``pip install loom-ai[chatbridge]``
"""

from loom.contrib.chatbridge.base import ChatBridge, ChatResponse, SessionInfo

__all__ = ["ChatBridge", "ChatResponse", "SessionInfo"]
