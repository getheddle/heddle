"""Tests for loom.workshop.app_manager — ZIP deployment, list, remove."""

import zipfile
from pathlib import Path

import pytest
import yaml

from loom.workshop.app_manager import AppDeployError, AppManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_MANIFEST = {
    "name": "test-app",
    "version": "1.0.0",
    "description": "A test application",
    "loom_version": ">=0.4.0",
    "entry_configs": {
        "workers": [
            {"config": "configs/workers/my_worker.yaml"},
        ],
    },
}

WORKER_CONFIG = {
    "name": "my_worker",
    "system_prompt": "You are a test worker.",
    "input_schema": {"text": "string"},
    "output_schema": {"result": "string"},
}


def _make_app_zip(
    tmp_path: Path, manifest: dict | None = None, include_config: bool = True,
) -> Path:
    """Create a test ZIP archive with manifest and optional config files."""
    zip_path = tmp_path / "test-app.zip"
    manifest = manifest or VALID_MANIFEST

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.yaml", yaml.dump(manifest))
        if include_config:
            zf.writestr(
                "configs/workers/my_worker.yaml",
                yaml.dump(WORKER_CONFIG),
            )
    return zip_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAppManager:
    def test_list_apps_empty(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path))
        assert mgr.list_apps() == []

    def test_deploy_and_list(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))
        zip_path = _make_app_zip(tmp_path)

        manifest = mgr.deploy_app(zip_path)
        assert manifest.name == "test-app"
        assert manifest.version == "1.0.0"

        apps = mgr.list_apps()
        assert len(apps) == 1
        assert apps[0].name == "test-app"

    def test_deploy_extracts_files(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))
        zip_path = _make_app_zip(tmp_path)
        mgr.deploy_app(zip_path)

        app_dir = tmp_path / "apps" / "test-app"
        assert (app_dir / "manifest.yaml").exists()
        assert (app_dir / "configs" / "workers" / "my_worker.yaml").exists()

    def test_get_app(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))
        zip_path = _make_app_zip(tmp_path)
        mgr.deploy_app(zip_path)

        manifest = mgr.get_app("test-app")
        assert manifest.name == "test-app"

    def test_get_app_not_found(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))
        with pytest.raises(FileNotFoundError):
            mgr.get_app("nonexistent")

    def test_get_app_configs_dir(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))
        zip_path = _make_app_zip(tmp_path)
        mgr.deploy_app(zip_path)

        configs_dir = mgr.get_app_configs_dir("test-app")
        assert configs_dir == tmp_path / "apps" / "test-app" / "configs"

    def test_remove_app(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))
        zip_path = _make_app_zip(tmp_path)
        mgr.deploy_app(zip_path)

        mgr.remove_app("test-app")
        assert mgr.list_apps() == []
        assert not (tmp_path / "apps" / "test-app").exists()

    def test_remove_app_not_found(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))
        with pytest.raises(FileNotFoundError):
            mgr.remove_app("nonexistent")

    def test_deploy_replaces_existing(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))
        zip_path = _make_app_zip(tmp_path)
        mgr.deploy_app(zip_path)

        # Deploy again with updated version
        updated = {**VALID_MANIFEST, "version": "2.0.0"}
        v2_dir = tmp_path / "v2"
        v2_dir.mkdir(exist_ok=True)
        zip_path2 = _make_app_zip(v2_dir, manifest=updated)
        mgr.deploy_app(zip_path2)

        apps = mgr.list_apps()
        assert len(apps) == 1
        assert apps[0].version == "2.0.0"


class TestAppManagerErrors:
    def test_zip_not_found(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path))
        with pytest.raises(AppDeployError, match="not found"):
            mgr.deploy_app(tmp_path / "nonexistent.zip")

    def test_not_a_zip(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path))
        bad_file = tmp_path / "bad.zip"
        bad_file.write_text("not a zip file")
        with pytest.raises(AppDeployError, match="Not a valid ZIP"):
            mgr.deploy_app(bad_file)

    def test_no_manifest(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path))
        zip_path = tmp_path / "no-manifest.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "no manifest here")
        with pytest.raises(AppDeployError, match=r"manifest\.yaml"):
            mgr.deploy_app(zip_path)

    def test_invalid_manifest(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path))
        zip_path = tmp_path / "bad-manifest.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.yaml", yaml.dump({"name": "BAD"}))
        with pytest.raises(AppDeployError, match="Invalid manifest"):
            mgr.deploy_app(zip_path)

    def test_missing_referenced_config(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path))
        zip_path = tmp_path / "missing-config.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.yaml", yaml.dump(VALID_MANIFEST))
            # Don't include configs/workers/my_worker.yaml
        with pytest.raises(AppDeployError, match="missing file"):
            mgr.deploy_app(zip_path)

    def test_unsafe_path_in_zip(self, tmp_path):
        mgr = AppManager(apps_dir=str(tmp_path))
        zip_path = tmp_path / "unsafe.zip"
        manifest = {
            "name": "safe-app",
            "version": "1.0.0",
            "description": "Test",
        }
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.yaml", yaml.dump(manifest))
            zf.writestr("../escape.txt", "escaped!")
        with pytest.raises(AppDeployError, match="unsafe path"):
            mgr.deploy_app(zip_path)


class TestAppManagerReload:
    @pytest.mark.asyncio
    async def test_notify_reload_no_bus(self, tmp_path):
        """notify_reload should not raise when no bus is configured."""
        mgr = AppManager(apps_dir=str(tmp_path))
        await mgr.notify_reload()  # should not raise

    @pytest.mark.asyncio
    async def test_notify_reload_with_bus(self, tmp_path):
        """notify_reload publishes to loom.control.reload."""
        from loom.bus.memory import InMemoryBus

        bus = InMemoryBus()
        await bus.connect()
        sub = await bus.subscribe("loom.control.reload")

        mgr = AppManager(apps_dir=str(tmp_path), bus=bus)
        await mgr.notify_reload()

        # Check the message was published
        msg = await sub._queue.get()
        assert msg["action"] == "reload"
        await bus.close()
