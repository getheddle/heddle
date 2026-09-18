"""Event-sourcing wire bodies for ``heddle.contrib.events``.

Canonical wire format for the event-sourcing layer
(see ``heddle-contrib-events-m2-architecture-v7.md`` §4.1). Ride
:class:`heddle.core.envelope.WireEnvelope` as ``events.Event`` /
``events.Command`` bodies (wire-envelope S3a) — the frame carries
``occurred_at``/``recorded_at``; these bodies carry no timestamps of
their own.

Distinct from :mod:`heddle.core.messages`:

- ``TaskMessage`` / ``TaskResult`` (in ``heddle.core.messages``) carry
  router-dispatched WORKER tasks and results.
- ``Event`` / ``Command`` (here) carry AGGREGATE state-change events
  and the commands that produce them — targeted by natural identity +
  CAS rather than worker class.

Issuer convention: every event and command carries
``metadata.issued_by`` with a reserved prefix. See
:mod:`heddle.contrib.events.issuer_conventions`.

See Also:
    heddle.core.envelope — WireEnvelope base, wrap()/unwrap(), the payload-type registry
    heddle.contrib.events.subjects — NATS subject helpers for these envelopes
    heddle.contrib.events.issuer_conventions — reserved ``issued_by`` prefixes
    heddle.core.messages — router-dispatched worker message envelopes
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from heddle.core.envelope import register_payload_type


def _uuid7() -> str:
    # Lazy import so bare ``pip install heddle`` (without the [events]
    # extra) still imports this module. Only callers that actually
    # construct an envelope without supplying an id pay the dependency
    # cost.
    import uuid_utils

    return str(uuid_utils.uuid7())


class EventMetadata(BaseModel):
    """Provenance and correlation for an event.

    `issued_by` is a semi-structured identifier with one of six reserved
    prefixes — see ``heddle.contrib.events.issuer_conventions``. Framework
    enforces the prefix at ``apply()`` for sensitive event types (e.g.
    ``InternalFinalized`` requires ``framework:*``).
    """

    command_id: str | None = None
    correlation_id: str | None = None
    issued_by: str = Field(
        ...,
        description=(
            "Semi-structured issuer identifier. Reserved prefixes: framework:, "
            "observer:{name}, projector:{name}, user:badge:{id}, "
            "user:system:{component}, bridge:{worker_type}. See "
            "heddle.contrib.events.issuer_conventions."
        ),
    )
    extra: dict[str, Any] = Field(default_factory=dict)


class Event(BaseModel):
    """Canonical event body for heddle.contrib.events. Rides ``WireEnvelope``.

    Persisted in JetStream ``HEDDLE_EVENTS_{TYPE}`` streams. Replayed by
    aggregates to reconstruct state. See architecture v7 §4.1.

    Ordering authority:
      - ``aggregate_version``: authoritative for in-aggregate ordering;
        CAS field on ``EventLog.append()``.
      - the enclosing envelope's ``recorded_at``: authoritative for
        cross-aggregate log ordering.
      - the enclosing envelope's ``occurred_at``: for domain queries
        only — never for ordering computation.
    """

    event_id: str = Field(
        default_factory=_uuid7,
        description="UUIDv7. Used as JetStream Nats-Msg-Id for opportunistic dedup.",
    )
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int = Field(..., ge=1)
    event_type: str = Field(
        ...,
        description=(
            "CamelCase event type, e.g. 'JobClockedIn'. "
            "(aggregate_type, event_type) is global identity."
        ),
    )
    event_version: int = 1
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: EventMetadata
    # No occurred_at/recorded_at: the WireEnvelope carries both.


register_payload_type("events.Event", Event)


class CommandMetadata(BaseModel):
    """Provenance and correlation for a command.

    Same ``issued_by`` reserved-prefix conventions as :class:`EventMetadata`.
    The ``issued_by_legacy`` slot is reserved for future use and is NOT part
    of the Sprint 1 surface — included in the schema so adding it later
    doesn't break wire-compat.
    """

    correlation_id: str | None = None
    issued_by: str = Field(
        ...,
        description="Same reserved prefix conventions as EventMetadata.issued_by.",
    )
    issued_by_legacy: str | None = None  # reserved; not used in M2
    extra: dict[str, Any] = Field(default_factory=dict)


class Command(BaseModel):
    """Canonical command body for heddle.contrib.events. Not itself durably logged.

    Published to JetStream ``HEDDLE_COMMANDS_{TYPE}`` streams. Consumed by
    ``CommandHandler`` (Sprint 2/3). Distinct from :class:`TaskMessage`:
    ``Command`` targets an aggregate by natural identity and CAS;
    ``TaskMessage`` targets a worker class via router rules.

    ``expected_aggregate_version`` is the optimistic concurrency token.
    ``None`` means "no version check" (typical for create-from-PF observers
    that have no prior state).
    """

    command_id: str = Field(
        default_factory=_uuid7,
        description="UUIDv7. Used as JetStream Nats-Msg-Id.",
    )
    aggregate_type: str
    aggregate_id: str
    command_type: str = Field(
        ...,
        description="CamelCase command type, e.g. 'JobClockIn'.",
    )
    command_version: int = 1
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: CommandMetadata
    expected_aggregate_version: int | None = None
    # No issued_at: when a command rides the WireEnvelope, the frame
    # carries occurred_at/recorded_at.


register_payload_type("events.Command", Command)
