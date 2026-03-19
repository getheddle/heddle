"""DuckDB integration for Loom — tools and backends for DuckDB-backed workflows.

Requires the ``duckdb`` optional dependency::

    pip install loom[duckdb]
"""

from loom.contrib.duckdb.query_backend import DuckDBQueryBackend, DuckDBQueryError
from loom.contrib.duckdb.vector_tool import DuckDBVectorTool
from loom.contrib.duckdb.view_tool import DuckDBViewTool

__all__ = [
    "DuckDBQueryBackend",
    "DuckDBQueryError",
    "DuckDBVectorTool",
    "DuckDBViewTool",
]
