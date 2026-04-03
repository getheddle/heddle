"""LanceDB integration for Heddle — vector store and tools for LanceDB-backed workflows.

Requires the ``lancedb`` optional dependency::

    pip install heddle-ai[lancedb]
"""

from heddle.contrib.lancedb.store import LanceDBVectorStore
from heddle.contrib.lancedb.tool import LanceDBVectorTool

__all__ = [
    "LanceDBVectorStore",
    "LanceDBVectorTool",
]
