"""Unit tests for loom.contrib.rag.tools — RTL normalizer and temporal batcher."""

from datetime import UTC, datetime, timedelta


class TestRTLNormalizer:
    def test_basic_normalization(self):
        from loom.contrib.rag.tools.rtl_normalizer import normalize

        result = normalize("Hello world!", strip_emojis=True)
        assert result.text_clean == "Hello world!"
        assert result.language_hint == "en"
        assert result.is_rtl is False

    def test_persian_text(self):
        from loom.contrib.rag.tools.rtl_normalizer import normalize

        result = normalize("\u0633\u0644\u0627\u0645 \u062f\u0646\u06cc\u0627")  # سلام دنیا
        assert result.is_rtl is True
        assert result.language_hint == "fa"

    def test_digit_normalization(self):
        from loom.contrib.rag.tools.rtl_normalizer import normalize

        # Eastern Arabic digits -> Western
        result = normalize("\u06f1\u06f2\u06f3\u06f4", normalize_digits=True)
        assert "1234" in result.text_clean

    def test_emoji_stripping(self):
        from loom.contrib.rag.tools.rtl_normalizer import normalize

        result = normalize("Hello \U0001f600 world", strip_emojis=True)
        assert "\U0001f600" not in result.text_clean
        assert len(result.emojis_found) > 0

    def test_emoji_preservation(self):
        from loom.contrib.rag.tools.rtl_normalizer import normalize

        result = normalize("Hello \U0001f600 world", strip_emojis=False)
        assert "\U0001f600" in result.text_clean

    def test_hashtag_extraction(self):
        from loom.contrib.rag.tools.rtl_normalizer import normalize

        result = normalize("Check #trending and #news today")
        assert "#trending" in result.hashtags
        assert "#news" in result.hashtags

    def test_mention_extraction(self):
        from loom.contrib.rag.tools.rtl_normalizer import normalize

        result = normalize("Follow @channel_name")
        assert "@channel_name" in result.mentions

    def test_tg_footer_stripping(self):
        from loom.contrib.rag.tools.rtl_normalizer import normalize

        text = "Real content.\n@channelname"
        result = normalize(text, strip_tg_footer=True)
        assert "@channelname" not in result.text_clean

    def test_link_extraction(self):
        from loom.contrib.rag.tools.rtl_normalizer import extract_links_from_entities

        entities = [
            {"type": "text_link", "text": "click", "href": "https://example.com"},
            {"type": "bold", "text": "bold"},
        ]
        links = extract_links_from_entities(entities)
        assert links == ["https://example.com"]

    def test_arabic_to_persian_substitution(self):
        from loom.contrib.rag.tools.rtl_normalizer import normalize

        # Arabic kaf (U+0643) -> Persian kaf (U+06A9)
        result = normalize("\u0643\u062a\u0627\u0628")
        assert "\u06a9" in result.text_clean


class TestTemporalBatcher:
    """Test tumbling_windows, sliding_windows, daily_windows."""

    class FakeItem:
        def __init__(self, ts: datetime, channel_id: int = 1):
            self.timestamp = ts
            self.channel_id = channel_id

    def _make_items(self, count: int = 10, start_hour: int = 0) -> list:
        base = datetime(2026, 3, 1, start_hour, tzinfo=UTC)
        return [self.FakeItem(base + timedelta(hours=i)) for i in range(count)]

    def test_tumbling_windows_basic(self):
        from loom.contrib.rag.tools.temporal_batcher import tumbling_windows

        items = self._make_items(24)
        batches = list(tumbling_windows(items, timedelta(hours=6)))
        assert len(batches) == 4
        assert all(b.count == 6 for b in batches)

    def test_tumbling_empty(self):
        from loom.contrib.rag.tools.temporal_batcher import tumbling_windows

        assert list(tumbling_windows([], timedelta(hours=6))) == []

    def test_sliding_windows_overlap(self):
        from loom.contrib.rag.tools.temporal_batcher import sliding_windows

        items = self._make_items(12)
        batches = list(
            sliding_windows(
                items,
                duration=timedelta(hours=6),
                step=timedelta(hours=3),
            )
        )
        # With overlap, we get more windows than tumbling
        assert len(batches) >= 3

    def test_daily_windows(self):
        from loom.contrib.rag.tools.temporal_batcher import daily_windows

        items = self._make_items(48)  # 2 days
        batches = list(daily_windows(items))
        assert len(batches) == 2

    def test_describe_windows(self):
        from loom.contrib.rag.tools.temporal_batcher import describe_windows, tumbling_windows

        items = self._make_items(12)
        batches = list(tumbling_windows(items, timedelta(hours=6)))
        stats = describe_windows(batches)
        assert stats["total_windows"] == 2
        assert stats["total_items"] == 12

    def test_describe_empty(self):
        from loom.contrib.rag.tools.temporal_batcher import describe_windows

        assert describe_windows([])["total_windows"] == 0

    def test_window_batch_channel_ids(self):
        from loom.contrib.rag.tools.temporal_batcher import tumbling_windows

        items = [
            self.FakeItem(datetime(2026, 3, 1, tzinfo=UTC), channel_id=1),
            self.FakeItem(datetime(2026, 3, 1, 1, tzinfo=UTC), channel_id=2),
            self.FakeItem(datetime(2026, 3, 1, 2, tzinfo=UTC), channel_id=1),
        ]
        batches = list(tumbling_windows(items, timedelta(hours=24)))
        assert batches[0].channel_ids() == {1, 2}


class TestToolImports:
    def test_all_exports(self):
        pass
