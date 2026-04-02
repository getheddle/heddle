"""Tests for OllamaChatBridge."""

from unittest.mock import AsyncMock, patch

import httpx

from loom.contrib.chatbridge.ollama import OllamaChatBridge


def _mock_response(content="Local model says hi", prompt_eval=30, eval_count=10):
    return httpx.Response(
        200,
        json={
            "message": {"role": "assistant", "content": content},
            "model": "llama3.2:3b",
            "done": True,
            "prompt_eval_count": prompt_eval,
            "eval_count": eval_count,
        },
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )


class TestOllamaChatBridge:
    async def test_send_turn_basic(self):
        bridge = OllamaChatBridge()
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response("Hello from Ollama")
            resp = await bridge.send_turn("Test", {}, "sess_1")

        assert resp.content == "Hello from Ollama"
        assert resp.model == "llama3.2:3b"
        assert resp.token_usage["prompt_tokens"] == 30
        assert resp.token_usage["completion_tokens"] == 10

    async def test_stream_false(self):
        bridge = OllamaChatBridge()
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response()
            await bridge.send_turn("Test", {}, "sess_1")

        body = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
        assert body["stream"] is False

    async def test_session_accumulation(self):
        bridge = OllamaChatBridge()
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response()
            await bridge.send_turn("M1", {}, "sess_1")
            await bridge.send_turn("M2", {}, "sess_1")

        info = await bridge.get_session_info("sess_1")
        assert info.message_count == 4
