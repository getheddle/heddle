"""Normalized post schema — the canonical representation after ingestion.

All ingestion adapters (Telegram, RSS, etc.) normalize raw platform data into
NormalizedPost instances.  Downstream stages (chunker, mux, analysis) operate
exclusively on this schema, making them platform-agnostic.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime by Pydantic
from enum import StrEnum

from pydantic import BaseModel, Field


class Language(StrEnum):
    """Language codes relevant to the RAG pipeline."""

    PERSIAN = "fa"
    ARABIC = "ar"
    ENGLISH = "en"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ChannelBias(StrEnum):
    """Editorial orientation of a source channel."""

    STATE_MEDIA = "state_media"
    STATE_ALIGNED = "state_aligned"
    INDEPENDENT = "independent"
    OPPOSITION = "opposition"
    FACT_CHECK = "fact_check"
    NEUTRAL = "neutral"
    EDUCATIONAL = "educational"
    UNKNOWN = "unknown"


class ChannelEditorProfile(BaseModel, extra="allow"):
    """Metadata for a source channel used during ingestion and weighting.

    The trust_weight is a normalized score [0, 1] used by downstream
    analysis stages to weight assertions from this channel.
    """

    channel_id: int
    channel_name: str
    channel_handle: str | None = None
    bias: ChannelBias
    trust_weight: float = Field(ge=0.0, le=1.0)
    language: Language = Language.UNKNOWN
    description: str = ""


class NormalizedPost(BaseModel, extra="allow"):
    """Platform-agnostic post representation produced by ingestion adapters.

    The global_id format ``{channel_id}:{message_id}`` uniquely identifies a
    post across channels.  Fields named ``source_*`` refer to the originating
    channel to avoid ambiguity after muxing.
    """

    global_id: str = Field(
        ...,
        description='Unique identifier "{channel_id}:{message_id}".',
    )
    source_channel_id: int
    source_channel_name: str
    message_id: int
    timestamp: datetime
    timestamp_unix: int = 0

    # Text -------------------------------------------------------------------
    text_raw: str = ""
    text_clean: str = ""
    text_rtl: bool = True
    language: Language = Language.UNKNOWN

    # Links, hashtags, mentions -----------------------------------------------
    links: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)

    # Media -------------------------------------------------------------------
    has_media: bool = False
    has_photo: bool = False
    media_type: str | None = None

    # Threading / forwarding --------------------------------------------------
    is_forward: bool = False
    forwarded_from: str | None = None
    reply_to_id: int | None = None

    # Engagement --------------------------------------------------------------
    reaction_total: int = 0
    reaction_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Emoji -> count mapping (excludes paid reactions).",
    )

    # Edit tracking -----------------------------------------------------------
    was_edited: bool = False

    # Convenience computed from text_clean length
    word_count: int = 0
