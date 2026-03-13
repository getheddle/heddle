"""Ingestion adapters — convert raw platform exports to NormalizedPost."""
from loom.contrib.rag.ingestion.telegram_ingestor import (
    DEFAULT_PROFILES,
    TelegramIngestor,
)

__all__ = ["DEFAULT_PROFILES", "TelegramIngestor"]
