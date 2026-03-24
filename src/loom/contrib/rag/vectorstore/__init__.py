"""Vector store — embedding storage and similarity search backends."""

from loom.contrib.rag.vectorstore.base import VectorStore
from loom.contrib.rag.vectorstore.duckdb_store import DuckDBVectorStore

__all__ = ["DuckDBVectorStore", "VectorStore"]
