"""Tests for heddle.core.manifest — app manifest schema and validation."""

import pytest
import yaml

from heddle.core.manifest import AppManifest, load_manifest, validate_app_manifest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_MANIFEST = {
    "name": "test-app",
    "version": "1.0.0",
    "description": "A test application",
    "heddle_version": ">=0.4.0",
    "required_extras": ["duckdb", "mcp"],
    "entry_configs": {
        "workers": [
            {"config": "configs/workers/my_worker.yaml", "tier": "local"},
        ],
        "pipelines": [
            {"config": "configs/orchestrators/my_pipeline.yaml"},
        ],
    },
}


# ---------------------------------------------------------------------------
# validate_app_manifest
# ---------------------------------------------------------------------------


class TestValidateAppManifest:
    def test_valid_manifest(self):
        errors = validate_app_manifest(VALID_MANIFEST)
        assert errors == []

    def test_minimal_manifest(self):
        errors = validate_app_manifest(
            {
                "name": "minimal",
                "version": "0.1.0",
                "description": "Minimal app",
            }
        )
        assert errors == []

    def test_missing_name(self):
        data = {**VALID_MANIFEST}
        del data["name"]
        errors = validate_app_manifest(data)
        assert any("name" in e for e in errors)

    def test_missing_version(self):
        data = {**VALID_MANIFEST}
        del data["version"]
        errors = validate_app_manifest(data)
        assert any("version" in e for e in errors)

    def test_missing_description(self):
        data = {**VALID_MANIFEST}
        del data["description"]
        errors = validate_app_manifest(data)
        assert any("description" in e for e in errors)

    def test_invalid_name_uppercase(self):
        data = {**VALID_MANIFEST, "name": "MyApp"}
        errors = validate_app_manifest(data)
        assert any("name" in e.lower() or "validation" in e.lower() for e in errors)

    def test_invalid_name_starts_with_digit(self):
        data = {**VALID_MANIFEST, "name": "1app"}
        errors = validate_app_manifest(data)
        assert len(errors) > 0

    def test_invalid_version(self):
        data = {**VALID_MANIFEST, "version": "not-a-version"}
        errors = validate_app_manifest(data)
        assert len(errors) > 0

    def test_invalid_config_extension(self):
        data = {
            **VALID_MANIFEST,
            "entry_configs": {
                "workers": [{"config": "configs/workers/bad.json"}],
            },
        }
        errors = validate_app_manifest(data)
        assert any(".yaml" in e for e in errors)

    def test_with_python_package(self):
        data = {
            **VALID_MANIFEST,
            "python_package": {"name": "mylib", "install_path": "src/"},
        }
        errors = validate_app_manifest(data)
        assert errors == []

    def test_with_scripts(self):
        data = {
            **VALID_MANIFEST,
            "scripts": [
                {"path": "scripts/setup.py", "description": "Setup script"},
            ],
        }
        errors = validate_app_manifest(data)
        assert errors == []


# ---------------------------------------------------------------------------
# AppManifest model
# ---------------------------------------------------------------------------


class TestAppManifest:
    def test_parse_valid(self):
        m = AppManifest(**VALID_MANIFEST)
        assert m.name == "test-app"
        assert m.version == "1.0.0"
        assert len(m.entry_configs.workers) == 1
        assert len(m.entry_configs.pipelines) == 1

    def test_defaults(self):
        m = AppManifest(name="test", version="1.0.0", description="Test")
        assert m.heddle_version == ">=0.4.0"
        assert m.required_extras == []
        assert m.python_package is None
        assert m.entry_configs.workers == []
        assert m.scripts == []

    def test_name_validation(self):
        with pytest.raises(ValueError):
            AppManifest(name="Bad Name!", version="1.0.0", description="Test")

    def test_version_validation(self):
        with pytest.raises(ValueError):
            AppManifest(name="test", version="bad", description="Test")

    def test_version_with_prerelease(self):
        m = AppManifest(name="test", version="1.0.0-beta.1", description="Test")
        assert m.version == "1.0.0-beta.1"


# ---------------------------------------------------------------------------
# load_manifest
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_load_valid(self, tmp_path):
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(yaml.dump(VALID_MANIFEST))
        m = load_manifest(manifest_path)
        assert m.name == "test-app"

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_manifest(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml(self, tmp_path):
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text("not: a: valid: yaml: [")
        with pytest.raises((ValueError, yaml.YAMLError)):
            load_manifest(manifest_path)

    def test_not_a_dict(self, tmp_path):
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text("- a list\n- not a dict\n")
        with pytest.raises(ValueError, match="mapping"):
            load_manifest(manifest_path)

    def test_invalid_manifest_content(self, tmp_path):
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(yaml.dump({"name": "BAD"}))
        with pytest.raises(ValueError, match="Invalid manifest"):
            load_manifest(manifest_path)
