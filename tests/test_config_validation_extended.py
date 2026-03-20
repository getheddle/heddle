"""Extended tests for config validation — orchestrator, router, and deep checks.

Complements test_config_validation.py (which covers basic worker/pipeline validation).
Tests the new validation functions: validate_orchestrator_config, validate_router_rules,
and the deeper checks added to worker and pipeline validation.
"""

from __future__ import annotations

import pytest

from loom.core.config import (
    VALID_MODEL_TIERS,
    ConfigValidationError,
    load_config,
    validate_orchestrator_config,
    validate_pipeline_config,
    validate_router_rules,
    validate_worker_config,
)

# ---------------------------------------------------------------------------
# Worker config — extended checks
# ---------------------------------------------------------------------------


class TestWorkerValidationExtended:
    """Test the deeper checks added to validate_worker_config."""

    def test_valid_llm_worker(self):
        cfg = {
            "name": "test",
            "system_prompt": "You are a test worker.",
            "default_model_tier": "local",
            "timeout_seconds": 30,
            "max_output_tokens": 1000,
            "reset_after_task": True,
            "input_schema": {
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
            "output_schema": {
                "type": "object",
                "required": ["result"],
                "properties": {"result": {"type": "string"}},
            },
        }
        assert validate_worker_config(cfg) == []

    def test_missing_system_prompt_for_llm_worker(self):
        cfg = {"name": "test"}
        errors = validate_worker_config(cfg)
        assert any("system_prompt" in e for e in errors)

    def test_processor_worker_valid(self):
        cfg = {
            "name": "proc",
            "worker_kind": "processor",
            "processing_backend": "mypackage.backends.MyBackend",
        }
        assert validate_worker_config(cfg) == []

    def test_processor_missing_backend(self):
        cfg = {"name": "proc", "worker_kind": "processor"}
        errors = validate_worker_config(cfg)
        assert any("processing_backend" in e for e in errors)

    def test_processor_backend_not_dotted(self):
        cfg = {"name": "proc", "worker_kind": "processor", "processing_backend": "MyBackend"}
        errors = validate_worker_config(cfg)
        assert any("fully qualified" in e for e in errors)

    def test_invalid_worker_kind(self):
        cfg = {"name": "x", "worker_kind": "magic"}
        errors = validate_worker_config(cfg)
        assert any("'llm' or 'processor'" in e for e in errors)

    def test_invalid_tier(self):
        cfg = {"name": "x", "system_prompt": "test", "default_model_tier": "mega"}
        errors = validate_worker_config(cfg)
        assert any("default_model_tier" in e for e in errors)

    def test_valid_tiers_accepted(self):
        for tier in VALID_MODEL_TIERS:
            cfg = {"name": "x", "system_prompt": "test", "default_model_tier": tier}
            errors = validate_worker_config(cfg)
            assert not any("default_model_tier" in e for e in errors)

    def test_negative_timeout(self):
        cfg = {"name": "x", "system_prompt": "test", "timeout_seconds": -5}
        errors = validate_worker_config(cfg)
        assert any("positive" in e for e in errors)

    def test_zero_max_tokens(self):
        cfg = {"name": "x", "system_prompt": "test", "max_output_tokens": 0}
        errors = validate_worker_config(cfg)
        assert any("positive" in e for e in errors)

    def test_boolean_timeout_rejected(self):
        cfg = {"name": "x", "system_prompt": "test", "timeout_seconds": True}
        errors = validate_worker_config(cfg)
        assert any("number" in e for e in errors)

    def test_reset_after_task_must_be_true(self):
        cfg = {"name": "x", "system_prompt": "test", "reset_after_task": False}
        errors = validate_worker_config(cfg)
        assert any("stateless" in e for e in errors)

    def test_resolve_file_refs_requires_workspace_dir(self):
        cfg = {"name": "x", "system_prompt": "test", "resolve_file_refs": ["file_ref"]}
        errors = validate_worker_config(cfg)
        assert any("workspace_dir" in e for e in errors)

    def test_resolve_file_refs_with_workspace_ok(self):
        cfg = {
            "name": "x",
            "system_prompt": "test",
            "resolve_file_refs": ["file_ref"],
            "workspace_dir": "/tmp/ws",
        }
        errors = validate_worker_config(cfg)
        assert not any("workspace_dir" in e for e in errors)

    def test_invalid_schema_type(self):
        cfg = {
            "name": "x",
            "system_prompt": "test",
            "input_schema": {"type": "banana"},
        }
        errors = validate_worker_config(cfg)
        assert any("valid JSON Schema type" in e for e in errors)

    def test_schema_required_not_list(self):
        cfg = {
            "name": "x",
            "system_prompt": "test",
            "input_schema": {"type": "object", "required": "text"},
        }
        errors = validate_worker_config(cfg)
        assert any("required must be a list" in e for e in errors)

    def test_schema_properties_not_dict(self):
        cfg = {
            "name": "x",
            "system_prompt": "test",
            "output_schema": {"type": "object", "properties": "bad"},
        }
        errors = validate_worker_config(cfg)
        assert any("properties must be a dict" in e for e in errors)


# ---------------------------------------------------------------------------
# Pipeline config — extended checks
# ---------------------------------------------------------------------------


class TestPipelineValidationExtended:
    """Test deeper pipeline config validation."""

    def test_valid_pipeline(self):
        cfg = {
            "name": "test-pipeline",
            "timeout_seconds": 60,
            "pipeline_stages": [
                {
                    "name": "a",
                    "worker_type": "extractor",
                    "tier": "local",
                    "input_mapping": {"f": "goal.context.f"},
                },
                {
                    "name": "b",
                    "worker_type": "classifier",
                    "tier": "standard",
                    "input_mapping": {"t": "a.output.text"},
                },
            ],
        }
        assert validate_pipeline_config(cfg) == []

    def test_duplicate_stage_names(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "stage1", "worker_type": "a"},
                {"name": "stage1", "worker_type": "b"},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert any("duplicate" in e for e in errors)

    def test_invalid_tier_in_stage(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "s", "worker_type": "w", "tier": "ultra"},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert any("tier" in e for e in errors)

    def test_input_mapping_must_be_dict(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "s", "worker_type": "w", "input_mapping": "bad"},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert any("input_mapping" in e and "dict" in e for e in errors)

    def test_input_mapping_empty_path(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "s", "worker_type": "w", "input_mapping": {"field": ""}},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert any("empty" in e for e in errors)

    def test_depends_on_unknown_stage(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "s", "worker_type": "w", "depends_on": ["nonexistent"]},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert any("unknown stage" in e for e in errors)

    def test_condition_bad_syntax(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "s", "worker_type": "w", "condition": "too few"},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert any("3 space-separated parts" in e for e in errors)

    def test_condition_bad_operator(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "s", "worker_type": "w", "condition": "a.b > 5"},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert any("operator" in e for e in errors)

    def test_condition_valid(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "s", "worker_type": "w", "condition": "a.output.flag == true"},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert not any("condition" in e for e in errors)

    def test_max_concurrent_goals_must_be_positive(self):
        cfg = {"name": "p", "pipeline_stages": [], "max_concurrent_goals": 0}
        errors = validate_pipeline_config(cfg)
        assert any("max_concurrent_goals" in e for e in errors)


# ---------------------------------------------------------------------------
# Orchestrator config
# ---------------------------------------------------------------------------


class TestOrchestratorValidation:
    """Test validate_orchestrator_config."""

    def test_valid_config(self):
        cfg = {
            "name": "test-orch",
            "system_prompt": "You are an orchestrator.",
            "checkpoint": {"token_threshold": 50000, "recent_window": 5},
            "max_concurrent_goals": 1,
            "max_concurrent_tasks": 5,
            "timeout_seconds": 300,
        }
        assert validate_orchestrator_config(cfg) == []

    def test_missing_name(self):
        cfg = {"system_prompt": "test"}
        errors = validate_orchestrator_config(cfg)
        assert any("name" in e for e in errors)

    def test_missing_system_prompt(self):
        cfg = {"name": "test"}
        errors = validate_orchestrator_config(cfg)
        assert any("system_prompt" in e for e in errors)

    def test_checkpoint_invalid_structure(self):
        cfg = {"name": "x", "system_prompt": "test", "checkpoint": "bad"}
        errors = validate_orchestrator_config(cfg)
        assert any("checkpoint" in e and "dict" in e for e in errors)

    def test_checkpoint_bad_threshold(self):
        cfg = {"name": "x", "system_prompt": "test", "checkpoint": {"token_threshold": -1}}
        errors = validate_orchestrator_config(cfg)
        assert any("token_threshold" in e for e in errors)

    def test_checkpoint_bad_window(self):
        cfg = {"name": "x", "system_prompt": "test", "checkpoint": {"recent_window": -1}}
        errors = validate_orchestrator_config(cfg)
        assert any("recent_window" in e for e in errors)

    def test_bad_max_concurrent_goals(self):
        cfg = {"name": "x", "system_prompt": "test", "max_concurrent_goals": 0}
        errors = validate_orchestrator_config(cfg)
        assert any("max_concurrent_goals" in e for e in errors)

    def test_available_workers_not_list(self):
        cfg = {"name": "x", "system_prompt": "test", "available_workers": "bad"}
        errors = validate_orchestrator_config(cfg)
        assert any("available_workers" in e and "list" in e for e in errors)

    def test_available_workers_missing_fields(self):
        cfg = {
            "name": "x",
            "system_prompt": "test",
            "available_workers": [{"name": "w"}],  # missing description
        }
        errors = validate_orchestrator_config(cfg)
        assert any("description" in e for e in errors)

    def test_not_a_dict(self):
        errors = validate_orchestrator_config("not a dict")
        assert len(errors) == 1
        assert "expected dict" in errors[0]


# ---------------------------------------------------------------------------
# Router rules
# ---------------------------------------------------------------------------


class TestRouterRulesValidation:
    """Test validate_router_rules."""

    def test_valid_rules(self):
        cfg = {
            "tier_overrides": {"summarizer": "local", "extractor": "standard"},
            "rate_limits": {
                "local": {"max_concurrent": 4, "tokens_per_minute": 100000},
                "frontier": {"max_concurrent": 3},
            },
        }
        assert validate_router_rules(cfg) == []

    def test_empty_rules_ok(self):
        assert validate_router_rules({}) == []

    def test_not_a_dict(self):
        errors = validate_router_rules("bad")
        assert len(errors) == 1

    def test_invalid_tier_override(self):
        cfg = {"tier_overrides": {"worker": "mega_tier"}}
        errors = validate_router_rules(cfg)
        assert any("mega_tier" in e for e in errors)

    def test_tier_override_valid_tiers(self):
        cfg = {"tier_overrides": {"w": "local", "x": "standard", "y": "frontier"}}
        assert validate_router_rules(cfg) == []

    def test_rate_limit_unknown_tier(self):
        cfg = {"rate_limits": {"ultra": {"max_concurrent": 5}}}
        errors = validate_router_rules(cfg)
        assert any("unknown tier" in e for e in errors)

    def test_rate_limit_bad_max_concurrent(self):
        cfg = {"rate_limits": {"local": {"max_concurrent": 0}}}
        errors = validate_router_rules(cfg)
        assert any("positive integer" in e for e in errors)

    def test_rate_limit_bad_tokens_per_minute(self):
        cfg = {"rate_limits": {"local": {"tokens_per_minute": -1}}}
        errors = validate_router_rules(cfg)
        assert any("positive number" in e for e in errors)

    def test_rate_limit_not_dict(self):
        cfg = {"rate_limits": {"local": "fast"}}
        errors = validate_router_rules(cfg)
        assert any("must be a dict" in e for e in errors)

    def test_tier_overrides_not_dict(self):
        cfg = {"tier_overrides": ["local"]}
        errors = validate_router_rules(cfg)
        assert any("must be a dict" in e for e in errors)


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """Test load_config raises on non-dict YAML."""

    def test_non_dict_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("- just a list")
        with pytest.raises(ConfigValidationError, match="expected YAML mapping"):
            load_config(p)

    def test_valid_dict(self, tmp_path):
        p = tmp_path / "good.yaml"
        p.write_text("name: test\n")
        result = load_config(p)
        assert result == {"name": "test"}

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "missing.yaml")


# ---------------------------------------------------------------------------
# P3.4 — Config validation at load time
# ---------------------------------------------------------------------------


class TestInputMappingPathValidation:
    """Test that input_mapping source paths are validated against stage names."""

    def test_input_mapping_referencing_nonexistent_stage(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {
                    "name": "b",
                    "worker_type": "classifier",
                    "input_mapping": {"text": "nonexistent.output.text"},
                },
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert any("unknown source 'nonexistent'" in e for e in errors)

    def test_input_mapping_referencing_goal(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {
                    "name": "a",
                    "worker_type": "extractor",
                    "input_mapping": {"text": "goal.context.document"},
                },
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert not any("unknown source" in e for e in errors)

    def test_input_mapping_referencing_valid_stage(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "a", "worker_type": "extractor"},
                {
                    "name": "b",
                    "worker_type": "classifier",
                    "input_mapping": {"text": "a.output.text"},
                },
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert not any("unknown source" in e for e in errors)

    def test_input_mapping_referencing_later_stage_fails(self):
        """A stage can only reference stages defined before it."""
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {
                    "name": "a",
                    "worker_type": "extractor",
                    "input_mapping": {"text": "b.output.text"},
                },
                {"name": "b", "worker_type": "classifier"},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert any("unknown source 'b'" in e for e in errors)


class TestProcessingBackendValidation:
    """Test processing_backend format validation."""

    def test_valid_backend_path(self):
        cfg = {
            "name": "proc",
            "worker_kind": "processor",
            "processing_backend": "loom.contrib.duckdb.query_backend.DuckDBQueryBackend",
        }
        errors = validate_worker_config(cfg)
        assert errors == []

    def test_valid_two_segment_path(self):
        cfg = {
            "name": "proc",
            "worker_kind": "processor",
            "processing_backend": "mypackage.MyBackend",
        }
        errors = validate_worker_config(cfg)
        assert errors == []

    def test_single_segment_fails(self):
        cfg = {
            "name": "proc",
            "worker_kind": "processor",
            "processing_backend": "notamodule",
        }
        errors = validate_worker_config(cfg)
        assert any("fully qualified" in e or "at least two segments" in e for e in errors)

    def test_invalid_identifier_segment(self):
        cfg = {
            "name": "proc",
            "worker_kind": "processor",
            "processing_backend": "my-package.backends.MyBackend",
        }
        errors = validate_worker_config(cfg)
        assert any("not a valid Python identifier" in e for e in errors)

    def test_empty_segment_fails(self):
        cfg = {
            "name": "proc",
            "worker_kind": "processor",
            "processing_backend": "mypackage..MyBackend",
        }
        errors = validate_worker_config(cfg)
        assert any("not a valid Python identifier" in e for e in errors)


class TestConditionValidation:
    """Test condition operator validation at config load time."""

    def test_valid_equals_condition(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "s", "worker_type": "w", "condition": "a.output.flag == true"},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert not any("condition" in e for e in errors)

    def test_valid_not_equals_condition(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "s", "worker_type": "w", "condition": "a.output.flag != false"},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert not any("condition" in e for e in errors)

    def test_invalid_operator(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "s", "worker_type": "w", "condition": "a.output.count > 5"},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert any("operator must be '==' or '!='" in e for e in errors)

    def test_wrong_number_of_parts_too_few(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "s", "worker_type": "w", "condition": "incomplete"},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert any("3 space-separated parts" in e for e in errors)

    def test_wrong_number_of_parts_too_many(self):
        cfg = {
            "name": "p",
            "pipeline_stages": [
                {"name": "s", "worker_type": "w", "condition": "a == b extra stuff"},
            ],
        }
        errors = validate_pipeline_config(cfg)
        assert any("3 space-separated parts" in e for e in errors)
