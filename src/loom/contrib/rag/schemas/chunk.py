"""Text chunk schemas for RAG splitting."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ChunkStrategy(StrEnum):
    """Chunking strategy used to split post text."""

    WHOLE_POST = "whole_post"
    PARAGRAPH = "paragraph"
    SENTENCE = "sentence"
    FIXED_CHAR = "fixed_char"


class TextChunk(BaseModel, extra="allow"):
    """A contiguous text fragment produced by a chunking stage.

    Carries full provenance: which post, which channel, character offsets,
    and the chunking strategy used.
    """

    chunk_id: str = Field(
        ...,
        description='Format: "{global_id}:{chunk_index}".',
    )
    source_global_id: str
    source_channel_id: int
    source_channel_name: str
    timestamp_unix: int = 0
    text: str
    char_start: int
    char_end: int
    chunk_index: int
    total_chunks: int
    strategy: ChunkStrategy = ChunkStrategy.SENTENCE
    overlap_chars: int = 0
