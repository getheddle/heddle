"""Tests for loom.workshop.app_manager — ZIP deployment, list, remove."""

import zipfile
from pathlib import Path

import pytest
import yaml

from loom.workshop.app_manager import AppDeployError, AppManager, _validate_config_path

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
    tmp_path: Path,
    manifest: dict | None = None,
    include_config: bool = True,
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


# ---------------------------------------------------------------------------
# P1.5 — Deployment safety (symlinks, atomic deploy, path traversal)
# ---------------------------------------------------------------------------


class TestDeploymentSafety:
    """Tests for ZIP symlink rejection, atomic deploy, and config path validation."""

    def test_symlink_in_zip_rejected(self, tmp_path):
        """ZIP entries with symlink external_attr are rejected."""
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))
        zip_path = tmp_path / "symlink-app.zip"

        manifest = {
            "name": "sym-app",
            "version": "1.0.0",
            "description": "Test",
        }

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.yaml", yaml.dump(manifest))
            # Create a ZipInfo that looks like a symlink.
            info = zipfile.ZipInfo("evil-link")
            # S_IFLNK (0o120000) in the upper 16 bits of external_attr.
            info.external_attr = (0o120777) << 16
            zf.writestr(info, "/etc/passwd")

        with pytest.raises(AppDeployError, match="symlink"):
            mgr.deploy_app(zip_path)

    def test_atomic_deploy_preserves_old_on_failure(self, tmp_path):
        """If deployment fails mid-extraction, the previous version stays intact."""
        apps_dir = tmp_path / "apps"
        mgr = AppManager(apps_dir=str(apps_dir))

        # Deploy v1 successfully.
        zip_v1 = _make_app_zip(tmp_path)
        mgr.deploy_app(zip_v1)
        assert mgr.get_app("test-app").version == "1.0.0"

        # Create a v2 ZIP with a symlink that will cause deploy to fail.
        v2_dir = tmp_path / "v2"
        v2_dir.mkdir()
        v2_manifest = {**VALID_MANIFEST, "version": "2.0.0"}
        zip_v2 = v2_dir / "test-app-v2.zip"
        with zipfile.ZipFile(zip_v2, "w") as zf:
            zf.writestr("manifest.yaml", yaml.dump(v2_manifest))
            zf.writestr("configs/workers/my_worker.yaml", yaml.dump(WORKER_CONFIG))
            info = zipfile.ZipInfo("sneaky-link")
            info.external_attr = (0o120777) << 16
            zf.writestr(info, "target")

        with pytest.raises(AppDeployError, match="symlink"):
            mgr.deploy_app(zip_v2)

        # v1 should still be intact.
        assert mgr.get_app("test-app").version == "1.0.0"

    def test_atomic_deploy_cleans_temp_dir_on_failure(self, tmp_path):
        """Temp directories are cleaned up when deployment fails."""
        apps_dir = tmp_path / "apps"
        mgr = AppManager(apps_dir=str(apps_dir))

        # Create a ZIP with a symlink to trigger failure after extraction.
        zip_path = tmp_path / "bad.zip"
        manifest = {"name": "bad-app", "version": "1.0.0", "description": "Test"}
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.yaml", yaml.dump(manifest))
            info = zipfile.ZipInfo("link")
            info.external_attr = (0o120777) << 16
            zf.writestr(info, "target")

        with pytest.raises(AppDeployError):
            mgr.deploy_app(zip_path)

        # No temp dirs should remain in apps_dir.
        remaining = list(apps_dir.iterdir())
        temp_dirs = [d for d in remaining if d.name.startswith(".deploy-")]
        assert temp_dirs == []

    def test_config_path_traversal_rejected(self, tmp_path):
        """Manifest config paths that escape the app dir are rejected."""
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))

        bad_manifest = {
            "name": "traverse-app",
            "version": "1.0.0",
            "description": "Test",
            "entry_configs": {
                "workers": [
                    {"config": "../../../etc/passwd"},
                ],
            },
        }
        zip_path = tmp_path / "traverse.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.yaml", yaml.dump(bad_manifest))
            # The unsafe path check runs before the "file missing" check,
            # but the ".." check in names runs first. Add the path so it
            # doesn't fail there.

        # Should fail on either the ".." in names check or config path validation.
        with pytest.raises(AppDeployError):
            mgr.deploy_app(zip_path)

    def test_absolute_config_path_rejected(self, tmp_path):
        """Manifest config paths that are absolute are rejected."""
        with pytest.raises(AppDeployError, match="absolute"):
            _validate_config_path("/etc/passwd")

    def test_valid_config_path_accepted(self):
        """Normal config paths pass validation."""
        # Should not raise.
        _validate_config_path("configs/workers/my_worker.yaml")
        _validate_config_path("configs/pipelines/pipeline.yaml")

    def test_deploy_creates_no_symlinks_on_disk(self, tmp_path):
        """Successful deployment has no symlinks in the extracted directory."""
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))
        zip_path = _make_app_zip(tmp_path)
        mgr.deploy_app(zip_path)

        app_dir = tmp_path / "apps" / "test-app"
        for item in app_dir.rglob("*"):
            assert not item.is_symlink(), f"Unexpected symlink: {item}"

    def test_config_path_escapes_app_dir(self):
        """Config path that resolves to app-root itself (no trailing slash) is rejected."""
        from loom.workshop.app_manager import _validate_config_path

        # A path like "." resolves to "/app-root" which doesn't start with "/app-root/"
        with pytest.raises(AppDeployError, match="escapes app directory"):
            _validate_config_path(".")

    def test_list_apps_apps_dir_removed_after_init(self, tmp_path):
        """list_apps returns [] when apps_dir is removed after initialization."""
        import shutil

        apps_dir = tmp_path / "apps"
        mgr = AppManager(apps_dir=str(apps_dir))
        # Remove the directory that __init__ created
        shutil.rmtree(apps_dir)
        apps = mgr.list_apps()
        assert apps == []

    def test_list_apps_skips_non_dirs(self, tmp_path):
        """Files (not dirs) inside apps_dir are silently skipped."""
        mgr = AppManager(apps_dir=str(tmp_path))
        # Place a plain file in the apps dir (not a directory)
        (tmp_path / "stray-file.txt").write_text("not an app")
        apps = mgr.list_apps()
        assert apps == []

    def test_list_apps_skips_dir_without_manifest(self, tmp_path):
        """Dirs without manifest.yaml are silently skipped."""
        mgr = AppManager(apps_dir=str(tmp_path))
        # A directory with no manifest.yaml
        (tmp_path / "no-manifest-app").mkdir()
        apps = mgr.list_apps()
        assert apps == []

    def test_list_apps_logs_corrupt_manifest(self, tmp_path):
        """Dirs with a corrupt manifest.yaml are skipped with a warning (no crash)."""
        mgr = AppManager(apps_dir=str(tmp_path))
        app_dir = tmp_path / "bad-app"
        app_dir.mkdir()
        (app_dir / "manifest.yaml").write_text(": invalid: yaml: [")
        # Should not raise — corrupt manifests are logged and skipped
        apps = mgr.list_apps()
        assert apps == []

    def test_manifest_yaml_non_dict_rejected(self, tmp_path):
        """manifest.yaml that is not a YAML mapping is rejected."""
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))
        zip_path = tmp_path / "scalar-manifest.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.yaml", "just a string\n")
        with pytest.raises(AppDeployError, match="must be a YAML mapping"):
            mgr.deploy_app(zip_path)

    def test_deploy_with_python_package_logs_warning(self, tmp_path):
        """Manifests with python_package trigger a warning log (no crash)."""
        mgr = AppManager(apps_dir=str(tmp_path / "apps"))
        manifest = {
            "name": "pkg-app",
            "version": "1.0.0",
            "description": "App with python package",
            "python_package": {"name": "pkg-app", "install_path": "src/"},
        }
        zip_path = tmp_path / "pkg-app.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.yaml", yaml.dump(manifest))
        result = mgr.deploy_app(zip_path)
        assert result.name == "pkg-app"
        assert result.python_package is not None
        assert result.python_package.name == "pkg-app"


class TestAppManagerReloadErrors:
    @pytest.mark.asyncio
    async def test_notify_reload_bus_publish_raises(self, tmp_path):
        """notify_reload logs a warning when bus.publish raises (no crash)."""
        from unittest.mock import AsyncMock

        mock_bus = AsyncMock()
        mock_bus.publish.side_effect = RuntimeError("connection lost")

        mgr = AppManager(apps_dir=str(tmp_path), bus=mock_bus)
        # Should not raise — failure is caught and logged
        await mgr.notify_reload()
