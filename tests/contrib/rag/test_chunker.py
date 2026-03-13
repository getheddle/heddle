"""Unit tests for loom.contrib.rag.chunker — sentence chunker."""
import pytest
from datetime import datetime, timezone


def _make_post(text: str, gid: str = "1:1") -> "NormalizedPost":
    from loom.contrib.rag.schemas.post import NormalizedPost
    return NormalizedPost(
        global_id=gid,
        source_channel_id=1,
        source_channel_name="test_ch",
        message_id=1,
        timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc),
        text_clean=text,
    )


class TestSentenceChunker:
    def test_empty_text(self):
        from loom.contrib.rag.chunker.sentence_chunker import chunk_post
        post = _make_post("")
        assert chunk_post(post) == []

    def test_whitespace_only(self):
        from loom.contrib.rag.chunker.sentence_chunker import chunk_post
        post = _make_post("   \n\n   ")
        assert chunk_post(post) == []

    def test_short_text_single_chunk(self):
        from loom.contrib.rag.chunker.sentence_chunker import chunk_post
        post = _make_post("This is a short sentence.")
        chunks = chunk_post(post)
        assert len(chunks) == 1
        assert chunks[0].text == "This is a short sentence."
        assert chunks[0].chunk_index == 0
        assert chunks[0].total_chunks == 1

    def test_whole_post_strategy(self):
        from loom.contrib.rag.chunker.sentence_chunker import chunk_post, ChunkConfig
        from loom.contrib.rag.schemas.chunk import ChunkStrategy
        text = "First sentence. Second sentence. Third sentence."
        post = _make_post(text)
        cfg = ChunkConfig(strategy=ChunkStrategy.WHOLE_POST)
        chunks = chunk_post(post, config=cfg)
        assert len(chunks) == 1
        assert chunks[0].text == text

    def test_paragraph_split(self):
        from loom.contrib.rag.chunker.sentence_chunker import chunk_post, ChunkConfig
        from loom.contrib.rag.schemas.chunk import ChunkStrategy
        text = "First paragraph with enough text to meet minimum.\n\nSecond paragraph also with enough text here."
        post = _make_post(text)
        cfg = ChunkConfig(strategy=ChunkStrategy.PARAGRAPH, min_chars=10)
        chunks = chunk_post(post, config=cfg)
        assert len(chunks) >= 1

    def test_chunk_ids_sequential(self):
        from loom.contrib.rag.chunker.sentence_chunker import chunk_post, ChunkConfig
        text = "A" * 200 + ".\n\n" + "B" * 200 + ".\n\n" + "C" * 200 + "."
        post = _make_post(text, gid="100:5")
        cfg = ChunkConfig(target_chars=100, max_chars=250, min_chars=10)
        chunks = chunk_post(post, config=cfg)
        for i, c in enumerate(chunks):
            assert c.chunk_index == i
            assert c.chunk_id == f"100:5:{i}"
            assert c.total_chunks == len(chunks)

    def test_source_provenance(self):
        from loom.contrib.rag.chunker.sentence_chunker import chunk_post
        post = _make_post("A sentence with enough chars for one chunk.", gid="999:42")
        chunks = chunk_post(post)
        assert chunks[0].source_global_id == "999:42"
        assert chunks[0].source_channel_id == 1
        assert chunks[0].source_channel_name == "test_ch"

    def test_chunk_mux_entry(self):
        from loom.contrib.rag.chunker.sentence_chunker import chunk_mux_entry
        from loom.contrib.rag.schemas.mux import MuxEntry
        post = _make_post("Enough text for a chunk here definitely.")
        entry = MuxEntry(mux_seq=0, post=post)
        chunks = chunk_mux_entry(entry)
        assert len(chunks) >= 1

    def test_fixed_char_strategy(self):
        from loom.contrib.rag.chunker.sentence_chunker import chunk_post, ChunkConfig
        from loom.contrib.rag.schemas.chunk import ChunkStrategy
        text = "X" * 1500
        post = _make_post(text)
        cfg = ChunkConfig(strategy=ChunkStrategy.FIXED_CHAR, max_chars=500, min_chars=10)
        chunks = chunk_post(post, config=cfg)
        assert len(chunks) == 3
