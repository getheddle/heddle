"""CommandHandler — orchestrates the command -> event flow.

Per v7 §4.6, every command goes through nine steps:

1. Look up aggregate class via the registry.
2. Load events from EventLog and replay through ``apply()`` (a
   KeyValueStore snapshot fast path short-circuits full replay).
3. Check ``has_processed(command_id)`` — dedup buffer.
4. Validate ``expected_aggregate_version`` if not None.
5. Look up ``handle_<command_type_snake>`` on the aggregate.
6. Invoke handler -> ``(event_type, event_payload)``.
7. On :class:`CommandRejected`: append a
   :class:`Rejection` to RejectionLog and re-raise.
8. Construct :class:`Event` (new event_id, version=current+1,
   propagated correlation_id + command_id), wrap it in a
   ``WireEnvelope``.
9. Append the frame with CAS, then ``apply()`` the body to the
   in-memory aggregate and ``mark_processed(command_id)``. Return the
   body.

``handle()`` takes and returns bare bodies (``Command`` in, ``Event``
out) — commands aren't durably logged in-process, and callers here
only ever need event identity/metadata, never envelope-level
``occurred_at``/``recorded_at``. Only the durable log traffics in
``WireEnvelope`` frames; see :mod:`heddle.contrib.events.event_log`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from heddle.contrib.events.aggregate import Aggregate, snake_case
from heddle.contrib.events.cache import AggregateCache, CacheKey
from heddle.contrib.events.dedup_publisher import DedupPublisher, NullDedupPublisher
from heddle.contrib.events.dedup_subscriber import DedupSubscriber, NullDedupSubscriber
from heddle.contrib.events.envelopes import (
    Event,
    EventMetadata,
)
from heddle.contrib.events.errors import (
    CommandRejected,
    ConcurrencyError,
)
from heddle.contrib.events.registry import get_aggregate_class
from heddle.contrib.events.rejection_log import Rejection
from heddle.contrib.events.sli import get_recorder, time_observation
from heddle.contrib.events.snapshot_store import SNAPSHOT_EVERY_N, SnapshotStore
from heddle.core.envelope import unwrap, wrap

if TYPE_CHECKING:
    from heddle.contrib.events.envelopes import Command
    from heddle.contrib.events.event_log import EventLog
    from heddle.contrib.events.rejection_log import RejectionLog


class CommandHandler:
    """Orchestrate command processing through the aggregate model.

    Supports process-local caching (T2), snapshot persistence (T3),
    and cross-process dedup via published ``mark_processed`` events
    (T4). All three are optional via dependency injection — pass
    ``cache=AggregateCache(max_size=0)`` to disable caching; pass
    ``snapshot_store=None`` to skip the snapshot fast path; pass a
    ``NullDedupPublisher`` / ``NullDedupSubscriber`` (the defaults)
    for single-process deployments.
    """

    def __init__(
        self,
        event_log: EventLog,
        rejection_log: RejectionLog,
        *,
        cache: AggregateCache | None = None,
        snapshot_store: SnapshotStore | None = None,
        dedup_publisher: DedupPublisher | None = None,
        dedup_subscriber: DedupSubscriber | None = None,
        snapshot_every_n: int = SNAPSHOT_EVERY_N,
    ) -> None:
        self._event_log = event_log
        self._rejection_log = rejection_log
        self._snapshot_store = snapshot_store
        self._dedup_publisher = dedup_publisher or NullDedupPublisher()
        self._dedup_subscriber = dedup_subscriber or NullDedupSubscriber()
        self._snapshot_every_n = snapshot_every_n
        # Wire cache eviction to dedup-subscriber unsubscribe so stale
        # subscriptions don't outlive their aggregate.
        if cache is None:
            cache = AggregateCache(on_evict=self._on_cache_evict)
        elif cache.on_evict is None:
            cache.on_evict = self._on_cache_evict
        self._cache = cache

    async def _on_cache_evict(self, key: CacheKey, _aggregate: Aggregate) -> None:
        agg_type, agg_id = key
        await self._dedup_subscriber.unsubscribe(agg_type, agg_id)

    async def handle(self, cmd: Command) -> Event:
        """Process a command and produce the resulting event.

        Raises:
            KeyError: ``aggregate_type`` not registered.
            ConcurrencyError: ``expected_aggregate_version`` mismatch.
            CommandRejected: aggregate handler rejected the command.
            AttributeError: aggregate has no ``handle_<command_type>``.
        """
        with time_observation() as elapsed:
            outcome = "error"
            try:
                event = await self._handle_impl(cmd)
                outcome = "success"
                return event
            except CommandRejected:
                outcome = "rejected"
                raise
            except ConcurrencyError:
                outcome = "concurrency_error"
                raise
            finally:
                get_recorder().observe_command_handle(
                    aggregate_type=cmd.aggregate_type,
                    command_type=cmd.command_type,
                    outcome=outcome,
                    duration_seconds=elapsed(),
                )

    async def _handle_impl(self, cmd: Command) -> Event:
        cls = get_aggregate_class(cmd.aggregate_type)
        aggregate = await self._load_or_create(cls, cmd.aggregate_id)

        # ---- 3. Dedup check — idempotent retry path. -----------------------
        if aggregate.has_processed(cmd.command_id):
            replay = await self._find_event_by_command_id(
                cmd.aggregate_type, cmd.aggregate_id, cmd.command_id
            )
            if replay is not None:
                return replay
            # Edge case (v7 §4.11): dedup buffer says yes but no event
            # carries this command_id — buffer-restore-without-events.
            # Fall through and re-execute; the resulting duplicate
            # event with a new event_id is harmless.

        # ---- 4. Optimistic concurrency check at command level. -------------
        if (
            cmd.expected_aggregate_version is not None
            and cmd.expected_aggregate_version != aggregate.aggregate_version
        ):
            raise ConcurrencyError(
                f"command expected_aggregate_version="
                f"{cmd.expected_aggregate_version} but aggregate "
                f"version={aggregate.aggregate_version}"
            )

        # ---- 5. Dispatch to aggregate.handle_<command_type>(). -------------
        handler_name = f"handle_{snake_case(cmd.command_type)}"
        handler = getattr(aggregate, handler_name, None)
        if handler is None:
            raise AttributeError(f"{type(aggregate).__name__} has no {handler_name}")

        # ---- 6+7. Invoke handler; rejection -> append + re-raise. ----------
        try:
            event_type, event_payload = handler(cmd.payload, cmd.metadata)
        except CommandRejected as rej:
            await self._rejection_log.append(
                wrap(
                    "events.Rejection",
                    Rejection(command=cmd, reason=rej.reason, detail=rej.detail),
                )
            )
            raise

        # ---- 8. Build event body. -------------------------------------------
        current_version = aggregate.aggregate_version
        event = Event(
            aggregate_type=cmd.aggregate_type,
            aggregate_id=cmd.aggregate_id,
            aggregate_version=current_version + 1,
            event_type=event_type,
            event_version=1,
            payload=event_payload,
            metadata=EventMetadata(
                command_id=cmd.command_id,
                correlation_id=cmd.metadata.correlation_id,
                issued_by=cmd.metadata.issued_by,
            ),
        )

        # ---- 9. Append with CAS, then apply + mark_processed. --------------
        await self._event_log.append(wrap("events.Event", event), expected_version=current_version)
        aggregate.apply(event)
        aggregate.mark_processed(cmd.command_id)

        # ---- 10. Cross-process dedup announcement. ------------------------
        await self._dedup_publisher.publish(cmd.aggregate_type, cmd.aggregate_id, cmd.command_id)

        # ---- 11. Snapshot-on-write (count-based). -------------------------
        if (
            self._snapshot_store is not None
            and self._snapshot_every_n > 0
            and aggregate.aggregate_version % self._snapshot_every_n == 0
        ):
            await self._snapshot_store.save(aggregate)

        return event

    async def _load_or_create(self, cls: type[Aggregate], aggregate_id: str) -> Aggregate:
        """Rebuild aggregate, preferring cache > snapshot > event replay.

        Sprint 3 path:

        1. Cache hit: return the cached instance immediately.
        2. Cache miss: try snapshot (if configured); replay only events
           with ``aggregate_version > snapshot_version``.
        3. No snapshot: fresh aggregate + full replay from version 0.

        Per v7 §4.5 the dedup buffer is restored from snapshot only —
        pure-replay rebuilds (path 3) start with an empty buffer.
        """
        key: CacheKey = (cls.aggregate_type, aggregate_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        aggregate: Aggregate | None = None
        from_version = 0
        if self._snapshot_store is not None:
            aggregate = await self._snapshot_store.load(cls, aggregate_id)
            if aggregate is not None:
                from_version = aggregate.aggregate_version

        if aggregate is None:
            aggregate = cls(aggregate_id=aggregate_id)

        async for envelope in self._event_log.load(
            cls.aggregate_type, aggregate_id, from_version=from_version
        ):
            body = unwrap(envelope)
            assert isinstance(body, Event)
            aggregate.apply(body)

        await self._cache.put(key, aggregate)
        await self._dedup_subscriber.subscribe(cls.aggregate_type, aggregate_id, self._cache)
        return aggregate

    async def _find_event_by_command_id(
        self, aggregate_type: str, aggregate_id: str, command_id: str
    ) -> Event | None:
        """Locate a previously-produced event by command_id.

        Linear scan over the aggregate's event log. A future pass may
        swap this for a KeyValueStore secondary index so dedup-replay
        stays O(1).
        """
        async for envelope in self._event_log.load(aggregate_type, aggregate_id):
            body = unwrap(envelope)
            assert isinstance(body, Event)
            if body.metadata.command_id == command_id:
                return body
        return None
