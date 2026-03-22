"""
Scheduler actor — time-driven dispatch of goals and tasks.

The scheduler is a long-lived actor that reads a YAML config defining
cron expressions and fixed-interval timers.  When a timer fires, it
publishes either an OrchestratorGoal or a TaskMessage to the appropriate
NATS subject.

Design:
    - Extends BaseActor (long-lived, not TaskWorker)
    - Overrides run() to launch a background timer loop alongside
      the standard message subscription
    - handle_message() is a minimal no-op (satisfies the ABC)
    - Uses croniter for cron parsing, asyncio.sleep for intervals
    - Graceful shutdown cancels the timer loop via _running flag

NATS subjects:

- Subscribes to: ``loom.scheduler.{name}``  (health checks / future control)
- Publishes to: ``loom.goals.incoming`` (for dispatch_type "goal")
  or ``loom.tasks.incoming`` (for dispatch_type "task")
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
import yaml

from loom.core.actor import BaseActor
from loom.core.messages import (
    ModelTier,
    OrchestratorGoal,
    TaskMessage,
    TaskPriority,
)

if TYPE_CHECKING:
    from loom.bus.base import MessageBus

logger = structlog.get_logger()


@dataclass
class ScheduleEntry:
    """Parsed schedule entry from YAML config.

    If ``expand_from`` is set, the scheduler calls the referenced function
    before each fire.  The function must return a list of context dicts.
    One goal/task is dispatched per dict, with the context merged into
    the payload (for tasks) or context (for goals).  This enables
    per-session dispatch where the expansion function queries for active
    sessions and returns ``[{"session_id": "s1"}, {"session_id": "s2"}]``.
    """

    name: str
    cron: str | None
    interval_seconds: float | None
    dispatch_type: str  # "goal" or "task"
    goal_config: dict[str, Any] | None = None
    task_config: dict[str, Any] | None = None
    expand_from: str | None = None  # dotted path to expansion function
    next_fire: float = 0.0  # monotonic timestamp of next fire


class SchedulerActor(BaseActor):
    """Time-driven actor that dispatches goals and tasks on schedule.

    All schedules are defined at startup via YAML config.  The actor
    maintains a background timer loop that checks schedules every second
    and fires due entries by publishing to the appropriate NATS subject.
    """

    def __init__(
        self,
        actor_id: str,
        config_path: str,
        nats_url: str = "nats://nats:4222",
        *,
        bus: MessageBus | None = None,
    ) -> None:
        super().__init__(actor_id, nats_url, bus=bus)
        self.config = self._load_config(config_path)
        self._schedules: list[ScheduleEntry] = self._parse_schedules(
            self.config.get("schedules", [])
        )
        self._timer_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(path: str) -> dict[str, Any]:
        with open(path) as f:
            return yaml.safe_load(f)

    @staticmethod
    def _parse_schedules(raw: list[dict[str, Any]]) -> list[ScheduleEntry]:
        """Convert raw YAML schedule dicts into ScheduleEntry objects."""
        return [
            ScheduleEntry(
                name=item["name"],
                cron=item.get("cron"),
                interval_seconds=item.get("interval_seconds"),
                dispatch_type=item["dispatch_type"],
                goal_config=item.get("goal"),
                task_config=item.get("task"),
                expand_from=item.get("expand_from"),
            )
            for item in raw
        ]

    # ------------------------------------------------------------------
    # run() override — adds background timer alongside subscription loop
    #
    # BaseActor.run() blocks on ``async for data in self._sub`` (the
    # subscription loop).  The scheduler needs BOTH that loop AND a
    # background timer.  We override run() and launch _timer_loop() as
    # an asyncio.Task before entering the subscription loop.  On
    # shutdown the timer task is cancelled cleanly.
    # ------------------------------------------------------------------

    async def run(self, subject: str, queue_group: str | None = None) -> None:
        """Start the scheduler with background timer loop and subscription."""
        self._shutdown_event = asyncio.Event()
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

        await self.connect()
        await self.subscribe(subject, queue_group)
        self._running = True
        self._install_signal_handlers()

        self._initialize_fire_times()

        logger.info(
            "scheduler.running",
            actor_id=self.actor_id,
            subject=subject,
            schedule_count=len(self._schedules),
        )

        # Launch background timer loop
        self._timer_task = asyncio.create_task(self._timer_loop())
        self._background_tasks: set[asyncio.Task[None]] = set()

        try:
            # Standard subscription loop (mirrors BaseActor.run)
            async for data in self._sub:
                if not self._running:
                    break
                if self.max_concurrent == 1:
                    await self._process_one(data)
                else:
                    task = asyncio.create_task(self._process_one(data))
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            if self._timer_task and not self._timer_task.done():
                self._timer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._timer_task
            await self.disconnect()

    # ------------------------------------------------------------------
    # Timer loop
    # ------------------------------------------------------------------

    async def _timer_loop(self) -> None:
        """Background loop — checks schedules every second, fires when due."""
        while self._running:
            now = time.monotonic()
            for entry in self._schedules:
                if now >= entry.next_fire:
                    await self._fire_schedule(entry)
                    self._advance_next_fire(entry)
            await asyncio.sleep(1.0)

    def _initialize_fire_times(self) -> None:
        """Set initial next_fire for each schedule entry."""
        now_mono = time.monotonic()
        now_utc = datetime.now(UTC)

        for entry in self._schedules:
            if entry.interval_seconds is not None:
                entry.next_fire = now_mono + entry.interval_seconds
            elif entry.cron is not None:
                from croniter import croniter

                cron = croniter(entry.cron, now_utc)
                next_dt = cron.get_next(datetime)
                delta = (next_dt - now_utc).total_seconds()
                entry.next_fire = now_mono + delta

            logger.info(
                "scheduler.schedule_initialized",
                schedule=entry.name,
                next_fire_in_seconds=round(entry.next_fire - now_mono, 1),
            )

    def _advance_next_fire(self, entry: ScheduleEntry) -> None:
        """Compute the next fire time after a schedule fires."""
        now_mono = time.monotonic()
        now_utc = datetime.now(UTC)

        if entry.interval_seconds is not None:
            entry.next_fire = now_mono + entry.interval_seconds
        elif entry.cron is not None:
            from croniter import croniter

            cron = croniter(entry.cron, now_utc)
            next_dt = cron.get_next(datetime)
            delta = (next_dt - now_utc).total_seconds()
            entry.next_fire = now_mono + delta

    # ------------------------------------------------------------------
    # Dispatch logic
    # ------------------------------------------------------------------

    async def _fire_schedule(self, entry: ScheduleEntry) -> None:
        """Dispatch the configured goal or task for a schedule entry.

        If ``expand_from`` is set, the expansion function is called first.
        One dispatch is made per expansion result, with the expansion context
        merged into the payload (tasks) or goal context (goals).

        If no expansion is configured, a single dispatch is made as before.

        Exceptions from the underlying dispatch methods are caught and
        logged so that a single broken schedule never crashes the actor.
        """
        logger.info(
            "scheduler.firing",
            schedule=entry.name,
            dispatch_type=entry.dispatch_type,
            expand_from=entry.expand_from or "none",
        )

        try:
            if entry.expand_from:
                contexts = self._run_expansion(entry.expand_from, entry.name)
                if not contexts:
                    logger.info("scheduler.expansion_empty", schedule=entry.name)
                    return
                for ctx in contexts:
                    if entry.dispatch_type == "goal":
                        await self._dispatch_goal(entry, extra_context=ctx)
                    elif entry.dispatch_type == "task":
                        await self._dispatch_task(entry, extra_payload=ctx)
                logger.info(
                    "scheduler.expansion_dispatched",
                    schedule=entry.name,
                    count=len(contexts),
                )
            elif entry.dispatch_type == "goal":
                await self._dispatch_goal(entry)
            elif entry.dispatch_type == "task":
                await self._dispatch_task(entry)
            else:
                logger.error(
                    "scheduler.unknown_dispatch_type",
                    schedule=entry.name,
                    dispatch_type=entry.dispatch_type,
                )
        except Exception:
            logger.exception(
                "scheduler.dispatch_error",
                schedule=entry.name,
                dispatch_type=entry.dispatch_type,
            )

    @staticmethod
    def _run_expansion(dotted_path: str, schedule_name: str) -> list[dict[str, Any]]:
        """Import and call an expansion function by dotted path.

        The function must be callable with no arguments and return a list
        of dicts.  Each dict is merged into the dispatch payload/context.

        Example expand_from value:
            ``myapp.sessions.get_active_sessions``

        The referenced function should return something like:
            ``[{"session_id": "s1"}, {"session_id": "s2"}]``
        """
        import importlib

        if "." not in dotted_path:
            logger.error(
                "scheduler.invalid_expand_from",
                schedule=schedule_name,
                expand_from=dotted_path,
                hint="Must be a fully qualified function path (e.g., myapp.sessions.get_active)",
            )
            return []

        module_path, func_name = dotted_path.rsplit(".", 1)
        try:
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
        except (ImportError, AttributeError) as exc:
            logger.error(
                "scheduler.expand_from_import_failed",
                schedule=schedule_name,
                expand_from=dotted_path,
                error=str(exc),
            )
            return []

        try:
            result = func()
            if not isinstance(result, list):
                logger.error(
                    "scheduler.expand_from_bad_return",
                    schedule=schedule_name,
                    expand_from=dotted_path,
                    got=type(result).__name__,
                )
                return []
            return result
        except Exception as exc:
            logger.error(
                "scheduler.expand_from_call_failed",
                schedule=schedule_name,
                expand_from=dotted_path,
                error=str(exc),
            )
            return []

    async def _dispatch_goal(
        self,
        entry: ScheduleEntry,
        extra_context: dict[str, Any] | None = None,
    ) -> None:
        """Publish an OrchestratorGoal to loom.goals.incoming."""
        cfg = entry.goal_config or {}
        priority_str = cfg.get("priority", "normal")
        context = {**cfg.get("context", {}), **(extra_context or {})}
        goal = OrchestratorGoal(
            instruction=cfg.get("instruction", ""),
            context=context,
            priority=TaskPriority(priority_str),
        )
        await self.publish(
            "loom.goals.incoming",
            goal.model_dump(mode="json"),
        )
        logger.info(
            "scheduler.goal_dispatched",
            schedule=entry.name,
            goal_id=str(goal.goal_id),
        )

    async def _dispatch_task(
        self,
        entry: ScheduleEntry,
        extra_payload: dict[str, Any] | None = None,
    ) -> None:
        """Publish a TaskMessage to loom.tasks.incoming."""
        cfg = entry.task_config or {}
        payload = {**cfg.get("payload", {}), **(extra_payload or {})}
        task = TaskMessage(
            worker_type=cfg["worker_type"],
            payload=payload,
            model_tier=ModelTier(cfg.get("model_tier", "local")),
            priority=TaskPriority(cfg.get("priority", "normal")),
            metadata={"scheduled_by": entry.name},
        )
        await self.publish(
            "loom.tasks.incoming",
            task.model_dump(mode="json"),
        )
        logger.info(
            "scheduler.task_dispatched",
            schedule=entry.name,
            task_id=str(task.task_id),
            worker_type=task.worker_type,
        )

    # ------------------------------------------------------------------
    # handle_message — no-op (satisfies BaseActor ABC)
    # ------------------------------------------------------------------

    async def handle_message(self, data: dict[str, Any]) -> None:
        """No-op message handler.  The scheduler is timer-driven.

        Satisfies BaseActor's abstract requirement.  A future enhancement
        could respond to health-check or status queries here.
        """
        logger.debug(
            "scheduler.message_received",
            actor_id=self.actor_id,
            keys=list(data.keys()),
        )
