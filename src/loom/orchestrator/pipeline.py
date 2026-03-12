"""
Pipeline orchestrator for multi-stage sequential processing.

Executes a defined sequence of stages, passing results from each stage
as input to the next. Each stage maps to a worker_type. Stages can be
LLM workers, processor workers, or any other actor — the pipeline
doesn't care about the implementation, only the message contract.

Pipeline definition comes from YAML config with stages, input mappings,
and optional conditions.

Data flow through the pipeline:

    OrchestratorGoal arrives at handle_message()
        ↓
    context = { "goal": { "instruction": ..., "context": { ... } } }
        ↓
    For each stage in pipeline_stages:
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

See also:
    loom.orchestrator.runner — dynamic LLM-based orchestrator (not yet implemented)
    loom.core.messages.OrchestratorGoal — the input message type
    configs/orchestrators/ — pipeline config YAML files
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import structlog
import yaml

from loom.core.actor import BaseActor
from loom.core.messages import (
    ModelTier,
    OrchestratorGoal,
    TaskMessage,
    TaskResult,
    TaskStatus,
)

logger = structlog.get_logger()


class PipelineOrchestrator(BaseActor):
    """
    Sequential pipeline orchestrator.

    Processes an OrchestratorGoal by running it through a series of stages.
    Each stage dispatches a task to a worker and waits for the result before
    proceeding to the next stage. Stage outputs are accumulated in a context
    dict and can be referenced by subsequent stages via input_mapping.
    """

    def __init__(
        self,
        actor_id: str,
        config_path: str,
        nats_url: str = "nats://nats:4222",
    ):
        super().__init__(actor_id, nats_url)
        self.config = self._load_config(config_path)

    def _load_config(self, path: str) -> dict:
        with open(path) as f:
            return yaml.safe_load(f)

    async def handle_message(self, data: dict[str, Any]) -> None:
        goal = OrchestratorGoal(**data)
        stages = self.config["pipeline_stages"]
        timeout = self.config.get("timeout_seconds", 300)

        log = logger.bind(goal_id=goal.goal_id, pipeline=self.config["name"])
        log.info("pipeline.started", stages=len(stages))

        # Accumulated context: goal info + results from each completed stage.
        # Each completed stage adds: context[stage_name] = {"output": ..., "model_used": ..., ...}
        # Subsequent stages reference these via dot-notation in their input_mapping.
        context: dict[str, Any] = {
            "goal": {
                "instruction": goal.instruction,
                "context": goal.context,
            },
        }

        start = time.monotonic()

        for i, stage in enumerate(stages):
            stage_name = stage["name"]
            stage_log = log.bind(stage=stage_name, stage_index=i)

            # Check condition (if present)
            condition = stage.get("condition")
            if condition and not self._evaluate_condition(condition, context):
                stage_log.info("pipeline.stage_skipped", reason="condition_false")
                continue

            # Build task payload from input_mapping
            try:
                payload = self._build_stage_payload(stage, context)
            except (KeyError, ValueError) as e:
                stage_log.error("pipeline.mapping_error", error=str(e))
                await self._publish_pipeline_result(
                    goal, TaskStatus.FAILED,
                    error=f"Stage '{stage_name}' mapping error: {e}",
                )
                return

            # Create and dispatch task.
            # Tasks are sent to loom.tasks.incoming (the router's subject),
            # which resolves the tier and forwards to loom.tasks.{worker_type}.{tier}.
            task = TaskMessage(
                worker_type=stage["worker_type"],
                payload=payload,
                model_tier=ModelTier(stage.get("tier", "local")),
                parent_task_id=goal.goal_id,
                metadata={
                    "pipeline_stage": i,
                    "stage_name": stage_name,
                    "model_tier": stage.get("tier", "local"),
                },
            )

            stage_log.info("pipeline.stage_dispatching", worker_type=stage["worker_type"])
            await self.publish("loom.tasks.incoming", task.model_dump(mode="json"))

            # Wait for result
            stage_timeout = stage.get("timeout_seconds", timeout)
            result = await self._wait_for_result(task.task_id, goal.goal_id, stage_timeout)

            if result is None:
                stage_log.error("pipeline.stage_timeout")
                await self._publish_pipeline_result(
                    goal, TaskStatus.FAILED,
                    error=f"Stage '{stage_name}' timed out after {stage_timeout}s",
                )
                return

            if result.status == TaskStatus.FAILED:
                stage_log.error("pipeline.stage_failed", error=result.error)
                await self._publish_pipeline_result(
                    goal, TaskStatus.FAILED,
                    error=f"Stage '{stage_name}' failed: {result.error}",
                )
                return

            # Store result in context for subsequent stages
            context[stage_name] = {
                "output": result.output,
                "model_used": result.model_used,
                "processing_time_ms": result.processing_time_ms,
            }
            stage_log.info("pipeline.stage_completed", ms=result.processing_time_ms)

        # All stages complete
        elapsed = int((time.monotonic() - start) * 1000)
        log.info("pipeline.completed", ms=elapsed, stages_run=len(context) - 1)

        # Build final output from all stage results
        final_output = {
            name: data["output"]
            for name, data in context.items()
            if name != "goal" and isinstance(data, dict) and "output" in data
        }
        await self._publish_pipeline_result(
            goal, TaskStatus.COMPLETED,
            output=final_output,
            elapsed=elapsed,
        )

    def _build_stage_payload(
        self, stage: dict[str, Any], context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build a stage's task payload by resolving input_mapping against context.

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
                raise ValueError(f"Path '{path}': cannot traverse into {type(current).__name__} at '{part}'")
        return current

    @staticmethod
    def _evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
        """
        Evaluate a simple condition string against context.

        Supports: "path.to.value == true", "path.to.value == false",
                  "path.to.value != null"

        TODO: This is a minimal condition evaluator. If more complex conditions
              are needed (AND/OR, numeric comparisons, regex), consider using
              a safe expression evaluator rather than extending this ad-hoc parser.
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
        elif expected_lower == "null" or expected_lower == "none":
            expected_val = None
        else:
            expected_val = expected

        if op == "==":
            return value == expected_val
        elif op == "!=":
            return value != expected_val
        else:
            logger.warning("pipeline.unsupported_operator", op=op)
            return True

    async def _wait_for_result(
        self, task_id: str, goal_id: str, timeout: float,
    ) -> TaskResult | None:
        """
        Wait for a specific TaskResult by subscribing to the results subject.

        Subscribes to loom.results.{goal_id}, filters by task_id,
        and returns the matching result (or None on timeout).
        """
        # FIXME: asyncio.get_event_loop() is deprecated in Python 3.10+.
        # Use asyncio.get_running_loop() instead to avoid DeprecationWarning.
        result_future: asyncio.Future[TaskResult] = asyncio.get_event_loop().create_future()
        subject = f"loom.results.{goal_id}"

        async def _handler(msg):
            data = json.loads(msg.data.decode())
            if data.get("task_id") == task_id:
                try:
                    result_future.set_result(TaskResult(**data))
                except asyncio.InvalidStateError:
                    pass  # Already resolved

        # NOTE: This subscribes directly to NATS (bypassing NATSBus) because
        # we need the raw nats.aio.msg.Msg for fine-grained subscription control.
        # NATSBus.subscribe() auto-decodes JSON, but here we need to filter by
        # task_id before resolving the future.
        sub = await self._nc.subscribe(subject, cb=_handler)

        try:
            return await asyncio.wait_for(result_future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
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
