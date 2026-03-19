"""Unit tests for loom.contrib.rag.schemas — all schema modules."""

from datetime import UTC, datetime, timedelta


class TestLanguageEnum:
    def test_values(self):
        from loom.contrib.rag.schemas.post import Language

        assert Language.PERSIAN.value == "fa"
        assert Language.ARABIC.value == "ar"
        assert Language.ENGLISH.value == "en"
        assert Language.MIXED.value == "mixed"
        assert Language.UNKNOWN.value == "unknown"

    def test_from_value(self):
        from loom.contrib.rag.schemas.post import Language

        assert Language("fa") == Language.PERSIAN
        assert Language("unknown") == Language.UNKNOWN


class TestChannelBias:
    def test_all_bias_values(self):
        from loom.contrib.rag.schemas.post import ChannelBias

        expected = {
            "state_media",
            "state_aligned",
            "independent",
            "opposition",
            "fact_check",
            "neutral",
            "educational",
            "unknown",
        }
        actual = {b.value for b in ChannelBias}
        assert actual == expected


class TestNormalizedPost:
    def test_create_minimal(self):
        from loom.contrib.rag.schemas.post import NormalizedPost

        post = NormalizedPost(
            global_id="123:1",
            source_channel_id=123,
            source_channel_name="test",
            message_id=1,
            timestamp=datetime(2026, 3, 1, tzinfo=UTC),
        )
        assert post.global_id == "123:1"
        assert post.text_clean == ""
        assert post.language.value == "unknown"
        assert post.word_count == 0

    def test_extra_fields_allowed(self):
        from loom.contrib.rag.schemas.post import NormalizedPost

        post = NormalizedPost(
            global_id="123:1",
            source_channel_id=123,
            source_channel_name="test",
            message_id=1,
            timestamp=datetime(2026, 3, 1, tzinfo=UTC),
            custom_field="hello",
        )
        assert post.custom_field == "hello"


class TestMuxSchemas:
    def test_window_config_defaults(self):
        from loom.contrib.rag.schemas.mux import MuxWindowConfig

        cfg = MuxWindowConfig()
        assert cfg.window_duration == timedelta(hours=6)
        assert cfg.step is None
        assert cfg.is_sliding is False
        assert cfg.tz_offset_hours == 3.5

    def test_sliding_config(self):
        from loom.contrib.rag.schemas.mux import MuxWindowConfig

        cfg = MuxWindowConfig(
            window_duration=timedelta(hours=4),
            step=timedelta(hours=1),
        )
        assert cfg.is_sliding is True

    def test_mux_entry_delegates(self):
        from loom.contrib.rag.schemas.mux import MuxEntry
        from loom.contrib.rag.schemas.post import NormalizedPost

        ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        post = NormalizedPost(
            global_id="100:5",
            source_channel_id=100,
            source_channel_name="test_ch",
            message_id=5,
            timestamp=ts,
            text_clean="hello world",
        )
        entry = MuxEntry(mux_seq=0, post=post)
        assert entry.channel_id == 100
        assert entry.channel_name == "test_ch"
        assert entry.text == "hello world"
        assert entry.global_id == "100:5"
        assert entry.timestamp == ts

    def test_muxed_stream_properties(self):
        from loom.contrib.rag.schemas.mux import MuxedStream, MuxEntry
        from loom.contrib.rag.schemas.post import NormalizedPost

        ts1 = datetime(2026, 3, 1, tzinfo=UTC)
        ts2 = datetime(2026, 3, 2, tzinfo=UTC)
        p1 = NormalizedPost(
            global_id="1:1",
            source_channel_id=1,
            source_channel_name="a",
            message_id=1,
            timestamp=ts1,
        )
        p2 = NormalizedPost(
            global_id="2:1",
            source_channel_id=2,
            source_channel_name="b",
            message_id=1,
            timestamp=ts2,
        )
        stream = MuxedStream(
            source_ids=[1, 2],
            source_names=["a", "b"],
            start_time=ts1,
            end_time=ts2,
            total_entries=2,
            entries=[
                MuxEntry(mux_seq=0, post=p1, window_id="w1"),
                MuxEntry(mux_seq=1, post=p2, window_id="w1"),
            ],
        )
        assert stream.channel_count == 2
        assert stream.time_span_hours == 24.0
        assert stream.window_ids == ["w1"]
        assert len(stream.window("w1")) == 2


class TestChunkSchemas:
    def test_chunk_strategy(self):
        from loom.contrib.rag.schemas.chunk import ChunkStrategy

        assert ChunkStrategy.SENTENCE.value == "sentence"
        assert ChunkStrategy.WHOLE_POST.value == "whole_post"

    def test_text_chunk(self):
        from loom.contrib.rag.schemas.chunk import ChunkStrategy, TextChunk

        chunk = TextChunk(
            chunk_id="100:1:0",
            source_global_id="100:1",
            source_channel_id=100,
            source_channel_name="test",
            text="some text",
            char_start=0,
            char_end=9,
            chunk_index=0,
            total_chunks=1,
        )
        assert chunk.strategy == ChunkStrategy.SENTENCE
        assert chunk.overlap_chars == 0


class TestEmbeddingSchemas:
    def test_embedded_chunk(self):
        from loom.contrib.rag.schemas.embedding import EmbeddedChunk

        ec = EmbeddedChunk(
            chunk_id="1:1:0",
            source_global_id="1:1",
            source_channel_id=1,
            text="test",
            embedding=[0.1, 0.2, 0.3],
            model="nomic-embed-text",
            dimensions=3,
        )
        assert ec.dimensions == 3
        assert ec.embedded_at.tzinfo is not None

    def test_similarity_result(self):
        from loom.contrib.rag.schemas.embedding import SimilarityResult

        sr = SimilarityResult(
            chunk_id="1:1:0",
            text="hello",
            score=0.95,
            source_channel_id=1,
            source_global_id="1:1",
        )
        assert sr.score == 0.95


class TestAnalysisSchemas:
    def test_analysis_type_enum(self):
        from loom.contrib.rag.schemas.analysis import AnalysisType

        assert AnalysisType.TREND.value == "trend"
        assert AnalysisType.DATA_EXTRACT.value == "data_extract"

    def test_trend_signal(self):
        from loom.contrib.rag.schemas.analysis import Severity, TrendSignal

        ts = TrendSignal(
            window_id="w1",
            window_start=datetime(2026, 3, 1, tzinfo=UTC),
            window_end=datetime(2026, 3, 1, 6, tzinfo=UTC),
            actor_id="trend-1",
            source_entry_ids=["1:1"],
            confidence=0.8,
            model_used="test",
            topic_label="Economy",
            description="Economic topics",
            channels_present=["ch1"],
            post_count=5,
            exemplar_post_ids=["1:1"],
            keywords=["economy"],
        )
        assert ts.severity == Severity.LOW
        assert ts.analysis_type.value == "trend"

    def test_extracted_data_by_type(self):
        from loom.contrib.rag.schemas.analysis import (
            ExtractedData,
            ExtractedDataType,
            ExtractedDatum,
        )

        data = ExtractedData(
            window_id="w1",
            window_start=datetime(2026, 3, 1, tzinfo=UTC),
            window_end=datetime(2026, 3, 1, 6, tzinfo=UTC),
            actor_id="extractor-1",
            source_entry_ids=["1:1"],
            confidence=0.8,
            model_used="test",
            data=[
                ExtractedDatum(
                    datum_type=ExtractedDataType.STATISTIC,
                    value="50%",
                    source_global_id="1:1",
                    source_channel="ch1",
                    timestamp_unix=0,
                    context_snippet="about 50%",
                ),
                ExtractedDatum(
                    datum_type=ExtractedDataType.PERSON,
                    value="Ali",
                    source_global_id="1:2",
                    source_channel="ch1",
                    timestamp_unix=0,
                    context_snippet="Ali said",
                ),
            ],
        )
        by_type = data.by_type()
        assert ExtractedDataType.STATISTIC in by_type
        assert ExtractedDataType.PERSON in by_type
        assert len(by_type[ExtractedDataType.STATISTIC]) == 1


class TestTelegramSchemas:
    def test_raw_message_plain_text_string(self):
        from loom.contrib.rag.schemas.telegram import RawTelegramMessage

        msg = RawTelegramMessage(
            id=1,
            type="message",
            date=datetime(2026, 3, 1),
            date_unixtime="1740787200",
            text="simple text",
        )
        assert msg.plain_text == "simple text"
        assert msg.has_text is True

    def test_raw_message_plain_text_list(self):
        from loom.contrib.rag.schemas.telegram import RawTelegramMessage

        msg = RawTelegramMessage(
            id=2,
            type="message",
            date=datetime(2026, 3, 1),
            date_unixtime="1740787200",
            text=[
                "Hello ",
                {"type": "bold", "text": "world"},
                "!",
            ],
        )
        assert msg.plain_text == "Hello world!"

    def test_reaction_total(self):
        from loom.contrib.rag.schemas.telegram import RawTelegramMessage, ReactionCount

        msg = RawTelegramMessage(
            id=3,
            type="message",
            date=datetime(2026, 3, 1),
            date_unixtime="1740787200",
            text="test",
            reactions=[
                ReactionCount(type="emoji", count=5, emoji="\U0001f44d"),
                ReactionCount(type="emoji", count=3, emoji="\u2764"),
            ],
        )
        assert msg.reaction_total == 8
        assert msg.is_forward is False

    def test_channel_model(self):
        from loom.contrib.rag.schemas.telegram import TelegramChannel

        ch = TelegramChannel(name="Test", type="public_channel", id=12345)
        assert len(ch.messages) == 0
        assert len(ch.message_messages) == 0


class TestSchemaImports:
    """Ensure all public exports from schemas/__init__.py work."""

    def test_all_exports(self):
        from loom.contrib.rag.schemas import (
            Language,
        )

        assert Language.PERSIAN.value == "fa"
