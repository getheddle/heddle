"""Vector store interface for RAG retrieval.

All vector store backends (DuckDB, LanceDB, etc.) extend :class:`VectorStore`
and provide embedding storage and similarity search over text chunks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..schemas.chunk import TextChunk
    from ..schemas.embedding import EmbeddedChunk, SimilarityResult


class VectorStore(ABC):
    """Base class for vector store backends.

    Subclasses must implement all abstract methods. The interface supports:
      - Batch insertion of raw text chunks (with embedding generation)
      - Insertion of pre-embedded chunks
      - Cosine similarity search with optional metadata filters
      - Single-item get/delete and source-level delete
      - Statistics and counts

    Usage::

        store = MyVectorStore("/tmp/vectors.db")
        store.initialize()
        store.add_chunks(chunks)
        results = store.search("query text", limit=5)
        store.close()
    """

    @abstractmethod
    def initialize(self) -> VectorStore:
        """Create the backing storage (tables, indexes, etc.) if needed.

        Returns ``self`` for chaining.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Release resources and close connections."""
        ...

    @abstractmethod
    def add_chunks(
        self,
        chunks: list[TextChunk],
        batch_size: int = 64,
    ) -> int:
        """Embed and insert TextChunk objects.

        Returns count of successfully inserted rows.
        """
        ...

    @abstractmethod
    def add_embedded_chunks(self, chunks: list[EmbeddedChunk]) -> int:
        """Insert pre-embedded chunks (no embedding generation needed).

        Returns count of successfully inserted rows.
        """
        ...

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
        channel_ids: list[int] | None = None,
    ) -> list[SimilarityResult]:
        """Semantic similarity search.

        Args:
            query:       Natural language query text
            limit:       Maximum results to return
            min_score:   Minimum similarity score threshold
            channel_ids: Optional filter by source channel ID

        Returns:
            List of SimilarityResult sorted by descending similarity
        """
        ...

    @abstractmethod
    def get(self, chunk_id: str) -> EmbeddedChunk | None:
        """Retrieve a single embedded chunk by ID."""
        ...

    @abstractmethod
    def delete(self, chunk_id: str) -> bool:
        """Delete a chunk by ID. Returns True if a row was deleted."""
        ...

    @abstractmethod
    def delete_by_source(self, source_global_id: str) -> int:
        """Delete all chunks for a given source post. Returns count."""
        ...

    @abstractmethod
    def count(self) -> int:
        """Return total number of stored chunks."""
        ...

    @abstractmethod
    def stats(self) -> dict[str, Any]:
        """Return summary statistics about the store."""
        ...
