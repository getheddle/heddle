"""
Embedding provider abstraction for vector generation.

Workers and tools can generate vector embeddings from text via an
EmbeddingProvider. The default implementation uses Ollama's /api/embed
endpoint with models like nomic-embed-text.

Example usage::

    provider = OllamaEmbeddingProvider(model="nomic-embed-text")
    vector = await provider.embed("some text to embed")
    vectors = await provider.embed_batch(["text 1", "text 2"])
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import httpx
import structlog

logger = structlog.get_logger()


class EmbeddingProvider(ABC):
    """Common interface for generating vector embeddings from text."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return embedding vector for the given text."""
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a batch of texts."""
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the dimensionality of embeddings produced by this provider."""
        ...


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Generate embeddings via Ollama's /api/embed endpoint.

    Uses the Ollama embedding API which supports both single and batch
    embedding generation. Dimensions are detected lazily from the first
    embedding call and cached.

    Args:
        model: Embedding model name (default: "nomic-embed-text").
        base_url: Ollama server URL. Falls back to OLLAMA_URL env var,
            then "http://localhost:11434".
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url or os.environ.get("OLLAMA_URL") or "http://localhost:11434"
        self._dimensions: int | None = None
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text string."""
        resp = await self._client.post(
            "/api/embed",
            json={"model": self.model, "input": text},
        )
        resp.raise_for_status()
        data = resp.json()
        embedding = data["embeddings"][0]

        # Cache dimensions from first call
        if self._dimensions is None:
            self._dimensions = len(embedding)

        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts in one call.

        Ollama's /api/embed supports batch input via the ``input`` field
        accepting a list of strings.
        """
        if not texts:
            return []

        resp = await self._client.post(
            "/api/embed",
            json={"model": self.model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data["embeddings"]

        if self._dimensions is None and embeddings:
            self._dimensions = len(embeddings[0])

        return embeddings

    @property
    def dimensions(self) -> int:
        """Return embedding dimensionality (detected from first call)."""
        if self._dimensions is None:
            raise RuntimeError(
                "Embedding dimensions not yet known. Call embed() or embed_batch() first."
            )
        return self._dimensions
