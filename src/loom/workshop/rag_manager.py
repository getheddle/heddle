"""RAG pipeline manager for the Workshop dashboard.

Wraps vector store operations and channel registry access for the Workshop
web UI. No NATS required — uses vector store directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from loom.contrib.rag.vectorstore.base import VectorStore

logger = logging.getLogger(__name__)


class ChannelInfo:
    """Lightweight channel metadata for display."""

    def __init__(
        self,
        handle: str,
        name_en: str,
        name_fa: str = "",
        faction: str = "",
        source_tier: int = 5,
        monitoring_priority: str = "low",
        language: str = "fa",
        notes: str = "",
        status: str = "verified",
    ) -> None:
        self.handle = handle
        self.name_en = name_en
        self.name_fa = name_fa
        self.faction = faction
        self.source_tier = source_tier
        self.monitoring_priority = monitoring_priority
        self.language = language
        self.notes = notes
        self.status = status


class RAGManager:
    """Manages vector store and channel registry for the Workshop RAG dashboard.

    Args:
        store: A VectorStore instance (DuckDB or LanceDB).
        channel_registry_path: Path to itp_telegram_channels.yaml (optional).
    """

    def __init__(
        self,
        store: VectorStore | None = None,
        channel_registry_path: str | None = None,
    ) -> None:
        self._store = store
        self._channels: list[ChannelInfo] = []
        self._registry_path = channel_registry_path
        if channel_registry_path:
            self._load_channel_registry(channel_registry_path)

    def _load_channel_registry(self, path: str) -> None:
        """Load channel metadata from the ITP channel registry YAML."""
        registry_path = Path(path)
        if not registry_path.exists():
            logger.warning("Channel registry not found: %s", path)
            return

        try:
            data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse channel registry: %s", exc)
            return

        categories = data.get("categories", [])
        for category in categories:
            faction = category.get("faction", "unknown")
            tier = category.get("source_tier", 5)
            priority = category.get("monitoring_priority", "low")
            for ch in category.get("channels", []):
                self._channels.append(
                    ChannelInfo(
                        handle=ch.get("handle", ""),
                        name_en=ch.get("name_en", ""),
                        name_fa=ch.get("name_fa", ""),
                        faction=faction,
                        source_tier=tier,
                        monitoring_priority=priority,
                        language=ch.get("language", "fa"),
                        notes=ch.get("notes", ""),
                        status=ch.get("status", "verified"),
                    )
                )

        logger.info("Loaded %d channels from registry", len(self._channels))

    @property
    def store(self) -> VectorStore | None:
        """Return the configured vector store, or None."""
        return self._store

    @property
    def channels(self) -> list[ChannelInfo]:
        """Return all registered channels."""
        return self._channels

    def get_store_stats(self) -> dict[str, Any]:
        """Return vector store statistics."""
        if self._store is None:
            return {"total_chunks": 0, "status": "not_configured"}
        try:
            return self._store.stats()
        except Exception as exc:
            logger.warning("Failed to get store stats: %s", exc)
            return {"total_chunks": 0, "error": str(exc)}

    def search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
        channel_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a vector search and return results as dicts."""
        if self._store is None:
            return []
        try:
            results = self._store.search(
                query, limit=limit, min_score=min_score, channel_ids=channel_ids
            )
            return [r.model_dump(mode="json") for r in results]
        except Exception as exc:
            logger.warning("Search failed: %s", exc)
            return []

    def get_channels_by_faction(self) -> dict[str, list[ChannelInfo]]:
        """Group channels by faction for display."""
        groups: dict[str, list[ChannelInfo]] = {}
        for ch in self._channels:
            groups.setdefault(ch.faction, []).append(ch)
        return groups

    def get_channels_by_priority(self) -> dict[str, list[ChannelInfo]]:
        """Group channels by monitoring priority."""
        groups: dict[str, list[ChannelInfo]] = {}
        for ch in self._channels:
            groups.setdefault(ch.monitoring_priority, []).append(ch)
        return groups

    def get_channel(self, handle: str) -> ChannelInfo | None:
        """Look up a channel by handle."""
        for ch in self._channels:
            if ch.handle == handle:
                return ch
        return None

    def channel_count(self) -> int:
        """Total number of registered channels."""
        return len(self._channels)

    def verified_channel_count(self) -> int:
        """Number of verified channels."""
        return sum(1 for ch in self._channels if ch.status == "verified")
