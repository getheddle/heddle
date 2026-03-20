"""
Streaming result collection for orchestrators.

Provides ``ResultStream``, an async iterator that yields ``TaskResult``
objects as they arrive from the message bus — rather than blocking until
all results are collected.

Two consumption modes:

    1. **Batch** (backward compatible with pre-Strategy-A code)::

           stream = ResultStream(bus, subject, expected_ids, timeout)
           results = await stream.collect_all()

    2. **Incremental** (new — enables progress callbacks and early exit)::

           stream = ResultStream(bus, subject, expected_ids, timeout,
                                 on_result=my_progress_callback)
           async for result in stream:
               # process each result as it arrives
               ...

The ``on_result`` callback is invoked for every arriving result with the
signature ``(result, collected_count, expected_count) -> bool | None``.
Returning ``True`` signals early exit — the stream stops collecting and
the caller gets whatever has arrived so far.

This module is used by:

- ``OrchestratorActor._collect_results()`` — dynamic orchestrator
- Potentially by ``MCPBridge`` for richer progress reporting (future)

Design decisions:

- **Single-use**: a ``ResultStream`` can only be iterated once (it owns
  the bus subscription lifecycle).
- **Callback errors are non-fatal**: if ``on_result`` raises, the error
  is logged and collection continues.
- **Duplicate filtering**: results for the same ``task_id`` are silently
  skipped (at-least-once delivery tolerance).
- **Unknown task_ids are ignored**: only results matching
  ``expected_task_ids`` are collected.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

import structlog

from loom.core.messages import TaskResult

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from loom.bus.base import MessageBus

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Callback protocol
# ---------------------------------------------------------------------------


class ResultCallback(Protocol):
    """Callback invoked when a result arrives during streaming collection.

    Parameters
    ----------
    result : TaskResult
        The just-arrived result.
    collected : int
        How many results have been collected so far (including this one).
    expected : int
        Total number of expected results.

    Returns:
    -------
    bool | None
        Return ``True`` to signal early exit (stop collecting).
        Return ``None`` or ``False`` to continue.
    """

    async def __call__(  # noqa: D102
        self,
        result: TaskResult,
        collected: int,
        expected: int,
    ) -> bool | None: ...


# ---------------------------------------------------------------------------
# ResultStream
# ---------------------------------------------------------------------------


class ResultStream:
    """Async iterator that yields ``TaskResult`` objects as they arrive.

    Wraps a bus subscription for a specific result subject, filtering
    incoming messages to only those matching ``expected_task_ids``.

    The stream terminates when:

    - All expected results have arrived, OR
    - The timeout expires, OR
    - The ``on_result`` callback returns ``True`` (early exit), OR
    - The subscription is closed.

    After iteration, inspect :attr:`collected`, :attr:`timed_out`, and
    :attr:`early_exited` for post-mortem state.

    Parameters
    ----------
    bus : MessageBus
        The message bus to subscribe on.
    subject : str
        NATS subject to subscribe to (e.g. ``loom.results.{goal_id}``).
    expected_task_ids : set[str]
        Set of task_ids we expect results for.
    timeout : float
        Maximum seconds to wait for all results.
    on_result : ResultCallback | None
        Optional callback invoked as each result arrives.

    Example:
    -------
    ::

        stream = ResultStream(
            bus=nats_bus,
            subject=f"loom.results.{goal_id}",
            expected_task_ids={"task-1", "task-2", "task-3"},
            timeout=60.0,
            on_result=my_progress_handler,
        )

        # Batch mode (drop-in replacement for old collect):
        results = await stream.collect_all()

        # Or streaming mode:
        async for result in stream:
            print(f"Got {result.worker_type}: {result.status}")
    """

    def __init__(
        self,
        bus: MessageBus,
        subject: str,
        expected_task_ids: set[str],
        timeout: float,
        *,
        on_result: ResultCallback | None = None,
    ) -> None:
        self._bus = bus
        self._subject = subject
        self._expected_ids = frozenset(expected_task_ids)
        self._timeout = timeout
        self._on_result = on_result

        # Mutable state — populated during iteration.
        self._collected: dict[str, TaskResult] = {}
        self._timed_out: bool = False
        self._early_exited: bool = False
        self._consumed: bool = False

    # ------------------------------------------------------------------
    # Read-only state inspection
    # ------------------------------------------------------------------

    @property
    def collected(self) -> dict[str, TaskResult]:
        """Map of task_id → TaskResult for all collected results."""
        return self._collected

    @property
    def expected_count(self) -> int:
        """Number of results we expect."""
        return len(self._expected_ids)

    @property
    def collected_count(self) -> int:
        """Number of results collected so far."""
        return len(self._collected)

    @property
    def all_collected(self) -> bool:
        """True when every expected result has arrived."""
        return self.collected_count >= self.expected_count

    @property
    def timed_out(self) -> bool:
        """True if collection ended due to timeout."""
        return self._timed_out

    @property
    def early_exited(self) -> bool:
        """True if collection ended due to on_result callback signaling stop."""
        return self._early_exited

    @property
    def pending_ids(self) -> frozenset[str]:
        """Task IDs that were expected but never arrived."""
        return self._expected_ids - frozenset(self._collected.keys())

    # ------------------------------------------------------------------
    # Consumption API
    # ------------------------------------------------------------------

    async def collect_all(self) -> list[TaskResult]:
        """Consume the stream fully, returning all collected results as a list.

        This is the backward-compatible entry point — it behaves identically
        to the pre-Strategy-A ``_collect_results()`` method.
        """
        return [result async for result in self]

    def __aiter__(self) -> AsyncIterator[TaskResult]:
        """Return the async iterator (self — delegates to _stream)."""
        if self._consumed:
            raise RuntimeError(
                "ResultStream has already been consumed. "
                "Create a new ResultStream for another iteration."
            )
        self._consumed = True
        return self._stream()

    async def _stream(self) -> AsyncIterator[TaskResult]:
        """Internal async generator that drives the collection loop.

        Subscribes to the bus subject, reads messages one at a time,
        filters/deduplicates, invokes callbacks, and yields results.
        """
        sub = await self._bus.subscribe(self._subject)
        deadline = asyncio.get_running_loop().time() + self._timeout

        log = logger.bind(
            subject=self._subject,
            expected=self.expected_count,
        )
        log.debug("result_stream.started", timeout=self._timeout)

        try:
            while not self.all_collected and not self._early_exited:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    self._timed_out = True
                    log.warning(
                        "result_stream.timeout",
                        collected=self.collected_count,
                        expected=self.expected_count,
                    )
                    break

                # Wait for the next message from the bus.
                try:
                    data = await asyncio.wait_for(
                        sub.__anext__(),
                        timeout=remaining,
                    )
                except (TimeoutError, StopAsyncIteration):
                    self._timed_out = True
                    log.warning(
                        "result_stream.timeout",
                        collected=self.collected_count,
                        expected=self.expected_count,
                    )
                    break

                # Filter: only accept results we dispatched.
                task_id = data.get("task_id")
                if task_id not in self._expected_ids:
                    log.debug(
                        "result_stream.ignored",
                        task_id=task_id,
                        reason="not_expected",
                    )
                    continue

                # Deduplicate: skip results we already collected.
                if task_id in self._collected:
                    log.debug(
                        "result_stream.duplicate",
                        task_id=task_id,
                    )
                    continue

                # Parse the result.
                try:
                    result = TaskResult(**data)
                except Exception as e:
                    log.warning(
                        "result_stream.parse_error",
                        task_id=task_id,
                        error=str(e),
                    )
                    continue

                self._collected[task_id] = result
                log.info(
                    "result_stream.collected",
                    task_id=task_id,
                    worker_type=result.worker_type,
                    status=result.status.value,
                    collected=self.collected_count,
                    expected=self.expected_count,
                )

                # Invoke callback (non-fatal on error).
                if self._on_result is not None:
                    try:
                        stop = self._on_result(
                            result,
                            self.collected_count,
                            self.expected_count,
                        )
                        if asyncio.iscoroutine(stop):
                            stop = await stop
                        if stop:
                            self._early_exited = True
                            log.info(
                                "result_stream.early_exit",
                                collected=self.collected_count,
                            )
                    except Exception as cb_err:
                        log.warning(
                            "result_stream.callback_error",
                            error=str(cb_err),
                        )

                yield result

        finally:
            await sub.unsubscribe()
            log.debug(
                "result_stream.finished",
                collected=self.collected_count,
                timed_out=self._timed_out,
                early_exited=self._early_exited,
            )
