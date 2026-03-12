"""
Base actor class — the foundation of Loom's actor model.

All Loom actors (workers, orchestrators, routers) inherit from BaseActor.
This class handles the NATS subscription lifecycle, message dispatch,
signal-based shutdown, and error isolation. Each actor is an independent
process with no shared memory.

Design invariant: actors communicate ONLY through NATS messages (see messages.py).
Direct method calls between actors are forbidden.
"""
from __future__ import annotations

import asyncio
import json
import signal
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
    - Processes messages with configurable concurrency (default: 1 = strict ordering)
    - Communicates only through structured messages
    - Has isolated state (no shared memory)
    - Shuts down gracefully on SIGTERM/SIGINT

    Concurrency can be configured via max_concurrent. Values > 1 allow parallel
    message processing within a single actor instance — use with care, as it
    relaxes ordering guarantees. Horizontal scaling via queue groups (multiple
    replicas) is the preferred way to increase throughput while preserving
    per-message isolation.
    """

    def __init__(
        self,
        actor_id: str,
        nats_url: str = "nats://nats:4222",
        max_concurrent: int = 1,
    ):
        self.actor_id = actor_id
        self.nats_url = nats_url  # Default points to K8s service name; override for local dev
        self.max_concurrent = max_concurrent
        self._nc: nats.NATS | None = None
        self._sub = None
        self._running = False
        self._shutdown_event: asyncio.Event | None = None
        # Semaphore is created at run() time inside the event loop
        self._semaphore: asyncio.Semaphore | None = None

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

    def _install_signal_handlers(self) -> None:
        """Register SIGTERM/SIGINT handlers for graceful shutdown.

        When a signal is received, the actor finishes processing any in-flight
        messages before disconnecting from NATS. This prevents message loss
        during container restarts or manual stops.
        """
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._request_shutdown, sig)

    def _request_shutdown(self, sig: signal.Signals) -> None:
        """Signal callback — sets the shutdown event to break the message loop."""
        logger.info("actor.shutdown_requested", actor_id=self.actor_id, signal=sig.name)
        self._running = False
        if self._shutdown_event:
            self._shutdown_event.set()

    async def _process_one(self, msg) -> None:
        """Process a single NATS message with semaphore-bounded concurrency."""
        async with self._semaphore:
            try:
                data = json.loads(msg.data.decode())
                start = time.monotonic()
                await self.handle_message(data)
                elapsed = int((time.monotonic() - start) * 1000)
                logger.info("actor.processed", actor_id=self.actor_id, ms=elapsed)
            except Exception as e:
                # Individual message failures don't kill the actor loop.
                # The actor stays alive to process subsequent messages.
                logger.error("actor.error", actor_id=self.actor_id, error=str(e))

    async def run(self, subject: str, queue_group: str | None = None) -> None:
        """Main actor loop — subscribe, process messages, and handle shutdown.

        This method blocks until a shutdown signal (SIGTERM/SIGINT) is received
        or the NATS connection drops. Messages are processed with bounded
        concurrency controlled by max_concurrent (default 1 = strict ordering).

        Graceful shutdown sequence:
        1. Signal received -> _request_shutdown() sets the shutdown event
        2. Message loop breaks after finishing in-flight messages
        3. Actor disconnects from NATS (drains pending publishes)
        """
        self._shutdown_event = asyncio.Event()
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

        await self.connect()
        await self.subscribe(subject, queue_group)
        self._running = True
        self._install_signal_handlers()

        logger.info(
            "actor.running",
            actor_id=self.actor_id,
            subject=subject,
            max_concurrent=self.max_concurrent,
        )

        try:
            async for msg in self._sub.messages:
                if not self._running:
                    break
                if self.max_concurrent == 1:
                    # Sequential processing — strict mailbox semantics
                    await self._process_one(msg)
                else:
                    # Concurrent processing — fire-and-forget within semaphore bound
                    asyncio.create_task(self._process_one(msg))
        except asyncio.CancelledError:
            pass  # Clean shutdown via task cancellation
        finally:
            self._running = False
            await self.disconnect()

    @abstractmethod
    async def handle_message(self, data: dict[str, Any]) -> None:
        """Process a single message. Subclasses implement this."""
        ...
