"""DuckDB integration for Heddle — tools and backends for DuckDB-backed workflows.

Requires the ``duckdb`` optional dependency::

    pip install heddle-ai[duckdb]
"""

from heddle.contrib.duckdb.query_backend import DuckDBQueryBackend, DuckDBQueryError
from heddle.contrib.duckdb.vector_tool import DuckDBVectorTool
from heddle.contrib.duckdb.view_tool import DuckDBViewTool

__all__ = [
    "DuckDBQueryBackend",
    "DuckDBQueryError",
    "DuckDBVectorTool",
    "DuckDBViewTool",
]
