"""Tests for embedding provider abstraction and Ollama implementation."""

from unittest.mock import AsyncMock

import httpx
import pytest

from heddle.worker.embeddings import (
    EmbeddingProvider,
    OllamaEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)


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


class TestOpenAICompatibleEmbeddingProvider:
    """Tests for OpenAICompatibleEmbeddingProvider (LM Studio etc.)."""

    def test_default_base_url_strips_v1(self):
        """Default base URL is the LM Studio default with trailing /v1 stripped."""
        provider = OpenAICompatibleEmbeddingProvider()
        # Internal storage normalizes /v1 away — the request path
        # appends /v1/embeddings to reach the right URL.
        assert provider.base_url == "http://localhost:1234"

    def test_custom_base_url_with_v1(self):
        provider = OpenAICompatibleEmbeddingProvider(base_url="http://gpu:8000/v1")
        assert provider.base_url == "http://gpu:8000"

    def test_custom_base_url_without_v1(self):
        provider = OpenAICompatibleEmbeddingProvider(base_url="http://gpu:8000")
        assert provider.base_url == "http://gpu:8000"

    def test_uses_lm_studio_url_env_fallback(self, monkeypatch):
        monkeypatch.setenv("LM_STUDIO_URL", "http://env-host:1234/v1")
        provider = OpenAICompatibleEmbeddingProvider()
        assert provider.base_url == "http://env-host:1234"

    def test_dimensions_raises_before_first_call(self):
        provider = OpenAICompatibleEmbeddingProvider()
        with pytest.raises(RuntimeError, match="not yet known"):
            _ = provider.dimensions

    @pytest.mark.asyncio
    async def test_embed_single(self):
        """embed() posts to /v1/embeddings and parses OpenAI shape."""
        provider = OpenAICompatibleEmbeddingProvider(
            model="text-embedding-nomic-embed-text-v1.5",
            base_url="http://test:1234/v1",
        )

        mock_request = httpx.Request("POST", "http://test:1234/v1/embeddings")
        mock_response = httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}],
            },
            request=mock_request,
        )
        mock_post = AsyncMock(return_value=mock_response)
        provider._client.post = mock_post

        result = await provider.embed("hello world")
        assert result == [0.1, 0.2, 0.3]
        assert provider.dimensions == 3

        # Confirm we hit /v1/embeddings (not /v1/v1/embeddings).
        called_path = mock_post.call_args[0][0]
        assert called_path == "/v1/embeddings"

    @pytest.mark.asyncio
    async def test_embed_batch_in_input_order(self):
        """embed_batch() preserves order via the OpenAI 'index' field."""
        provider = OpenAICompatibleEmbeddingProvider(
            model="text-embedding-3-small",
            base_url="http://test:1234/v1",
        )

        # Server returns out of order — provider should re-sort by index.
        mock_response = httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.9, 0.9]},
                    {"object": "embedding", "index": 0, "embedding": [0.1, 0.1]},
                ],
            },
            request=httpx.Request("POST", "http://test:1234/v1/embeddings"),
        )
        provider._client.post = AsyncMock(return_value=mock_response)

        result = await provider.embed_batch(["text1", "text2"])
        assert result[0] == [0.1, 0.1]
        assert result[1] == [0.9, 0.9]
        assert provider.dimensions == 2

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self):
        """Empty input list returns empty without an HTTP call."""
        provider = OpenAICompatibleEmbeddingProvider(base_url="http://test:1234/v1")
        result = await provider.embed_batch([])
        assert result == []
