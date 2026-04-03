"""Vector store — embedding storage and similarity search backends."""

from heddle.contrib.rag.vectorstore.base import VectorStore
from heddle.contrib.rag.vectorstore.duckdb_store import DuckDBVectorStore

__all__ = ["DuckDBVectorStore", "VectorStore"]
