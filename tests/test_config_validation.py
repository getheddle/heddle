"""Tests for config loading and validation (src/loom/core/config.py)."""

from __future__ import annotations

import pytest
import yaml

from loom.core.config import (
    _validate_knowledge_silos,
    load_config,
    validate_pipeline_config,
    validate_worker_config,
)

# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_valid_yaml(self, tmp_path):
        p = tmp_path / "valid.yaml"
        p.write_text("name: test\nsystem_prompt: do stuff\n")
        result = load_config(p)
        assert result == {"name": "test", "system_prompt": "do stuff"}

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text(":\n  :\n    - :\n  bad: [unterminated")
        with pytest.raises(yaml.YAMLError):
            load_config(p)


# ---------------------------------------------------------------------------
# validate_worker_config
# ---------------------------------------------------------------------------


class TestValidateWorkerConfig:
    def test_valid_minimal(self):
        errors = validate_worker_config({"name": "w", "system_prompt": "do it"})
        assert errors == []

    def test_missing_name(self):
        errors = validate_worker_config({"system_prompt": "do it"})
        assert len(errors) == 1
        assert "'name'" in errors[0]

    def test_missing_system_prompt(self):
        errors = validate_worker_config({"name": "w"})
        assert len(errors) == 1
        assert "'system_prompt'" in errors[0]

    def test_name_wrong_type(self):
        errors = validate_worker_config({"name": 123, "system_prompt": "do it"})
        assert len(errors) == 1
        assert "expected str" in errors[0]

    def test_input_schema_string(self):
        cfg = {"name": "w", "system_prompt": "do it", "input_schema": "bad"}
        errors = validate_worker_config(cfg)
        assert len(errors) == 1
        assert "input_schema" in errors[0]

    def test_output_schema_string(self):
        cfg = {"name": "w", "system_prompt": "do it", "output_schema": "bad"}
        errors = validate_worker_config(cfg)
        assert len(errors) == 1
        assert "output_schema" in errors[0]

    def test_non_dict_config(self):
        errors = validate_worker_config("not a dict")
        assert len(errors) == 1
        assert "expected dict" in errors[0]

    def test_multiple_missing_fields(self):
        errors = validate_worker_config({})
        assert len(errors) == 2
        missing_keys = " ".join(errors)
        assert "'name'" in missing_keys
        assert "'system_prompt'" in missing_keys


# ---------------------------------------------------------------------------
# validate_pipeline_config
# ---------------------------------------------------------------------------


class TestValidatePipelineConfig:
    def test_valid(self):
        cfg = {
            "name": "pipe",
            "pipeline_stages": [{"name": "s1", "worker_type": "summarizer"}],
        }
        assert validate_pipeline_config(cfg) == []

    def test_missing_pipeline_stages(self):
        errors = validate_pipeline_config({"name": "pipe"})
        assert len(errors) == 1
        assert "'pipeline_stages'" in errors[0]

    def test_stage_missing_name(self):
        cfg = {
            "name": "pipe",
            "pipeline_stages": [{"worker_type": "summarizer"}],
        }
        errors = validate_pipeline_config(cfg)
        assert any("missing required key 'name'" in e for e in errors)

    def test_stage_missing_worker_type(self):
        cfg = {
            "name": "pipe",
            "pipeline_stages": [{"name": "s1"}],
        }
        errors = validate_pipeline_config(cfg)
        assert any("missing required key 'worker_type'" in e for e in errors)

    def test_non_dict_stage(self):
        cfg = {
            "name": "pipe",
            "pipeline_stages": ["not_a_dict"],
        }
        errors = validate_pipeline_config(cfg)
        assert any("expected dict" in e for e in errors)

    def test_multiple_bad_stages(self):
        cfg = {
            "name": "pipe",
            "pipeline_stages": [
                {"worker_type": "summarizer"},  # missing name
                {"name": "s2"},  # missing worker_type
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert len(errors) == 2


# ---------------------------------------------------------------------------
# _validate_knowledge_silos
# ---------------------------------------------------------------------------


class TestValidateKnowledgeSilos:
    def test_valid_folder_silo(self):
        silos = [{"name": "docs", "type": "folder", "path": "/data/docs"}]
        assert _validate_knowledge_silos(silos, "test.yaml") == []

    def test_valid_tool_silo(self):
        silos = [{"name": "search", "type": "tool", "provider": "duckdb"}]
        assert _validate_knowledge_silos(silos, "test.yaml") == []

    def test_missing_name(self):
        silos = [{"type": "folder", "path": "/data"}]
        errors = _validate_knowledge_silos(silos, "test.yaml")
        assert any("'name'" in e for e in errors)

    def test_missing_type(self):
        silos = [{"name": "docs"}]
        errors = _validate_knowledge_silos(silos, "test.yaml")
        assert any("'type'" in e for e in errors)

    def test_folder_missing_path(self):
        silos = [{"name": "docs", "type": "folder"}]
        errors = _validate_knowledge_silos(silos, "test.yaml")
        assert any("missing required key 'path'" in e for e in errors)

    def test_tool_missing_provider(self):
        silos = [{"name": "search", "type": "tool"}]
        errors = _validate_knowledge_silos(silos, "test.yaml")
        assert any("missing required key 'provider'" in e for e in errors)

    def test_invalid_permissions(self):
        silos = [{"name": "docs", "type": "folder", "path": "/d", "permissions": "write"}]
        errors = _validate_knowledge_silos(silos, "test.yaml")
        assert any("permissions" in e for e in errors)

    def test_unknown_silo_type(self):
        silos = [{"name": "x", "type": "database"}]
        errors = _validate_knowledge_silos(silos, "test.yaml")
        assert any("unknown silo type" in e for e in errors)

    def test_non_list_silos(self):
        errors = _validate_knowledge_silos("not a list", "test.yaml")
        assert len(errors) == 1
        assert "should be a list" in errors[0]

    def test_non_dict_entry(self):
        errors = _validate_knowledge_silos(["not a dict"], "test.yaml")
        assert len(errors) == 1
        assert "expected dict" in errors[0]

    def test_tool_config_not_dict(self):
        silos = [{"name": "s", "type": "tool", "provider": "p", "config": "bad"}]
        errors = _validate_knowledge_silos(silos, "test.yaml")
        assert any("'config' must be a dict" in e for e in errors)
