"""
NATS message bus adapter.

Subject naming convention:
  loom.tasks.{worker_type}     - Worker task queues
  loom.results.{goal_id}       - Results routed back to orchestrators
  loom.control.{actor_id}      - Control messages (shutdown, status)
  loom.events                  - System-wide events (logging, metrics)
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

import nats
from nats.aio.client import Client as NATSClient
import structlog

logger = structlog.get_logger()


class NATSBus:
    """Thin wrapper over nats-py for Loom's messaging patterns."""

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
        """Request-reply pattern for synchronous-style calls."""
        resp = await self._nc.request(
            subject,
            json.dumps(data).encode(),
            timeout=timeout,
        )
        return json.loads(resp.data.decode())
