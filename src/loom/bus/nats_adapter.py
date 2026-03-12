"""
NATS message bus adapter — the transport layer for all Loom communication.

All inter-actor communication flows through this adapter. Actors never
touch NATS directly; they use NATSBus (or BaseActor's publish/subscribe
wrappers, which delegate here).

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
from typing import Any, Awaitable, Callable

import nats
from nats.aio.client import Client as NATSClient
import structlog

logger = structlog.get_logger()


class NATSBus:
    """Thin wrapper over nats-py for Loom's messaging patterns.

    Provides three messaging patterns:
    - publish(): Fire-and-forget (tasks, results)
    - subscribe(): Async callback with optional queue groups for load balancing
    - request(): Request-reply for synchronous-style calls (not yet used by any actor)
    """

    def __init__(self, url: str = "nats://nats:4222"):
        self.url = url
        self._nc: NATSClient | None = None

    async def connect(self) -> None:
        self._nc = await nats.connect(
            self.url,
            reconnect_time_wait=2,
            max_reconnect_attempts=30,
        )
        logger.info("bus.connected", url=self.url)

    async def close(self) -> None:
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
        handler: Callable[[dict[str, Any]], Awaitable[None]],
        queue_group: str | None = None,
    ):
        """
        Subscribe with a handler callback.
        Queue group enables competing consumers for horizontal scaling.
        """
        async def _cb(msg):
            data = json.loads(msg.data.decode())
            await handler(data)

        if queue_group:
            return await self._nc.subscribe(subject, queue=queue_group, cb=_cb)
        return await self._nc.subscribe(subject, cb=_cb)

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
