"""PlainTextIngestor: read plain-text files and emit NormalizedPost objects.

One file = one document. Accepts a single file or a directory (in which
case files are discovered with a glob pattern).
"""

from __future__ import annotations

import hashlib
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
    digest = hashlib.sha256(s.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


class PlainTextIngestor(Ingestor):
    """Read plain-text files and emit one :class:`NormalizedPost` per file.

    Args:
        source_path: Path to a single file or a directory.
        glob: Pattern used when ``source_path`` is a directory
            (default ``**/*.txt`` — recursive).
        encoding: Primary encoding (default ``utf-8``). On decode failure
            the file is re-read with ``errors="replace"`` and a warning
            is logged.

    The doc id is the filename stem; ``file_path``, ``file_size``, and
    the mtime are attached as extra fields on the emitted post.
    """

    DEFAULT_GLOB = "**/*.txt"

    def __init__(
        self,
        source_path: str | Path,
        glob: str = DEFAULT_GLOB,
        encoding: str = "utf-8",
    ) -> None:
        self.source_path = Path(source_path)
        self.glob_pattern = glob
        self.encoding = encoding

        self._files: list[Path] = []
        self._channel_id: int | None = None
        self._channel_name: str | None = None

    def load(self) -> PlainTextIngestor:
        """Discover files (single or via glob). Call before :meth:`ingest`."""
        if not self.source_path.exists():
            raise FileNotFoundError(f"Source path not found: {self.source_path}")

        if self.source_path.is_file():
            self._files = [self.source_path]
            self._channel_name = self.source_path.parent.name or self.source_path.stem
        else:
            self._files = sorted(
                p for p in self.source_path.glob(self.glob_pattern) if p.is_file()
            )
            self._channel_name = self.source_path.name or "plain_text"

        self._channel_id = _stable_id(str(self.source_path.resolve()))
        logger.info(
            "Loaded plain-text source '%s': %d files",
            self._channel_name,
            len(self._files),
        )
        return self

    def ingest(self) -> Generator[NormalizedPost, None, None]:
        """Yield one :class:`NormalizedPost` per non-empty file."""
        if self._channel_id is None or self._channel_name is None:
            raise RuntimeError("Call load() before ingest()")

        for path in self._files:
            try:
                text = path.read_text(encoding=self.encoding)
            except UnicodeDecodeError:
                logger.warning(
                    "%s is not valid %s; re-reading with errors='replace'",
                    path,
                    self.encoding,
                )
                text = path.read_text(encoding=self.encoding, errors="replace")

            text = text.strip()
            if not text:
                continue

            try:
                stat = path.stat()
                ts = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
                size = stat.st_size
            except OSError:
                ts = datetime.now(tz=UTC)
                size = len(text)

            message_id = _stable_id(str(path.resolve())) % (2**31)

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
                doc_id=path.stem,
                file_path=str(path),
                file_size=size,
            )

    @property
    def channel_id(self) -> int | None:
        """Stable synthetic channel id derived from the source path."""
        return self._channel_id

    @property
    def channel_name(self) -> str | None:
        """Source name (directory or file stem)."""
        return self._channel_name
