"""CsvIngestor: parse CSV files and emit NormalizedPost objects.

Each row becomes one :class:`NormalizedPost`. The column named by
``text_column`` carries the document text; remaining columns can be
preserved as extra metadata via ``metadata_columns``.

The synthetic ``source_channel_*`` fields use the file stem as the
channel name and a stable hash as the channel id, so multiple CSVs
remain distinguishable downstream.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..schemas.post import Language, NormalizedPost
from .base import Ingestor

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


def _stable_id(s: str) -> int:
    """SHA-256 based positive 63-bit int — stable across processes."""
    digest = hashlib.sha256(s.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


class CsvIngestor(Ingestor):
    """Read a CSV and emit one :class:`NormalizedPost` per row.

    Args:
        source_path: Path to the CSV file.
        text_column: Required. Column whose value is used as document text.
        id_column: Optional. Column for stable per-row identifiers; row
            index is used when None.
        metadata_columns: Optional. Extra columns to attach as extra
            fields on the emitted post (Pydantic ``extra="allow"``).
        delimiter: CSV delimiter (default ``,``).
        encoding: Primary text encoding to try (default ``utf-8``). On
            decode failure the file is re-read with
            ``errors="replace"`` and a warning is logged.
    """

    def __init__(
        self,
        source_path: str | Path,
        text_column: str,
        id_column: str | None = None,
        metadata_columns: list[str] | None = None,
        delimiter: str = ",",
        encoding: str = "utf-8",
    ) -> None:
        self.source_path = Path(source_path)
        self.text_column = text_column
        self.id_column = id_column
        self.metadata_columns = list(metadata_columns) if metadata_columns else []
        self.delimiter = delimiter
        self.encoding = encoding

        self._rows: list[dict[str, str]] = []
        self._channel_id: int | None = None
        self._channel_name: str | None = None

    def load(self) -> CsvIngestor:
        """Read and parse the CSV file. Call before :meth:`ingest`."""
        if not self.source_path.exists():
            raise FileNotFoundError(f"CSV file not found: {self.source_path}")

        try:
            text = self.source_path.read_text(encoding=self.encoding)
        except UnicodeDecodeError:
            logger.warning(
                "CSV %s is not valid %s; re-reading with errors='replace'",
                self.source_path,
                self.encoding,
            )
            text = self.source_path.read_text(encoding=self.encoding, errors="replace")

        reader = csv.DictReader(io.StringIO(text), delimiter=self.delimiter)
        if not reader.fieldnames or self.text_column not in reader.fieldnames:
            raise ValueError(
                f"text_column '{self.text_column}' not in CSV columns: {reader.fieldnames}"
            )
        if self.id_column and self.id_column not in reader.fieldnames:
            raise ValueError(
                f"id_column '{self.id_column}' not in CSV columns: {reader.fieldnames}"
            )
        for col in self.metadata_columns:
            if col not in reader.fieldnames:
                raise ValueError(f"metadata column '{col}' not in CSV columns: {reader.fieldnames}")

        self._rows = [dict(row) for row in reader]
        self._channel_name = self.source_path.stem
        self._channel_id = _stable_id(str(self.source_path.resolve()))
        logger.info("Loaded CSV '%s': %d rows", self._channel_name, len(self._rows))
        return self

    def ingest(self) -> Generator[NormalizedPost, None, None]:
        """Yield one :class:`NormalizedPost` per non-empty row."""
        if self._channel_id is None or self._channel_name is None:
            raise RuntimeError("Call load() before ingest()")

        try:
            ts = datetime.fromtimestamp(self.source_path.stat().st_mtime, tz=UTC)
        except OSError:
            ts = datetime.now(tz=UTC)

        seen_ids: set[int] = set()
        for idx, row in enumerate(self._rows):
            text = (row.get(self.text_column) or "").strip()
            if not text:
                continue

            if self.id_column:
                raw_id = (row.get(self.id_column) or "").strip()
                if not raw_id:
                    continue
                try:
                    message_id = int(raw_id)
                except ValueError:
                    message_id = _stable_id(raw_id) % (2**31)
            else:
                message_id = idx

            if message_id in seen_ids:
                logger.warning(
                    "Duplicate message_id %d in %s row %d; skipping",
                    message_id,
                    self.source_path,
                    idx,
                )
                continue
            seen_ids.add(message_id)

            metadata = {
                col: row.get(col) for col in self.metadata_columns if row.get(col) is not None
            }

            yield NormalizedPost(
                global_id=f"{self._channel_id}:{message_id}",
                source_channel_id=self._channel_id,
                source_channel_name=self._channel_name,
                message_id=message_id,
                timestamp=ts,
                timestamp_unix=int(ts.timestamp()),
                text_raw=text,
                text_clean=text,
                text_rtl=False,
                language=Language.UNKNOWN,
                **metadata,
            )

    @property
    def channel_id(self) -> int | None:
        """Stable synthetic channel id derived from the source path."""
        return self._channel_id

    @property
    def channel_name(self) -> str | None:
        """Source name (file stem)."""
        return self._channel_name
