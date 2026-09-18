"""JetStreamRejectionLog — production :class:`RejectionLog` over JetStream.

Smaller scope than :class:`JetStreamEventLog`: no CAS, no per-
aggregate ordering. Append is a simple publish; load is a one-shot
pull subscription with the appropriate subject filter.

Subjects: ``heddle.rejections.{aggregate_type}.{aggregate_id}.{command_type}``
Stream:   ``HEDDLE_REJECTIONS_{TYPE_UPPER}``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import nats.errors

from heddle.contrib.events.jetstream.stream_config import (
    rejection_subject,
)
from heddle.contrib.events.rejection_log import Rejection, RejectionLog
from heddle.core.envelope import WireEnvelope, unwrap

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from nats.js import JetStreamContext


def _body(envelope: WireEnvelope) -> Rejection:
    body = unwrap(envelope)
    assert isinstance(body, Rejection)
    return body


class JetStreamRejectionLog(RejectionLog):
    """Production :class:`RejectionLog` backed by NATS JetStream."""

    def __init__(self, js: JetStreamContext) -> None:
        self._js = js

    async def append(self, envelope: WireEnvelope) -> None:
        """Publish a rejection frame. No CAS."""
        body = _body(envelope)
        subject = rejection_subject(
            body.command.aggregate_type,
            body.command.aggregate_id,
            body.command.command_type,
        )
        await self._js.publish(subject, envelope.model_dump_json().encode())

    async def load(
        self, aggregate_type: str, aggregate_id: str | None = None
    ) -> AsyncIterator[WireEnvelope]:
        """Stream rejection frames in append-order, optionally narrowed by ``aggregate_id``."""
        if aggregate_id is None:
            subject = f"heddle.rejections.{aggregate_type}.>"
        else:
            subject = f"heddle.rejections.{aggregate_type}.{aggregate_id}.>"

        sub = await self._js.pull_subscribe(subject=subject, durable=None)
        try:
            while True:
                try:
                    msgs = await sub.fetch(batch=64, timeout=0.25)
                except nats.errors.TimeoutError:
                    return
                if not msgs:
                    return
                for msg in msgs:
                    await msg.ack()
                    yield WireEnvelope.model_validate_json(msg.data)
        finally:
            await sub.unsubscribe()
