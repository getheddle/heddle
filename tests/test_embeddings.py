"""Tests for embedding provider abstraction and Ollama implementation."""

from unittest.mock import AsyncMock

import httpx
import pytest

from loom.worker.embeddings import EmbeddingProvider, OllamaEmbeddingProvider


class TestEmbeddingProviderABC:
    """Tests for the EmbeddingProvider abstract base class."""

    def test_cannot_instantiate(self):
        """EmbeddingProvider is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            EmbeddingProvider()

    def test_requires_embed(self):
        """Subclasses must implement embed()."""

        class Partial(EmbeddingProvider):
            async def embed_batch(self, texts):
                return []

            @property
            def dimensions(self):
                return 0

        with pytest.raises(TypeError):
            Partial()

    def test_requires_embed_batch(self):
        """Subclasses must implement embed_batch()."""

        class Partial(EmbeddingProvider):
            async def embed(self, text):
                return []

            @property
            def dimensions(self):
                return 0

        with pytest.raises(TypeError):
            Partial()

    def test_requires_dimensions(self):
        """Subclasses must implement dimensions property."""

        class Partial(EmbeddingProvider):
            async def embed(self, text):
                return []

            async def embed_batch(self, texts):
                return []

        with pytest.raises(TypeError):
            Partial()


class TestOllamaEmbeddingProvider:
    """Tests for OllamaEmbeddingProvider."""

    def test_default_model(self):
        """Default model is nomic-embed-text."""
        provider = OllamaEmbeddingProvider()
        assert provider.model == "nomic-embed-text"

    def test_custom_model(self):
        """Custom model is accepted."""
        provider = OllamaEmbeddingProvider(model="all-minilm")
        assert provider.model == "all-minilm"

    def test_default_base_url(self):
        """Default base URL is localhost:11434."""
        provider = OllamaEmbeddingProvider()
        assert "11434" in provider.base_url

    def test_custom_base_url(self):
        """Custom base URL is accepted."""
        provider = OllamaEmbeddingProvider(base_url="http://gpu-server:11434")
        assert provider.base_url == "http://gpu-server:11434"

    def test_dimensions_raises_before_first_call(self):
        """Dimensions raises RuntimeError before any embed call."""
        provider = OllamaEmbeddingProvider()
        with pytest.raises(RuntimeError, match="not yet known"):
            _ = provider.dimensions

    @pytest.mark.asyncio
    async def test_embed_single(self):
        """embed() sends correct request and returns embedding."""
        provider = OllamaEmbeddingProvider(
            model="nomic-embed-text",
            base_url="http://test:11434",
        )

        mock_request = httpx.Request("POST", "http://test:11434/api/embed")
        mock_response = httpx.Response(
            200,
            json={"embeddings": [[0.1, 0.2, 0.3, 0.4]]},
            request=mock_request,
        )
        provider._client.post = AsyncMock(return_value=mock_response)

        result = await provider.embed("hello world")
        assert result == [0.1, 0.2, 0.3, 0.4]
        assert provider.dimensions == 4
        provider._client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        """embed_batch() sends batch request and returns all embeddings."""
        provider = OllamaEmbeddingProvider(
            model="nomic-embed-text",
            base_url="http://test:11434",
        )

        mock_request = httpx.Request("POST", "http://test:11434/api/embed")
        mock_response = httpx.Response(
            200,
            json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]},
            request=mock_request,
        )
        provider._client.post = AsyncMock(return_value=mock_response)

        result = await provider.embed_batch(["text1", "text2"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]
        assert provider.dimensions == 2

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self):
        """embed_batch() with empty list returns empty list without HTTP call."""
        provider = OllamaEmbeddingProvider(base_url="http://test:11434")
        result = await provider.embed_batch([])
        assert result == []
