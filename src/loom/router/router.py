"""
Deterministic task router. NOT an LLM — pure logic.

Reads router_rules.yaml and routes tasks to appropriate
NATS subjects based on worker_type and model_tier.
"""
from __future__ import annotations

from typing import Any

import structlog
import yaml

from loom.bus.nats_adapter import NATSBus
from loom.core.messages import ModelTier, TaskMessage

logger = structlog.get_logger()


class TaskRouter:
    """
    Routes TaskMessages to worker queues based on rules.

    Subscribes to: loom.tasks.incoming
    Publishes to:  loom.tasks.{worker_type}.{tier}
    """

    def __init__(self, config_path: str, bus: NATSBus):
        self.bus = bus
        self.rules = self._load_rules(config_path)

    def _load_rules(self, path: str) -> dict:
        with open(path) as f:
            return yaml.safe_load(f)

    def resolve_tier(self, task: TaskMessage) -> ModelTier:
        """
        Determine model tier for a task.

        Priority:
        1. Explicit tier in the TaskMessage
        2. Worker-specific override in router_rules.yaml
        3. Default from worker config
        """
        # Check for worker-specific overrides
        overrides = self.rules.get("tier_overrides", {})
        if task.worker_type in overrides:
            return ModelTier(overrides[task.worker_type])
        return task.model_tier

    async def route(self, data: dict[str, Any]) -> None:
        task = TaskMessage(**data)
        tier = self.resolve_tier(task)
        subject = f"loom.tasks.{task.worker_type}.{tier.value}"

        logger.info(
            "router.routing",
            task_id=task.task_id,
            worker_type=task.worker_type,
            tier=tier.value,
            subject=subject,
        )
        await self.bus.publish(subject, task.model_dump(mode="json"))

    async def run(self) -> None:
        await self.bus.connect()
        await self.bus.subscribe("loom.tasks.incoming", self.route)
        logger.info("router.running")
