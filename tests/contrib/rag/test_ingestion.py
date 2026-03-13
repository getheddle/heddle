"""Unit tests for loom.contrib.rag.ingestion.telegram_ingestor."""
import json
import pytest
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _make_export(messages: list[dict], channel_name: str = "test", channel_id: int = 99) -> Path:
    """Create a minimal Telegram export JSON in a temp file."""
    data = {
        "name": channel_name,
        "type": "public_channel",
        "id": channel_id,
        "messages": messages,
    }
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return Path(f.name)


class TestTelegramIngestor:
    def test_basic_ingestion(self):
        from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor
        path = _make_export([
            {"id": 1, "type": "message", "date": "2026-03-01T10:00:00",
             "date_unixtime": "1740826800", "text": "Hello world from Telegram channel."},
            {"id": 2, "type": "message", "date": "2026-03-01T11:00:00",
             "date_unixtime": "1740830400", "text": "Another message with enough text for ingestion."},
        ])
        ingestor = TelegramIngestor(path, min_text_len=5).load()
        posts = ingestor.ingest_all()
        assert len(posts) == 2
        assert posts[0].source_channel_id == 99
        assert posts[0].global_id == "99:1"

    def test_skip_service_messages(self):
        from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor
        path = _make_export([
            {"id": 1, "type": "service", "date": "2026-03-01T10:00:00",
             "date_unixtime": "1740826800", "text": "joined the channel"},
            {"id": 2, "type": "message", "date": "2026-03-01T11:00:00",
             "date_unixtime": "1740830400", "text": "A real message that should be included."},
        ])
        ingestor = TelegramIngestor(path, min_text_len=5).load()
        posts = ingestor.ingest_all()
        assert len(posts) == 1

    def test_skip_short_messages(self):
        from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor
        path = _make_export([
            {"id": 1, "type": "message", "date": "2026-03-01T10:00:00",
             "date_unixtime": "1740826800", "text": "Hi"},
        ])
        ingestor = TelegramIngestor(path, min_text_len=10).load()
        posts = ingestor.ingest_all()
        assert len(posts) == 0

    def test_polymorphic_text(self):
        from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor
        path = _make_export([
            {"id": 1, "type": "message", "date": "2026-03-01T10:00:00",
             "date_unixtime": "1740826800",
             "text": ["Hello ", {"type": "bold", "text": "bold"}, " world!"]},
        ])
        ingestor = TelegramIngestor(path, min_text_len=5).load()
        posts = ingestor.ingest_all()
        assert len(posts) == 1
        assert "bold" in posts[0].text_raw

    def test_file_not_found(self):
        from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor
        with pytest.raises(FileNotFoundError):
            TelegramIngestor("/nonexistent/path.json").load()

    def test_reactions_extracted(self):
        from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor
        path = _make_export([
            {"id": 1, "type": "message", "date": "2026-03-01T10:00:00",
             "date_unixtime": "1740826800",
             "text": "Post with reactions from users that like it.",
             "reactions": [
                 {"type": "emoji", "count": 10, "emoji": "\U0001f44d"},
                 {"type": "paid", "count": 5},
             ]},
        ])
        ingestor = TelegramIngestor(path, min_text_len=5).load()
        posts = ingestor.ingest_all()
        assert posts[0].reaction_total == 15
        assert posts[0].reaction_breakdown["\U0001f44d"] == 10

    def test_forwarded_detection(self):
        from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor
        path = _make_export([
            {"id": 1, "type": "message", "date": "2026-03-01T10:00:00",
             "date_unixtime": "1740826800",
             "text": "Forwarded message content is here for testing.",
             "forwarded_from": "other_channel"},
        ])
        ingestor = TelegramIngestor(path, min_text_len=5).load()
        posts = ingestor.ingest_all()
        assert posts[0].is_forward is True
        assert posts[0].forwarded_from == "other_channel"

    def test_default_profiles(self):
        from loom.contrib.rag.ingestion.telegram_ingestor import DEFAULT_PROFILES
        from loom.contrib.rag.schemas.post import ChannelBias
        # FarsNews
        assert 1006939659 in DEFAULT_PROFILES
        assert DEFAULT_PROFILES[1006939659].bias == ChannelBias.STATE_MEDIA
        assert DEFAULT_PROFILES[1006939659].trust_weight == 0.3

        # Factnameh
        assert 1098179827 in DEFAULT_PROFILES
        assert DEFAULT_PROFILES[1098179827].bias == ChannelBias.FACT_CHECK


class TestIngestorProperties:
    def test_channel_properties(self):
        from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor
        path = _make_export(
            [{"id": 1, "type": "message", "date": "2026-03-01T10:00:00",
              "date_unixtime": "1740826800", "text": "Test message content here."}],
            channel_name="MyChannel",
            channel_id=42,
        )
        ingestor = TelegramIngestor(path, min_text_len=5).load()
        assert ingestor.channel_id == 42
        assert ingestor.channel_name == "MyChannel"
