"""Tests for DuckDBViewTool — LLM-callable DuckDB view query tool."""

import json

import duckdb
import pytest

from heddle.contrib.duckdb import DuckDBViewTool


@pytest.fixture
def db_with_view(tmp_path):
    """Create a DuckDB database with a table and view, populated with test data."""
    db_path = str(tmp_path / "test.duckdb")
    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE items (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            category VARCHAR,
            description TEXT,
            price DOUBLE,
            active BOOLEAN,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE VIEW item_summaries AS
        SELECT id, name, category, description, price, active, created_at
        FROM items
    """)

    conn.execute("""
        INSERT INTO items (id, name, category, description, price, active)
        VALUES
            ('i1', 'Widget A', 'tools', 'A useful widget for building', 9.99, true),
            ('i2', 'Gadget B', 'electronics', 'An electronic gadget', 24.50, true),
            ('i3', 'Tool C', 'tools', 'A power tool for construction', 149.00, false),
            ('i4', 'Device D', 'electronics', 'A smart device for home', 199.00, true)
    """)
    conn.close()
    return db_path


class TestDuckDBViewToolDefinition:
    """Tests for tool definition generation."""

    def test_definition_has_correct_name(self, db_with_view):
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        defn = tool.get_definition()
        assert defn["name"] == "query_item_summaries"

    def test_definition_has_operations(self, db_with_view):
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        defn = tool.get_definition()
        ops = defn["parameters"]["properties"]["operation"]
        assert ops["enum"] == ["search", "list"]

    def test_definition_includes_filter_columns(self, db_with_view):
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        defn = tool.get_definition()
        filters = defn["parameters"]["properties"]["filters"]["properties"]
        assert "category" in filters
        assert "price" in filters
        assert "active" in filters

    def test_custom_description(self, db_with_view):
        tool = DuckDBViewTool(
            db_path=db_with_view,
            view_name="item_summaries",
            description="Custom tool description",
        )
        defn = tool.get_definition()
        assert defn["description"] == "Custom tool description"

    def test_is_tool_provider_subclass(self, db_with_view):
        from heddle.worker.tools import ToolProvider

        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        assert isinstance(tool, ToolProvider)


class TestDuckDBViewToolSearch:
    """Tests for search operation."""

    def test_search_finds_matching_records(self, db_with_view):
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        result = json.loads(tool.execute_sync({"operation": "search", "query": "widget"}))
        assert result["total"] >= 1
        assert any(
            "widget" in r.get("name", "").lower() or "widget" in r.get("description", "").lower()
            for r in result["results"]
        )

    def test_search_empty_query_returns_empty(self, db_with_view):
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        result = json.loads(tool.execute_sync({"operation": "search", "query": ""}))
        assert result["results"] == []
        assert result["total"] == 0

    def test_search_no_matches(self, db_with_view):
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        result = json.loads(tool.execute_sync({"operation": "search", "query": "xyznonexistent"}))
        assert result["total"] == 0

    def test_search_respects_limit(self, db_with_view):
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        result = json.loads(tool.execute_sync({"operation": "search", "query": "e", "limit": 2}))
        assert len(result["results"]) <= 2

    def test_search_case_insensitive(self, db_with_view):
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        result = json.loads(tool.execute_sync({"operation": "search", "query": "WIDGET"}))
        assert result["total"] >= 1


class TestDuckDBViewToolList:
    """Tests for list operation."""

    def test_list_all_records(self, db_with_view):
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        result = json.loads(tool.execute_sync({"operation": "list", "limit": 100}))
        assert result["total"] == 4

    def test_list_with_filter(self, db_with_view):
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        result = json.loads(
            tool.execute_sync(
                {
                    "operation": "list",
                    "filters": {"category": "tools"},
                }
            )
        )
        assert result["total"] >= 1
        assert all(r["category"] == "tools" for r in result["results"])

    def test_list_with_boolean_filter(self, db_with_view):
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        result = json.loads(
            tool.execute_sync(
                {
                    "operation": "list",
                    "filters": {"active": True},
                }
            )
        )
        assert result["total"] >= 1
        assert all(r["active"] is True for r in result["results"])

    def test_list_respects_limit(self, db_with_view):
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        result = json.loads(tool.execute_sync({"operation": "list", "limit": 2}))
        assert len(result["results"]) == 2

    def test_list_ignores_invalid_filter_columns(self, db_with_view):
        """Filters on columns not in the view are silently ignored."""
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        result = json.loads(
            tool.execute_sync(
                {
                    "operation": "list",
                    "filters": {"nonexistent_col": "value"},
                }
            )
        )
        assert result["total"] == 4


class TestDuckDBViewToolLimits:
    """Tests for max_results enforcement."""

    def test_max_results_caps_limit(self, db_with_view):
        tool = DuckDBViewTool(
            db_path=db_with_view,
            view_name="item_summaries",
            max_results=2,
        )
        result = json.loads(tool.execute_sync({"operation": "list", "limit": 100}))
        assert len(result["results"]) <= 2

    def test_error_on_bad_db(self, tmp_path):
        """Graceful error when database doesn't exist."""
        tool = DuckDBViewTool(
            db_path=str(tmp_path / "nonexistent.duckdb"),
            view_name="item_summaries",
        )
        result = json.loads(tool.execute_sync({"operation": "list"}))
        assert "error" in result or result.get("total", 0) == 0


class TestDuckDBViewToolSQLInjection:
    """Verify parameterized queries prevent SQL injection."""

    def test_search_injection_attempt(self, db_with_view):
        """SQL injection in search query is safely escaped."""
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        result = json.loads(
            tool.execute_sync(
                {
                    "operation": "search",
                    "query": "'; DROP TABLE items; --",
                }
            )
        )
        assert isinstance(result, dict)

        # Verify table still exists
        conn = duckdb.connect(db_with_view, read_only=True)
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        conn.close()
        assert count == 4

    def test_filter_injection_attempt(self, db_with_view):
        """SQL injection in filter values is safely escaped."""
        tool = DuckDBViewTool(db_path=db_with_view, view_name="item_summaries")
        result = json.loads(
            tool.execute_sync(
                {
                    "operation": "list",
                    "filters": {"category": "'; DROP TABLE items; --"},
                }
            )
        )
        assert isinstance(result, dict)
