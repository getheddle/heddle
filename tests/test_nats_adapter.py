"""
Test NATS adapter (unit tests, no infrastructure).

Tests the NATSBus and NATSSubscription classes from loom.bus.nats_adapter.
All NATS interactions are mocked — no running NATS server is needed.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from loom.bus.nats_adapter import NATSBus, NATSSubscription

# ---------------------------------------------------------------------------
# NATSBus — connection lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_calls_nats_connect_with_defaults():
    """connect() passes URL, reconnect settings, and callbacks to nats.connect."""
    bus = NATSBus(url="nats://localhost:4222")
    mock_nc = AsyncMock()

    with patch(
        "loom.bus.nats_adapter.nats.connect", new_callable=AsyncMock, return_value=mock_nc
    ) as mock_connect:
        await bus.connect()

    mock_connect.assert_awaited_once()
    call_kwargs = mock_connect.call_args
    assert call_kwargs[0][0] == "nats://localhost:4222"
    assert call_kwargs[1]["reconnect_time_wait"] == 1
    assert call_kwargs[1]["max_reconnect_attempts"] == 60
    assert callable(call_kwargs[1]["reconnected_cb"])
    assert callable(call_kwargs[1]["disconnected_cb"])
    assert bus._nc is mock_nc


@pytest.mark.asyncio
async def test_close_drains_connection():
    """close() calls nc.drain() on the underlying NATS client."""
    bus = NATSBus()
    bus._nc = AsyncMock()

    await bus.close()

    bus._nc.drain.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_without_connection_is_noop():
    """close() does nothing if connect() was never called."""
    bus = NATSBus()
    # _nc is None by default — should not raise
    await bus.close()


# ---------------------------------------------------------------------------
# NATSBus — publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_serializes_dict_to_json_bytes():
    """publish() JSON-encodes the dict and sends bytes to the subject."""
    bus = NATSBus()
    bus._nc = AsyncMock()
    data = {"task_id": "abc", "payload": 42}

    await bus.publish("loom.tasks.incoming", data)

    expected_bytes = json.dumps(data).encode()
    bus._nc.publish.assert_awaited_once_with("loom.tasks.incoming", expected_bytes)


# ---------------------------------------------------------------------------
# NATSBus — subscribe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_without_queue_group():
    """subscribe() without queue_group calls nc.subscribe(subject) only."""
    bus = NATSBus()
    mock_nats_sub = AsyncMock()
    bus._nc = AsyncMock()
    bus._nc.subscribe = AsyncMock(return_value=mock_nats_sub)

    sub = await bus.subscribe("loom.tasks.incoming")

    bus._nc.subscribe.assert_awaited_once_with("loom.tasks.incoming")
    assert isinstance(sub, NATSSubscription)


@pytest.mark.asyncio
async def test_subscribe_with_queue_group():
    """subscribe() with queue_group passes queue= kwarg to nc.subscribe."""
    bus = NATSBus()
    mock_nats_sub = AsyncMock()
    bus._nc = AsyncMock()
    bus._nc.subscribe = AsyncMock(return_value=mock_nats_sub)

    sub = await bus.subscribe("loom.tasks.summarizer.local", queue_group="workers-summarizer")

    bus._nc.subscribe.assert_awaited_once_with(
        "loom.tasks.summarizer.local",
        queue="workers-summarizer",
    )
    assert isinstance(sub, NATSSubscription)


# ---------------------------------------------------------------------------
# NATSBus — request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_serializes_and_deserializes():
    """request() sends JSON bytes and decodes the response."""
    bus = NATSBus()
    bus._nc = AsyncMock()

    response_data = {"status": "ok", "count": 3}
    mock_resp = MagicMock()
    mock_resp.data = json.dumps(response_data).encode()
    bus._nc.request = AsyncMock(return_value=mock_resp)

    result = await bus.request("loom.health", {"check": True}, timeout=5.0)

    expected_bytes = json.dumps({"check": True}).encode()
    bus._nc.request.assert_awaited_once_with("loom.health", expected_bytes, timeout=5.0)
    assert result == response_data


# ---------------------------------------------------------------------------
# NATSSubscription — iteration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscription_anext_decodes_json():
    """__anext__() decodes msg.data as JSON and returns a dict."""
    payload = {"task_id": "t1", "worker_type": "summarizer"}
    mock_msg = MagicMock()
    mock_msg.data = json.dumps(payload).encode()

    mock_nats_sub = AsyncMock()
    mock_nats_sub.next_msg = AsyncMock(return_value=mock_msg)

    sub = NATSSubscription(mock_nats_sub)
    result = await sub.__anext__()

    mock_nats_sub.next_msg.assert_awaited_once_with(timeout=None)
    assert result == payload


@pytest.mark.asyncio
async def test_subscription_anext_raises_stop_on_exception():
    """__anext__() catches exceptions from next_msg and raises StopAsyncIteration."""
    mock_nats_sub = AsyncMock()
    mock_nats_sub.next_msg = AsyncMock(side_effect=Exception("subscription closed"))

    sub = NATSSubscription(mock_nats_sub)

    with pytest.raises(StopAsyncIteration):
        await sub.__anext__()


# ---------------------------------------------------------------------------
# NATSSubscription — unsubscribe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscription_unsubscribe_delegates():
    """unsubscribe() delegates to the underlying NATS subscription."""
    mock_nats_sub = AsyncMock()
    sub = NATSSubscription(mock_nats_sub)

    await sub.unsubscribe()

    mock_nats_sub.unsubscribe.assert_awaited_once()


# ---------------------------------------------------------------------------
# NATSSubscription — malformed message handling (P1.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscription_skips_malformed_json():
    """Malformed JSON messages are skipped; next valid message is returned."""
    bad_msg = MagicMock()
    bad_msg.data = b"not valid json {{"
    bad_msg.subject = "loom.tasks.incoming"

    good_payload = {"task_id": "t2", "worker_type": "summarizer"}
    good_msg = MagicMock()
    good_msg.data = json.dumps(good_payload).encode()

    mock_nats_sub = AsyncMock()
    mock_nats_sub.next_msg = AsyncMock(side_effect=[bad_msg, good_msg])

    sub = NATSSubscription(mock_nats_sub)
    result = await sub.__anext__()

    # Should have skipped the bad message and returned the good one.
    assert result == good_payload
    assert mock_nats_sub.next_msg.await_count == 2


@pytest.mark.asyncio
async def test_subscription_skips_unicode_decode_error():
    """Messages with invalid encoding are skipped; next valid message is returned."""
    bad_msg = MagicMock()
    # Invalid UTF-8 bytes
    bad_msg.data = b"\x80\x81\x82"
    bad_msg.subject = "loom.tasks.incoming"

    good_payload = {"ok": True}
    good_msg = MagicMock()
    good_msg.data = json.dumps(good_payload).encode()

    mock_nats_sub = AsyncMock()
    mock_nats_sub.next_msg = AsyncMock(side_effect=[bad_msg, good_msg])

    sub = NATSSubscription(mock_nats_sub)
    result = await sub.__anext__()

    assert result == good_payload
    assert mock_nats_sub.next_msg.await_count == 2


@pytest.mark.asyncio
async def test_subscription_multiple_malformed_before_valid():
    """Multiple consecutive malformed messages are all skipped."""
    bad1 = MagicMock()
    bad1.data = b"bad1"
    bad1.subject = "test"

    bad2 = MagicMock()
    bad2.data = b"bad2"
    bad2.subject = "test"

    good_payload = {"result": "ok"}
    good = MagicMock()
    good.data = json.dumps(good_payload).encode()

    mock_nats_sub = AsyncMock()
    mock_nats_sub.next_msg = AsyncMock(side_effect=[bad1, bad2, good])

    sub = NATSSubscription(mock_nats_sub)
    result = await sub.__anext__()

    assert result == good_payload
    assert mock_nats_sub.next_msg.await_count == 3


@pytest.mark.asyncio
async def test_subscription_nats_error_after_malformed_still_stops():
    """If NATS subscription errors after skipping malformed, StopAsyncIteration is raised."""
    bad_msg = MagicMock()
    bad_msg.data = b"not json"
    bad_msg.subject = "test"

    mock_nats_sub = AsyncMock()
    mock_nats_sub.next_msg = AsyncMock(side_effect=[bad_msg, Exception("connection lost")])

    sub = NATSSubscription(mock_nats_sub)

    with pytest.raises(StopAsyncIteration):
        await sub.__anext__()
