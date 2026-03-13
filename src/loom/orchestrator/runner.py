"""
Orchestrator actor lifecycle -- the "thinking" layer above workers.

The orchestrator is a longer-lived LLM actor that:
- Receives high-level goals (OrchestratorGoal messages)
- Decomposes them into subtasks for workers (via decomposer.py)
- Dispatches subtasks through the router and collects results
- Synthesizes worker outputs into a coherent final answer (via synthesizer.py)
- Performs periodic self-summarization checkpoints (via checkpoint.py)

This differs from PipelineOrchestrator in that it uses an LLM to dynamically
decide which workers to invoke, rather than following a fixed stage sequence.

Message flow::

    loom.goals.incoming --> OrchestratorActor.handle_message()
        --> GoalDecomposer breaks goal into subtasks
        --> Publishes TaskMessages to loom.tasks.incoming (one per subtask)
        --> Subscribes to loom.results.{goal_id} for worker responses
        --> ResultSynthesizer combines results into a coherent answer
        --> Publishes final TaskResult to loom.results.{goal_id}

Concurrency model:
    Each goal is processed sequentially within a single OrchestratorActor
    instance (max_concurrent=1 by default from BaseActor).  Multiple goals
    are queued in the NATS subscription and processed one at a time.  For
    horizontal scaling, run multiple OrchestratorActor instances with a
    NATS queue group -- each goal will be handled by exactly one instance.

    Within a single goal, subtasks are dispatched concurrently (all published
    to loom.tasks.incoming at once) and results are collected as they arrive.

State tracking:
    The orchestrator is the ONLY stateful component in Loom.  It maintains:
    - ``_active_goals``: maps goal_id -> GoalState for in-flight goals
    - ``_conversation_history``: accumulated context for checkpoint decisions
    - ``_checkpoint_counter``: monotonically increasing checkpoint version

    Workers and the router are stateless by design.

See also:
    loom.orchestrator.pipeline -- PipelineOrchestrator (fixed stage sequence)
    loom.orchestrator.decomposer -- GoalDecomposer (LLM-based task breakdown)
    loom.orchestrator.synthesizer -- ResultSynthesizer (result combination)
    loom.orchestrator.checkpoint -- CheckpointManager (context compression)
    loom.core.messages -- all message schemas
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
import yaml

from loom.core.actor import BaseActor
from loom.core.messages import (
    OrchestratorGoal,
    TaskMessage,
    TaskResult,
    TaskStatus,
)
from loom.orchestrator.checkpoint import CheckpointManager
from loom.orchestrator.decomposer import GoalDecomposer
from loom.orchestrator.store import CheckpointStore
from loom.orchestrator.synthesizer import ResultSynthesizer
from loom.worker.backends import LLMBackend

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Internal state container
# ---------------------------------------------------------------------------


@dataclass
class GoalState:
    """Tracks the lifecycle of a single goal through decomposition and collection.

    One ``GoalState`` exists per in-flight goal.  It is created when a goal
    arrives, populated during decomposition, updated as results trickle in,
    and discarded after synthesis completes.

    Attributes:
        goal: The original ``OrchestratorGoal`` message.
        dispatched_tasks: Maps ``task_id`` -> ``TaskMessage`` for every subtask
            that was published to ``loom.tasks.incoming``.
        collected_results: Maps ``task_id`` -> ``TaskResult`` for every result
            received on ``loom.results.{goal_id}``.
        start_time: Monotonic timestamp when processing began.
    """

    goal: OrchestratorGoal
    dispatched_tasks: dict[str, TaskMessage] = field(default_factory=dict)
    collected_results: dict[str, TaskResult] = field(default_factory=dict)
    start_time: float = field(default_factory=time.monotonic)

    @property
    def all_collected(self) -> bool:
        """True when every dispatched task has a corresponding result."""
        return (
            len(self.dispatched_tasks) > 0
            and len(self.collected_results) >= len(self.dispatched_tasks)
        )

    @property
    def pending_count(self) -> int:
        """Number of dispatched tasks still awaiting results."""
        return len(self.dispatched_tasks) - len(self.collected_results)


# ---------------------------------------------------------------------------
# Orchestrator actor
# ---------------------------------------------------------------------------


class OrchestratorActor(BaseActor):
    """Dynamic orchestrator actor -- LLM-driven goal decomposition and synthesis.

    Unlike :class:`PipelineOrchestrator` which follows a fixed stage sequence,
    this actor uses an LLM to dynamically reason about which workers to invoke
    and how to combine their results.

    Lifecycle per goal:

    1. **Receive** -- parse the incoming dict as an ``OrchestratorGoal``.
    2. **Decompose** -- call :class:`GoalDecomposer` to break the goal into
       a list of ``TaskMessage`` subtasks.
    3. **Dispatch** -- publish each subtask to ``loom.tasks.incoming`` so the
       router can forward them to the appropriate workers.
    4. **Collect** -- subscribe to ``loom.results.{goal_id}`` and gather
       ``TaskResult`` messages until all subtasks have responded or the
       timeout expires.
    5. **Synthesize** -- call :class:`ResultSynthesizer` to combine all
       collected results into a coherent final answer.
    6. **Publish** -- send the synthesized ``TaskResult`` to
       ``loom.results.{goal_id}`` for the original caller.
    7. **Checkpoint** (optional) -- if the accumulated conversation history
       exceeds the token threshold, compress it via :class:`CheckpointManager`.

    Parameters
    ----------
    actor_id : str
        Unique identifier for this actor instance.
    config_path : str
        Path to the orchestrator YAML config file (e.g.
        ``configs/orchestrators/default.yaml``).
    backend : LLMBackend
        LLM backend used for both decomposition and synthesis.  Typically
        the same backend instance, but could be different tiers.
    nats_url : str
        NATS server URL.
    checkpoint_store : CheckpointStore | None
        Checkpoint persistence backend.  Pass None to disable checkpointing.

    Example
    -------
    ::

        from loom.worker.backends import OllamaBackend
        from loom.contrib.redis.store import RedisCheckpointStore

        backend = OllamaBackend(model="command-r7b:latest")
        store = RedisCheckpointStore("redis://localhost:6379")
        actor = OrchestratorActor(
            actor_id="orchestrator-1",
            config_path="configs/orchestrators/default.yaml",
            backend=backend,
            nats_url="nats://localhost:4222",
            checkpoint_store=store,
        )
        await actor.run("loom.goals.incoming")
    """

    def __init__(
        self,
        actor_id: str,
        config_path: str,
        backend: LLMBackend,
        nats_url: str = "nats://nats:4222",
        checkpoint_store: CheckpointStore | None = None,
    ):
        super().__init__(actor_id, nats_url)
        self.config = self._load_config(config_path)
        self.backend = backend

        # Build the decomposer from config-defined available workers.
        # Each entry needs at least "name" and "description".
        available_workers = self.config.get("available_workers", [])
        if not available_workers:
            # Fallback: infer from the system_prompt if no explicit list.
            # The default.yaml lists workers in the system prompt text; callers
            # should provide an explicit list for production use.
            logger.warning(
                "orchestrator.no_available_workers",
                hint="Add 'available_workers' list to orchestrator config",
            )
        self.decomposer = GoalDecomposer(
            backend=backend,
            available_workers=available_workers,
        )

        # Synthesizer uses the same backend for LLM-based synthesis.
        self.synthesizer = ResultSynthesizer(backend=backend)

        # Checkpoint manager -- only initialized if a checkpoint store is provided.
        checkpoint_config = self.config.get("checkpoint", {})
        self._checkpoint_manager: CheckpointManager | None = None
        if checkpoint_store is not None:
            self._checkpoint_manager = CheckpointManager(
                store=checkpoint_store,
                token_threshold=checkpoint_config.get("token_threshold", 50_000),
                recent_window_size=checkpoint_config.get("recent_window", 5),
            )

        # Configurable timeouts and concurrency limits from YAML.
        self._task_timeout: float = float(
            self.config.get("timeout_seconds", 300)
        )
        self._max_concurrent_tasks: int = self.config.get(
            "max_concurrent_tasks", 5
        )

        # ---------- Mutable state ----------
        # Active goals being processed.  Keyed by goal_id.
        # In the default single-concurrency mode (max_concurrent=1), there
        # is at most one entry at a time.  With higher concurrency, multiple
        # goals can be in-flight simultaneously.
        self._active_goals: dict[str, GoalState] = {}

        # Conversation history for checkpoint decisions.  Accumulates across
        # multiple goals within the same actor lifetime.  Reset on checkpoint.
        self._conversation_history: list[dict[str, Any]] = []
        self._checkpoint_counter: int = 0

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(path: str) -> dict[str, Any]:
        """Load orchestrator YAML configuration."""
        with open(path) as f:
            return yaml.safe_load(f)

    # ------------------------------------------------------------------
    # Core message handler
    # ------------------------------------------------------------------

    async def handle_message(self, data: dict[str, Any]) -> None:
        """Handle an incoming OrchestratorGoal.

        This is the main entry point called by :meth:`BaseActor._process_one`
        for every message received on ``loom.goals.incoming``.

        The method orchestrates the full goal lifecycle: parse, decompose,
        dispatch, collect, synthesize, publish.  Errors at any stage result
        in a ``FAILED`` TaskResult published to the goal's result subject.

        Parameters
        ----------
        data : dict[str, Any]
            Raw message dict, expected to conform to
            :class:`OrchestratorGoal` schema.
        """
        # -- 1. Parse --
        try:
            goal = OrchestratorGoal(**data)
        except Exception as e:
            logger.error(
                "orchestrator.parse_error",
                error=str(e),
                data_keys=list(data.keys()),
            )
            return

        log = logger.bind(goal_id=goal.goal_id)
        log.info("orchestrator.goal_received", instruction=goal.instruction[:120])

        goal_state = GoalState(goal=goal)
        self._active_goals[goal.goal_id] = goal_state

        try:
            # -- 2. Decompose --
            subtasks = await self._decompose_goal(goal, log)
            if not subtasks:
                log.warning("orchestrator.no_subtasks")
                await self._publish_final_result(
                    goal,
                    TaskStatus.FAILED,
                    error="Decomposition produced no subtasks for this goal.",
                )
                return

            # Enforce max concurrent tasks limit.
            if len(subtasks) > self._max_concurrent_tasks:
                log.warning(
                    "orchestrator.subtask_limit",
                    requested=len(subtasks),
                    limit=self._max_concurrent_tasks,
                )
                subtasks = subtasks[: self._max_concurrent_tasks]

            # -- 3. Dispatch --
            await self._dispatch_subtasks(goal_state, subtasks, log)

            # -- 4. Collect results --
            results = await self._collect_results(goal_state, log)

            # -- 5. Synthesize --
            synthesis = await self._synthesize_results(goal, results, log)

            # -- 6. Publish final result --
            elapsed = int((time.monotonic() - goal_state.start_time) * 1000)
            await self._publish_final_result(
                goal,
                TaskStatus.COMPLETED,
                output=synthesis,
                elapsed=elapsed,
            )
            log.info("orchestrator.goal_completed", ms=elapsed)

            # -- 7. Record in conversation history and check for checkpoint --
            self._record_in_history(goal, results, synthesis)
            await self._maybe_checkpoint(goal, goal_state, log)

        except Exception as e:
            log.error("orchestrator.goal_failed", error=str(e), exc_info=True)
            elapsed = int((time.monotonic() - goal_state.start_time) * 1000)
            await self._publish_final_result(
                goal,
                TaskStatus.FAILED,
                error=f"Orchestrator error: {e}",
                elapsed=elapsed,
            )
        finally:
            # Clean up goal state regardless of outcome.
            self._active_goals.pop(goal.goal_id, None)

    # ------------------------------------------------------------------
    # Step 2: Decomposition
    # ------------------------------------------------------------------

    async def _decompose_goal(
        self,
        goal: OrchestratorGoal,
        log: Any,
    ) -> list[TaskMessage]:
        """Use the GoalDecomposer to break a goal into subtasks.

        Returns
        -------
        list[TaskMessage]
            Ready-to-dispatch task messages.  May be empty if the LLM
            determines the goal cannot be decomposed.
        """
        log.info("orchestrator.decomposing")
        try:
            subtasks = await self.decomposer.decompose(goal)
            log.info("orchestrator.decomposed", subtask_count=len(subtasks))
            return subtasks
        except (ValueError, RuntimeError) as e:
            log.error("orchestrator.decomposition_failed", error=str(e))
            raise

    # ------------------------------------------------------------------
    # Step 3: Dispatch
    # ------------------------------------------------------------------

    async def _dispatch_subtasks(
        self,
        goal_state: GoalState,
        subtasks: list[TaskMessage],
        log: Any,
    ) -> None:
        """Publish all subtasks to ``loom.tasks.incoming`` for the router.

        Each subtask is registered in ``goal_state.dispatched_tasks`` so we
        know which results to expect during collection.

        All subtasks are published concurrently -- the router and workers
        handle parallelism.  There is no dependency ordering here; the
        dynamic orchestrator treats all decomposed subtasks as independent.
        (For sequential dependencies, use PipelineOrchestrator instead.)
        """
        for task in subtasks:
            goal_state.dispatched_tasks[task.task_id] = task
            await self.publish(
                "loom.tasks.incoming",
                task.model_dump(mode="json"),
            )
            log.info(
                "orchestrator.dispatched",
                task_id=task.task_id,
                worker_type=task.worker_type,
                model_tier=task.model_tier.value,
            )

        log.info(
            "orchestrator.all_dispatched",
            total=len(subtasks),
        )

    # ------------------------------------------------------------------
    # Step 4: Result collection
    # ------------------------------------------------------------------

    async def _collect_results(
        self,
        goal_state: GoalState,
        log: Any,
    ) -> list[TaskResult]:
        """Subscribe to ``loom.results.{goal_id}`` and collect worker results.

        Creates a temporary bus subscription that listens for TaskResult
        messages.  Each result is matched by ``task_id`` against the set of
        dispatched tasks.  Collection completes when:

        - All dispatched tasks have returned results, OR
        - The configurable timeout expires.

        On timeout, whatever results have been collected so far are returned.
        The synthesizer handles partial results gracefully.

        Returns
        -------
        list[TaskResult]
            Collected results (may be fewer than dispatched on timeout).
        """
        goal = goal_state.goal
        expected_count = len(goal_state.dispatched_tasks)
        expected_task_ids = set(goal_state.dispatched_tasks.keys())

        log.info(
            "orchestrator.collecting",
            expected=expected_count,
            timeout_seconds=self._task_timeout,
        )

        # Asyncio event that fires when all results are in.
        all_done = asyncio.Event()
        subject = f"loom.results.{goal.goal_id}"

        sub = await self._bus.subscribe(subject)

        async def _consume() -> None:
            """Iterate over subscription and store matching results."""
            async for data in sub:
                try:
                    task_id = data.get("task_id")

                    # Only accept results for tasks we actually dispatched.
                    if task_id not in expected_task_ids:
                        log.debug(
                            "orchestrator.result_ignored",
                            task_id=task_id,
                            reason="not_dispatched_by_this_goal",
                        )
                        continue

                    # Skip duplicates (at-least-once delivery).
                    if task_id in goal_state.collected_results:
                        log.debug(
                            "orchestrator.result_duplicate",
                            task_id=task_id,
                        )
                        continue

                    result = TaskResult(**data)
                    goal_state.collected_results[task_id] = result

                    log.info(
                        "orchestrator.result_received",
                        task_id=task_id,
                        worker_type=result.worker_type,
                        status=result.status.value,
                        collected=len(goal_state.collected_results),
                        expected=expected_count,
                    )

                    if goal_state.all_collected:
                        all_done.set()
                        break

                except Exception as e:
                    log.error(
                        "orchestrator.result_parse_error",
                        error=str(e),
                    )

        consume_task = asyncio.create_task(_consume())

        try:
            await asyncio.wait_for(all_done.wait(), timeout=self._task_timeout)
            log.info("orchestrator.all_results_collected")
        except asyncio.TimeoutError:
            collected = len(goal_state.collected_results)
            log.warning(
                "orchestrator.collection_timeout",
                collected=collected,
                expected=expected_count,
                timeout_seconds=self._task_timeout,
            )
        finally:
            consume_task.cancel()
            await sub.unsubscribe()

        return list(goal_state.collected_results.values())

    # ------------------------------------------------------------------
    # Step 5: Synthesis
    # ------------------------------------------------------------------

    async def _synthesize_results(
        self,
        goal: OrchestratorGoal,
        results: list[TaskResult],
        log: Any,
    ) -> dict[str, Any]:
        """Combine collected results into a final answer using the synthesizer.

        Uses :meth:`ResultSynthesizer.synthesize` with the goal instruction
        to produce an LLM-driven coherent narrative.  If no LLM backend is
        available, falls back to deterministic merge.

        Returns
        -------
        dict[str, Any]
            The synthesized output dict, ready for inclusion in the final
            TaskResult.
        """
        log.info(
            "orchestrator.synthesizing",
            result_count=len(results),
            successful=sum(1 for r in results if r.status == TaskStatus.COMPLETED),
            failed=sum(1 for r in results if r.status == TaskStatus.FAILED),
        )

        synthesis = await self.synthesizer.synthesize(
            results,
            goal=goal.instruction,
        )

        log.info(
            "orchestrator.synthesized",
            confidence=synthesis.get("confidence"),
        )
        return synthesis

    # ------------------------------------------------------------------
    # Step 6: Final result publication
    # ------------------------------------------------------------------

    async def _publish_final_result(
        self,
        goal: OrchestratorGoal,
        status: TaskStatus,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        elapsed: int = 0,
    ) -> None:
        """Publish the final orchestration result to ``loom.results.{goal_id}``.

        This result is consumed by whoever submitted the original goal --
        typically the CLI ``loom submit`` command or an external system.

        The ``task_id`` is set to the ``goal_id`` so the caller can correlate
        the result with the original goal submission.
        """
        result = TaskResult(
            task_id=goal.goal_id,
            parent_task_id=None,
            worker_type=self.config.get("name", "orchestrator"),
            status=status,
            output=output,
            error=error,
            model_used=None,
            token_usage={},
            processing_time_ms=elapsed,
        )
        subject = f"loom.results.{goal.goal_id}"
        await self.publish(subject, result.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # Step 7: Conversation history and checkpointing
    # ------------------------------------------------------------------

    def _record_in_history(
        self,
        goal: OrchestratorGoal,
        results: list[TaskResult],
        synthesis: dict[str, Any],
    ) -> None:
        """Append a goal's lifecycle to the conversation history.

        The conversation history accumulates across goals within the same
        actor lifetime.  When it exceeds the token threshold, the
        CheckpointManager compresses it.

        Each history entry is a compact summary -- not the full result data.
        """
        result_summaries = []
        for r in results:
            summary: dict[str, Any] = {
                "task_id": r.task_id,
                "worker_type": r.worker_type,
                "status": r.status.value,
            }
            if r.status == TaskStatus.COMPLETED and r.output:
                # Store a truncated version of the output to limit history size.
                output_str = json.dumps(r.output, default=str)
                summary["output_preview"] = output_str[:500]
            elif r.status == TaskStatus.FAILED:
                summary["error"] = r.error
            result_summaries.append(summary)

        entry = {
            "goal_id": goal.goal_id,
            "instruction": goal.instruction,
            "subtask_count": len(results),
            "results": result_summaries,
            "synthesis_confidence": synthesis.get("confidence"),
            "timestamp": time.time(),
        }
        self._conversation_history.append(entry)

    async def _maybe_checkpoint(
        self,
        goal: OrchestratorGoal,
        goal_state: GoalState,
        log: Any,
    ) -> None:
        """Check if the conversation history needs compression.

        If a CheckpointManager is configured and the history exceeds the
        token threshold, creates a checkpoint and resets the history to
        only the most recent entries (the "recent window").
        """
        if self._checkpoint_manager is None:
            return

        if not self._checkpoint_manager.should_checkpoint(
            self._conversation_history
        ):
            return

        log.info("orchestrator.checkpoint_triggered")
        self._checkpoint_counter += 1

        # Build completed/pending task summaries for the checkpoint.
        completed_tasks = []
        for entry in self._conversation_history:
            for r in entry.get("results", []):
                completed_tasks.append({
                    "task_id": r.get("task_id"),
                    "worker_type": r.get("worker_type"),
                    "status": r.get("status"),
                    "summary": r.get("output_preview", r.get("error", "")),
                })

        try:
            checkpoint = await self._checkpoint_manager.create_checkpoint(
                goal_id=goal.goal_id,
                original_instruction=goal.instruction,
                completed_tasks=completed_tasks,
                pending_tasks=[],  # No pending tasks at checkpoint time
                open_issues=[],
                decisions_made=[],
                checkpoint_number=self._checkpoint_counter,
            )

            # Reset conversation history, keeping only the recent window.
            window = self._checkpoint_manager.recent_window_size
            self._conversation_history = self._conversation_history[-window:]

            log.info(
                "orchestrator.checkpoint_created",
                checkpoint_number=checkpoint.checkpoint_number,
                token_count=checkpoint.context_token_count,
                history_entries_kept=len(self._conversation_history),
            )
        except Exception as e:
            # Checkpoint failure is non-fatal -- the orchestrator continues
            # with a growing history.  The next goal will try again.
            log.error("orchestrator.checkpoint_failed", error=str(e))
