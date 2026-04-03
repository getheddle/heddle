"""Tests for heddle.mcp.config — MCP gateway config loading and validation."""

import pytest

from heddle.mcp.config import validate_mcp_config


class TestValidateMCPConfig:
    """Test the validate_mcp_config function."""

    def test_valid_minimal(self):
        config = {"name": "test-gateway"}
        assert validate_mcp_config(config) == []

    def test_valid_full(self):
        config = {
            "name": "docman",
            "description": "Document processing",
            "nats_url": "nats://localhost:4222",
            "tools": {
                "workers": [
                    {"config": "configs/workers/classifier.yaml"},
                ],
                "pipelines": [
                    {"config": "configs/orchestrators/pipeline.yaml", "name": "process_doc"},
                ],
                "queries": [
                    {
                        "backend": "my.backend.QueryBackend",
                        "actions": ["search", "filter"],
                        "name_prefix": "docman",
                    },
                ],
            },
            "resources": {
                "workspace_dir": "/tmp/workspace",
                "patterns": ["*.pdf", "*.json"],
            },
        }
        assert validate_mcp_config(config) == []

    def test_missing_name(self):
        errors = validate_mcp_config({})
        assert any("name" in e for e in errors)

    def test_name_wrong_type(self):
        errors = validate_mcp_config({"name": 123})
        assert any("'name' must be a string" in e for e in errors)

    def test_description_wrong_type(self):
        errors = validate_mcp_config({"name": "test", "description": 42})
        assert any("'description' must be a string" in e for e in errors)

    def test_nats_url_wrong_type(self):
        errors = validate_mcp_config({"name": "test", "nats_url": 42})
        assert any("'nats_url' must be a string" in e for e in errors)

    def test_tools_wrong_type(self):
        errors = validate_mcp_config({"name": "test", "tools": "bad"})
        assert any("'tools' must be a dict" in e for e in errors)

    def test_not_a_dict(self):
        errors = validate_mcp_config("just a string")
        assert len(errors) == 1
        assert "expected dict" in errors[0]


class TestValidateWorkerEntries:
    def test_missing_config(self):
        config = {"name": "test", "tools": {"workers": [{"name": "foo"}]}}
        errors = validate_mcp_config(config)
        assert any("'config'" in e for e in errors)

    def test_config_wrong_type(self):
        config = {"name": "test", "tools": {"workers": [{"config": 123}]}}
        errors = validate_mcp_config(config)
        assert any("'config' must be a string" in e for e in errors)

    def test_optional_overrides_wrong_type(self):
        config = {
            "name": "test",
            "tools": {"workers": [{"config": "x.yaml", "name": 42, "tier": 99}]},
        }
        errors = validate_mcp_config(config)
        assert any("'name' must be a string" in e for e in errors)
        assert any("'tier' must be a string" in e for e in errors)

    def test_workers_not_list(self):
        config = {"name": "test", "tools": {"workers": "bad"}}
        errors = validate_mcp_config(config)
        assert any("must be a list" in e for e in errors)


class TestValidatePipelineEntries:
    def test_missing_config_and_name(self):
        config = {"name": "test", "tools": {"pipelines": [{}]}}
        errors = validate_mcp_config(config)
        assert any("'config'" in e for e in errors)
        assert any("'name'" in e for e in errors)

    def test_valid_pipeline(self):
        config = {
            "name": "test",
            "tools": {
                "pipelines": [
                    {"config": "p.yaml", "name": "run_pipeline", "description": "desc"},
                ]
            },
        }
        assert validate_mcp_config(config) == []


class TestValidateQueryEntries:
    def test_missing_required_keys(self):
        config = {"name": "test", "tools": {"queries": [{}]}}
        errors = validate_mcp_config(config)
        assert any("'backend'" in e for e in errors)
        assert any("'actions'" in e for e in errors)
        assert any("'name_prefix'" in e for e in errors)

    def test_actions_wrong_type(self):
        config = {
            "name": "test",
            "tools": {
                "queries": [
                    {
                        "backend": "x.Y",
                        "actions": "search",
                        "name_prefix": "q",
                    }
                ]
            },
        }
        errors = validate_mcp_config(config)
        assert any("'actions' must be a list" in e for e in errors)

    def test_backend_config_wrong_type(self):
        config = {
            "name": "test",
            "tools": {
                "queries": [
                    {
                        "backend": "x.Y",
                        "actions": ["search"],
                        "name_prefix": "q",
                        "backend_config": "bad",
                    }
                ]
            },
        }
        errors = validate_mcp_config(config)
        assert any("'backend_config' must be a dict" in e for e in errors)


class TestValidateResources:
    def test_missing_workspace_dir(self):
        config = {"name": "test", "resources": {}}
        errors = validate_mcp_config(config)
        assert any("workspace_dir" in e for e in errors)

    def test_workspace_dir_wrong_type(self):
        config = {"name": "test", "resources": {"workspace_dir": 42}}
        errors = validate_mcp_config(config)
        assert any("'workspace_dir' must be a string" in e for e in errors)

    def test_patterns_wrong_type(self):
        config = {"name": "test", "resources": {"workspace_dir": "/tmp", "patterns": "*.pdf"}}
        errors = validate_mcp_config(config)
        assert any("'patterns' must be a list" in e for e in errors)

    def test_resources_wrong_type(self):
        config = {"name": "test", "resources": "bad"}
        errors = validate_mcp_config(config)
        assert any("'resources' must be a dict" in e for e in errors)


class TestValidateWorkshopConfig:
    def test_valid_workshop(self):
        config = {
            "name": "test",
            "tools": {
                "workshop": {
                    "configs_dir": "configs/",
                    "enable": ["worker", "test", "eval"],
                },
            },
        }
        assert validate_mcp_config(config) == []

    def test_workshop_empty_dict(self):
        config = {"name": "test", "tools": {"workshop": {}}}
        assert validate_mcp_config(config) == []

    def test_workshop_not_dict(self):
        config = {"name": "test", "tools": {"workshop": "bad"}}
        errors = validate_mcp_config(config)
        assert any("must be a dict" in e for e in errors)

    def test_workshop_configs_dir_wrong_type(self):
        config = {"name": "test", "tools": {"workshop": {"configs_dir": 123}}}
        errors = validate_mcp_config(config)
        assert any("'configs_dir' must be a string" in e for e in errors)

    def test_workshop_enable_wrong_type(self):
        config = {"name": "test", "tools": {"workshop": {"enable": "worker"}}}
        errors = validate_mcp_config(config)
        assert any("'enable' must be a list" in e for e in errors)

    def test_workshop_enable_unknown_group(self):
        config = {"name": "test", "tools": {"workshop": {"enable": ["worker", "bogus"]}}}
        errors = validate_mcp_config(config)
        assert any("unknown group 'bogus'" in e for e in errors)

    def test_workshop_apps_dir_wrong_type(self):
        config = {"name": "test", "tools": {"workshop": {"apps_dir": 123}}}
        errors = validate_mcp_config(config)
        assert any("'apps_dir' must be a string" in e for e in errors)

    def test_workshop_absent_is_valid(self):
        config = {"name": "test", "tools": {}}
        assert validate_mcp_config(config) == []


# ---------------------------------------------------------------------------
# load_mcp_config — ConfigValidationError path (line 61)
# ---------------------------------------------------------------------------


class TestLoadMCPConfig:
    def test_raises_config_validation_error_on_invalid_config(self, tmp_path):
        """Line 61: load_mcp_config raises ConfigValidationError for invalid configs."""
        import yaml

        from heddle.core.config import ConfigValidationError
        from heddle.mcp.config import load_mcp_config

        bad_config = {"description": "no name here"}
        config_file = tmp_path / "bad.yaml"
        config_file.write_text(yaml.dump(bad_config))

        with pytest.raises(ConfigValidationError, match="error"):
            load_mcp_config(str(config_file))

    def test_raises_file_not_found_for_missing_file(self, tmp_path):
        """load_mcp_config raises FileNotFoundError for missing file."""
        from heddle.mcp.config import load_mcp_config

        with pytest.raises(FileNotFoundError):
            load_mcp_config(str(tmp_path / "nonexistent.yaml"))

    def test_valid_config_returns_dict(self, tmp_path):
        """load_mcp_config returns the config dict for a valid file."""
        import yaml

        from heddle.mcp.config import load_mcp_config

        config = {"name": "test-gateway"}
        config_file = tmp_path / "valid.yaml"
        config_file.write_text(yaml.dump(config))

        result = load_mcp_config(str(config_file))
        assert result["name"] == "test-gateway"


# ---------------------------------------------------------------------------
# _validate_worker_entries — non-dict entry (lines 129-130)
# ---------------------------------------------------------------------------


class TestValidateWorkerEntriesNonDict:
    def test_worker_entry_not_dict(self):
        """Lines 129-130: non-dict worker entry produces error and continues."""
        from heddle.mcp.config import validate_mcp_config

        config = {"name": "test", "tools": {"workers": ["just-a-string"]}}
        errors = validate_mcp_config(config)
        assert any("expected dict" in e for e in errors)

    def test_worker_entry_integer_is_not_dict(self):
        """Non-dict (int) entry reports error and continues to next entry."""
        from heddle.mcp.config import validate_mcp_config

        config = {
            "name": "test",
            "tools": {"workers": [42, {"config": "good.yaml"}]},
        }
        errors = validate_mcp_config(config)
        # Should report error for the int, but not for the valid dict.
        assert any("expected dict" in e for e in errors)
        # Exactly one error (no cascade from the valid entry).
        assert sum(1 for e in errors if "expected dict" in e) == 1


# ---------------------------------------------------------------------------
# _validate_pipeline_entries — non-dict entry and type errors (lines 149, 154-155, 159, 163, 165)
# ---------------------------------------------------------------------------


class TestValidatePipelineEntriesEdgeCases:
    def test_pipeline_entry_not_dict(self):
        """Line 149: non-dict pipeline entry produces error."""
        from heddle.mcp.config import validate_mcp_config

        config = {"name": "test", "tools": {"pipelines": ["bad-entry"]}}
        errors = validate_mcp_config(config)
        assert any("expected dict" in e for e in errors)

    def test_pipeline_config_wrong_type(self):
        """Lines 154-155: 'config' present but not a string."""
        from heddle.mcp.config import validate_mcp_config

        config = {
            "name": "test",
            "tools": {"pipelines": [{"config": 42, "name": "run_it"}]},
        }
        errors = validate_mcp_config(config)
        assert any("'config' must be a string" in e for e in errors)

    def test_pipeline_name_wrong_type(self):
        """Line 163: 'name' present but not a string."""
        from heddle.mcp.config import validate_mcp_config

        config = {
            "name": "test",
            "tools": {"pipelines": [{"config": "p.yaml", "name": 99}]},
        }
        errors = validate_mcp_config(config)
        assert any("'name' must be a string" in e for e in errors)

    def test_pipeline_description_wrong_type(self):
        """Line 165: 'description' present but not a string."""
        from heddle.mcp.config import validate_mcp_config

        config = {
            "name": "test",
            "tools": {"pipelines": [{"config": "p.yaml", "name": "run_it", "description": 123}]},
        }
        errors = validate_mcp_config(config)
        assert any("'description' must be a string" in e for e in errors)

    def test_pipelines_not_list(self):
        """Line 149: pipelines value not a list returns early."""
        from heddle.mcp.config import validate_mcp_config

        config = {"name": "test", "tools": {"pipelines": "bad"}}
        errors = validate_mcp_config(config)
        assert any("must be a list" in e for e in errors)


# ---------------------------------------------------------------------------
# _validate_query_entries — non-dict and type errors (lines 199, 204-205, 209, 217)
# ---------------------------------------------------------------------------


class TestValidateQueryEntriesEdgeCases:
    def test_query_entry_not_dict(self):
        """Lines 204-205: non-dict query entry produces error."""
        from heddle.mcp.config import validate_mcp_config

        config = {"name": "test", "tools": {"queries": ["not-a-dict"]}}
        errors = validate_mcp_config(config)
        assert any("expected dict" in e for e in errors)

    def test_query_backend_wrong_type(self):
        """Lines 204-205 (backend branch): backend present but not a string."""
        from heddle.mcp.config import validate_mcp_config

        config = {
            "name": "test",
            "tools": {
                "queries": [
                    {
                        "backend": 123,
                        "actions": ["search"],
                        "name_prefix": "q",
                    }
                ]
            },
        }
        errors = validate_mcp_config(config)
        assert any("'backend' must be a string" in e for e in errors)

    def test_query_name_prefix_wrong_type(self):
        """Line 209 (name_prefix branch): name_prefix present but not a string."""
        from heddle.mcp.config import validate_mcp_config

        config = {
            "name": "test",
            "tools": {
                "queries": [
                    {
                        "backend": "my.Backend",
                        "actions": ["search"],
                        "name_prefix": 99,
                    }
                ]
            },
        }
        errors = validate_mcp_config(config)
        assert any("'name_prefix' must be a string" in e for e in errors)

    def test_query_backend_config_wrong_type(self):
        """Line 217: backend_config present but not a dict."""
        from heddle.mcp.config import validate_mcp_config

        config = {
            "name": "test",
            "tools": {
                "queries": [
                    {
                        "backend": "my.Backend",
                        "actions": ["search"],
                        "name_prefix": "q",
                        "backend_config": "should-be-dict",
                    }
                ]
            },
        }
        errors = validate_mcp_config(config)
        assert any("'backend_config' must be a dict" in e for e in errors)

    def test_queries_not_list(self):
        """Line 199: queries value not a list returns early."""
        from heddle.mcp.config import validate_mcp_config

        config = {"name": "test", "tools": {"queries": "bad"}}
        errors = validate_mcp_config(config)
        assert any("must be a list" in e for e in errors)
