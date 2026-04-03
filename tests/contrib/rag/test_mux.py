"""Unit tests for heddle.contrib.rag.mux.stream_mux."""

from datetime import UTC, datetime, timedelta

import pytest

from heddle.contrib.rag.schemas.mux import MuxWindowConfig
from heddle.contrib.rag.schemas.post import NormalizedPost


def _make_post(channel_id: int, msg_id: int, hour: int) -> NormalizedPost:
    return NormalizedPost(
        global_id=f"{channel_id}:{msg_id}",
        source_channel_id=channel_id,
        source_channel_name=f"ch_{channel_id}",
        message_id=msg_id,
        timestamp=datetime(2026, 3, 1, hour, tzinfo=UTC),
        text_clean=f"Post {msg_id} from channel {channel_id}",
    )


class TestStreamMux:
    def test_merge_two_channels(self):
        from heddle.contrib.rag.mux.stream_mux import StreamMux

        mux = StreamMux()
        mux.add_stream([_make_post(1, 1, 0), _make_post(1, 2, 2)])
        mux.add_stream([_make_post(2, 1, 1), _make_post(2, 2, 3)])

        stream = mux.merge()
        assert stream.total_entries == 4
        assert stream.channel_count == 2
        # Check chronological order
        timestamps = [e.timestamp for e in stream.entries]
        assert timestamps == sorted(timestamps)

    def test_merge_with_windows(self):
        from heddle.contrib.rag.mux.stream_mux import StreamMux

        mux = StreamMux()
        # Create posts spanning 12 hours
        for h in range(12):
            mux.add_stream([_make_post(1, h, h)])

        config = MuxWindowConfig(window_duration=timedelta(hours=6))
        stream = mux.merge(window_config=config)
        assert stream.total_entries == 12
        # Should have 2 windows of 6 hours each
        window_ids = stream.window_ids
        assert len(window_ids) == 2

    def test_merge_empty_stream_skipped(self):
        from heddle.contrib.rag.mux.stream_mux import StreamMux

        mux = StreamMux()
        mux.add_stream([])  # empty
        mux.add_stream([_make_post(1, 1, 0)])

        stream = mux.merge()
        assert stream.total_entries == 1

    def test_merge_no_streams_raises(self):
        from heddle.contrib.rag.mux.stream_mux import StreamMux

        mux = StreamMux()
        with pytest.raises(ValueError, match="No streams registered"):
            mux.merge()

    def test_mux_seq_sequential(self):
        from heddle.contrib.rag.mux.stream_mux import StreamMux

        mux = StreamMux()
        mux.add_stream([_make_post(1, i, i) for i in range(5)])
        stream = mux.merge()
        seqs = [e.mux_seq for e in stream.entries]
        assert seqs == [0, 1, 2, 3, 4]

    def test_windows_grouping(self):
        from heddle.contrib.rag.mux.stream_mux import StreamMux

        mux = StreamMux()
        for h in range(12):
            mux.add_stream([_make_post(1, h, h)])

        config = MuxWindowConfig(window_duration=timedelta(hours=6))
        stream = mux.merge(window_config=config)
        windows = stream.windows()
        assert len(windows) == 2
        for wid, entries in windows.items():
            assert len(entries) == 6

    def test_merge_from_ingestors(self, tmp_path):
        """Test merge_from_ingestors convenience function."""
        import json

        from heddle.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor
        from heddle.contrib.rag.mux.stream_mux import merge_from_ingestors

        # Create two minimal exports
        for i, cid in enumerate([100, 200]):
            data = {
                "name": f"channel_{cid}",
                "type": "public_channel",
                "id": cid,
                "messages": [
                    {
                        "id": j,
                        "type": "message",
                        "date": f"2026-03-01T{10 + j}:00:00",
                        "date_unixtime": str(1740826800 + j * 3600),
                        "text": f"Message {j} from channel {cid} with enough text.",
                    }
                    for j in range(3)
                ],
            }
            (tmp_path / f"ch{i}.json").write_text(json.dumps(data))

        ingestors = [
            TelegramIngestor(tmp_path / f"ch{i}.json", min_text_len=5).load() for i in range(2)
        ]
        stream = merge_from_ingestors(ingestors)
        assert stream.total_entries == 6
        assert stream.channel_count == 2
