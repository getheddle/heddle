"""LanceDB integration for Loom — vector store and tools for LanceDB-backed workflows.

Requires the ``lancedb`` optional dependency::

    pip install loom[lancedb]
"""

from loom.contrib.lancedb.store import LanceDBVectorStore
from loom.contrib.lancedb.tool import LanceDBVectorTool

__all__ = [
    "LanceDBVectorStore",
    "LanceDBVectorTool",
]
