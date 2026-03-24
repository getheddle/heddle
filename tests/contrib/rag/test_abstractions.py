"""Tests for RAG abstraction layer — Ingestor and VectorStore ABCs."""

import pytest


class TestIngestorABC:
    """Verify the Ingestor ABC contract."""

    def test_abc_cannot_be_instantiated(self):
        from loom.contrib.rag.ingestion.base import Ingestor

        with pytest.raises(TypeError):
            Ingestor()

    def test_telegram_ingestor_is_subclass(self):
        from loom.contrib.rag.ingestion.base import Ingestor
        from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor

        assert issubclass(TelegramIngestor, Ingestor)

    def test_ingest_all_default(self):
        """ingest_all() is a concrete method that calls ingest()."""
        from loom.contrib.rag.ingestion.base import Ingestor

        class DummyIngestor(Ingestor):
            def load(self):
                return self

            def ingest(self):
                yield "a"
                yield "b"

        d = DummyIngestor()
        assert d.ingest_all() == ["a", "b"]

    def test_exports(self):
        from loom.contrib.rag.ingestion import Ingestor, TelegramIngestor

        assert Ingestor is not None
        assert TelegramIngestor is not None


class TestVectorStoreABC:
    """Verify the VectorStore ABC contract."""

    def test_abc_cannot_be_instantiated(self):
        from loom.contrib.rag.vectorstore.base import VectorStore

        with pytest.raises(TypeError):
            VectorStore()

    def test_duckdb_store_is_subclass(self):
        from loom.contrib.rag.vectorstore.base import VectorStore
        from loom.contrib.rag.vectorstore.duckdb_store import DuckDBVectorStore

        assert issubclass(DuckDBVectorStore, VectorStore)

    def test_exports(self):
        from loom.contrib.rag.vectorstore import DuckDBVectorStore, VectorStore

        assert VectorStore is not None
        assert DuckDBVectorStore is not None


class TestIngestorBackendConfigurable:
    """Test that IngestorBackend supports configurable ingestor classes."""

    def test_default_uses_telegram(self):
        from loom.contrib.rag.backends import IngestorBackend
        from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor

        backend = IngestorBackend()
        cls = backend._resolve_ingestor_class()
        assert cls is TelegramIngestor

    def test_custom_class_resolution(self):
        from loom.contrib.rag.backends import IngestorBackend

        backend = IngestorBackend(
            ingestor_class="loom.contrib.rag.ingestion.telegram_ingestor.TelegramIngestor"
        )
        cls = backend._resolve_ingestor_class()
        # Should resolve to the same class
        from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor
        assert cls is TelegramIngestor


class TestVectorStoreBackendConfigurable:
    """Test that VectorStoreBackend supports configurable store classes."""

    def test_default_uses_duckdb(self):
        from loom.contrib.rag.backends import VectorStoreBackend
        from loom.contrib.rag.vectorstore.duckdb_store import DuckDBVectorStore

        backend = VectorStoreBackend()
        cls = backend._resolve_store_class()
        assert cls is DuckDBVectorStore

    def test_custom_class_resolution(self):
        from loom.contrib.rag.backends import VectorStoreBackend

        backend = VectorStoreBackend(
            store_class="loom.contrib.rag.vectorstore.duckdb_store.DuckDBVectorStore"
        )
        cls = backend._resolve_store_class()
        from loom.contrib.rag.vectorstore.duckdb_store import DuckDBVectorStore
        assert cls is DuckDBVectorStore
