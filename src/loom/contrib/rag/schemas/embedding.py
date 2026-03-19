"""Embedding and vector store schemas for RAG retrieval."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class EmbeddedChunk(BaseModel, extra="allow"):
    """A text chunk paired with its dense vector embedding."""

    chunk_id: str
    source_global_id: str
    source_channel_id: int
    text: str
    embedding: list[float]
    model: str
    dimensions: int
    embedded_at: datetime = Field(default_factory=_utcnow)


class SimilarityResult(BaseModel, extra="allow"):
    """A single result from vector similarity search."""

    chunk_id: str
    text: str
    score: float = Field(ge=0.0, le=1.0)
    source_channel_id: int
    source_global_id: str
    metadata: dict = Field(default_factory=dict)
