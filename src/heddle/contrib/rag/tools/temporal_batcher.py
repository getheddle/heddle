"""Generic time-window batching utility for muxed streams.

Supports:
  - Tumbling windows (non-overlapping, step == duration)
  - Sliding windows (overlapping, step < duration)
  - Calendar-aligned windows (hour, day, week aligned to UTC midnight)

Operates on any sequence of objects that have a .timestamp (datetime) attribute.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


class HasTimestamp(Protocol):
    """Protocol for objects with a timestamp attribute."""

    timestamp: datetime


T = TypeVar("T", bound=HasTimestamp)


def _format_window_id(start: datetime, end: datetime) -> str:
    """Format a URL/path-safe window identifier using underscores."""
    return f"{start.isoformat()}_{end.isoformat()}"


@dataclass
class WindowBatch(Generic[T]):
    """A batch of items within a time window."""

    window_id: str  # ISO-8601 interval: "<start>_<end>" (underscore-separated)
    window_index: int
    window_start: datetime
    window_end: datetime
    items: list[T]

    @property
    def duration(self) -> timedelta:
        """Return the window duration."""
        return self.window_end - self.window_start

    @property
    def count(self) -> int:
        """Return the number of items in the window."""
        return len(self.items)

    def channel_ids(self) -> set:
        """Return set of unique channel IDs if items have .channel_id."""
        result = set()
        for item in self.items:
            cid = getattr(item, "channel_id", None)
            if cid is not None:
                result.add(cid)
        return result


def tumbling_windows(
    items: Sequence[T],
    duration: timedelta,
    *,
    align_to_midnight: bool = False,
    min_items: int = 1,
) -> Iterator[WindowBatch[T]]:
    """
    Yield non-overlapping time windows over a sorted sequence of items.

    Args:
        items:              Sequence sorted by .timestamp (ascending)
        duration:           Window size
        align_to_midnight:  Snap window starts to UTC midnight
        min_items:          Skip windows with fewer items
    """
    if not items:
        return

    sorted_items = sorted(items, key=lambda x: x.timestamp)
    t_start = sorted_items[0].timestamp

    if align_to_midnight:
        t_start = t_start.replace(hour=0, minute=0, second=0, microsecond=0)

    window_idx = 0
    total_items = len(sorted_items)
    consumed = 0

    while consumed < total_items:
        t_end = t_start + duration
        batch = [x for x in sorted_items[consumed:] if x.timestamp < t_end]

        # Fast-forward consumed pointer
        consumed += len(batch)

        if len(batch) >= min_items:
            yield WindowBatch(
                window_id=_format_window_id(t_start, t_end),
                window_index=window_idx,
                window_start=t_start,
                window_end=t_end,
                items=batch,
            )
        window_idx += 1
        t_start = t_end


def sliding_windows(
    items: Sequence[T],
    duration: timedelta,
    step: timedelta,
    *,
    min_items: int = 1,
    require_unique_channels: int = 0,
) -> Iterator[WindowBatch[T]]:
    """
    Yield overlapping (sliding) time windows.

    Uses a sorted-scan approach with two pointers for efficiency instead of
    scanning the full list for every window.

    Args:
        items:                    Items with .timestamp
        duration:                 Window width
        step:                     Step size (< duration for overlap)
        min_items:                Minimum items per window
        require_unique_channels:  Skip windows with fewer than N unique channel_ids
    """
    if not items:
        return

    sorted_items = sorted(items, key=lambda x: x.timestamp)
    t_start = sorted_items[0].timestamp
    t_final = sorted_items[-1].timestamp
    n = len(sorted_items)

    window_idx = 0
    lo = 0  # left pointer: first item that could be >= t_start

    while t_start <= t_final:
        t_end = t_start + duration

        # Advance lo to skip items before t_start
        while lo < n and sorted_items[lo].timestamp < t_start:
            lo += 1

        # Collect items in [t_start, t_end) starting from lo
        batch: list[T] = []
        for i in range(lo, n):
            if sorted_items[i].timestamp >= t_end:
                break
            batch.append(sorted_items[i])

        if len(batch) >= min_items and (
            require_unique_channels == 0
            or len({getattr(x, "channel_id", None) for x in batch} - {None})
            >= require_unique_channels
        ):
            yield WindowBatch(
                window_id=_format_window_id(t_start, t_end),
                window_index=window_idx,
                window_start=t_start,
                window_end=t_end,
                items=batch,
            )
        window_idx += 1
        t_start += step


def daily_windows(
    items: Sequence[T],
    tz_offset_hours: float = 0.0,
    min_items: int = 1,
) -> Iterator[WindowBatch[T]]:
    """Convenience wrapper for calendar-day tumbling windows.

    tz_offset_hours: shift from UTC (e.g. 3.5 for Iran Standard Time).
    Items in the yielded WindowBatch are the original objects (not proxies).
    """
    offset = timedelta(hours=tz_offset_hours)

    # Create lightweight wrappers that shift the timestamp for alignment,
    # but track the original item so we can return it in the batch.
    wrappers = [_OffsetItem(item, item.timestamp + offset) for item in items]

    for batch in tumbling_windows(
        wrappers,
        duration=timedelta(hours=24),
        align_to_midnight=True,
        min_items=min_items,
    ):
        # Unwrap: return original items, not the offset wrappers
        yield WindowBatch(
            window_id=batch.window_id,
            window_index=batch.window_index,
            window_start=batch.window_start,
            window_end=batch.window_end,
            items=[w._original for w in batch.items],
        )


class _OffsetItem:
    """Internal: wraps an item with a shifted timestamp for alignment."""

    __slots__ = ("_original", "timestamp")

    def __init__(self, original: T, timestamp: datetime) -> None:
        self._original = original
        self.timestamp = timestamp

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


def describe_windows(batches: list[WindowBatch]) -> dict:
    """Return summary statistics for a list of window batches."""
    if not batches:
        return {"total_windows": 0}
    counts = [b.count for b in batches]
    return {
        "total_windows": len(batches),
        "total_items": sum(counts),
        "avg_items_per_window": round(sum(counts) / len(counts), 1),
        "min_items": min(counts),
        "max_items": max(counts),
        "first_window": batches[0].window_id,
        "last_window": batches[-1].window_id,
    }
