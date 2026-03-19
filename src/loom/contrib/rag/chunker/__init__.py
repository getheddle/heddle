"""Text chunking — split posts into fragments for embedding."""

from loom.contrib.rag.chunker.sentence_chunker import (
    ChunkConfig,
    chunk_mux_entry,
    chunk_post,
)

__all__ = ["ChunkConfig", "chunk_mux_entry", "chunk_post"]
