"""JetStreamRejectionLog — production :class:`RejectionLog` over JetStream.

Smaller scope than :class:`JetStreamEventLog`: no CAS, no per-
aggregate ordering. Append/load delegate to the generic
:func:`heddle.bus.jetstream.publish` / :func:`heddle.bus.jetstream.pull`
primitives — this module owns only subject naming.

Subjects: ``heddle.rejections.{aggregate_type}.{aggregate_id}.{command_type}``
Stream:   ``HEDDLE_REJECTIONS_{TYPE_UPPER}``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from heddle.bus.jetstream import publish as js_publish
from heddle.bus.jetstream import pull as js_pull
from heddle.contrib.events.rejection_log import Rejection, RejectionLog
from heddle.contrib.events.subjects import rejection_subject
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
        await js_publish(
            self._js,
            subject,
            envelope.model_dump_json().encode(),
            msg_id=body.rejection_id,
        )

    async def load(
        self, aggregate_type: str, aggregate_id: str | None = None
    ) -> AsyncIterator[WireEnvelope]:
        """Stream rejection frames in append-order, optionally narrowed by ``aggregate_id``."""
        if aggregate_id is None:
            subject = f"heddle.rejections.{aggregate_type}.>"
        else:
            subject = f"heddle.rejections.{aggregate_type}.{aggregate_id}.>"

        async for msg in js_pull(self._js, subject=subject, durable=None):
            await msg.ack()
            yield WireEnvelope.model_validate_json(msg.data)
