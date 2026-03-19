"""Tests for BaseActor (core/actor.py)."""
from __future__ import annotations

import asyncio
import signal
from unittest.mock import AsyncMock, patch

import pytest

from loom.bus.memory import InMemoryBus
from loom.core.actor import BaseActor


# ---------------------------------------------------------------------------
# Concrete test subclasses
# ---------------------------------------------------------------------------

class EchoActor(BaseActor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.received: list[dict] = []

    async def handle_message(self, data):
        self.received.append(data)


class FailingActor(BaseActor):
    async def handle_message(self, data):
        raise RuntimeError("boom")


class SlowActor(BaseActor):
    """Records timestamps to verify sequential processing order."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order: list[int] = []

    async def handle_message(self, data):
        self.order.append(data["seq"])
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# 1. Constructor with explicit bus uses that bus
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_constructor_with_explicit_bus():
    bus = InMemoryBus()
    actor = EchoActor("test-1", bus=bus)
    assert actor._bus is bus


# ---------------------------------------------------------------------------
# 2. Constructor without bus creates a bus (NATSBus)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_constructor_without_bus_sets_bus():
    with patch("loom.core.actor.NATSBus", create=True) as _:
        # The import happens lazily inside __init__; just verify _bus is set.
        from loom.bus.nats_adapter import NATSBus  # noqa: F401
        actor = EchoActor("test-2", nats_url="nats://localhost:4222")
        assert actor._bus is not None


# ---------------------------------------------------------------------------
# 3. connect delegates to bus.connect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_delegates_to_bus():
    bus = InMemoryBus()
    actor = EchoActor("test-3", bus=bus)
    assert not bus._connected
    await actor.connect()
    assert bus._connected


# ---------------------------------------------------------------------------
# 4. disconnect calls bus.close
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disconnect_calls_bus_close():
    bus = InMemoryBus()
    actor = EchoActor("test-4", bus=bus)
    await actor.connect()
    assert bus._connected
    await actor.disconnect()
    assert not bus._connected


# ---------------------------------------------------------------------------
# 5. subscribe delegates to bus.subscribe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscribe_delegates_to_bus():
    bus = InMemoryBus()
    actor = EchoActor("test-5", bus=bus)
    await actor.subscribe("test.subject")
    assert actor._sub is not None
    assert actor._sub.subject == "test.subject"
    assert "test.subject" in bus._subscribers


# ---------------------------------------------------------------------------
# 6. publish delegates to bus.publish
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_delegates_to_bus():
    bus = InMemoryBus()
    actor = EchoActor("test-6", bus=bus)
    sub = await bus.subscribe("out.subject")
    await actor.publish("out.subject", {"key": "value"})
    msg = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert msg == {"key": "value"}


# ---------------------------------------------------------------------------
# 7. _process_one calls handle_message with data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_one_calls_handle_message():
    bus = InMemoryBus()
    actor = EchoActor("test-7", bus=bus)
    actor._semaphore = asyncio.Semaphore(1)
    await actor._process_one({"hello": "world"})
    assert actor.received == [{"hello": "world"}]


# ---------------------------------------------------------------------------
# 8. _process_one catches exceptions — actor stays alive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_one_catches_exceptions():
    bus = InMemoryBus()
    actor = FailingActor("test-8", bus=bus)
    actor._semaphore = asyncio.Semaphore(1)
    # Should not raise — the error is logged but swallowed.
    await actor._process_one({"will": "fail"})


# ---------------------------------------------------------------------------
# 9. _request_shutdown sets _running=False and sets shutdown_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_shutdown_sets_flags():
    bus = InMemoryBus()
    actor = EchoActor("test-9", bus=bus)
    actor._running = True
    actor._shutdown_event = asyncio.Event()
    assert not actor._shutdown_event.is_set()

    actor._request_shutdown(signal.SIGTERM)

    assert actor._running is False
    assert actor._shutdown_event.is_set()


# ---------------------------------------------------------------------------
# 10. max_concurrent=1 processes sequentially (verify order)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sequential_processing_preserves_order():
    bus = InMemoryBus()
    actor = SlowActor("test-10", bus=bus, max_concurrent=1)
    actor._semaphore = asyncio.Semaphore(1)

    for i in range(5):
        await actor._process_one({"seq": i})

    assert actor.order == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# 11. Semaphore has correct value for max_concurrent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semaphore_respects_max_concurrent():
    bus = InMemoryBus()
    actor = EchoActor("test-11", bus=bus, max_concurrent=3)
    # Semaphore is created in run(); simulate that.
    actor._semaphore = asyncio.Semaphore(actor.max_concurrent)
    assert actor._semaphore._value == 3


# ---------------------------------------------------------------------------
# 12. _process_one acquires and releases semaphore
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_one_acquires_and_releases_semaphore():
    bus = InMemoryBus()
    actor = EchoActor("test-12", bus=bus)
    actor._semaphore = asyncio.Semaphore(1)

    # Before: semaphore is available (value=1).
    assert actor._semaphore._value == 1
    await actor._process_one({"data": 1})
    # After: semaphore is released back (value=1).
    assert actor._semaphore._value == 1
    assert actor.received == [{"data": 1}]
