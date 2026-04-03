"""Tests for ChatBridgeBackend."""

from unittest.mock import AsyncMock, patch

import pytest

from heddle.contrib.chatbridge.base import ChatResponse
from heddle.contrib.chatbridge.worker import ChatBridgeBackend, ChatBridgeBackendError


class TestChatBridgeBackend:
    def test_missing_bridge_class_raises(self):
        with pytest.raises(ChatBridgeBackendError, match="bridge_class"):
            ChatBridgeBackend()

    def test_invalid_bridge_class_raises(self):
        with pytest.raises(ChatBridgeBackendError, match="Failed to import"):
            ChatBridgeBackend(bridge_class="nonexistent.module.BridgeClass")

    async def test_process_delegates_to_bridge(self):
        mock_response = ChatResponse(
            content="Bridge response",
            model="test-model",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5},
            session_id="default",
        )

        with patch(
            "heddle.contrib.chatbridge.worker.ChatBridgeBackend._create_bridge"
        ) as mock_create:
            mock_bridge = AsyncMock()
            mock_bridge.send_turn.return_value = mock_response
            mock_create.return_value = mock_bridge

            backend = ChatBridgeBackend(
                bridge_class="heddle.contrib.chatbridge.ollama.OllamaChatBridge"
            )

        result = await backend.process(
            {"message": "Hello", "_session_id": "sess_1"},
            {},
        )

        assert result["output"]["content"] == "Bridge response"
        assert result["model_used"] == "test-model"
        mock_bridge.send_turn.assert_called_once()

    async def test_process_without_message_field(self):
        mock_response = ChatResponse(
            content="ok",
            model="m",
            session_id="default",
        )

        with patch(
            "heddle.contrib.chatbridge.worker.ChatBridgeBackend._create_bridge"
        ) as mock_create:
            mock_bridge = AsyncMock()
            mock_bridge.send_turn.return_value = mock_response
            mock_create.return_value = mock_bridge

            backend = ChatBridgeBackend(
                bridge_class="heddle.contrib.chatbridge.ollama.OllamaChatBridge"
            )

        await backend.process(
            {"text": "some content", "topic": "test"},
            {},
        )

        # Should serialize the payload as JSON message.
        call_args = mock_bridge.send_turn.call_args
        message = call_args[0][0]
        assert "some content" in message
        assert "topic" in message

    async def test_process_bridge_error(self):
        with patch(
            "heddle.contrib.chatbridge.worker.ChatBridgeBackend._create_bridge"
        ) as mock_create:
            mock_bridge = AsyncMock()
            mock_bridge.send_turn.side_effect = RuntimeError("API error")
            mock_create.return_value = mock_bridge

            backend = ChatBridgeBackend(
                bridge_class="heddle.contrib.chatbridge.ollama.OllamaChatBridge"
            )

        with pytest.raises(ChatBridgeBackendError, match="API error"):
            await backend.process({"message": "Hello"}, {})
