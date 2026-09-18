"""EventLog ABC and in-memory implementation.

EventLog is the per-aggregate-type append-only event store (v7 §4.6).
``JetStreamEventLog`` (``heddle.contrib.events.jetstream.event_log``)
is the production implementation; :class:`InMemoryEventLog` here is
for tests and the framework→app coherence guard.

``Event`` (``heddle.contrib.events.envelopes``) rides
:class:`heddle.core.envelope.WireEnvelope` as ``events.Event``
(wire-envelope S3a) — this ABC and its implementations traffic in the
frame, preserving ``occurred_at``/``recorded_at`` for the audit-grade
log. Callers that need the body call
:func:`heddle.core.envelope.unwrap`.

Contract:

- ``append(envelope, expected_version)`` — CAS append. ``None`` skips
  the version check (creation path, used by PF observers).
- ``load(aggregate_type, aggregate_id, from_version=0)`` — async
  stream of frames in aggregate_version order, with
  ``aggregate_version > from_version``.
- ``subscribe(aggregate_type)`` — async method returning an
  :class:`AsyncIterator` of newly-appended frames. The underlying
  subscription is registered BEFORE this method returns; callers may
  publish to ``aggregate_type`` immediately after ``await subscribe(...)``
  and be sure those events will be delivered. Iteration is forever
  unless cancelled.
"""

from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from heddle.contrib.events.envelopes import Event
from heddle.contrib.events.errors import ConcurrencyError
from heddle.core.envelope import unwrap

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from heddle.core.envelope import WireEnvelope


class EventLog(ABC):
    """Per-aggregate-type append-only event store."""

    @abstractmethod
    async def append(self, envelope: WireEnvelope, expected_version: int | None) -> None:
        """Append an event frame with optimistic concurrency control.

        ``expected_version`` semantics:

        - ``None`` — no check. Used by PF observers that create an
          aggregate from existing PF state and trust their source.
        - ``N`` — current persisted version MUST be exactly ``N``;
          otherwise :class:`ConcurrencyError`.

        Regardless of ``expected_version``, the body's ``aggregate_version``
        MUST equal current_version + 1. The two checks compose: passing
        ``expected_version=None`` with an out-of-order envelope still
        fails the monotonicity check.
        """

    @abstractmethod
    def load(
        self,
        aggregate_type: str,
        aggregate_id: str,
        from_version: int = 0,
    ) -> AsyncIterator[WireEnvelope]:
        """Stream event frames for an aggregate, ordered by aggregate_version."""

    @abstractmethod
    async def subscribe(self, aggregate_type: str) -> AsyncIterator[WireEnvelope]:
        """Subscribe to live event frames for an aggregate type.

        Returns an async iterator that yields frames as they're
        appended. The underlying subscription is ALREADY REGISTERED
        with the log by the time this method returns; callers do NOT
        need to await the first yield to be sure registration is
        complete. Iteration is forever unless the consumer cancels.
        Cancellation cleans up subscriber state.
        """


class InMemoryEventLog(EventLog):
    """Thread-safe in-memory EventLog for tests.

    Stores event frames in a dict keyed by ``(aggregate_type, aggregate_id)``.
    Subscribe broadcasts via a per-subscriber ``asyncio.Queue``.

    NOT suitable for production — process-local, no persistence.
    ``JetStreamEventLog`` is the real one.
    """

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], list[WireEnvelope]] = {}
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[asyncio.Queue[WireEnvelope]]] = {}

    async def append(self, envelope: WireEnvelope, expected_version: int | None) -> None:
        """Append a frame with the CAS+monotonicity contract from the ABC."""
        body = unwrap(envelope)
        assert isinstance(body, Event)
        key = (body.aggregate_type, body.aggregate_id)
        with self._lock:
            current = self._events.get(key, [])
            current_version = self._version_of(current[-1]) if current else 0
            if expected_version is not None and expected_version != current_version:
                raise ConcurrencyError(
                    f"append for {body.aggregate_type}:"
                    f"{body.aggregate_id} expected_version="
                    f"{expected_version} but current_version="
                    f"{current_version}"
                )
            if body.aggregate_version != current_version + 1:
                raise ConcurrencyError(
                    f"envelope aggregate_version="
                    f"{body.aggregate_version} does not follow "
                    f"current_version={current_version}"
                )
            self._events.setdefault(key, []).append(envelope)
            subs = list(self._subscribers.get(body.aggregate_type, []))

        # Broadcast outside the lock — never await under it.
        for q in subs:
            await q.put(envelope)

    @staticmethod
    def _version_of(envelope: WireEnvelope) -> int:
        body = unwrap(envelope)
        assert isinstance(body, Event)
        return body.aggregate_version

    async def load(
        self,
        aggregate_type: str,
        aggregate_id: str,
        from_version: int = 0,
    ) -> AsyncIterator[WireEnvelope]:
        """Yield stored event frames for ``(aggregate_type, aggregate_id)`` in order."""
        key = (aggregate_type, aggregate_id)
        with self._lock:
            # Snapshot to avoid yielding under the lock.
            events = list(self._events.get(key, []))
        for envelope in events:
            if self._version_of(envelope) > from_version:
                yield envelope

    async def subscribe(self, aggregate_type: str) -> AsyncIterator[WireEnvelope]:
        """Register a subscription then return an iterator over new event frames.

        Registration is synchronous w.r.t. this method's return — the
        caller's queue is in ``self._subscribers[aggregate_type]`` by the
        time ``await subscribe(...)`` resolves, so any subsequent
        ``append()`` is guaranteed delivery.
        """
        q: asyncio.Queue[WireEnvelope] = asyncio.Queue()
        with self._lock:
            self._subscribers.setdefault(aggregate_type, []).append(q)
        return self._iterate_subscription(q, aggregate_type)

    async def _iterate_subscription(
        self,
        q: asyncio.Queue[WireEnvelope],
        aggregate_type: str,
    ) -> AsyncIterator[WireEnvelope]:
        try:
            while True:
                envelope = await q.get()
                yield envelope
        finally:
            with self._lock:
                subs = self._subscribers.get(aggregate_type, [])
                if q in subs:
                    subs.remove(q)
