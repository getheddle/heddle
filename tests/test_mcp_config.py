"""Tests for loom.mcp.config — MCP gateway config loading and validation."""

from loom.mcp.config import validate_mcp_config


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
