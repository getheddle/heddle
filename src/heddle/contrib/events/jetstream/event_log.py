"""JetStreamEventLog — production :class:`EventLog` backed by NATS JetStream.

A thin specialization over the generic primitives in
:mod:`heddle.bus.jetstream`: this module owns subject/stream naming and
the domain error translation; :func:`heddle.bus.jetstream.publish` /
:func:`heddle.bus.jetstream.pull` own the actual dedup/CAS/pull-consumer
mechanics.

Subject convention:
    ``heddle.events.{aggregate_type}.{aggregate_id}.{event_type}``

Streams (one per aggregate_type):
    ``HEDDLE_EVENTS_{TYPE_UPPER}``

CAS append
----------
``expected_version`` (the aggregate version BEFORE this event) is
passed through as ``bus.jetstream.publish``'s
``expected_last_subject_sequence``. A :class:`WrongLastSequenceError`
from that CAS check is translated into :class:`ConcurrencyError`.
``expected_version=None`` skips the CAS check. Used by PF observers
that ingest from an external source-of-truth.

The event body's ``event_id`` (a UUIDv7) is passed as the publish's
``msg_id``, enabling JetStream's server-side ``Nats-Msg-Id`` dedup
within the event stream's duplicate window.

Load
----
A one-shot ordered consumer with subject filter
``heddle.events.{type}.{id}.>`` streams events in stream-order. Only
events whose ``aggregate_version > from_version`` are yielded.

Subscribe
---------
A push subscription with a durable consumer name keyed on the
aggregate_type. Returns an async iterator whose underlying subscription
is already registered when ``subscribe()`` returns, per the Sprint 3
R4 contract. No generic push-subscribe primitive exists in
``bus.jetstream`` (only the pull-consumer path is generic), so this
method talks to the JetStream client directly.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, cast

from heddle.bus.jetstream import WrongLastSequenceError
from heddle.bus.jetstream import publish as js_publish
from heddle.bus.jetstream import pull as js_pull
from heddle.contrib.events.envelopes import Event
from heddle.contrib.events.errors import ConcurrencyError
from heddle.contrib.events.event_log import EventLog
from heddle.contrib.events.subjects import event_subject, event_subject_filter
from heddle.core.envelope import WireEnvelope, unwrap

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from nats.js import JetStreamContext


def _body(envelope: WireEnvelope) -> Event:
    body = unwrap(envelope)
    assert isinstance(body, Event)
    return body


class JetStreamEventLog(EventLog):
    """Production :class:`EventLog` backed by NATS JetStream.

    Construction does NOT verify that the underlying stream exists.
    Operators call :func:`ensure_event_stream` once at startup for each
    aggregate_type used in the deployment.
    """

    def __init__(self, js: JetStreamContext) -> None:
        self._js = js

    async def append(self, envelope: WireEnvelope, expected_version: int | None) -> None:
        """Publish the ``envelope`` frame with optional CAS on ``aggregate_version``."""
        body = _body(envelope)
        subject = event_subject(body.aggregate_type, body.aggregate_id, body.event_type)
        payload = envelope.model_dump_json().encode()
        try:
            await js_publish(
                self._js,
                subject,
                payload,
                msg_id=body.event_id,
                expected_last_subject_sequence=expected_version,
            )
        except WrongLastSequenceError as exc:
            raise ConcurrencyError(
                f"append for {body.aggregate_type}:"
                f"{body.aggregate_id} expected_version="
                f"{expected_version} but JetStream rejected with "
                f"wrong-last-sequence ({exc.description})"
            ) from exc

    async def load(
        self,
        aggregate_type: str,
        aggregate_id: str,
        from_version: int = 0,
    ) -> AsyncIterator[WireEnvelope]:
        """Stream event frames for one aggregate ordered by ``aggregate_version``.

        Delegates the pull-consumer loop to :func:`heddle.bus.jetstream.pull`
        with subject filter ``heddle.events.{type}.{id}.>``.
        """
        async for msg in js_pull(
            self._js,
            subject=f"heddle.events.{aggregate_type}.{aggregate_id}.>",
            durable=None,
        ):
            await msg.ack()  # type: ignore[reportUnknownMemberType]
            data = cast("bytes", msg.data)  # type: ignore[reportUnknownMemberType]
            envelope = WireEnvelope.model_validate_json(data)
            if _body(envelope).aggregate_version > from_version:
                yield envelope

    async def subscribe(self, aggregate_type: str) -> AsyncIterator[WireEnvelope]:
        """Return an async iterator of newly-appended event frames for ``aggregate_type``.

        The underlying push subscription is established BEFORE this
        method returns — callers may publish immediately afterwards
        and be sure of delivery.
        """
        sub = await self._js.subscribe(
            subject=event_subject_filter(aggregate_type),
        )
        return self._iterate_subscription(sub)

    async def _iterate_subscription(self, sub: object) -> AsyncIterator[WireEnvelope]:
        try:
            while True:
                msg = await sub.next_msg(timeout=None)  # type: ignore[attr-defined]
                await msg.ack()  # type: ignore[reportUnknownMemberType]
                data = cast("bytes", msg.data)  # type: ignore[reportUnknownMemberType]
                yield WireEnvelope.model_validate_json(data)
        finally:
            with contextlib.suppress(Exception):
                await sub.unsubscribe()  # type: ignore[attr-defined]
