"""
Abstract message bus interface for Loom actor communication.

All inter-actor communication flows through a MessageBus implementation.
The default implementation is NATSBus (nats_adapter.py), but the abstraction
allows alternative transports for testing (InMemoryBus) or portability.

Subscriptions are iterator-based: subscribe() returns a Subscription that
yields parsed message dicts via ``async for data in subscription:``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Subscription(ABC):
    """An active subscription to a message bus subject.

    Yields parsed message dicts (not raw bytes) when iterated.
    Must be unsubscribed when no longer needed.

    Usage::

        sub = await bus.subscribe("loom.tasks.incoming")
        async for data in sub:
            await handle(data)
        await sub.unsubscribe()
    """

    @abstractmethod
    async def unsubscribe(self) -> None:
        """Stop receiving messages and release resources."""
        ...

    @abstractmethod
    def __aiter__(self) -> Subscription: ...

    @abstractmethod
    async def __anext__(self) -> dict[str, Any]:
        """Yield the next message as a parsed dict."""
        ...


class MessageBus(ABC):
    """Abstract message bus for inter-actor communication.

    Implementations must provide:
    - Publish/subscribe with subject-based routing
    - JSON serialization/deserialization (callers pass dicts, not bytes)
    - Optional queue groups for competing-consumer load balancing

    The bus does NOT guarantee delivery. If no subscriber is listening,
    published messages may be silently dropped (fire-and-forget semantics).
    Implementations that need persistence should layer it on top.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the message transport."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Gracefully disconnect, draining pending publishes."""
        ...

    @abstractmethod
    async def publish(self, subject: str, data: dict[str, Any]) -> None:
        """Publish a message dict to a subject (fire-and-forget)."""
        ...

    @abstractmethod
    async def subscribe(
        self,
        subject: str,
        queue_group: str | None = None,
    ) -> Subscription:
        """Subscribe to a subject, returning an async-iterable Subscription.

        Args:
            subject: The subject to subscribe to.
            queue_group: Optional queue group name. When multiple subscribers
                share a queue group, each message is delivered to exactly one
                member (competing consumers for load balancing).

        Returns:
            A Subscription that yields parsed message dicts.
        """
        ...
