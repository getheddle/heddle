"""Shared normalization utilities for Telegram message processing.

Extracted from TelegramIngestor to allow reuse by both the batch
JSON ingestor and the live Telethon-based ingestor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..schemas.post import ChannelBias, ChannelEditorProfile, Language, NormalizedPost
from ..tools.rtl_normalizer import extract_links_from_entities, normalize

if TYPE_CHECKING:
    from ..schemas.telegram import RawTelegramMessage

logger = logging.getLogger(__name__)


def normalize_telegram_message(  # pragma: no cover
    msg: RawTelegramMessage,
    channel_id: int,
    channel_name: str,
    *,
    skip_empty: bool = True,
    min_text_len: int = 10,
) -> NormalizedPost | None:
    """Normalize a single RawTelegramMessage into a NormalizedPost.

    Returns None if the message should be skipped (empty, too short, etc.).

    Args:
        msg: Validated Telegram message.
        channel_id: Numeric channel ID.
        channel_name: Human-readable channel name.
        skip_empty: Skip messages with empty text.
        min_text_len: Minimum text length after normalization.
    """
    plain = msg.plain_text
    if skip_empty and not plain.strip():
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

    if len(norm.text_clean) < min_text_len:
        return None

    # Reaction breakdown (skip 'paid' type which has no emoji)
    reaction_breakdown = {r.emoji: r.count for r in msg.reactions if r.emoji is not None}

    # Resolve language hint safely
    try:
        language = Language(norm.language_hint)
    except ValueError:
        language = Language.UNKNOWN

    return NormalizedPost(
        source_channel_id=channel_id,
        source_channel_name=channel_name,
        message_id=msg.id,
        global_id=f"{channel_id}:{msg.id}",
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


def resolve_editor_profile(
    channel_id: int,
    channel_name: str,
    profiles: dict[int, ChannelEditorProfile] | None = None,
    override: ChannelEditorProfile | None = None,
) -> ChannelEditorProfile:
    """Resolve the editorial profile for a channel.

    Priority: override > profiles dict > synthesized default.
    """
    if override:
        return override
    if profiles and channel_id in profiles:
        return profiles[channel_id]
    return ChannelEditorProfile(
        channel_id=channel_id,
        channel_name=channel_name,
        bias=ChannelBias.UNKNOWN,
        language=Language.PERSIAN,
        trust_weight=0.5,
    )
