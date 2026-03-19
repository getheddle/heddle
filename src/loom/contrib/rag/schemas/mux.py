"""Multiplexed stream schemas — entries, windows, and merged stream containers.

The stream multiplexer merges posts from multiple channels into a single
chronologically-ordered stream, optionally partitioned into time windows.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from pydantic import BaseModel, Field, computed_field

from loom.contrib.rag.schemas.post import NormalizedPost  # noqa: TC001 — runtime Pydantic field


class MuxWindowConfig(BaseModel, extra="allow"):
    """Configuration for time-window partitioning of a multiplexed stream.

    Supports tumbling (non-overlapping) and sliding (overlapping) strategies.
    """

    window_duration: timedelta = Field(
        default_factory=lambda: timedelta(hours=6),
        description="Window size as a timedelta.",
    )
    step: timedelta | None = Field(
        default=None,
        description="Slide interval (only for sliding strategy). None = tumbling.",
    )
    align_to_midnight: bool = True
    min_entries: int = 1
    require_multi_channel: bool = True
    tz_offset_hours: float = Field(
        default=3.5,
        description="UTC offset for window alignment (default: Iran Standard Time).",
    )

    @property
    def is_sliding(self) -> bool:
        """Return True if sliding window strategy is active."""
        return self.step is not None


class MuxEntry(BaseModel, extra="allow"):
    """A single entry in a multiplexed stream.

    Wraps a NormalizedPost with stream-level metadata (sequence number,
    window assignment).  Computed properties delegate to the underlying post.
    """

    mux_seq: int = Field(..., description="Sequence number in the merged stream.")
    window_id: str | None = None
    window_seq: int | None = None
    post: NormalizedPost

    @computed_field  # type: ignore[prop-decorator]
    @property
    def channel_id(self) -> int:
        """Return the source channel ID."""
        return self.post.source_channel_id

    @computed_field  # type: ignore[prop-decorator]
    @property
    def channel_name(self) -> str:
        """Return the source channel name."""
        return self.post.source_channel_name

    @property
    def timestamp(self) -> datetime:
        """Datetime delegated from the underlying post (not serialised)."""
        return self.post.timestamp

    @computed_field  # type: ignore[prop-decorator]
    @property
    def text(self) -> str:
        """Return the cleaned text from the underlying post."""
        return self.post.text_clean

    @computed_field  # type: ignore[prop-decorator]
    @property
    def global_id(self) -> str:
        """Return the global ID from the underlying post."""
        return self.post.global_id


class MuxedStream(BaseModel, extra="allow"):
    """A fully merged, chronologically-ordered multi-channel stream."""

    source_ids: list[int] = Field(..., description="Channel IDs in the stream.")
    source_names: list[str] = Field(..., description="Channel names in the stream.")
    start_time: datetime
    end_time: datetime
    total_entries: int
    entries: list[MuxEntry]
    window_config: MuxWindowConfig | None = None

    @property
    def channel_count(self) -> int:
        """Return the number of source channels."""
        return len(self.source_ids)

    @property
    def time_span_hours(self) -> float:
        """Return the time span in hours."""
        return (self.end_time - self.start_time).total_seconds() / 3600

    @property
    def window_ids(self) -> list[str]:
        """Return ordered list of unique window IDs in this stream."""
        seen: list[str] = []
        for e in self.entries:
            if e.window_id and e.window_id not in seen:
                seen.append(e.window_id)
        return seen

    def window(self, window_id: str) -> list[MuxEntry]:
        """Return entries belonging to a specific window."""
        return [e for e in self.entries if e.window_id == window_id]

    def windows(self) -> dict[str, list[MuxEntry]]:
        """Group all entries by window_id."""
        result: dict[str, list[MuxEntry]] = defaultdict(list)
        for entry in self.entries:
            key = entry.window_id if entry.window_id is not None else "__unwindowed__"
            result[key].append(entry)
        return dict(result)
