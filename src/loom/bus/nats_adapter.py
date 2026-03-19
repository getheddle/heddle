"""
NATS message bus adapter — the default transport layer for Loom communication.

All inter-actor communication flows through this adapter. Actors never
touch NATS directly; they use the MessageBus interface (or BaseActor's
publish/subscribe wrappers, which delegate here).

Subject naming convention:
    loom.tasks.incoming          — Router's inbox (all task dispatch goes here first)
    loom.tasks.{worker_type}.{tier} — Worker queues (router publishes here)
    loom.results.{goal_id}       — Results routed back to orchestrators
    loom.results.default         — Results with no parent_task_id
    loom.goals.incoming          — Pipeline orchestrator's inbox
    loom.control.{actor_id}      — Control messages (shutdown, status) [not yet used]
    loom.events                  — System-wide events (logging, metrics) [not yet used]

Connection defaults:
    reconnect_time_wait=2s, max_reconnect_attempts=30 — totals ~60s of retry.
    If NATS is down longer than that, the actor will crash and needs restart.

NOTE: All messages are JSON-serialized dicts. Binary payloads are not supported.
      Large data should be passed via file references (workspace directory), not
      inline in messages.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import nats
import structlog

from loom.bus.base import MessageBus, Subscription

if TYPE_CHECKING:
    from nats.aio.client import Client as NATSClient

logger = structlog.get_logger()


class NATSSubscription(Subscription):
    """Wraps a nats-py subscription as an async iterator of parsed dicts."""

    def __init__(self, nats_sub: Any) -> None:
        self._sub = nats_sub

    async def unsubscribe(self) -> None:
        """Unsubscribe from the underlying NATS subscription."""
        await self._sub.unsubscribe()

    def __aiter__(self) -> NATSSubscription:
        return self

    async def __anext__(self) -> dict[str, Any]:
        """Yield the next message, JSON-decoded.

        Blocks until a message arrives. Raises StopAsyncIteration when the
        underlying NATS subscription is drained or closed.
        """
        try:
            msg = await self._sub.next_msg(timeout=None)
        except Exception as e:
            logger.error("nats.subscription_error", error=str(e), error_type=type(e).__name__)
            raise StopAsyncIteration from e
        return json.loads(msg.data.decode())


class NATSBus(MessageBus):
    """NATS-backed MessageBus implementation.

    Provides three messaging patterns:
    - publish(): Fire-and-forget (tasks, results)
    - subscribe(): Async iterator with optional queue groups for load balancing
    - request(): Request-reply for synchronous-style calls (not yet used by any actor)
    """

    def __init__(self, url: str = "nats://nats:4222") -> None:
        self.url = url
        self._nc: NATSClient | None = None

    async def connect(self) -> None:
        """Connect to the NATS server."""
        self._nc = await nats.connect(
            self.url,
            reconnect_time_wait=2,
            max_reconnect_attempts=30,
        )
        logger.info("bus.connected", url=self.url)

    async def close(self) -> None:
        """Drain and close the NATS connection."""
        if self._nc:
            await self._nc.drain()

    async def publish(self, subject: str, data: dict[str, Any]) -> None:
        """Publish a JSON-serialized dict to a NATS subject.

        NOTE: No delivery guarantee — if no subscriber is listening,
        the message is silently dropped. NATS JetStream would add
        persistence but is not yet configured.
        """
        await self._nc.publish(subject, json.dumps(data).encode())

    async def subscribe(
        self,
        subject: str,
        queue_group: str | None = None,
    ) -> NATSSubscription:
        """Subscribe to a subject, returning an async-iterable NATSSubscription.

        Queue group enables competing consumers for horizontal scaling.
        """
        if queue_group:
            nats_sub = await self._nc.subscribe(subject, queue=queue_group)
        else:
            nats_sub = await self._nc.subscribe(subject)
        return NATSSubscription(nats_sub)

    async def request(self, subject: str, data: dict[str, Any], timeout: float = 30.0) -> dict:
        """Request-reply pattern for synchronous-style calls.

        NOTE: Not currently used by any Loom actor. Available for future
        use cases like health checks or synchronous worker queries.
        Raises nats.errors.TimeoutError if no reply within timeout.
        """
        resp = await self._nc.request(
            subject,
            json.dumps(data).encode(),
            timeout=timeout,
        )
        return json.loads(resp.data.decode())
