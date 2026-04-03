"""Tests for TelegramLiveIngestor — live channel monitoring via Telethon."""

import pytest


class TestTelegramLiveIngestorConfig:
    """Test configuration and validation (no Telethon needed)."""

    def test_extends_ingestor(self):
        from heddle.contrib.rag.ingestion.base import Ingestor
        from heddle.contrib.rag.ingestion.telegram_live import TelegramLiveIngestor

        assert issubclass(TelegramLiveIngestor, Ingestor)

    def test_load_requires_credentials(self):
        from heddle.contrib.rag.ingestion.telegram_live import TelegramLiveIngestor

        ingestor = TelegramLiveIngestor(channels=["@test"])
        with pytest.raises(ValueError, match="credentials"):
            ingestor.load()

    def test_load_requires_channels(self):
        from heddle.contrib.rag.ingestion.telegram_live import TelegramLiveIngestor

        ingestor = TelegramLiveIngestor(api_id=12345, api_hash="abc123", channels=[])
        with pytest.raises(ValueError, match="channel"):
            ingestor.load()

    def test_load_success(self):
        from heddle.contrib.rag.ingestion.telegram_live import TelegramLiveIngestor

        ingestor = TelegramLiveIngestor(
            channels=["@test"],
            api_id=12345,
            api_hash="abc123",
        )
        result = ingestor.load()
        assert result is ingestor

    def test_status_before_start(self):
        from heddle.contrib.rag.ingestion.telegram_live import TelegramLiveIngestor

        ingestor = TelegramLiveIngestor(
            channels=["@a", "@b"],
            api_id=1,
            api_hash="x",
        )
        status = ingestor.status()
        assert status["running"] is False
        assert status["channels_configured"] == 2
        assert status["total_received"] == 0
        assert status["buffer_size"] == 0

    def test_ingest_empty_buffer(self):
        from heddle.contrib.rag.ingestion.telegram_live import TelegramLiveIngestor

        ingestor = TelegramLiveIngestor(
            channels=["@test"],
            api_id=1,
            api_hash="x",
        )
        posts = ingestor.ingest_all()
        assert posts == []

    def test_ingest_drains_buffer(self):
        from datetime import UTC, datetime

        from heddle.contrib.rag.ingestion.telegram_live import TelegramLiveIngestor
        from heddle.contrib.rag.schemas.post import NormalizedPost

        ingestor = TelegramLiveIngestor(
            channels=["@test"],
            api_id=1,
            api_hash="x",
        )

        # Manually add posts to buffer
        post = NormalizedPost(
            global_id="1:1",
            source_channel_id=1,
            source_channel_name="test",
            message_id=1,
            timestamp=datetime(2026, 3, 1, tzinfo=UTC),
            text_clean="test post content",
        )
        ingestor._buffer.append(post)
        assert ingestor.buffer_size == 1

        posts = ingestor.ingest_all()
        assert len(posts) == 1
        assert posts[0].global_id == "1:1"
        assert ingestor.buffer_size == 0

    def test_fetch_recent(self):
        from datetime import UTC, datetime

        from heddle.contrib.rag.ingestion.telegram_live import TelegramLiveIngestor
        from heddle.contrib.rag.schemas.post import NormalizedPost

        ingestor = TelegramLiveIngestor(
            channels=["@test"],
            api_id=1,
            api_hash="x",
        )

        for i in range(5):
            post = NormalizedPost(
                global_id=f"1:{i}",
                source_channel_id=1,
                source_channel_name="test",
                message_id=i,
                timestamp=datetime(2026, 3, 1, i, tzinfo=UTC),
                text_clean=f"post {i}",
            )
            ingestor._buffer.append(post)

        recent = ingestor.fetch_recent(limit=3)
        assert len(recent) == 3
        # Should not drain the buffer
        assert ingestor.buffer_size == 5

    def test_env_var_defaults(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_API_ID", "99999")
        monkeypatch.setenv("TELEGRAM_API_HASH", "env_hash")
        monkeypatch.setenv("TELEGRAM_SESSION", "/tmp/test.session")

        from heddle.contrib.rag.ingestion.telegram_live import TelegramLiveIngestor

        ingestor = TelegramLiveIngestor(channels=["@test"])
        assert ingestor._api_id == 99999
        assert ingestor._api_hash == "env_hash"
        assert ingestor._session_path == "/tmp/test.session"


class TestNormalize:
    """Test shared normalization utilities."""

    def test_resolve_editor_profile_override(self):
        from heddle.contrib.rag.ingestion.normalize import resolve_editor_profile
        from heddle.contrib.rag.schemas.post import ChannelBias, ChannelEditorProfile

        override = ChannelEditorProfile(
            channel_id=1, channel_name="override", bias=ChannelBias.INDEPENDENT, trust_weight=0.9
        )
        result = resolve_editor_profile(1, "test", override=override)
        assert result.channel_name == "override"

    def test_resolve_editor_profile_from_dict(self):
        from heddle.contrib.rag.ingestion.normalize import resolve_editor_profile
        from heddle.contrib.rag.schemas.post import ChannelBias, ChannelEditorProfile

        profiles = {
            42: ChannelEditorProfile(
                channel_id=42, channel_name="dict", bias=ChannelBias.STATE_MEDIA, trust_weight=0.3
            )
        }
        result = resolve_editor_profile(42, "test", profiles=profiles)
        assert result.channel_name == "dict"

    def test_resolve_editor_profile_default(self):
        from heddle.contrib.rag.ingestion.normalize import resolve_editor_profile

        result = resolve_editor_profile(999, "fallback")
        assert result.channel_name == "fallback"
        assert result.trust_weight == 0.5
