"""ChatBridge — external chat/LLM session adapters for Heddle.

Wraps external chat APIs (Claude, OpenAI, Ollama, human-in-loop) as
Heddle-compatible participants.  Each adapter maintains per-session
conversation history, enabling multi-turn interactions in council
discussions or standalone use.

Requires: ``pip install heddle-ai[chatbridge]``
"""

from heddle.contrib.chatbridge.base import ChatBridge, ChatResponse, SessionInfo

__all__ = ["ChatBridge", "ChatResponse", "SessionInfo"]
