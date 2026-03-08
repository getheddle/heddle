"""
Base actor class. All Loom actors (workers, orchestrators) inherit from this.
Handles the NATS subscription lifecycle and message dispatch.
"""
from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from typing import Any

import nats
import structlog

logger = structlog.get_logger()


class BaseActor(ABC):
    """
    Actor model base class.

    Each actor:
    - Subscribes to a NATS subject
    - Processes one message at a time (mailbox semantics)
    - Communicates only through structured messages
    - Has isolated state (no shared memory)
    """

    def __init__(self, actor_id: str, nats_url: str = "nats://nats:4222"):
        self.actor_id = actor_id
        self.nats_url = nats_url
        self._nc: nats.NATS | None = None
        self._sub = None
        self._running = False

    async def connect(self) -> None:
        self._nc = await nats.connect(self.nats_url)
        logger.info("actor.connected", actor_id=self.actor_id)

    async def disconnect(self) -> None:
        if self._sub:
            await self._sub.unsubscribe()
        if self._nc:
            await self._nc.drain()
        logger.info("actor.disconnected", actor_id=self.actor_id)

    async def subscribe(self, subject: str, queue_group: str | None = None) -> None:
        """
        Subscribe to a NATS subject. Queue group enables competing consumers
        (multiple worker replicas share load).
        """
        if queue_group:
            self._sub = await self._nc.subscribe(subject, queue=queue_group)
        else:
            self._sub = await self._nc.subscribe(subject)
        logger.info("actor.subscribed", actor_id=self.actor_id, subject=subject)

    async def publish(self, subject: str, message: dict[str, Any]) -> None:
        await self._nc.publish(subject, json.dumps(message).encode())

    async def run(self, subject: str, queue_group: str | None = None) -> None:
        """Main actor loop. Process messages one at a time."""
        await self.connect()
        await self.subscribe(subject, queue_group)
        self._running = True

        logger.info("actor.running", actor_id=self.actor_id, subject=subject)

        try:
            async for msg in self._sub.messages:
                try:
                    data = json.loads(msg.data.decode())
                    start = time.monotonic()
                    await self.handle_message(data)
                    elapsed = int((time.monotonic() - start) * 1000)
                    logger.info("actor.processed", actor_id=self.actor_id, ms=elapsed)
                except Exception as e:
                    logger.error("actor.error", actor_id=self.actor_id, error=str(e))
        except asyncio.CancelledError:
            pass
        finally:
            await self.disconnect()

    @abstractmethod
    async def handle_message(self, data: dict[str, Any]) -> None:
        """Process a single message. Subclasses implement this."""
        ...
