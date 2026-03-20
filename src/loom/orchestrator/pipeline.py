"""
Pipeline orchestrator for multi-stage processing with automatic parallelism.

Executes a defined sequence of stages, passing results from each stage
as input to later stages. Each stage maps to a worker_type. Stages can be
LLM workers, processor workers, or any other actor — the pipeline
doesn't care about the implementation, only the message contract.

Stage dependencies are **automatically inferred** from ``input_mapping``
paths: if stage B references ``"A.output.field"``, then B depends on A.
Stages with no inter-stage dependencies (only ``goal.*`` paths) are
independent and execute in parallel. Alternatively, explicit
``depends_on`` lists in the YAML config override automatic inference.

Execution proceeds in *levels* — each level contains stages whose
dependencies are all satisfied by earlier levels. Stages within a level
run concurrently via ``asyncio.gather``.

Pipeline definition comes from YAML config with stages, input mappings,
and optional conditions.

Data flow through the pipeline:

    OrchestratorGoal arrives at handle_message()
        ↓
    context = { "goal": { "instruction": ..., "context": { ... } } }
        ↓
    Build execution levels from stage dependencies (Kahn's algorithm)
        ↓
    For each level:
        For each stage in level (concurrently if >1):
            1. Evaluate condition (skip if false)
            2. Build payload via input_mapping (dot-notation paths into context)
            3. Publish TaskMessage to loom.tasks.incoming
            4. Wait for TaskResult on loom.results.{goal_id}
            5. Store result: context[stage_name] = { "output": ..., ... }
        ↓
    Publish final TaskResult with all stage outputs

Input mapping example (from doc_pipeline.yaml):
    input_mapping:
        text_preview: "extract.output.text_preview"
        metadata: "extract.output.metadata"

    This resolves to:
        payload["text_preview"] = context["extract"]["output"]["text_preview"]
        payload["metadata"] = context["extract"]["output"]["metadata"]

See Also:
    loom.orchestrator.runner — dynamic LLM-based orchestrator
    loom.core.messages.OrchestratorGoal — the input message type
    configs/orchestrators/ — pipeline config YAML files
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

import structlog
import yaml

from loom.core.actor import BaseActor
from loom.core.contracts import validate_input, validate_output
from loom.core.messages import (
    ModelTier,
    OrchestratorGoal,
    TaskMessage,
    TaskResult,
    TaskStatus,
)

logger = structlog.get_logger()


class PipelineStageError(Exception):
    """Raised when a pipeline stage fails or times out."""

    def __init__(self, stage_name: str, message: str) -> None:
        self.stage_name = stage_name
        super().__init__(message)


class PipelineOrchestrator(BaseActor):
    """
    Pipeline orchestrator with automatic stage parallelism.

    Processes an OrchestratorGoal by running it through a series of stages
    organized into execution levels based on their dependencies. Stages
    within the same level run concurrently; levels execute sequentially.
    Stage outputs are accumulated in a context dict and can be referenced
    by subsequent stages via input_mapping.
    """

    def __init__(
        self,
        actor_id: str,
        config_path: str,
        nats_url: str = "nats://nats:4222",
        *,
        bus: Any | None = None,
    ) -> None:
        self._config_path = config_path
        self.config = self._load_config(config_path)
        max_goals = self.config.get("max_concurrent_goals", 1)
        super().__init__(actor_id, nats_url, max_concurrent=max_goals, bus=bus)

    def _load_config(self, path: str) -> dict:
        with open(path) as f:
            return yaml.safe_load(f)

    async def on_reload(self) -> None:
        """Re-read the pipeline config from disk on reload signal."""
        self.config = self._load_config(self._config_path)
        logger.info("pipeline.config_reloaded", config_path=self._config_path)

    # ------------------------------------------------------------------
    # Dependency inference and execution level construction
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_dependencies(
        stages: list[dict[str, Any]],
    ) -> dict[str, set[str]]:
        """Infer stage dependencies from input_mapping paths.

        For each stage, parse the first segment of every ``input_mapping``
        source path.  If that segment matches another stage's name (and
        is not ``"goal"``), record it as a dependency.

        If a stage has an explicit ``depends_on`` list in its config, that
        takes precedence over automatic inference.

        Returns a dict mapping stage name → set of stage names it depends on.
        """
        stage_names = {s["name"] for s in stages}
        deps: dict[str, set[str]] = {}

        for stage in stages:
            name = stage["name"]

            if "depends_on" in stage:
                # Explicit override — use as-is (filtered to known stages).
                deps[name] = {d for d in stage["depends_on"] if d in stage_names}
                continue

            # Automatic inference from input_mapping paths.
            mapping = stage.get("input_mapping", {})
            inferred: set[str] = set()
            for source_path in mapping.values():
                first_segment = source_path.split(".")[0]
                if first_segment != "goal" and first_segment in stage_names:
                    inferred.add(first_segment)
            deps[name] = inferred

        return deps

    @staticmethod
    def _build_execution_levels(
        stages: list[dict[str, Any]],
        deps: dict[str, set[str]],
    ) -> list[list[dict[str, Any]]]:
        """Group stages into execution levels using Kahn's algorithm.

        Stages with all dependencies satisfied by earlier levels are placed
        in the same level and can run concurrently.  Within each level,
        stages are sorted alphabetically for deterministic ordering.

        Raises ``ValueError`` if the dependency graph contains a cycle.
        """
        # Build adjacency and in-degree maps.
        stage_by_name = {s["name"]: s for s in stages}
        in_degree: dict[str, int] = {s["name"]: 0 for s in stages}
        dependents: dict[str, list[str]] = {s["name"]: [] for s in stages}

        for name, dep_set in deps.items():
            in_degree[name] = len(dep_set)
            for dep in dep_set:
                dependents[dep].append(name)

        levels: list[list[dict[str, Any]]] = []
        remaining = set(in_degree.keys())

        while remaining:
            # Collect all nodes with in-degree 0 (no unresolved deps).
            ready = sorted(n for n in remaining if in_degree[n] == 0)
            if not ready:
                raise ValueError(f"Circular dependency detected among stages: {sorted(remaining)}")

            level = [stage_by_name[n] for n in ready]
            levels.append(level)

            for n in ready:
                remaining.discard(n)
                for dep in dependents[n]:
                    in_degree[dep] -= 1

        return levels

    # ------------------------------------------------------------------
    # Single-stage execution
    # ------------------------------------------------------------------

    async def _execute_stage(
        self,
        stage: dict[str, Any],
        context: dict[str, Any],
        goal: OrchestratorGoal,
        timeout: float,
        log: Any,
    ) -> tuple[str, dict[str, Any]]:
        """Execute a single pipeline stage: build payload, dispatch, wait.

        Returns ``(stage_name, result_dict)`` on success where result_dict
        has keys ``output``, ``model_used``, ``processing_time_ms``.

        Raises ``PipelineStageError`` on mapping errors, timeouts, or
        worker failures.
        """
        stage_name = stage["name"]
        stage_log = log.bind(stage=stage_name)

        # Check condition (if present) — skipped stages return empty output.
        condition = stage.get("condition")
        if condition and not self._evaluate_condition(condition, context):
            stage_log.info("pipeline.stage_skipped", reason="condition_false")
            return stage_name, {
                "output": None,
                "model_used": None,
                "processing_time_ms": 0,
                "_skipped": True,
            }

        # Build task payload from input_mapping.
        try:
            payload = self._build_stage_payload(stage, context)
        except (KeyError, ValueError) as e:
            raise PipelineStageError(stage_name, f"Stage '{stage_name}' mapping error: {e}") from e

        # Validate payload against stage's input_schema (if declared).
        stage_input_schema = stage.get("input_schema")
        if stage_input_schema:
            errors = validate_input(payload, stage_input_schema)
            if errors:
                raise PipelineStageError(
                    stage_name,
                    f"Stage '{stage_name}' input validation failed: {errors}",
                )

        task = TaskMessage(
            worker_type=stage["worker_type"],
            payload=payload,
            model_tier=ModelTier(stage.get("tier", "local")),
            parent_task_id=goal.goal_id,
            metadata={
                "stage_name": stage_name,
                "model_tier": stage.get("tier", "local"),
            },
        )

        stage_log.info("pipeline.stage_dispatching", worker_type=stage["worker_type"])
        await self.publish("loom.tasks.incoming", task.model_dump(mode="json"))

        # Wait for result.
        stage_timeout = stage.get("timeout_seconds", timeout)
        result = await self._wait_for_result(task.task_id, goal.goal_id, stage_timeout)

        if result is None:
            raise PipelineStageError(
                stage_name,
                f"Stage '{stage_name}' timed out after {stage_timeout}s",
            )

        if result.status == TaskStatus.FAILED:
            raise PipelineStageError(
                stage_name,
                f"Stage '{stage_name}' failed: {result.error}",
            )

        # Validate result against stage's output_schema (if declared).
        stage_output_schema = stage.get("output_schema")
        if stage_output_schema and result.output is not None:
            output_errors = validate_output(result.output, stage_output_schema)
            if output_errors:
                raise PipelineStageError(
                    stage_name,
                    f"Stage '{stage_name}' output validation failed: {output_errors}",
                )

        stage_log.info("pipeline.stage_completed", ms=result.processing_time_ms)
        return stage_name, {
            "output": result.output,
            "model_used": result.model_used,
            "processing_time_ms": result.processing_time_ms,
        }

    # ------------------------------------------------------------------
    # Core message handler
    # ------------------------------------------------------------------

    async def handle_message(self, data: dict[str, Any]) -> None:
        """Execute the pipeline for an incoming orchestrator goal."""
        goal = OrchestratorGoal(**data)
        stages = self.config["pipeline_stages"]
        timeout = self.config.get("timeout_seconds", 300)

        log = logger.bind(goal_id=goal.goal_id, pipeline=self.config["name"])

        # Build execution levels from dependency graph.
        deps = self._infer_dependencies(stages)
        levels = self._build_execution_levels(stages, deps)

        # Log execution plan.
        level_summary = [[s["name"] for s in level] for level in levels]
        log.info(
            "pipeline.started",
            stages=len(stages),
            levels=len(levels),
            execution_plan=level_summary,
        )

        # Accumulated context: goal info + results from each completed stage.
        context: dict[str, Any] = {
            "goal": {
                "instruction": goal.instruction,
                "context": goal.context,
            },
        }

        start = time.monotonic()

        try:
            for level_idx, level in enumerate(levels):
                level_log = log.bind(level=level_idx)

                if len(level) == 1:
                    # Single stage — no gather overhead.
                    stage = level[0]
                    name, result_dict = await self._execute_stage(
                        stage,
                        context,
                        goal,
                        timeout,
                        level_log,
                    )
                    if not result_dict.get("_skipped"):
                        context[name] = result_dict
                else:
                    # Multiple stages — run concurrently.
                    level_log.info(
                        "pipeline.level_parallel",
                        stages=[s["name"] for s in level],
                    )
                    coros = [
                        self._execute_stage(s, context, goal, timeout, level_log) for s in level
                    ]
                    results = await asyncio.gather(
                        *coros,
                        return_exceptions=True,
                    )

                    # Check for failures.
                    for r in results:
                        if isinstance(r, PipelineStageError):
                            raise r
                        if isinstance(r, Exception):
                            raise r

                    # Store all results in context.
                    context.update(
                        {
                            name: result_dict
                            for name, result_dict in results
                            if not result_dict.get("_skipped")
                        }
                    )

        except PipelineStageError as e:
            log.error(
                "pipeline.stage_failed",
                stage=e.stage_name,
                error=str(e),
            )
            elapsed = int((time.monotonic() - start) * 1000)
            await self._publish_pipeline_result(
                goal,
                TaskStatus.FAILED,
                error=str(e),
                elapsed=elapsed,
            )
            return
        except Exception as e:
            log.error(
                "pipeline.unexpected_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            elapsed = int((time.monotonic() - start) * 1000)
            await self._publish_pipeline_result(
                goal,
                TaskStatus.FAILED,
                error=f"Pipeline error ({type(e).__name__}): {e}",
                elapsed=elapsed,
            )
            return

        # All stages complete.
        elapsed = int((time.monotonic() - start) * 1000)
        log.info("pipeline.completed", ms=elapsed, stages_run=len(context) - 1)

        # Build final output from all stage results.
        final_output = {
            name: data["output"]
            for name, data in context.items()
            if name != "goal" and isinstance(data, dict) and "output" in data
        }
        await self._publish_pipeline_result(
            goal,
            TaskStatus.COMPLETED,
            output=final_output,
            elapsed=elapsed,
        )

    # ------------------------------------------------------------------
    # Payload building and path resolution
    # ------------------------------------------------------------------

    def _build_stage_payload(
        self,
        stage: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a stage's task payload by resolving input_mapping against context.

        Mapping values are dot-separated paths into the context dict.

        Examples:
            "goal.context.file_ref" → context["goal"]["context"]["file_ref"]
            "extract.output.page_count" → context["extract"]["output"]["page_count"]
        """
        mapping = stage.get("input_mapping", {})
        payload: dict[str, Any] = {}
        for target_field, source_path in mapping.items():
            payload[target_field] = self._resolve_path(source_path, context)
        return payload

    @staticmethod
    def _resolve_path(path: str, context: dict[str, Any]) -> Any:
        """Resolve a dot-separated path against the context dict."""
        parts = path.split(".")
        current: Any = context
        for part in parts:
            if isinstance(current, dict):
                if part not in current:
                    raise KeyError(f"Path '{path}': key '{part}' not found in context")
                current = current[part]
            else:
                raise ValueError(
                    f"Path '{path}': cannot traverse into {type(current).__name__} at '{part}'"
                )
        return current

    @staticmethod
    def _evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
        """Evaluate a simple condition string against context.

        Supports: "path.to.value == true", "path.to.value == false",
                  "path.to.value != null"

        Note: This is a minimal condition evaluator supporting == and != against
        bool, null, and string literals. If more complex conditions are needed
        (AND/OR, numeric comparisons, regex), consider a safe expression evaluator.
        """
        parts = condition.split()
        if len(parts) != 3:
            logger.warning("pipeline.invalid_condition", condition=condition)
            return True  # Default to running the stage

        path, op, expected = parts
        try:
            value = PipelineOrchestrator._resolve_path(path, context)
        except (KeyError, ValueError):
            return False

        # Normalize expected value
        expected_lower = expected.lower()
        if expected_lower == "true":
            expected_val = True
        elif expected_lower == "false":
            expected_val = False
        elif expected_lower in {"null", "none"}:
            expected_val = None
        else:
            expected_val = expected

        if op == "==":
            return value == expected_val
        if op == "!=":
            return value != expected_val
        logger.warning("pipeline.unsupported_operator", op=op)
        return True

    # ------------------------------------------------------------------
    # Result waiting and publishing
    # ------------------------------------------------------------------

    async def _wait_for_result(
        self,
        task_id: str,
        goal_id: str,
        timeout: float,
    ) -> TaskResult | None:
        """
        Wait for a specific TaskResult by subscribing to the results subject.

        Subscribes to loom.results.{goal_id}, filters by task_id,
        and returns the matching result (or None on timeout).
        """
        result_future: asyncio.Future[TaskResult] = asyncio.get_running_loop().create_future()
        subject = f"loom.results.{goal_id}"

        sub = await self._bus.subscribe(subject)

        async def _consume() -> None:
            async for data in sub:
                if data.get("task_id") == task_id:
                    with contextlib.suppress(asyncio.InvalidStateError):
                        result_future.set_result(TaskResult(**data))
                    break

        consume_task = asyncio.create_task(_consume())

        try:
            return await asyncio.wait_for(result_future, timeout=timeout)
        except TimeoutError:
            return None
        finally:
            consume_task.cancel()
            await sub.unsubscribe()

    async def _publish_pipeline_result(
        self,
        goal: OrchestratorGoal,
        status: TaskStatus,
        output: dict | None = None,
        error: str | None = None,
        elapsed: int = 0,
    ) -> None:
        """Publish the final pipeline result back to the goal's result subject."""
        result = TaskResult(
            task_id=goal.goal_id,
            parent_task_id=None,
            worker_type=self.config["name"],
            status=status,
            output=output,
            error=error,
            model_used=None,
            token_usage={},
            processing_time_ms=elapsed,
        )
        subject = f"loom.results.{goal.goal_id}"
        await self.publish(subject, result.model_dump(mode="json"))
