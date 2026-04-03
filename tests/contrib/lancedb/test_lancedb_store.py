"""Unit tests for heddle.contrib.lancedb.store — LanceDB vector store."""

import pytest


def _can_import_lancedb():
    try:
        import lancedb  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.fixture
def lance_db_path(tmp_path):
    """Provide a temporary path for a LanceDB database."""
    return str(tmp_path / "test-vectors.lance")


def _mock_embed_batch(texts):
    """Return deterministic fake embeddings."""
    return [[float(i) / 10.0] * 8 for i in range(len(texts))]


def _make_text_chunk(chunk_id="c1", source_global_id="99:1", channel_id=99, text="test text"):
    """Create a TextChunk for testing."""
    from heddle.contrib.rag.schemas.chunk import TextChunk

    return TextChunk(
        chunk_id=chunk_id,
        source_global_id=source_global_id,
        source_channel_id=channel_id,
        source_channel_name="test_channel",
        text=text,
        char_start=0,
        char_end=len(text),
        chunk_index=0,
        total_chunks=1,
        timestamp_unix=1740826800,
    )


def _make_embedded_chunk(chunk_id="ec1", source_global_id="99:1", channel_id=99):
    """Create an EmbeddedChunk for testing."""
    from heddle.contrib.rag.schemas.embedding import EmbeddedChunk

    return EmbeddedChunk(
        chunk_id=chunk_id,
        source_global_id=source_global_id,
        source_channel_id=channel_id,
        text="pre-embedded test text",
        embedding=[0.1] * 8,
        model="test-model",
        dimensions=8,
    )


class TestLanceDBVectorStoreInterface:
    """Test that LanceDBVectorStore implements the VectorStore ABC."""

    def test_extends_vector_store(self):
        from heddle.contrib.lancedb.store import LanceDBVectorStore
        from heddle.contrib.rag.vectorstore.base import VectorStore

        assert issubclass(LanceDBVectorStore, VectorStore)

    @pytest.mark.skipif(
        not _can_import_lancedb(),
        reason="lancedb not installed",
    )
    def test_initialize_creates_db(self, lance_db_path):
        from heddle.contrib.lancedb.store import LanceDBVectorStore

        store = LanceDBVectorStore(db_path=lance_db_path)
        store.initialize()
        assert store.count() == 0
        store.close()

    @pytest.mark.skipif(
        not _can_import_lancedb(),
        reason="lancedb not installed",
    )
    def test_empty_stats(self, lance_db_path):
        from heddle.contrib.lancedb.store import LanceDBVectorStore

        store = LanceDBVectorStore(db_path=lance_db_path).initialize()
        stats = store.stats()
        assert stats["total_chunks"] == 0
        store.close()

    @pytest.mark.skipif(
        not _can_import_lancedb(),
        reason="lancedb not installed",
    )
    def test_add_embedded_chunks(self, lance_db_path):
        from heddle.contrib.lancedb.store import LanceDBVectorStore

        store = LanceDBVectorStore(db_path=lance_db_path).initialize()
        ec = _make_embedded_chunk()
        count = store.add_embedded_chunks([ec])
        assert count == 1
        assert store.count() == 1
        store.close()

    @pytest.mark.skipif(
        not _can_import_lancedb(),
        reason="lancedb not installed",
    )
    def test_get_chunk(self, lance_db_path):
        from heddle.contrib.lancedb.store import LanceDBVectorStore

        store = LanceDBVectorStore(db_path=lance_db_path).initialize()
        ec = _make_embedded_chunk(chunk_id="get-test")
        store.add_embedded_chunks([ec])

        result = store.get("get-test")
        assert result is not None
        assert result.chunk_id == "get-test"
        assert result.text == "pre-embedded test text"

        assert store.get("nonexistent") is None
        store.close()

    @pytest.mark.skipif(
        not _can_import_lancedb(),
        reason="lancedb not installed",
    )
    def test_delete_chunk(self, lance_db_path):
        from heddle.contrib.lancedb.store import LanceDBVectorStore

        store = LanceDBVectorStore(db_path=lance_db_path).initialize()
        ec = _make_embedded_chunk(chunk_id="del-test")
        store.add_embedded_chunks([ec])
        assert store.count() == 1

        assert store.delete("del-test") is True
        assert store.count() == 0
        assert store.delete("del-test") is False
        store.close()

    @pytest.mark.skipif(
        not _can_import_lancedb(),
        reason="lancedb not installed",
    )
    def test_delete_by_source(self, lance_db_path):
        from heddle.contrib.lancedb.store import LanceDBVectorStore

        store = LanceDBVectorStore(db_path=lance_db_path).initialize()
        ec1 = _make_embedded_chunk(chunk_id="s1-c1", source_global_id="99:1")
        ec2 = _make_embedded_chunk(chunk_id="s1-c2", source_global_id="99:1")
        ec3 = _make_embedded_chunk(chunk_id="s2-c1", source_global_id="99:2")
        store.add_embedded_chunks([ec1, ec2, ec3])
        assert store.count() == 3

        deleted = store.delete_by_source("99:1")
        assert deleted == 2
        assert store.count() == 1
        store.close()


class TestLanceDBVectorStoreImport:
    """Test import/export without requiring lancedb installed."""

    def test_import_path(self):
        """Verify the module can be imported (class definition only)."""
        # This just checks the module structure is valid Python
        from heddle.contrib.lancedb import store  # noqa: F401

    def test_tool_import(self):
        from heddle.contrib.lancedb import tool  # noqa: F401
