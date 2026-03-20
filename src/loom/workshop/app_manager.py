"""
AppManager — deploy, list, and remove Loom app bundles.

An app bundle is a ZIP archive containing a ``manifest.yaml`` and a set of
config files (workers, pipelines, schedulers, MCP configs) plus optional
scripts.  Apps are extracted to ``~/.loom/apps/{app_name}/`` and their
configs become visible in the Workshop alongside the base configs.

After deployment, a reload message is published to ``loom.control.reload``
so running actors pick up new or changed configs without restart.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from loom.core.manifest import AppManifest, load_manifest, validate_app_manifest

if TYPE_CHECKING:
    from loom.bus.base import MessageBus

logger = structlog.get_logger()

DEFAULT_APPS_DIR = "~/.loom/apps"


class AppDeployError(Exception):
    """Raised when app deployment fails."""


class AppManager:
    """Manages deployed Loom app bundles.

    Args:
        apps_dir: Root directory for deployed apps (``~`` is expanded).
        bus: Optional message bus for publishing reload notifications.
    """

    def __init__(
        self,
        apps_dir: str = DEFAULT_APPS_DIR,
        bus: MessageBus | None = None,
    ) -> None:
        self.apps_dir = Path(apps_dir).expanduser()
        self.apps_dir.mkdir(parents=True, exist_ok=True)
        self._bus = bus

    def list_apps(self) -> list[AppManifest]:
        """List all deployed apps by reading their manifests."""
        apps: list[AppManifest] = []
        if not self.apps_dir.exists():
            return apps
        for app_dir in sorted(self.apps_dir.iterdir()):
            manifest_path = app_dir / "manifest.yaml"
            if app_dir.is_dir() and manifest_path.exists():
                try:
                    apps.append(load_manifest(manifest_path))
                except Exception as e:
                    logger.warning(
                        "app_manager.manifest_load_failed",
                        app_dir=str(app_dir),
                        error=str(e),
                    )
        return apps

    def get_app(self, app_name: str) -> AppManifest:
        """Load a deployed app's manifest.

        Raises:
            FileNotFoundError: If the app is not deployed.
        """
        manifest_path = self.apps_dir / app_name / "manifest.yaml"
        return load_manifest(manifest_path)

    def get_app_configs_dir(self, app_name: str) -> Path:
        """Return the configs directory for a deployed app."""
        return self.apps_dir / app_name / "configs"

    def deploy_app(self, zip_path: Path) -> AppManifest:
        """Deploy an app from a ZIP archive.

        Steps:
        1. Validate the ZIP structure (must contain manifest.yaml)
        2. Parse and validate the manifest
        3. Extract to ``apps_dir / app_name /``
        4. Return the parsed manifest

        Args:
            zip_path: Path to the ZIP file.

        Returns:
            The parsed AppManifest.

        Raises:
            AppDeployError: If the ZIP is invalid or deployment fails.
        """
        if not zip_path.exists():
            msg = f"ZIP file not found: {zip_path}"
            raise AppDeployError(msg)

        if not zipfile.is_zipfile(zip_path):
            msg = f"Not a valid ZIP file: {zip_path}"
            raise AppDeployError(msg)

        with zipfile.ZipFile(zip_path, "r") as zf:
            # Check for manifest.yaml at root
            names = zf.namelist()
            if "manifest.yaml" not in names:
                msg = "ZIP must contain manifest.yaml at the root"
                raise AppDeployError(msg)

            # Read and validate manifest before extracting
            import yaml

            manifest_data = yaml.safe_load(zf.read("manifest.yaml"))
            if not isinstance(manifest_data, dict):
                msg = "manifest.yaml must be a YAML mapping"
                raise AppDeployError(msg)

            errors = validate_app_manifest(manifest_data)
            if errors:
                msg = f"Invalid manifest: {'; '.join(errors)}"
                raise AppDeployError(msg)

            manifest = AppManifest(**manifest_data)

            # Security: reject paths that escape the extraction directory
            for name in names:
                if name.startswith("/") or ".." in name:
                    msg = f"ZIP contains unsafe path: {name}"
                    raise AppDeployError(msg)

            # Verify referenced config files exist in the ZIP
            for ref_list in [
                manifest.entry_configs.workers,
                manifest.entry_configs.pipelines,
                manifest.entry_configs.schedulers,
                manifest.entry_configs.mcp,
            ]:
                for ref in ref_list:
                    if ref.config not in names:
                        msg = f"Manifest references missing file: {ref.config}"
                        raise AppDeployError(msg)

            # Extract to app directory
            app_dir = self.apps_dir / manifest.name
            if app_dir.exists():
                shutil.rmtree(app_dir)
            app_dir.mkdir(parents=True)
            zf.extractall(app_dir)

        # Warn about Python packages that need manual install
        if manifest.python_package:
            pkg = manifest.python_package
            install_dir = app_dir / pkg.install_path
            logger.warning(
                "app_manager.python_package_detected",
                app=manifest.name,
                package=pkg.name,
                hint=(
                    f"This app includes Python package '{pkg.name}'. "
                    f"Install it manually: pip install -e {install_dir}"
                ),
            )

        logger.info(
            "app_manager.deployed",
            app=manifest.name,
            version=manifest.version,
            app_dir=str(app_dir),
        )

        return manifest

    def remove_app(self, app_name: str) -> None:
        """Remove a deployed app.

        Raises:
            FileNotFoundError: If the app is not deployed.
        """
        app_dir = self.apps_dir / app_name
        if not app_dir.exists():
            raise FileNotFoundError(f"App not found: {app_name}")
        shutil.rmtree(app_dir)
        logger.info("app_manager.removed", app=app_name)

    async def notify_reload(self) -> None:
        """Publish a reload control message to notify running actors.

        This is a best-effort notification — if no NATS bus is connected
        or no actors are running, the message is silently dropped.
        """
        if self._bus is None:
            logger.info("app_manager.reload_skipped", reason="no bus configured")
            return
        try:
            await self._bus.publish("loom.control.reload", {"action": "reload"})
            logger.info("app_manager.reload_published")
        except Exception as e:
            logger.warning("app_manager.reload_failed", error=str(e))
