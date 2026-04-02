"""Tests for AnthropicChatBridge."""

from unittest.mock import AsyncMock, patch

import httpx

from loom.contrib.chatbridge.anthropic import AnthropicChatBridge


def _mock_response(content="Hello!", input_tokens=50, output_tokens=20):
    """Create a mock httpx response matching Anthropic Messages API."""
    return httpx.Response(
        200,
        json={
            "content": [{"type": "text", "text": content}],
            "model": "claude-sonnet-4-20250514",
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
            "stop_reason": "end_turn",
        },
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )


class TestAnthropicChatBridge:
    async def test_send_turn_basic(self):
        bridge = AnthropicChatBridge(api_key="test-key")
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response("I agree.")
            resp = await bridge.send_turn("What do you think?", {}, "sess_1")

        assert resp.content == "I agree."
        assert resp.model == "claude-sonnet-4-20250514"
        assert resp.token_usage["prompt_tokens"] == 50
        assert resp.session_id == "sess_1"

    async def test_messages_accumulate(self):
        bridge = AnthropicChatBridge(api_key="test-key")
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response("First response")
            await bridge.send_turn("First message", {}, "sess_1")

            mock_post.return_value = _mock_response("Second response")
            await bridge.send_turn("Second message", {}, "sess_1")

        # Verify the second call included accumulated messages.
        last_call = mock_post.call_args
        body = last_call.kwargs.get("json") or last_call[1].get("json")
        messages = body["messages"]
        assert len(messages) == 4  # user, assistant, user, assistant counted before call

    async def test_session_info(self):
        bridge = AnthropicChatBridge(api_key="test-key")
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response()
            await bridge.send_turn("Hello", {}, "sess_1")

        info = await bridge.get_session_info("sess_1")
        assert info.session_id == "sess_1"
        assert info.bridge_type == "anthropic"
        assert info.message_count == 2  # user + assistant

    async def test_close_session(self):
        bridge = AnthropicChatBridge(api_key="test-key")
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response()
            await bridge.send_turn("Hello", {}, "sess_1")

        await bridge.close_session("sess_1")
        info = await bridge.get_session_info("sess_1")
        assert info.message_count == 0

    async def test_separate_sessions(self):
        bridge = AnthropicChatBridge(api_key="test-key")
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response()
            await bridge.send_turn("Hello A", {}, "sess_a")
            await bridge.send_turn("Hello B", {}, "sess_b")

        info_a = await bridge.get_session_info("sess_a")
        info_b = await bridge.get_session_info("sess_b")
        assert info_a.message_count == 2  # user + assistant
        assert info_b.message_count == 2
