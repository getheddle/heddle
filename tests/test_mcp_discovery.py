"""Tests for loom.mcp.discovery — tool definition generation."""
import os
import tempfile

import pytest
import yaml

from loom.mcp.discovery import (
    discover_pipeline_tools,
    discover_query_tools,
    discover_worker_tools,
    make_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(dir_path: str, filename: str, data: dict) -> str:
    path = os.path.join(dir_path, filename)
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


# ---------------------------------------------------------------------------
# make_tool
# ---------------------------------------------------------------------------


class TestMakeTool:
    def test_basic(self):
        tool = make_tool("my_tool", "Does stuff", {"type": "object"})
        assert tool["name"] == "my_tool"
        assert tool["description"] == "Does stuff"
        assert tool["inputSchema"] == {"type": "object"}


# ---------------------------------------------------------------------------
# Worker tools
# ---------------------------------------------------------------------------


class TestDiscoverWorkerTools:
    def test_basic_worker(self, tmp_path):
        worker_cfg = {
            "name": "summarizer",
            "system_prompt": "Summarize the input document.\nBe concise.",
            "input_schema": {
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string"},
                },
            },
            "default_model_tier": "standard",
            "timeout_seconds": 120,
        }
        config_path = _write_yaml(str(tmp_path), "summarizer.yaml", worker_cfg)

        entries = [{"config": config_path}]
        tools = discover_worker_tools(entries)

        assert len(tools) == 1
        tool = tools[0]
        assert tool["name"] == "summarizer"
        assert tool["description"] == "Summarize the input document."
        assert tool["inputSchema"]["required"] == ["text"]

        # Verify _loom metadata.
        loom = tool["_loom"]
        assert loom["kind"] == "worker"
        assert loom["worker_type"] == "summarizer"
        assert loom["tier"] == "standard"
        assert loom["timeout"] == 120

    def test_name_and_description_override(self, tmp_path):
        worker_cfg = {
            "name": "classifier",
            "system_prompt": "Original description.",
            "input_schema": {"type": "object"},
        }
        config_path = _write_yaml(str(tmp_path), "classifier.yaml", worker_cfg)

        entries = [{
            "config": config_path,
            "name": "classify_document",
            "description": "Custom description",
            "tier": "local",
        }]
        tools = discover_worker_tools(entries)

        assert tools[0]["name"] == "classify_document"
        assert tools[0]["description"] == "Custom description"
        assert tools[0]["_loom"]["tier"] == "local"

    def test_description_from_worker_config(self, tmp_path):
        """Worker config 'description' field is used when no MCP override."""
        worker_cfg = {
            "name": "summarizer",
            "description": "Compresses text to a structured summary.",
            "system_prompt": "You are a text summarizer.\nBe concise.",
            "input_schema": {"type": "object"},
        }
        config_path = _write_yaml(str(tmp_path), "summarizer.yaml", worker_cfg)

        entries = [{"config": config_path}]
        tools = discover_worker_tools(entries)

        # Should use 'description' not first line of system_prompt.
        assert tools[0]["description"] == "Compresses text to a structured summary."

    def test_missing_config_skips_worker(self):
        entries = [{"config": "/nonexistent/worker.yaml"}]
        tools = discover_worker_tools(entries)
        assert tools == []

    def test_bare_schema_gets_wrapped(self, tmp_path):
        """If input_schema lacks 'type', it gets wrapped as properties."""
        worker_cfg = {
            "name": "bare",
            "system_prompt": "Test",
            "input_schema": {
                "text": {"type": "string"},
            },
        }
        config_path = _write_yaml(str(tmp_path), "bare.yaml", worker_cfg)
        entries = [{"config": config_path}]
        tools = discover_worker_tools(entries)

        schema = tools[0]["inputSchema"]
        assert schema["type"] == "object"
        assert "text" in schema["properties"]


# ---------------------------------------------------------------------------
# Pipeline tools
# ---------------------------------------------------------------------------


class TestDiscoverPipelineTools:
    def test_basic_pipeline(self, tmp_path):
        pipeline_cfg = {
            "name": "doc_pipeline",
            "pipeline_stages": [
                {
                    "name": "extract",
                    "worker_type": "doc_extractor",
                    "input_mapping": {
                        "file_ref": "goal.context.file_ref",
                    },
                },
                {
                    "name": "classify",
                    "worker_type": "doc_classifier",
                    "input_mapping": {
                        "text": "extract.output.text",
                    },
                },
            ],
            "timeout_seconds": 600,
        }
        config_path = _write_yaml(str(tmp_path), "pipeline.yaml", pipeline_cfg)

        entries = [{
            "config": config_path,
            "name": "process_document",
            "description": "Full doc pipeline",
        }]
        tools = discover_pipeline_tools(entries)

        assert len(tools) == 1
        tool = tools[0]
        assert tool["name"] == "process_document"
        assert tool["description"] == "Full doc pipeline"

        # Input schema should derive from goal.context.* references.
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert "file_ref" in schema["properties"]
        assert "file_ref" in schema["required"]

        loom = tool["_loom"]
        assert loom["kind"] == "pipeline"
        assert loom["timeout"] == 600

    def test_multi_stage_context_fields(self, tmp_path):
        """goal.context.* refs in later stages should also appear in schema."""
        pipeline_cfg = {
            "name": "multi",
            "pipeline_stages": [
                {
                    "name": "stage1",
                    "worker_type": "w1",
                    "input_mapping": {"file_ref": "goal.context.file_ref"},
                },
                {
                    "name": "stage2",
                    "worker_type": "w2",
                    "input_mapping": {
                        "text": "stage1.output.text",
                        "lang": "goal.context.lang",
                    },
                },
            ],
        }
        config_path = _write_yaml(str(tmp_path), "multi.yaml", pipeline_cfg)
        entries = [{"config": config_path, "name": "multi_tool"}]
        tools = discover_pipeline_tools(entries)

        schema = tools[0]["inputSchema"]
        assert "file_ref" in schema["properties"]
        assert "lang" in schema["properties"]

    def test_no_stages_returns_open_schema(self, tmp_path):
        pipeline_cfg = {"name": "empty", "pipeline_stages": []}
        config_path = _write_yaml(str(tmp_path), "empty.yaml", pipeline_cfg)
        entries = [{"config": config_path, "name": "empty_tool"}]
        tools = discover_pipeline_tools(entries)
        assert tools[0]["inputSchema"] == {"type": "object"}

    def test_missing_config_skips(self):
        entries = [{"config": "/nonexistent/pipeline.yaml", "name": "missing"}]
        tools = discover_pipeline_tools(entries)
        assert tools == []


# ---------------------------------------------------------------------------
# Query tools
# ---------------------------------------------------------------------------


class _MockQueryBackend:
    """Minimal mock of a query backend for testing discovery."""

    table_name = "documents"
    filter_fields = {
        "doc_type": "doc_type = ?",
        "has_tables": "has_tables::BOOLEAN",
        "page_count": "page_count >= ?",
    }
    stats_groups = {"doc_type", "status"}
    id_column = "doc_id"

    def _get_handlers(self):
        return {
            "search": self._search,
            "filter": self._filter,
            "stats": self._stats,
            "get": self._get,
        }

    def _search(self, **kw): pass
    def _filter(self, **kw): pass
    def _stats(self, **kw): pass
    def _get(self, **kw): pass


class TestDiscoverQueryTools:
    def test_basic_query_tools(self, monkeypatch):
        """Test query tool discovery with a mock backend."""
        # Monkeypatch _instantiate_backend to return our mock.
        import loom.mcp.discovery as disc
        monkeypatch.setattr(disc, "_instantiate_backend", lambda path, cfg: _MockQueryBackend())

        entries = [{
            "backend": "mock.MockQueryBackend",
            "backend_config": {},
            "actions": ["search", "filter", "stats", "get"],
            "name_prefix": "docs",
        }]
        tools = discover_query_tools(entries)

        names = {t["name"] for t in tools}
        assert names == {"docs_search", "docs_filter", "docs_stats", "docs_get"}

    def test_search_schema(self, monkeypatch):
        import loom.mcp.discovery as disc
        monkeypatch.setattr(disc, "_instantiate_backend", lambda path, cfg: _MockQueryBackend())

        entries = [{
            "backend": "mock.MockQueryBackend",
            "backend_config": {},
            "actions": ["search"],
            "name_prefix": "docs",
        }]
        tools = discover_query_tools(entries)
        schema = tools[0]["inputSchema"]
        assert schema["required"] == ["query"]
        assert "query" in schema["properties"]

    def test_filter_schema_infers_types(self, monkeypatch):
        import loom.mcp.discovery as disc
        monkeypatch.setattr(disc, "_instantiate_backend", lambda path, cfg: _MockQueryBackend())

        entries = [{
            "backend": "mock.MockQueryBackend",
            "backend_config": {},
            "actions": ["filter"],
            "name_prefix": "docs",
        }]
        tools = discover_query_tools(entries)
        schema = tools[0]["inputSchema"]

        # has_tables should be boolean (BOOLEAN in SQL)
        assert schema["properties"]["has_tables"]["type"] == "boolean"
        # page_count should be integer (>= in SQL)
        assert schema["properties"]["page_count"]["type"] == "integer"
        # doc_type should be string (default)
        assert schema["properties"]["doc_type"]["type"] == "string"

    def test_stats_schema(self, monkeypatch):
        import loom.mcp.discovery as disc
        monkeypatch.setattr(disc, "_instantiate_backend", lambda path, cfg: _MockQueryBackend())

        entries = [{
            "backend": "mock.MockQueryBackend",
            "backend_config": {},
            "actions": ["stats"],
            "name_prefix": "docs",
        }]
        tools = discover_query_tools(entries)
        schema = tools[0]["inputSchema"]
        assert "group_by" in schema["properties"]

    def test_get_schema_uses_id_column(self, monkeypatch):
        import loom.mcp.discovery as disc
        monkeypatch.setattr(disc, "_instantiate_backend", lambda path, cfg: _MockQueryBackend())

        entries = [{
            "backend": "mock.MockQueryBackend",
            "backend_config": {},
            "actions": ["get"],
            "name_prefix": "docs",
        }]
        tools = discover_query_tools(entries)
        schema = tools[0]["inputSchema"]
        assert "doc_id" in schema["required"]
        assert "doc_id" in schema["properties"]

    def test_unknown_action_skipped(self, monkeypatch):
        import loom.mcp.discovery as disc
        monkeypatch.setattr(disc, "_instantiate_backend", lambda path, cfg: _MockQueryBackend())

        entries = [{
            "backend": "mock.MockQueryBackend",
            "backend_config": {},
            "actions": ["search", "nonexistent"],
            "name_prefix": "docs",
        }]
        tools = discover_query_tools(entries)
        assert len(tools) == 1
        assert tools[0]["name"] == "docs_search"

    def test_backend_instantiation_failure_skips(self, monkeypatch):
        import loom.mcp.discovery as disc
        monkeypatch.setattr(disc, "_instantiate_backend", lambda path, cfg: None)

        entries = [{
            "backend": "bad.Backend",
            "backend_config": {},
            "actions": ["search"],
            "name_prefix": "bad",
        }]
        tools = discover_query_tools(entries)
        assert tools == []

    def test_loom_metadata(self, monkeypatch):
        import loom.mcp.discovery as disc
        monkeypatch.setattr(disc, "_instantiate_backend", lambda path, cfg: _MockQueryBackend())

        entries = [{
            "backend": "mock.MockQueryBackend",
            "backend_config": {"db_path": "/tmp/test.db"},
            "actions": ["search"],
            "name_prefix": "docs",
            "worker_type": "docs_query",
            "timeout": 45,
        }]
        tools = discover_query_tools(entries)
        loom = tools[0]["_loom"]
        assert loom["kind"] == "query"
        assert loom["worker_type"] == "docs_query"
        assert loom["action"] == "search"
        assert loom["timeout"] == 45
