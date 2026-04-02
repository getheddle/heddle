"""Tests for ManualChatBridge."""

import asyncio

import pytest

from loom.contrib.chatbridge.manual import ManualChatBridge


class TestManualCallbackMode:
    async def test_callback_returns_response(self):
        async def responder(message, context, session_id):
            return f"Human says: {message}"

        bridge = ManualChatBridge(on_prompt=responder)
        resp = await bridge.send_turn("What do you think?", {}, "sess_1")
        assert resp.content == "Human says: What do you think?"
        assert resp.model == "human"
        assert resp.stop_reason == "human_input"

    async def test_callback_timeout(self):
        async def slow_responder(message, context, session_id):
            await asyncio.sleep(10)
            return "too late"

        bridge = ManualChatBridge(on_prompt=slow_responder, timeout_seconds=0.1)
        with pytest.raises(asyncio.TimeoutError):
            await bridge.send_turn("Hello?", {}, "sess_1")


class TestManualQueueMode:
    async def test_queue_flow(self):
        prompt_q: asyncio.Queue = asyncio.Queue()
        response_q: asyncio.Queue = asyncio.Queue()

        bridge = ManualChatBridge(
            prompt_queue=prompt_q,
            response_queue=response_q,
            timeout_seconds=5.0,
        )

        # Simulate external responder.
        async def respond():
            prompt = await prompt_q.get()
            assert "session_id" in prompt
            await response_q.put("I agree with the proposal.")

        task = asyncio.create_task(respond())
        resp = await bridge.send_turn("Review this", {"round": 1}, "sess_1")
        await task

        assert resp.content == "I agree with the proposal."

    async def test_queue_timeout(self):
        prompt_q: asyncio.Queue = asyncio.Queue()
        response_q: asyncio.Queue = asyncio.Queue()

        bridge = ManualChatBridge(
            prompt_queue=prompt_q,
            response_queue=response_q,
            timeout_seconds=0.1,
        )

        with pytest.raises(asyncio.TimeoutError):
            await bridge.send_turn("Hello?", {}, "sess_1")


class TestManualSessionInfo:
    async def test_session_info_after_turns(self):
        async def responder(message, context, session_id):
            return "ok"

        bridge = ManualChatBridge(on_prompt=responder)
        await bridge.send_turn("Turn 1", {}, "sess_1")
        await bridge.send_turn("Turn 2", {}, "sess_1")

        info = await bridge.get_session_info("sess_1")
        assert info.bridge_type == "manual"
        assert info.message_count == 4  # 2 system + 2 human


class TestManualValidation:
    async def test_no_handler_raises(self):
        bridge = ManualChatBridge()
        with pytest.raises(ValueError, match="on_prompt"):
            await bridge.send_turn("Hello", {}, "sess_1")
