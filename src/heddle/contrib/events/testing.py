"""Public test utilities for ``heddle.contrib.events``.

Importable by downstream apps (shoppulse, baft, …) for their own
test suites. The pattern: construct envelopes and fake aggregates
without hand-rolling Pydantic fields every test.

Distinct from ``heddle/tests/fixtures.py`` (pytest fixtures internal
to heddle's own test suite).

Note on registration: :class:`FakeIntervalAggregate` and
:class:`FakeRootAggregate` register at module import time. If a test
needs to test the ``@register_aggregate`` decorator itself, use the
``registry_isolation`` fixture from ``heddle/tests/fixtures.py``  —
it snapshots ``AGGREGATE_REGISTRY`` at setup and restores at
teardown so the fakes registered here don't pollute test isolation.
"""

from __future__ import annotations

from typing import Any

from heddle.contrib.events.aggregate import IntervalAggregate, RootAggregate
from heddle.contrib.events.envelopes import (
    Command,
    CommandMetadata,
    Event,
    EventMetadata,
)
from heddle.contrib.events.errors import CommandRejected
from heddle.contrib.events.registry import register_aggregate


def make_event(
    *,
    aggregate_type: str = "FakeInterval",
    aggregate_id: str = "test-id",
    aggregate_version: int = 1,
    event_type: str = "ThingHappened",
    event_version: int = 1,
    payload: dict[str, Any] | None = None,
    issued_by: str = "user:badge:test",
    command_id: str | None = None,
    correlation_id: str | None = None,
) -> Event:
    """Construct an :class:`Event` body with sensible test defaults.

    Returns the bare body — no envelope timestamps. Use
    ``heddle.core.envelope.wrap("events.Event", make_event(...))`` to
    build the wire frame (e.g. to feed an ``EventLog``).
    """
    return Event(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        event_type=event_type,
        event_version=event_version,
        payload=payload or {},
        metadata=EventMetadata(
            command_id=command_id,
            correlation_id=correlation_id,
            issued_by=issued_by,
        ),
    )


def make_command(
    *,
    aggregate_type: str = "FakeInterval",
    aggregate_id: str = "test-id",
    command_type: str = "DoThing",
    command_version: int = 1,
    payload: dict[str, Any] | None = None,
    issued_by: str = "user:badge:test",
    correlation_id: str | None = None,
    expected_aggregate_version: int | None = None,
    command_id: str | None = None,
) -> Command:
    """Construct a :class:`Command` body with sensible test defaults."""
    kwargs: dict[str, Any] = {
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "command_type": command_type,
        "command_version": command_version,
        "payload": payload or {},
        "metadata": CommandMetadata(correlation_id=correlation_id, issued_by=issued_by),
        "expected_aggregate_version": expected_aggregate_version,
    }
    if command_id is not None:
        kwargs["command_id"] = command_id
    return Command(**kwargs)


# Reusable fake aggregates ----------------------------------------------------


@register_aggregate("FakeInterval")
class FakeIntervalAggregate(IntervalAggregate):
    """Minimal IntervalAggregate for testing dispatcher/handler wiring.

    - ``handle_do_thing(payload, metadata)`` → ``("ThingHappened", payload)``;
      raises :class:`CommandRejected` if ``payload['forbidden']`` is truthy.
    - ``apply_thing_happened`` stores the payload in ``self.last_payload``.
    """

    def __init__(self, aggregate_id: str) -> None:
        super().__init__(aggregate_id)
        self.last_payload: dict[str, Any] = {}

    def handle_do_thing(
        self, payload: dict[str, Any], metadata: CommandMetadata
    ) -> tuple[str, dict[str, Any]]:
        """Echo the payload as a ``ThingHappened`` event; reject if forbidden."""
        if payload.get("forbidden"):
            raise CommandRejected("FORBIDDEN", "test rejection")
        return "ThingHappened", dict(payload)

    def apply_thing_happened(self, payload: dict[str, Any], metadata: EventMetadata) -> None:
        """Record the most recent payload for assertion purposes."""
        self.last_payload = dict(payload)

    def handle_internal_finalize(
        self, payload: dict[str, Any], metadata: CommandMetadata
    ) -> tuple[str, dict[str, Any]]:
        """Emit ``InternalFinalized`` unless already finalized."""
        if self.phase == "finalized":
            raise CommandRejected("ALREADY_FINALIZED", "already finalized")
        return "InternalFinalized", {}


@register_aggregate("FakeRoot")
class FakeRootAggregate(RootAggregate):
    """Minimal RootAggregate for testing cascade behaviour.

    - ``handle_add_child({'child_id': X})`` → emits a ``ChildAdded``
      event with the reserved ``_child_membership`` payload key so
      P1 picks it up.
    - ``apply_child_added`` registers the child via ``register_child``.
    - ``handle_internal_finalize`` rejects if already finalized,
      otherwise emits ``InternalFinalized``.
    """

    def handle_add_child(
        self, payload: dict[str, Any], metadata: CommandMetadata
    ) -> tuple[str, dict[str, Any]]:
        """Emit ``ChildAdded`` with the ``_child_membership`` convention for P1."""
        child_id = payload["child_id"]
        return "ChildAdded", {
            "child_id": child_id,
            "_child_membership": {"add": [{"type": "FakeInterval", "id": child_id}]},
        }

    def apply_child_added(self, payload: dict[str, Any], metadata: EventMetadata) -> None:
        """Register the newly-added child in the in-aggregate registry."""
        self.register_child("FakeInterval", payload["child_id"])

    def handle_internal_finalize(
        self, payload: dict[str, Any], metadata: CommandMetadata
    ) -> tuple[str, dict[str, Any]]:
        """Emit ``InternalFinalized`` unless already finalized."""
        if self.phase == "finalized":
            raise CommandRejected("ALREADY_FINALIZED", "root already finalized")
        return "InternalFinalized", {}
