"""Tests for ChatBridge base models and ABC."""

from loom.contrib.chatbridge.base import ChatResponse, SessionInfo


class TestChatResponse:
    def test_minimal(self):
        r = ChatResponse(content="Hello!")
        assert r.content == "Hello!"
        assert r.model is None
        assert r.token_usage == {}

    def test_full(self):
        r = ChatResponse(
            content="Response",
            model="gpt-4o",
            token_usage={"prompt_tokens": 50, "completion_tokens": 20},
            stop_reason="stop",
            session_id="sess_1",
        )
        assert r.model == "gpt-4o"
        assert r.session_id == "sess_1"

    def test_serialization_roundtrip(self):
        r = ChatResponse(content="test", model="m")
        data = r.model_dump(mode="json")
        restored = ChatResponse(**data)
        assert restored.content == r.content


class TestSessionInfo:
    def test_minimal(self):
        s = SessionInfo(session_id="s1", bridge_type="test")
        assert s.message_count == 0

    def test_full(self):
        s = SessionInfo(
            session_id="s1",
            bridge_type="anthropic",
            model="claude-sonnet-4-20250514",
            message_count=10,
        )
        assert s.model == "claude-sonnet-4-20250514"
