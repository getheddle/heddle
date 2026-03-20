"""
ConfigManager — CRUD for worker and pipeline YAML configs.

Manages the filesystem-based worker and pipeline configs, with optional
version tracking via WorkshopDB.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import yaml

from loom.core.config import load_config, validate_pipeline_config, validate_worker_config

if TYPE_CHECKING:
    from loom.workshop.db import WorkshopDB

logger = structlog.get_logger()


class ConfigManager:
    """CRUD operations for worker and pipeline YAML configs.

    Args:
        configs_dir: Root directory containing ``workers/`` and ``orchestrators/``.
        db: Optional WorkshopDB for version tracking.
    """

    def __init__(
        self,
        configs_dir: str = "configs/",
        db: WorkshopDB | None = None,
        extra_config_dirs: list[Path] | None = None,
    ) -> None:
        self.configs_dir = Path(configs_dir)
        self.db = db
        self.extra_config_dirs: list[Path] = extra_config_dirs or []

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    def list_workers(self) -> list[dict[str, Any]]:
        """List all worker configs (excluding _template.yaml).

        Scans the main ``configs_dir/workers/`` and all extra config dirs
        from deployed apps. Each result includes an ``app_name`` field
        (empty string for base configs, app name for deployed apps).
        """
        results = []
        # Scan main configs dir
        results.extend(self._scan_workers_dir(self.configs_dir / "workers"))
        # Scan deployed app config dirs
        for extra_dir in self.extra_config_dirs:
            app_name = extra_dir.parent.name if extra_dir.name == "configs" else extra_dir.name
            results.extend(self._scan_workers_dir(extra_dir / "workers", app_name=app_name))
        return results

    def _scan_workers_dir(self, workers_dir: Path, app_name: str = "") -> list[dict[str, Any]]:
        """Scan a workers directory for YAML configs."""
        if not workers_dir.exists():
            return []
        results = []
        for path in sorted(workers_dir.glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            try:
                cfg = load_config(str(path))
                results.append(
                    {
                        "name": cfg.get("name", path.stem),
                        "description": cfg.get("description", ""),
                        "path": str(path),
                        "default_model_tier": cfg.get("default_model_tier", ""),
                        "worker_kind": cfg.get("worker_kind", "llm"),
                        "app_name": app_name,
                    }
                )
            except Exception as e:
                logger.warning("config.load_failed", path=str(path), error=str(e))
        return results

    def get_worker(self, name: str) -> dict[str, Any]:
        """Load a worker config by name.

        Raises FileNotFoundError if the config doesn't exist.
        """
        path = self.configs_dir / "workers" / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Worker config not found: {path}")
        return load_config(str(path))

    def get_worker_yaml(self, name: str) -> str:
        """Get raw YAML content for a worker config."""
        path = self.configs_dir / "workers" / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Worker config not found: {path}")
        return path.read_text()

    def save_worker(
        self,
        name: str,
        config: dict[str, Any],
        description: str | None = None,
    ) -> list[str]:
        """Validate and save a worker config.

        Returns list of validation errors (empty = success).
        Also saves a version to DB if available.
        """
        errors = validate_worker_config(config)
        if errors:
            return errors

        workers_dir = self.configs_dir / "workers"
        workers_dir.mkdir(parents=True, exist_ok=True)

        config_yaml = yaml.dump(config, default_flow_style=False, sort_keys=False)
        path = workers_dir / f"{name}.yaml"
        path.write_text(config_yaml)

        if self.db:
            self.db.save_worker_version(name, config_yaml, description)

        logger.info("config.worker_saved", name=name, path=str(path))
        return []

    def clone_worker(self, source_name: str, new_name: str) -> list[str]:
        """Clone a worker config with a new name."""
        config = self.get_worker(source_name)
        config["name"] = new_name
        return self.save_worker(new_name, config, description=f"Cloned from {source_name}")

    def delete_worker(self, name: str) -> None:
        """Delete a worker config file."""
        path = self.configs_dir / "workers" / f"{name}.yaml"
        if path.exists():
            path.unlink()
            logger.info("config.worker_deleted", name=name)
        else:
            raise FileNotFoundError(f"Worker config not found: {path}")

    def get_worker_version_history(self, name: str) -> list[dict[str, Any]]:
        """Get version history from DB (empty if no DB)."""
        if self.db:
            return self.db.get_worker_versions(name)
        return []

    # ------------------------------------------------------------------
    # Pipelines
    # ------------------------------------------------------------------

    def list_pipelines(self) -> list[dict[str, Any]]:
        """List all pipeline configs.

        Scans the main ``configs_dir/orchestrators/`` and all extra config dirs
        from deployed apps.
        """
        results = []
        results.extend(self._scan_pipelines_dir(self.configs_dir / "orchestrators"))
        for extra_dir in self.extra_config_dirs:
            app_name = extra_dir.parent.name if extra_dir.name == "configs" else extra_dir.name
            results.extend(self._scan_pipelines_dir(extra_dir / "orchestrators", app_name=app_name))
        return results

    def _scan_pipelines_dir(self, orch_dir: Path, app_name: str = "") -> list[dict[str, Any]]:
        """Scan an orchestrators directory for pipeline configs."""
        if not orch_dir.exists():
            return []
        results = []
        for path in sorted(orch_dir.glob("*.yaml")):
            try:
                cfg = load_config(str(path))
                stage_count = len(cfg.get("pipeline_stages", []))
                results.append(
                    {
                        "name": cfg.get("name", path.stem),
                        "path": str(path),
                        "stage_count": stage_count,
                        "has_pipeline_stages": stage_count > 0,
                        "app_name": app_name,
                    }
                )
            except Exception as e:
                logger.warning("config.load_failed", path=str(path), error=str(e))
        return results

    def get_pipeline(self, name: str) -> dict[str, Any]:
        """Load a pipeline config by name."""
        path = self.configs_dir / "orchestrators" / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Pipeline config not found: {path}")
        return load_config(str(path))

    def save_pipeline(self, name: str, config: dict[str, Any]) -> list[str]:
        """Validate and save a pipeline config.

        Returns list of validation errors (empty = success).
        """
        errors = validate_pipeline_config(config)
        if errors:
            return errors

        orch_dir = self.configs_dir / "orchestrators"
        orch_dir.mkdir(parents=True, exist_ok=True)

        config_yaml = yaml.dump(config, default_flow_style=False, sort_keys=False)
        path = orch_dir / f"{name}.yaml"
        path.write_text(config_yaml)

        logger.info("config.pipeline_saved", name=name, path=str(path))
        return []
