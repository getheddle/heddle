"""StreamMux: merge multiple NormalizedPost iterables into a time-ordered stream.

Key behaviors:
  - Stable sort by timestamp (UTC), tie-break by channel_id
  - Assigns global mux_seq and optional window_id
  - Emits MuxEntry objects (NormalizedPost + mux metadata)
  - In NATS actor mode: subscribes to rag.ingestion.* and publishes to rag.mux.stream

NATS actor contract:
  Subscribe: rag.ingestion.*           (all channel ingestion subjects)
  Publish:   rag.mux.stream            (MuxEntry JSON)
  Publish:   rag.mux.window.<window_id> (windowed batch for analysis actors)
"""

from __future__ import annotations

import logging
from itertools import chain
from typing import TYPE_CHECKING

from ..schemas.mux import MuxedStream, MuxEntry, MuxWindowConfig
from ..tools.temporal_batcher import describe_windows, sliding_windows, tumbling_windows

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..ingestion.telegram_ingestor import TelegramIngestor
    from ..schemas.post import NormalizedPost

logger = logging.getLogger(__name__)


class StreamMux:
    """Multiplex N NormalizedPost streams into a single chronological MuxedStream.

    Typical usage::

        mux = StreamMux()
        mux.add_stream(factnameh_posts)
        mux.add_stream(iranwire_posts)
        mux.add_stream(farsnews_posts)
        result = mux.merge()

        for window in result.iter_windows(MuxWindowConfig(window_duration=timedelta(hours=6))):
            process_window(window)
    """

    def __init__(self) -> None:
        self._streams: list[Iterable[NormalizedPost]] = []
        self._channel_meta: list[tuple[int, str]] = []  # (id, name)

    def add_stream(
        self,
        posts: Iterable[NormalizedPost],
        channel_id: int | None = None,
        channel_name: str | None = None,
    ) -> StreamMux:
        """Register a post stream.

        channel_id/name are auto-detected from first post if not provided.
        """
        # Materialize to list so we can inspect metadata
        post_list = list(posts)
        if not post_list:
            logger.warning("Empty stream added to mux -- skipping")
            return self

        cid = channel_id or post_list[0].source_channel_id
        cname = channel_name or post_list[0].source_channel_name

        self._streams.append(iter(post_list))
        self._channel_meta.append((cid, cname))
        logger.info("Registered stream: '%s' (id=%d) with %d posts", cname, cid, len(post_list))
        return self

    def merge(self, window_config: MuxWindowConfig | None = None) -> MuxedStream:
        """
        Merge all registered streams into a chronological MuxedStream.

        Args:
            window_config: If provided, assign window_id to each entry.
        """
        if not self._streams:
            raise ValueError("No streams registered. Call add_stream() first.")

        all_posts: list[NormalizedPost] = list(chain.from_iterable(self._streams))

        # Sort by timestamp, tie-break by channel_id for determinism
        all_posts.sort(key=lambda p: (p.timestamp, p.source_channel_id))

        if not all_posts:
            raise ValueError("All registered streams were empty.")

        # Assign window IDs if config provided
        window_map: dict[str, str] = {}  # global_id -> window_id
        window_seq_map: dict[str, int] = {}

        if window_config:
            window_map, window_seq_map = self._compute_window_assignments(all_posts, window_config)

        # Build MuxEntry list
        entries: list[MuxEntry] = []
        for seq, post in enumerate(all_posts):
            gid = post.global_id
            entries.append(
                MuxEntry(
                    mux_seq=seq,
                    post=post,
                    window_id=window_map.get(gid),
                    window_seq=window_seq_map.get(gid),
                )
            )

        source_ids = [m[0] for m in self._channel_meta]
        source_names = [m[1] for m in self._channel_meta]

        stream = MuxedStream(
            source_ids=source_ids,
            source_names=source_names,
            start_time=all_posts[0].timestamp,
            end_time=all_posts[-1].timestamp,
            total_entries=len(entries),
            entries=entries,
        )

        logger.info(
            "Merged %d posts from %d channels: %s -> %s",
            len(entries),
            len(self._channel_meta),
            stream.start_time.isoformat(),
            stream.end_time.isoformat(),
        )

        return stream

    def _compute_window_assignments(
        self,
        posts: list[NormalizedPost],
        config: MuxWindowConfig,
    ) -> tuple[dict[str, str], dict[str, int]]:
        """Pre-compute window_id for each post so MuxEntry can carry it.

        Returns (window_map, window_seq_map).

        NormalizedPost already has a ``timestamp`` attribute, so no proxy
        adapter is needed to satisfy the HasTimestamp protocol.
        """
        window_map: dict[str, str] = {}
        window_seq_map: dict[str, int] = {}

        if config.is_sliding and config.step:
            batches = list(sliding_windows(posts, config.window_duration, config.step))
        else:
            batches = list(tumbling_windows(posts, config.window_duration))

        logger.info("Window assignment: %s", describe_windows(batches))

        for batch in batches:
            for pos, post in enumerate(batch.items):
                gid = post.global_id
                # First window wins for overlapping windows
                if gid not in window_map:
                    window_map[gid] = batch.window_id
                    window_seq_map[gid] = pos

        return window_map, window_seq_map


def merge_from_ingestors(
    ingestors: list[TelegramIngestor],
    window_config: MuxWindowConfig | None = None,
) -> MuxedStream:
    """
    Convenience: load + ingest + merge from a list of TelegramIngestor instances.

    Args:
        ingestors:      List of TelegramIngestor (already load()-ed)
        window_config:  Optional windowing config

    Returns:
        MuxedStream ready for analysis
    """
    mux = StreamMux()
    for ingestor in ingestors:
        posts = ingestor.ingest_all()
        mux.add_stream(
            posts,
            channel_id=ingestor.channel_id,
            channel_name=ingestor.channel_name,
        )
    return mux.merge(window_config=window_config)
