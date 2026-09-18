"""Idempotent JetStream stream configuration helpers.

Per v7 §4.6 / Sprint 3 brief T8/T9. Each aggregate_type gets three
dedicated streams: events, commands, rejections.

Stream naming
-------------
``HEDDLE_EVENTS_{TYPE_UPPER}``  / subject ``heddle.events.{type}.>``
``HEDDLE_COMMANDS_{TYPE_UPPER}`` / subject ``heddle.commands.{type}.>``
``HEDDLE_REJECTIONS_{TYPE_UPPER}`` / subject ``heddle.rejections.{type}.>``

Stream and subject names come from :mod:`heddle.contrib.events.subjects`
(the single source of truth, shared with the wire-contract publish/
subscribe call sites) rather than being redefined here.

Defaults: file storage, single replica. The **event stream is the
source of truth**: unbounded age, ``discard=new`` (reject new writes
when full rather than silently drop the oldest events — replay needs
those first), and a 10m duplicate window for opportunistic dedup.
Command and rejection streams keep age-based retention (7d / 30d) with
``discard=old``.

Stream creation delegates to the generic
:func:`heddle.bus.jetstream.ensure_stream`, which takes durations in
**seconds** — see that module's docstring for why they must NOT be
pre-multiplied to nanoseconds here (``nats.js.api.StreamConfig``
converts once, in ``as_dict()``; pre-multiplying double-converts).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nats.js.api import DiscardPolicy, StorageType

from heddle.bus.jetstream import ensure_stream
from heddle.contrib.events.subjects import (
    command_stream_name,
    command_subject_filter,
    event_stream_name,
    event_subject_filter,
    rejection_stream_name,
    rejection_subject_filter,
)

if TYPE_CHECKING:
    from nats.js import JetStreamContext


# The event log is never aged out: it is the source of truth for replay
# and time-travel. 0 = unbounded.
DEFAULT_EVENTS_MAX_AGE_SECONDS: int = 0
EVENT_STREAM_DUPLICATE_WINDOW_SECONDS: int = 10 * 60
DEFAULT_COMMANDS_MAX_AGE_SECONDS: int = 7 * 24 * 3600
DEFAULT_REJECTIONS_MAX_AGE_SECONDS: int = 30 * 24 * 3600


async def ensure_event_stream(
    js: JetStreamContext,
    aggregate_type: str,
    max_age_seconds: int = DEFAULT_EVENTS_MAX_AGE_SECONDS,
    storage: StorageType = StorageType.FILE,
    replicas: int = 1,
) -> None:
    """Create or update the ``HEDDLE_EVENTS_{TYPE}`` stream.

    The event stream is the source of truth: unbounded age and
    ``discard=new`` so storage pressure never silently drops the oldest
    events (which replay needs first), plus a 10m duplicate window.
    """
    await ensure_stream(
        js,
        name=event_stream_name(aggregate_type),
        subjects=[event_subject_filter(aggregate_type)],
        max_age_seconds=max_age_seconds,
        storage=storage,
        replicas=replicas,
        discard=DiscardPolicy.NEW,
        duplicate_window_seconds=EVENT_STREAM_DUPLICATE_WINDOW_SECONDS,
    )


async def ensure_command_stream(
    js: JetStreamContext,
    aggregate_type: str,
    max_age_seconds: int = DEFAULT_COMMANDS_MAX_AGE_SECONDS,
    storage: StorageType = StorageType.FILE,
    replicas: int = 1,
) -> None:
    """Create or update the ``HEDDLE_COMMANDS_{TYPE}`` stream."""
    await ensure_stream(
        js,
        name=command_stream_name(aggregate_type),
        subjects=[command_subject_filter(aggregate_type)],
        max_age_seconds=max_age_seconds,
        storage=storage,
        replicas=replicas,
    )


async def ensure_rejection_stream(
    js: JetStreamContext,
    aggregate_type: str,
    max_age_seconds: int = DEFAULT_REJECTIONS_MAX_AGE_SECONDS,
    storage: StorageType = StorageType.FILE,
    replicas: int = 1,
) -> None:
    """Create or update the ``HEDDLE_REJECTIONS_{TYPE}`` stream."""
    await ensure_stream(
        js,
        name=rejection_stream_name(aggregate_type),
        subjects=[rejection_subject_filter(aggregate_type)],
        max_age_seconds=max_age_seconds,
        storage=storage,
        replicas=replicas,
    )
