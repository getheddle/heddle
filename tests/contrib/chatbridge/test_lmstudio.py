"""Tests for LMStudioChatBridge."""

from unittest.mock import AsyncMock, patch

import httpx

from heddle.contrib.chatbridge.lmstudio import LMStudioChatBridge


def _mock_response(content="LM Studio says hi", model="qwen2.5-7b"):
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8},
        },
        request=httpx.Request("POST", "http://localhost:1234/v1/chat/completions"),
    )


class TestLMStudioChatBridge:
    def test_default_base_url_strips_v1(self):
        bridge = LMStudioChatBridge()
        # The wrapped OpenAIChatBridge stores base_url on the httpx
        # client; verify the trailing /v1 was stripped.
        assert "1234" in str(bridge._client.base_url)
        assert not str(bridge._client.base_url).rstrip("/").endswith("/v1")

    def test_custom_base_url_with_v1(self):
        bridge = LMStudioChatBridge(base_url="http://gpu:1234/v1")
        assert not str(bridge._client.base_url).rstrip("/").endswith("/v1")

    def test_uses_lm_studio_url_env_fallback(self, monkeypatch):
        monkeypatch.setenv("LM_STUDIO_URL", "http://env-host:1234/v1")
        bridge = LMStudioChatBridge()
        assert "env-host" in str(bridge._client.base_url)

    def test_bridge_type_is_lmstudio(self):
        assert LMStudioChatBridge.bridge_type == "lmstudio"

    async def test_send_turn_basic(self):
        bridge = LMStudioChatBridge()
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response("Hello from LM Studio")
            resp = await bridge.send_turn("Test", {}, "sess_1")

        assert resp.content == "Hello from LM Studio"
        assert resp.token_usage["prompt_tokens"] == 12
        assert resp.token_usage["completion_tokens"] == 8

    async def test_posts_to_v1_chat_completions(self):
        """No URL doubling regression — request lands at /v1/chat/completions."""
        bridge = LMStudioChatBridge(base_url="http://localhost:1234/v1")
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response()
            await bridge.send_turn("Test", {}, "sess_1")

        called_path = mock_post.call_args[0][0]
        assert called_path == "/v1/chat/completions"

    async def test_session_accumulation(self):
        bridge = LMStudioChatBridge()
        with patch.object(bridge._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response()
            await bridge.send_turn("M1", {}, "sess_1")
            await bridge.send_turn("M2", {}, "sess_1")

        info = await bridge.get_session_info("sess_1")
        assert info.message_count == 4
