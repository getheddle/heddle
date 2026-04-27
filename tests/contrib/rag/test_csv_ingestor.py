"""Unit tests for heddle.contrib.rag.ingestion.csv_ingestor.CsvIngestor."""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING

import pytest

from heddle.contrib.rag.ingestion.csv_ingestor import CsvIngestor

if TYPE_CHECKING:
    from pathlib import Path


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


class TestCsvIngestor:
    def test_basic_ingestion(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "comments.csv",
            [
                {"id": "1", "body": "First comment about parking."},
                {"id": "2", "body": "Second comment about noise."},
                {"id": "3", "body": "Third comment about lights."},
            ],
            fieldnames=["id", "body"],
        )

        ing = CsvIngestor(csv_path, text_column="body").load()
        posts = ing.ingest_all()

        assert len(posts) == 3
        assert posts[0].text_clean == "First comment about parking."
        assert posts[0].source_channel_name == "comments"
        assert ing.channel_id is not None
        assert ing.channel_name == "comments"
        # No id_column → row index is the message_id
        assert [p.message_id for p in posts] == [0, 1, 2]
        # global_id is "<channel_id>:<message_id>"
        assert posts[0].global_id == f"{ing.channel_id}:0"

    def test_id_column_used(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "data.csv",
            [
                {"row_id": "100", "txt": "alpha"},
                {"row_id": "200", "txt": "beta"},
            ],
            fieldnames=["row_id", "txt"],
        )
        ing = CsvIngestor(csv_path, text_column="txt", id_column="row_id").load()
        posts = ing.ingest_all()
        assert [p.message_id for p in posts] == [100, 200]

    def test_id_column_with_non_integer_values(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "data.csv",
            [
                {"row_id": "abc-1", "txt": "alpha"},
                {"row_id": "abc-2", "txt": "beta"},
            ],
            fieldnames=["row_id", "txt"],
        )
        ing = CsvIngestor(csv_path, text_column="txt", id_column="row_id").load()
        posts = ing.ingest_all()
        # Non-integer ids → stable hash → still unique
        assert len(posts) == 2
        assert posts[0].message_id != posts[1].message_id

    def test_quoted_fields_with_commas(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "quoted.csv"
        csv_path.write_text(
            'id,body\n1,"hello, world"\n2,"line\nbreak"\n',
            encoding="utf-8",
        )
        ing = CsvIngestor(csv_path, text_column="body").load()
        posts = ing.ingest_all()
        assert len(posts) == 2
        assert posts[0].text_clean == "hello, world"
        assert posts[1].text_clean == "line\nbreak"

    def test_missing_text_skipped(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "missing.csv",
            [
                {"id": "1", "body": "present"},
                {"id": "2", "body": ""},
                {"id": "3", "body": "  "},
                {"id": "4", "body": "again"},
            ],
            fieldnames=["id", "body"],
        )
        ing = CsvIngestor(csv_path, text_column="body").load()
        posts = ing.ingest_all()
        assert len(posts) == 2
        assert [p.text_clean for p in posts] == ["present", "again"]

    def test_metadata_columns(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "meta.csv",
            [
                {"id": "1", "body": "hi", "author": "alice", "topic": "noise"},
                {"id": "2", "body": "hello", "author": "bob", "topic": "lights"},
            ],
            fieldnames=["id", "body", "author", "topic"],
        )
        ing = CsvIngestor(
            csv_path,
            text_column="body",
            metadata_columns=["author", "topic"],
        ).load()
        posts = ing.ingest_all()
        # extra="allow" surfaces metadata as extra fields
        assert posts[0].model_extra is not None
        assert posts[0].model_extra["author"] == "alice"
        assert posts[1].model_extra["topic"] == "lights"

    def test_unknown_text_column_raises(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "x.csv",
            [{"a": "1", "b": "2"}],
            fieldnames=["a", "b"],
        )
        with pytest.raises(ValueError, match="text_column"):
            CsvIngestor(csv_path, text_column="missing").load()

    def test_unknown_id_column_raises(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "x.csv",
            [{"a": "1", "b": "2"}],
            fieldnames=["a", "b"],
        )
        with pytest.raises(ValueError, match="id_column"):
            CsvIngestor(csv_path, text_column="b", id_column="bogus").load()

    def test_unknown_metadata_column_raises(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "x.csv",
            [{"a": "1", "b": "2"}],
            fieldnames=["a", "b"],
        )
        with pytest.raises(ValueError, match="metadata column"):
            CsvIngestor(csv_path, text_column="b", metadata_columns=["nope"]).load()

    def test_custom_delimiter(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "tsv.csv"
        csv_path.write_text("id\tbody\n1\thello\n2\tworld\n", encoding="utf-8")
        ing = CsvIngestor(csv_path, text_column="body", delimiter="\t").load()
        posts = ing.ingest_all()
        assert [p.text_clean for p in posts] == ["hello", "world"]

    def test_non_utf8_encoding_falls_back(self, tmp_path: Path, caplog) -> None:
        csv_path = tmp_path / "latin1.csv"
        # Write Latin-1 bytes that are invalid UTF-8 (0xe9 = é in Latin-1)
        csv_path.write_bytes("id,body\n1,caf\xe9\n".encode("latin-1"))

        ing = CsvIngestor(csv_path, text_column="body").load()
        posts = ing.ingest_all()
        # Decoding falls back to errors='replace' → text is preserved (lossy)
        assert len(posts) == 1
        assert posts[0].text_clean.startswith("caf")
        # Warning is logged about fallback
        assert any(
            "errors='replace'" in record.getMessage() for record in caplog.records
        )

    def test_load_required_before_ingest(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "x.csv",
            [{"id": "1", "body": "hi"}],
            fieldnames=["id", "body"],
        )
        ing = CsvIngestor(csv_path, text_column="body")
        with pytest.raises(RuntimeError, match="load"):
            list(ing.ingest())

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            CsvIngestor(tmp_path / "does-not-exist.csv", text_column="x").load()

    def test_skip_rows_with_blank_id(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "blanks.csv",
            [
                {"id": "1", "body": "first"},
                {"id": "", "body": "skip me"},
                {"id": "3", "body": "third"},
            ],
            fieldnames=["id", "body"],
        )
        ing = CsvIngestor(csv_path, text_column="body", id_column="id").load()
        posts = ing.ingest_all()
        assert [p.message_id for p in posts] == [1, 3]
