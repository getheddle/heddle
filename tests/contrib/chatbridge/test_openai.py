"""Tests for OpenAIChatBridge."""

from unittest.mock import AsyncMock, patch

import httpx

from loom.contrib.chatbridge.openai import OpenAIChatBridge


def _mock_response(content="Sure!", prompt_tokens=40, completion_tokens=15):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "model": "gpt-4o",
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )


class TestOpenAIChatBridge:
    async def test_send_turn_basic(self):
        bridge = OpenAIChatBridge(api_key="test-key")
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response("I think so.")
            resp = await bridge.send_turn("What's your view?", {}, "sess_1")

        assert resp.content == "I think so."
        assert resp.model == "gpt-4o"
        assert resp.token_usage["prompt_tokens"] == 40

    async def test_system_prompt_included(self):
        bridge = OpenAIChatBridge(api_key="test-key", system_prompt="You are a critic.")
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response()
            await bridge.send_turn("Hello", {}, "sess_1")

        body = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
        # First message should be the system prompt.
        assert body["messages"][0]["role"] == "system"
        assert "critic" in body["messages"][0]["content"]

    async def test_messages_accumulate(self):
        bridge = OpenAIChatBridge(api_key="test-key")
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response("R1")
            await bridge.send_turn("M1", {}, "sess_1")
            mock_post.return_value = _mock_response("R2")
            await bridge.send_turn("M2", {}, "sess_1")

        info = await bridge.get_session_info("sess_1")
        assert info.message_count == 4  # 2 user + 2 assistant

    async def test_session_info_empty(self):
        bridge = OpenAIChatBridge(api_key="test-key")
        info = await bridge.get_session_info("nonexistent")
        assert info.message_count == 0
