"""Tests for InMemoryBus edge cases (bus/memory.py)."""

from __future__ import annotations

import asyncio

import pytest

from loom.bus.memory import InMemoryBus, InMemorySubscription

# ---------------------------------------------------------------------------
# InMemorySubscription tests
# ---------------------------------------------------------------------------


class TestInMemorySubscription:
    @pytest.mark.asyncio
    async def test_unsubscribe_stops_iteration(self):
        """Unsubscribing stops further iteration."""
        sub = InMemorySubscription("test.subject")

        # Deliver a message before unsubscribing
        await sub._deliver({"msg": 1})

        # First message is available while active
        msg = await sub.__anext__()
        assert msg == {"msg": 1}

        # Now unsubscribe — next call should stop iteration
        await sub.unsubscribe()
        with pytest.raises(StopAsyncIteration):
            await sub.__anext__()

    @pytest.mark.asyncio
    async def test_inactive_subscription_raises_immediately(self):
        """Calling __anext__ on an already-inactive sub raises StopAsyncIteration."""
        sub = InMemorySubscription("test.subject")
        sub._active = False

        with pytest.raises(StopAsyncIteration):
            await sub.__anext__()

    @pytest.mark.asyncio
    async def test_deliver_to_inactive_is_noop(self):
        """_deliver to an inactive subscription does not enqueue."""
        sub = InMemorySubscription("test.subject")
        sub._active = False

        await sub._deliver({"msg": "ignored"})
        assert sub._queue.empty()

    @pytest.mark.asyncio
    async def test_aiter_returns_self(self):
        sub = InMemorySubscription("test")
        assert sub.__aiter__() is sub


# ---------------------------------------------------------------------------
# InMemoryBus tests
# ---------------------------------------------------------------------------


class TestInMemoryBus:
    @pytest.mark.asyncio
    async def test_publish_to_empty_subject_is_noop(self):
        """Publishing to a subject with no subscribers does nothing."""
        bus = InMemoryBus()
        await bus.connect()
        # Should not raise
        await bus.publish("nonexistent.subject", {"data": "dropped"})

    @pytest.mark.asyncio
    async def test_queue_group_round_robin(self):
        """Messages to a queue group are round-robined across members."""
        bus = InMemoryBus()
        await bus.connect()

        sub1 = await bus.subscribe("work.queue", queue_group="workers")
        sub2 = await bus.subscribe("work.queue", queue_group="workers")
        sub3 = await bus.subscribe("work.queue", queue_group="workers")

        # Publish 6 messages
        for i in range(6):
            await bus.publish("work.queue", {"seq": i})

        # Each subscriber should get exactly 2 messages (round-robin)
        received = {1: [], 2: [], 3: []}
        for sub, key in [(sub1, 1), (sub2, 2), (sub3, 3)]:
            for _ in range(2):
                msg = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
                received[key].append(msg["seq"])

        all_received = sorted(received[1] + received[2] + received[3])
        assert all_received == [0, 1, 2, 3, 4, 5]
        # Each got exactly 2
        assert len(received[1]) == 2
        assert len(received[2]) == 2
        assert len(received[3]) == 2

    @pytest.mark.asyncio
    async def test_close_unsubscribes_all(self):
        """close() unsubscribes all active subscriptions and clears state."""
        bus = InMemoryBus()
        await bus.connect()

        sub1 = await bus.subscribe("subject.a")
        sub2 = await bus.subscribe("subject.b")

        assert bus._connected
        await bus.close()

        assert not bus._connected
        assert len(bus._subscribers) == 0
        assert not sub1._active
        assert not sub2._active

    @pytest.mark.asyncio
    async def test_ungrouped_and_grouped_coexist(self):
        """Ungrouped subscribers get all messages; grouped get round-robin."""
        bus = InMemoryBus()
        await bus.connect()

        # One ungrouped subscriber
        all_sub = await bus.subscribe("mixed.subject")
        # Two grouped subscribers
        g1 = await bus.subscribe("mixed.subject", queue_group="pool")
        g2 = await bus.subscribe("mixed.subject", queue_group="pool")

        await bus.publish("mixed.subject", {"msg": 1})
        await bus.publish("mixed.subject", {"msg": 2})

        # Ungrouped gets both
        m1 = await asyncio.wait_for(all_sub.__anext__(), timeout=1.0)
        m2 = await asyncio.wait_for(all_sub.__anext__(), timeout=1.0)
        assert m1["msg"] == 1
        assert m2["msg"] == 2

        # Grouped: one gets msg 1, other gets msg 2
        gm1 = await asyncio.wait_for(g1.__anext__(), timeout=1.0)
        gm2 = await asyncio.wait_for(g2.__anext__(), timeout=1.0)
        assert {gm1["msg"], gm2["msg"]} == {1, 2}

    @pytest.mark.asyncio
    async def test_inactive_subscriber_skipped_in_publish(self):
        """Already-unsubscribed subscribers are skipped during publish."""
        bus = InMemoryBus()
        await bus.connect()

        sub1 = await bus.subscribe("test.skip")
        sub2 = await bus.subscribe("test.skip")

        # Unsubscribe sub1
        await sub1.unsubscribe()

        # Publish — only sub2 should receive
        await bus.publish("test.skip", {"data": "value"})

        msg = await asyncio.wait_for(sub2.__anext__(), timeout=1.0)
        assert msg == {"data": "value"}

    @pytest.mark.asyncio
    async def test_subscribe_with_queue_group(self):
        """subscribe() with queue_group stores the group correctly."""
        bus = InMemoryBus()
        sub = await bus.subscribe("grouped.subject", queue_group="my-group")

        assert sub.subject == "grouped.subject"
        # Verify group is stored in _subscribers
        entries = bus._subscribers["grouped.subject"]
        assert len(entries) == 1
        assert entries[0][0] == "my-group"
