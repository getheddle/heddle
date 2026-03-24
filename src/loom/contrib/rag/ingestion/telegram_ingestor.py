"""TelegramIngestor: parse Telegram JSON exports and emit NormalizedPost objects.

Reads a Telegram JSON channel export, validates via Pydantic, normalizes text,
and emits NormalizedPost objects onto the NATS subject
``rag.ingestion.<channel_id>``.

In batch/test mode it can return a list directly (no NATS required).

Actor message contract (NATS):
  Subject:  rag.ingestion.<channel_id>
  Payload:  NormalizedPost (JSON)

Errors are published to: rag.ingestion.errors
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..schemas.post import ChannelBias, ChannelEditorProfile, Language, NormalizedPost
from ..schemas.telegram import RawTelegramMessage, TelegramChannel
from ..tools.rtl_normalizer import extract_links_from_entities, normalize
from .base import Ingestor

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default editorial profiles -- override via SourceConfig
# ---------------------------------------------------------------------------
DEFAULT_PROFILES: dict[int, ChannelEditorProfile] = {
    1098179827: ChannelEditorProfile(
        channel_id=1098179827,
        channel_name="FactNameh | \u0641\u06a9\u062a\u200c\u0646\u0627\u0645\u0647",
        channel_handle="Factnameh",
        bias=ChannelBias.FACT_CHECK,
        language=Language.PERSIAN,
        trust_weight=0.9,
        description="Independent Persian fact-checking outlet",
    ),
    1008727276: ChannelEditorProfile(
        channel_id=1008727276,
        channel_name="Iranwire",
        channel_handle="IranWire",
        bias=ChannelBias.INDEPENDENT,
        language=Language.PERSIAN,
        trust_weight=0.85,
        description="Diaspora investigative journalism, human rights focus",
    ),
    1068530015: ChannelEditorProfile(
        channel_id=1068530015,
        channel_name="\U0001f4da\u0647\u0645\u06a9\u0644\u0627\u0633\u06cc \U0001f4da",
        channel_handle=None,
        bias=ChannelBias.EDUCATIONAL,
        language=Language.PERSIAN,
        trust_weight=0.6,
        description="Educational / school content channel",
    ),
    1006939659: ChannelEditorProfile(
        channel_id=1006939659,
        channel_name="\u062e\u0628\u0631\u06af\u0632\u0627\u0631\u06cc \u0641\u0627\u0631\u0633",
        channel_handle="Farsna",
        bias=ChannelBias.STATE_MEDIA,
        language=Language.PERSIAN,
        trust_weight=0.3,
        description="Fars News Agency -- IRGC-aligned state media",
    ),
}


class TelegramIngestor(Ingestor):
    """
    Reads a Telegram JSON export and yields NormalizedPost objects.

    Usage (batch mode)::

        ingestor = TelegramIngestor("channel_farsnews.json")
        posts = list(ingestor.ingest())
    """

    def __init__(
        self,
        source_path: str | Path,
        editor_profile: ChannelEditorProfile | None = None,
        skip_empty: bool = True,
        skip_media_only: bool = False,
        min_text_len: int = 10,
    ) -> None:
        self.source_path = Path(source_path)
        self._profile_override = editor_profile
        self.skip_empty = skip_empty
        self.skip_media_only = skip_media_only
        self.min_text_len = min_text_len

        self._channel: TelegramChannel | None = None
        self._profile: ChannelEditorProfile | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> TelegramIngestor:
        """Parse and validate the JSON export. Call before ingest()."""
        if not self.source_path.exists():
            raise FileNotFoundError(f"Telegram export file not found: {self.source_path}")
        raw = json.loads(self.source_path.read_text(encoding="utf-8"))
        self._channel = TelegramChannel(**raw)
        self._profile = self._resolve_profile()
        logger.info(
            "Loaded channel '%s' (id=%d): %d raw messages",
            self._channel.name,
            self._channel.id,
            len(self._channel.messages),
        )
        return self

    def ingest(self) -> Generator[NormalizedPost, None, None]:
        """Yield NormalizedPost objects for each qualifying message.

        Call load() first.
        """
        if self._channel is None:
            raise RuntimeError("Call load() before ingest()")

        stats = {"total": 0, "yielded": 0, "skipped_type": 0, "skipped_short": 0, "errors": 0}

        for raw_msg in self._channel.messages:
            stats["total"] += 1
            if raw_msg.type != "message":
                stats["skipped_type"] += 1
                continue

            try:
                post = self._normalize_message(raw_msg)
            except Exception:
                logger.exception(
                    "Failed to normalize message id=%d in channel '%s'",
                    raw_msg.id,
                    self._channel.name,
                )
                stats["errors"] += 1
                continue

            if post is None:
                stats["skipped_short"] += 1
                continue

            stats["yielded"] += 1
            yield post

        logger.info(
            "Ingestion complete -- %s: total=%d yielded=%d skipped(type=%d short=%d) errors=%d",
            self._channel.name,
            stats["total"],
            stats["yielded"],
            stats["skipped_type"],
            stats["skipped_short"],
            stats["errors"],
        )

    def ingest_all(self) -> list[NormalizedPost]:
        """Materialize all posts into a list."""
        return list(self.ingest())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_profile(self) -> ChannelEditorProfile:
        if self._profile_override:
            return self._profile_override
        ch = self._channel
        if ch and ch.id in DEFAULT_PROFILES:
            return DEFAULT_PROFILES[ch.id]
        # Synthesize a minimal default
        return ChannelEditorProfile(
            channel_id=ch.id if ch else 0,
            channel_name=ch.name if ch else "unknown",
            bias=ChannelBias.UNKNOWN,
            language=Language.PERSIAN,
            trust_weight=0.5,
        )

    def _normalize_message(self, msg: RawTelegramMessage) -> NormalizedPost | None:
        ch = self._channel

        plain = msg.plain_text
        if self.skip_empty and not plain.strip():
            return None

        # Extract links from entities
        entities_raw = [e.model_dump() for e in msg.text_entities] if msg.text_entities else []
        links = extract_links_from_entities(entities_raw)

        # Normalize text
        norm = normalize(
            plain,
            strip_emojis=True,
            normalize_digits=True,
            strip_tg_footer=True,
            preserve_zwnj=True,
            links=links,
        )

        if len(norm.text_clean) < self.min_text_len:
            return None

        # Reaction breakdown (skip 'paid' type which has no emoji)
        reaction_breakdown = {r.emoji: r.count for r in msg.reactions if r.emoji is not None}

        # Resolve language hint safely
        try:
            language = Language(norm.language_hint)
        except ValueError:
            language = Language.UNKNOWN

        return NormalizedPost(
            source_channel_id=ch.id,
            source_channel_name=ch.name,
            message_id=msg.id,
            global_id=f"{ch.id}:{msg.id}",
            timestamp=msg.date,
            timestamp_unix=int(msg.date_unixtime),
            text_raw=plain,
            text_clean=norm.text_clean,
            text_rtl=norm.is_rtl,
            language=language,
            has_media=msg.has_media,
            has_photo=bool(msg.photo),
            media_type=msg.media_type,
            is_forward=msg.is_forward,
            forwarded_from=msg.forwarded_from,
            reply_to_id=msg.reply_to_message_id,
            reaction_total=msg.reaction_total,
            reaction_breakdown=reaction_breakdown,
            was_edited=msg.edited is not None,
            links=norm.links,
            hashtags=norm.hashtags,
            mentions=norm.mentions,
        )

    @property
    def channel_id(self) -> int | None:
        """Return the channel ID, or None if not loaded."""
        return self._channel.id if self._channel else None

    @property
    def channel_name(self) -> str | None:
        """Return the channel name, or None if not loaded."""
        return self._channel.name if self._channel else None

    @property
    def profile(self) -> ChannelEditorProfile | None:
        """Return the resolved editorial profile."""
        return self._profile
