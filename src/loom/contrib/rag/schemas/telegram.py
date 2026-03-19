"""Raw Telegram JSON export schema (Telegram Desktop export format).

The ``text`` field in Telegram exports is polymorphic:
  - str   -> plain text message
  - list  -> mixed list of str and entity dicts (bold, link, mention, emoji...)

We model both and provide a helper to flatten to plain str.

Note: all ``datetime`` fields coming from the Telegram export are **naive**
(no timezone info).  Downstream code should treat them as UTC and attach
``timezone.utc`` explicitly when timezone-aware datetimes are required.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime by Pydantic
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TelegramMediaType(StrEnum):
    """Media types in Telegram exports."""

    AUDIO = "audio"
    DOCUMENT = "document"
    PHOTO = "photo"  # photo is a separate field, not media_type
    VIDEO = "video"
    VIDEO_FILE = "video_file"
    VOICE_MESSAGE = "voice_message"
    STICKER = "sticker"
    ANIMATION = "animation"


class TextEntity(BaseModel):
    """A single entity within a Telegram text list."""

    type: str  # plain, bold, italic, link, mention, custom_emoji, ...
    text: str
    href: str | None = None  # for text_link type
    document_id: str | None = None  # for custom_emoji type

    model_config = {"extra": "allow"}


# Telegram text field: either a plain str or a list of str / TextEntity
TelegramTextFragment = str | TextEntity
TelegramTextField = str | list[TelegramTextFragment]


class ReactionCount(BaseModel):
    """Reaction count for a Telegram message."""

    type: str  # "emoji" | "paid" (Telegram Stars reactions have no emoji field)
    count: int
    emoji: str | None = None  # None for type="paid"

    model_config = {"extra": "allow"}


class RawTelegramMessage(BaseModel):
    """Represents a single message from a Telegram JSON export.

    Non-message records (service events, etc.) are filtered out at ingestion.
    """

    id: int
    type: str  # "message" | "service"
    date: datetime
    date_unixtime: str
    from_: str | None = Field(None, alias="from")
    from_id: str | None = None

    # Text payload -- polymorphic, see module docstring
    text: TelegramTextField = ""
    text_entities: list[TextEntity] = Field(default_factory=list)

    # Media
    photo: str | None = None
    photo_file_size: int | None = None
    width: int | None = None
    height: int | None = None
    media_type: TelegramMediaType | str | None = None
    file: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    mime_type: str | None = None
    duration_seconds: int | None = None
    thumbnail: str | None = None
    thumbnail_file_size: int | None = None

    # Engagement & threading
    reactions: list[ReactionCount] = Field(default_factory=list)
    reply_to_message_id: int | None = None
    forwarded_from: str | None = None
    forwarded_from_id: str | None = None

    # Edit tracking
    edited: datetime | None = None
    edited_unixtime: str | None = None

    # Misc
    sticker_emoji: str | None = None

    model_config = {
        "populate_by_name": True,
        "extra": "allow",
    }

    @property
    def plain_text(self) -> str:
        """Flatten the polymorphic text field to a plain string."""
        if isinstance(self.text, str):
            return self.text
        parts: list[str] = []
        for fragment in self.text:
            if isinstance(fragment, str):
                parts.append(fragment)
            elif isinstance(fragment, TextEntity):
                parts.append(fragment.text)
            elif isinstance(fragment, dict):
                parts.append(fragment.get("text", ""))
        return "".join(parts)

    @property
    def has_text(self) -> bool:
        """Return True if the message contains non-empty text."""
        return bool(self.plain_text.strip())

    @property
    def has_media(self) -> bool:
        """Return True if the message contains media."""
        return bool(self.photo or self.media_type)

    @property
    def reaction_total(self) -> int:
        """Return the total number of reactions."""
        return sum(r.count for r in self.reactions)

    @property
    def is_forward(self) -> bool:
        """Return True if the message is forwarded."""
        return self.forwarded_from is not None

    @field_validator("text", mode="before")
    @classmethod
    def coerce_text(cls, v: Any) -> TelegramTextField:
        """Coerce None and mixed lists into a valid TelegramTextField."""
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            coerced: list[TelegramTextFragment] = []
            for item in v:
                if isinstance(item, str):
                    coerced.append(item)
                elif isinstance(item, dict):
                    coerced.append(TextEntity(**item))
                else:
                    coerced.append(str(item))
            return coerced
        return str(v)


class TelegramChannel(BaseModel):
    """Top-level structure of a Telegram JSON channel export."""

    name: str
    type: str  # "public_channel" | "private_channel" | "private_group" | ...
    id: int
    messages: list[RawTelegramMessage] = Field(default_factory=list)

    model_config = {"extra": "allow"}

    @property
    def message_messages(self) -> list[RawTelegramMessage]:
        """Filter to only type='message' records."""
        return [m for m in self.messages if m.type == "message"]
