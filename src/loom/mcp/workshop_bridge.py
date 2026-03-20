"""
Workshop MCP bridge — execute Workshop tool calls directly (no NATS).

Unlike the main MCPBridge which dispatches through NATS, WorkshopBridge
calls Workshop components (ConfigManager, WorkerTestRunner, EvalRunner,
DeadLetterConsumer) in-process.  This means Workshop MCP tools work
without a running NATS server, just like the Workshop web UI.
"""

from __future__ import annotations

import contextlib
import dataclasses
from typing import TYPE_CHECKING, Any

import structlog
import yaml

if TYPE_CHECKING:
    from loom.router.dead_letter import DeadLetterConsumer
    from loom.workshop.config_manager import ConfigManager
    from loom.workshop.db import WorkshopDB
    from loom.workshop.eval_runner import EvalRunner
    from loom.workshop.test_runner import WorkerTestRunner

logger = structlog.get_logger()


class WorkshopBridgeError(Exception):
    """Raised when a workshop tool call fails."""


class WorkshopBridge:
    """Bridge MCP tool calls to Workshop components.

    All components are optional — only tools whose backing component is
    provided will be functional.  Missing components return an error.
    """

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        test_runner: WorkerTestRunner | None = None,
        eval_runner: EvalRunner | None = None,
        db: WorkshopDB | None = None,
        dead_letter: DeadLetterConsumer | None = None,
        replay_bus: Any | None = None,
    ) -> None:
        self.config_manager = config_manager
        self.test_runner = test_runner
        self.eval_runner = eval_runner
        self.db = db
        self.dead_letter = dead_letter
        self.replay_bus = replay_bus

    async def dispatch(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch a workshop tool call by action name.

        Args:
            action: Dotted action name (e.g. ``"worker.list"``).
            arguments: Tool arguments from MCP client.

        Returns:
            Result dict (JSON-serializable).

        Raises:
            WorkshopBridgeError: On missing components or invalid arguments.
        """
        handler = _HANDLERS.get(action)
        if handler is None:
            raise WorkshopBridgeError(f"Unknown workshop action: {action}")
        return await handler(self, arguments)

    # ------------------------------------------------------------------
    # Worker config handlers
    # ------------------------------------------------------------------

    async def _worker_list(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        if self.config_manager is None:
            raise WorkshopBridgeError("ConfigManager not configured")
        workers = self.config_manager.list_workers()
        return {"workers": workers, "count": len(workers)}

    async def _worker_get(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.config_manager is None:
            raise WorkshopBridgeError("ConfigManager not configured")

        name = arguments.get("name")
        if not name:
            raise WorkshopBridgeError("'name' is required")

        try:
            config = self.config_manager.get_worker(name)
        except FileNotFoundError as exc:
            raise WorkshopBridgeError(f"Worker '{name}' not found") from exc

        result: dict[str, Any] = {"name": name, "config": config}

        with contextlib.suppress(FileNotFoundError):
            result["yaml"] = self.config_manager.get_worker_yaml(name)

        if self.db:
            result["version_history"] = self.config_manager.get_worker_version_history(name)

        return result

    async def _worker_update(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.config_manager is None:
            raise WorkshopBridgeError("ConfigManager not configured")

        name = arguments.get("name")
        config_yaml = arguments.get("config_yaml")
        if not name or not config_yaml:
            raise WorkshopBridgeError("'name' and 'config_yaml' are required")

        try:
            config = yaml.safe_load(config_yaml)
        except yaml.YAMLError as exc:
            raise WorkshopBridgeError(f"Invalid YAML: {exc}") from exc

        if not isinstance(config, dict):
            raise WorkshopBridgeError("Config must be a YAML mapping")

        description = arguments.get("description")
        errors = self.config_manager.save_worker(name, config, description=description)

        if errors:
            return {"success": False, "validation_errors": errors}

        return {"success": True, "name": name}

    # ------------------------------------------------------------------
    # Test bench handler
    # ------------------------------------------------------------------

    async def _worker_test(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.config_manager is None:
            raise WorkshopBridgeError("ConfigManager not configured")
        if self.test_runner is None:
            raise WorkshopBridgeError("WorkerTestRunner not configured (no LLM backends)")

        name = arguments.get("name")
        payload = arguments.get("payload")
        if not name or payload is None:
            raise WorkshopBridgeError("'name' and 'payload' are required")

        try:
            config = self.config_manager.get_worker(name)
        except FileNotFoundError as exc:
            raise WorkshopBridgeError(f"Worker '{name}' not found") from exc

        tier = arguments.get("tier")
        result = await self.test_runner.run(config, payload, tier=tier)

        return dataclasses.asdict(result)

    # ------------------------------------------------------------------
    # Eval handlers
    # ------------------------------------------------------------------

    async def _eval_run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.config_manager is None:
            raise WorkshopBridgeError("ConfigManager not configured")
        if self.eval_runner is None:
            raise WorkshopBridgeError("EvalRunner not configured")

        name = arguments.get("name")
        test_suite = arguments.get("test_suite")
        if not name or not test_suite:
            raise WorkshopBridgeError("'name' and 'test_suite' are required")

        try:
            config = self.config_manager.get_worker(name)
        except FileNotFoundError as exc:
            raise WorkshopBridgeError(f"Worker '{name}' not found") from exc

        scoring = arguments.get("scoring", "field_match")
        tier = arguments.get("tier")

        run_id = await self.eval_runner.run_suite(
            config=config,
            test_suite=test_suite,
            tier=tier,
            scoring=scoring,
        )

        # Fetch summary from DB
        if self.db:
            results = self.db.get_eval_results(run_id)
            scores = [r.get("score", 0) for r in results if r.get("score") is not None]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            return {
                "run_id": run_id,
                "worker": name,
                "cases": len(test_suite),
                "avg_score": round(avg_score, 3),
                "scoring": scoring,
            }

        return {"run_id": run_id, "worker": name, "cases": len(test_suite)}

    async def _eval_compare(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.db is None:
            raise WorkshopBridgeError("WorkshopDB not configured")

        name = arguments.get("name")
        run_id = arguments.get("run_id")
        if not name or not run_id:
            raise WorkshopBridgeError("'name' and 'run_id' are required")

        comparison = self.db.compare_against_baseline(name, run_id)
        if comparison is None:
            return {"error": f"No baseline set for worker '{name}'"}

        return comparison

    # ------------------------------------------------------------------
    # Impact analysis handler
    # ------------------------------------------------------------------

    async def _impact_analyze(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.config_manager is None:
            raise WorkshopBridgeError("ConfigManager not configured")

        name = arguments.get("name")
        if not name:
            raise WorkshopBridgeError("'name' is required")

        from loom.workshop.config_impact import get_impact

        return get_impact(name, self.config_manager)

    # ------------------------------------------------------------------
    # Dead-letter handlers
    # ------------------------------------------------------------------

    async def _deadletter_list(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.dead_letter is None:
            raise WorkshopBridgeError("DeadLetterConsumer not configured")

        limit = arguments.get("limit", 50)
        offset = arguments.get("offset", 0)
        entries = self.dead_letter.list_entries(limit=limit, offset=offset)
        return {
            "entries": entries,
            "count": len(entries),
            "total": self.dead_letter.count(),
        }

    async def _deadletter_replay(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.dead_letter is None:
            raise WorkshopBridgeError("DeadLetterConsumer not configured")

        entry_id = arguments.get("entry_id")
        if not entry_id:
            raise WorkshopBridgeError("'entry_id' is required")

        if self.replay_bus is None:
            raise WorkshopBridgeError("Dead-letter replay requires a connected message bus")

        success = await self.dead_letter.replay(entry_id, self.replay_bus)
        return {"success": success, "entry_id": entry_id}


# Handler dispatch table
_HANDLERS: dict[str, Any] = {
    "worker.list": WorkshopBridge._worker_list,
    "worker.get": WorkshopBridge._worker_get,
    "worker.update": WorkshopBridge._worker_update,
    "worker.test": WorkshopBridge._worker_test,
    "eval.run": WorkshopBridge._eval_run,
    "eval.compare": WorkshopBridge._eval_compare,
    "impact.analyze": WorkshopBridge._impact_analyze,
    "deadletter.list": WorkshopBridge._deadletter_list,
    "deadletter.replay": WorkshopBridge._deadletter_replay,
}
