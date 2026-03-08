"""
Worker actor. Processes a single task and resets.
No state carries between tasks — this is enforced, not optional.
"""
from __future__ import annotations

import json
import time
from typing import Any

import structlog
import yaml

from loom.core.actor import BaseActor
from loom.core.contracts import validate_input, validate_output
from loom.core.messages import TaskMessage, TaskResult, TaskStatus
from loom.worker.backends import LLMBackend

logger = structlog.get_logger()


class WorkerActor(BaseActor):
    """
    Stateless worker actor.

    Lifecycle per message:
    1. Receive TaskMessage
    2. Validate input against worker contract
    3. Build prompt from system_prompt + knowledge + payload
    4. Call LLM backend
    5. Validate output against worker contract
    6. Publish TaskResult
    7. Reset (no state retained)
    """

    def __init__(
        self,
        actor_id: str,
        config_path: str,
        backends: dict[str, LLMBackend],
        nats_url: str = "nats://nats:4222",
    ):
        super().__init__(actor_id, nats_url)
        self.backends = backends
        self.config = self._load_config(config_path)

    def _load_config(self, path: str) -> dict:
        with open(path) as f:
            return yaml.safe_load(f)

    async def handle_message(self, data: dict[str, Any]) -> None:
        task = TaskMessage(**data)
        start = time.monotonic()

        log = logger.bind(
            task_id=task.task_id,
            worker_type=task.worker_type,
            model_tier=task.model_tier.value,
        )

        try:
            # 1. Validate input
            errors = validate_input(task.payload, self.config.get("input_schema", {}))
            if errors:
                await self._publish_result(task, TaskStatus.FAILED, error=f"Input validation: {errors}")
                return

            # 2. Build prompt
            system_prompt = self.config["system_prompt"]
            user_message = json.dumps(task.payload, indent=2)

            # 3. Call LLM
            backend = self.backends.get(task.model_tier.value)
            if not backend:
                await self._publish_result(task, TaskStatus.FAILED, error=f"No backend for tier: {task.model_tier}")
                return

            log.info("worker.calling_llm")
            result = await backend.complete(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=self.config.get("max_output_tokens", 2000),
            )

            # 4. Parse and validate output
            try:
                output = json.loads(result["content"])
            except json.JSONDecodeError:
                await self._publish_result(
                    task, TaskStatus.FAILED,
                    error=f"LLM returned non-JSON: {result['content'][:200]}",
                    model_used=result["model"],
                    tokens=result,
                )
                return

            output_errors = validate_output(output, self.config.get("output_schema", {}))
            if output_errors:
                await self._publish_result(
                    task, TaskStatus.FAILED,
                    error=f"Output validation: {output_errors}",
                    model_used=result["model"],
                    tokens=result,
                )
                return

            # 5. Publish success
            elapsed = int((time.monotonic() - start) * 1000)
            await self._publish_result(
                task, TaskStatus.COMPLETED,
                output=output,
                model_used=result["model"],
                tokens=result,
                elapsed=elapsed,
            )
            log.info("worker.completed", ms=elapsed)

        except Exception as e:
            log.error("worker.exception", error=str(e))
            await self._publish_result(task, TaskStatus.FAILED, error=str(e))

        # 6. Reset — worker holds NO state from this task
        # (In this design, reset is implicit: no instance variables are modified during processing)

    async def _publish_result(
        self,
        task: TaskMessage,
        status: TaskStatus,
        output: dict | None = None,
        error: str | None = None,
        model_used: str | None = None,
        tokens: dict | None = None,
        elapsed: int = 0,
    ) -> None:
        result = TaskResult(
            task_id=task.task_id,
            parent_task_id=task.parent_task_id,
            worker_type=task.worker_type,
            status=status,
            output=output,
            error=error,
            model_used=model_used,
            token_usage={
                "prompt_tokens": tokens.get("prompt_tokens", 0) if tokens else 0,
                "completion_tokens": tokens.get("completion_tokens", 0) if tokens else 0,
            },
            processing_time_ms=elapsed,
        )
        subject = f"loom.results.{task.parent_task_id or 'default'}"
        await self.publish(subject, result.model_dump(mode="json"))
