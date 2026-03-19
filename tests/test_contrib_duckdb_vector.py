"""Tests for DuckDBVectorTool — semantic similarity search."""

import json

import duckdb
import pytest

from loom.contrib.duckdb import DuckDBVectorTool


@pytest.fixture
def db_with_embeddings(tmp_path):
    """DuckDB database with a table and pre-computed embeddings."""
    db_path = str(tmp_path / "test.duckdb")
    conn = duckdb.connect(db_path)

    conn.execute("""
        CREATE TABLE items (
            id VARCHAR PRIMARY KEY,
            name VARCHAR,
            category VARCHAR,
            description TEXT,
            full_text TEXT,
            embedding FLOAT[],
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Insert records with 4-dimensional embeddings.
    # Vectors chosen so that "tech" items cluster together.
    conn.execute("""
        INSERT INTO items VALUES
        ('i1', 'Laptop', 'tech', 'High-performance laptop', 'Full text about laptops',
         [0.9, 0.1, 0.0, 0.0], CURRENT_TIMESTAMP),
        ('i2', 'Tablet', 'tech', 'Portable tablet device', 'Full text about tablets',
         [0.8, 0.2, 0.1, 0.0], CURRENT_TIMESTAMP),
        ('i3', 'Hammer', 'tools', 'Heavy duty hammer', 'Full text about hammers',
         [0.0, 0.0, 0.9, 0.1], CURRENT_TIMESTAMP),
        ('i4', 'No Embed', 'misc', 'Item without embedding', 'Full text no embed',
         NULL, CURRENT_TIMESTAMP)
    """)

    conn.close()
    return db_path


class TestDuckDBVectorToolDefinition:
    """Tests for tool definition generation."""

    def test_default_tool_name(self, db_with_embeddings):
        tool = DuckDBVectorTool(db_path=db_with_embeddings)
        defn = tool.get_definition()
        assert defn["name"] == "find_similar"

    def test_custom_tool_name(self, db_with_embeddings):
        tool = DuckDBVectorTool(db_path=db_with_embeddings, tool_name="search_items")
        defn = tool.get_definition()
        assert defn["name"] == "search_items"

    def test_has_query_parameter(self, db_with_embeddings):
        tool = DuckDBVectorTool(db_path=db_with_embeddings)
        defn = tool.get_definition()
        assert "query" in defn["parameters"]["properties"]
        assert "query" in defn["parameters"]["required"]

    def test_has_limit_parameter(self, db_with_embeddings):
        tool = DuckDBVectorTool(db_path=db_with_embeddings)
        defn = tool.get_definition()
        assert "limit" in defn["parameters"]["properties"]

    def test_custom_description(self, db_with_embeddings):
        tool = DuckDBVectorTool(
            db_path=db_with_embeddings,
            description="Custom search desc",
        )
        defn = tool.get_definition()
        assert defn["description"] == "Custom search desc"


class TestDuckDBVectorToolSearch:
    """Tests for similarity search execution."""

    def test_search_returns_results(self, db_with_embeddings, monkeypatch):
        """Search returns similar records ranked by cosine similarity."""
        tool = DuckDBVectorTool(
            db_path=db_with_embeddings,
            table_name="items",
            result_columns=["id", "name", "category", "description", "created_at"],
        )

        # Mock the embedding call to return a tech-like vector
        def fake_embed_query(self_tool, text):
            return [0.85, 0.15, 0.0, 0.0]

        monkeypatch.setattr(DuckDBVectorTool, "_embed_query", fake_embed_query)

        result = json.loads(tool.execute_sync({"query": "technology"}))
        assert "results" in result
        assert len(result["results"]) > 0
        # Laptop should be most similar
        assert result["results"][0]["name"] == "Laptop"

    def test_excludes_null_embeddings(self, db_with_embeddings, monkeypatch):
        """Records without embeddings are excluded from results."""
        tool = DuckDBVectorTool(
            db_path=db_with_embeddings,
            table_name="items",
            result_columns=["id", "name", "category"],
        )

        def fake_embed_query(self_tool, text):
            return [0.5, 0.5, 0.5, 0.5]

        monkeypatch.setattr(DuckDBVectorTool, "_embed_query", fake_embed_query)

        result = json.loads(tool.execute_sync({"query": "anything"}))
        names = [r["name"] for r in result["results"]]
        assert "No Embed" not in names

    def test_respects_limit(self, db_with_embeddings, monkeypatch):
        """Limit parameter caps the number of results."""
        tool = DuckDBVectorTool(
            db_path=db_with_embeddings,
            table_name="items",
            result_columns=["id", "name"],
        )

        def fake_embed_query(self_tool, text):
            return [0.5, 0.5, 0.5, 0.5]

        monkeypatch.setattr(DuckDBVectorTool, "_embed_query", fake_embed_query)

        result = json.loads(tool.execute_sync({"query": "test", "limit": 1}))
        assert len(result["results"]) == 1

    def test_max_results_enforcement(self, db_with_embeddings, monkeypatch):
        """Limit is capped at max_results."""
        tool = DuckDBVectorTool(
            db_path=db_with_embeddings,
            table_name="items",
            result_columns=["id", "name"],
            max_results=2,
        )

        def fake_embed_query(self_tool, text):
            return [0.5, 0.5, 0.5, 0.5]

        monkeypatch.setattr(DuckDBVectorTool, "_embed_query", fake_embed_query)

        result = json.loads(tool.execute_sync({"query": "test", "limit": 100}))
        assert len(result["results"]) <= 2

    def test_empty_query(self, db_with_embeddings):
        """Empty query returns empty results without calling Ollama."""
        tool = DuckDBVectorTool(db_path=db_with_embeddings)
        result = json.loads(tool.execute_sync({"query": ""}))
        assert result["results"] == []
        assert result["total"] == 0

    def test_similarity_scores_included(self, db_with_embeddings, monkeypatch):
        """Results include similarity scores."""
        tool = DuckDBVectorTool(
            db_path=db_with_embeddings,
            table_name="items",
            result_columns=["id", "name"],
        )

        def fake_embed_query(self_tool, text):
            return [0.9, 0.1, 0.0, 0.0]

        monkeypatch.setattr(DuckDBVectorTool, "_embed_query", fake_embed_query)

        result = json.loads(tool.execute_sync({"query": "tech"}))
        for r in result["results"]:
            assert "similarity" in r
            assert isinstance(r["similarity"], (int, float))

    def test_embed_failure_returns_error(self, db_with_embeddings, monkeypatch):
        """Failed embedding returns an error dict."""
        tool = DuckDBVectorTool(db_path=db_with_embeddings)

        def fail_embed(self_tool, text):
            return None

        monkeypatch.setattr(DuckDBVectorTool, "_embed_query", fail_embed)

        result = json.loads(tool.execute_sync({"query": "anything"}))
        assert "error" in result


class TestDuckDBVectorToolIntrospection:
    """Tests for automatic column introspection."""

    def test_introspects_columns_when_none(self, db_with_embeddings):
        """result_columns are auto-discovered when not provided."""
        tool = DuckDBVectorTool(
            db_path=db_with_embeddings,
            table_name="items",
        )
        cols = tool.result_columns
        # Should include regular columns but exclude embedding and full_text
        assert "id" in cols
        assert "name" in cols
        assert "embedding" not in cols
        assert "full_text" not in cols

    def test_explicit_columns_used_directly(self, db_with_embeddings):
        """Explicit result_columns bypass introspection."""
        tool = DuckDBVectorTool(
            db_path=db_with_embeddings,
            table_name="items",
            result_columns=["id", "name"],
        )
        assert tool.result_columns == ["id", "name"]

    def test_custom_embedding_column(self, db_with_embeddings):
        """Custom embedding_column is used in queries."""
        tool = DuckDBVectorTool(
            db_path=db_with_embeddings,
            table_name="items",
            embedding_column="embedding",
            result_columns=["id", "name"],
        )
        defn = tool.get_definition()
        # Tool should still work with the standard embedding column
        assert defn["name"] == "find_similar"
