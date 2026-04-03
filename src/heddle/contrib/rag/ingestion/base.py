"""Platform-agnostic ingestion interface.

All ingestion adapters (Telegram, RSS, etc.) extend :class:`Ingestor` and
normalize raw platform data into :class:`NormalizedPost` instances.

Downstream stages (chunker, mux, analysis) operate exclusively on
NormalizedPost, making them platform-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

    from ..schemas.post import NormalizedPost


class Ingestor(ABC):
    """Base class for platform-specific ingestion adapters.

    Subclasses must implement :meth:`load` and :meth:`ingest`.

    Usage::

        ingestor = MyIngestor(source_path="data.json")
        ingestor.load()
        for post in ingestor.ingest():
            process(post)
    """

    @abstractmethod
    def load(self) -> Ingestor:
        """Parse and validate the raw source data.

        Must be called before :meth:`ingest`. Returns ``self`` for chaining.
        """
        ...

    @abstractmethod
    def ingest(self) -> Generator[NormalizedPost, None, None]:
        """Yield normalized posts from the loaded source data.

        Call :meth:`load` first.
        """
        ...

    def ingest_all(self) -> list[NormalizedPost]:
        """Materialize all posts into a list."""
        return list(self.ingest())
