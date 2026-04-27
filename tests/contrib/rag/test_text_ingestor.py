"""Unit tests for heddle.contrib.rag.ingestion.text_ingestor.PlainTextIngestor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from heddle.contrib.rag.ingestion.text_ingestor import PlainTextIngestor

if TYPE_CHECKING:
    from pathlib import Path


class TestPlainTextIngestor:
    def test_single_file(self, tmp_path: Path) -> None:
        f = tmp_path / "note.txt"
        f.write_text("hello world", encoding="utf-8")
        ing = PlainTextIngestor(f).load()
        posts = ing.ingest_all()
        assert len(posts) == 1
        assert posts[0].text_clean == "hello world"
        assert posts[0].model_extra is not None
        assert posts[0].model_extra["doc_id"] == "note"
        assert posts[0].model_extra["file_path"] == str(f)

    def test_directory_recursive(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("beta", encoding="utf-8")
        (sub / "c.txt").write_text("gamma", encoding="utf-8")

        ing = PlainTextIngestor(tmp_path).load()
        posts = ing.ingest_all()
        assert len(posts) == 3
        texts = sorted(p.text_clean for p in posts)
        assert texts == ["alpha", "beta", "gamma"]

    def test_directory_non_recursive_glob(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("beta", encoding="utf-8")

        ing = PlainTextIngestor(tmp_path, glob="*.txt").load()
        posts = ing.ingest_all()
        assert len(posts) == 1
        assert posts[0].text_clean == "alpha"

    def test_blank_files_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("real content", encoding="utf-8")
        (tmp_path / "b.txt").write_text("   \n\t\n", encoding="utf-8")
        (tmp_path / "c.txt").write_text("", encoding="utf-8")

        ing = PlainTextIngestor(tmp_path).load()
        posts = ing.ingest_all()
        assert len(posts) == 1
        assert posts[0].text_clean == "real content"

    def test_unique_ids_per_file(self, tmp_path: Path) -> None:
        (tmp_path / "x.txt").write_text("one", encoding="utf-8")
        (tmp_path / "y.txt").write_text("two", encoding="utf-8")
        ing = PlainTextIngestor(tmp_path).load()
        posts = ing.ingest_all()
        ids = {p.message_id for p in posts}
        assert len(ids) == 2

    def test_non_utf8_falls_back(self, tmp_path: Path, caplog) -> None:
        f = tmp_path / "latin1.txt"
        f.write_bytes("café".encode("latin-1"))
        ing = PlainTextIngestor(f).load()
        posts = ing.ingest_all()
        assert len(posts) == 1
        # Lossy decode preserves the prefix
        assert posts[0].text_clean.startswith("caf")
        assert any(
            "errors='replace'" in record.getMessage() for record in caplog.records
        )

    def test_metadata_extras(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("body of document", encoding="utf-8")
        ing = PlainTextIngestor(f).load()
        post = next(iter(ing.ingest()))
        extra = post.model_extra
        assert extra is not None
        assert extra["doc_id"] == "doc"
        assert isinstance(extra["file_size"], int)
        assert extra["file_size"] > 0

    def test_custom_glob_md(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("txt content", encoding="utf-8")
        (tmp_path / "b.md").write_text("md content", encoding="utf-8")
        ing = PlainTextIngestor(tmp_path, glob="**/*.md").load()
        posts = ing.ingest_all()
        assert len(posts) == 1
        assert posts[0].text_clean == "md content"

    def test_load_required_before_ingest(self, tmp_path: Path) -> None:
        ing = PlainTextIngestor(tmp_path)
        with pytest.raises(RuntimeError, match="load"):
            list(ing.ingest())

    def test_missing_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            PlainTextIngestor(tmp_path / "does-not-exist").load()

    def test_channel_id_stable_per_path(self, tmp_path: Path) -> None:
        f = tmp_path / "x.txt"
        f.write_text("hello", encoding="utf-8")
        a = PlainTextIngestor(f).load()
        b = PlainTextIngestor(f).load()
        assert a.channel_id == b.channel_id
