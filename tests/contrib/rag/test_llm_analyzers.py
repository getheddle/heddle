"""Tests for LLM-backed analysis actors (TrendAnalyzer, CorroborationFinder,
AnomalyDetector, DataExtractor).

All tests use a mock LLM backend to avoid real API calls.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from loom.contrib.rag.analysis.llm_analyzers import (
    AnomalyDetector,
    BaseAnalysisActor,
    CorroborationFinder,
    DataExtractor,
    LLMBackend,
    TrendAnalyzer,
)
from loom.contrib.rag.schemas.analysis import (
    AnalysisType,
    AnomalyType,
    Severity,
)
from loom.contrib.rag.schemas.mux import MuxEntry
from loom.contrib.rag.schemas.post import NormalizedPost

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class MockLLMBackend(LLMBackend):
    """LLM backend that returns pre-configured JSON responses."""

    def __init__(self, response: dict | str = "{}"):
        super().__init__(model="mock:test")
        self._response = response if isinstance(response, str) else json.dumps(response)

    def complete(self, system: str, user: str) -> str:
        return self._response


def _make_post(
    channel_id: int = 1098179827,
    channel_name: str = "FactNameh",
    text: str = "Test post text",
    ts: datetime | None = None,
    global_id: str = "post_1",
) -> NormalizedPost:
    ts = ts or datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    return NormalizedPost(
        source_channel_id=channel_id,
        source_channel_name=channel_name,
        global_id=global_id,
        message_id=int(global_id.rsplit("_", maxsplit=1)[-1]) if "_" in global_id else 1,
        text_raw=text,
        text_clean=text,
        timestamp=ts,
        timestamp_unix=int(ts.timestamp()),
        language="fa",
    )


def _make_entry(
    seq: int = 1,
    channel_id: int = 1098179827,
    channel_name: str = "FactNameh",
    text: str = "Test post text",
    ts: datetime | None = None,
    window_id: str = "w1",
    global_id: str | None = None,
) -> MuxEntry:
    gid = global_id or f"post_{seq}"
    post = _make_post(
        channel_id=channel_id,
        channel_name=channel_name,
        text=text,
        ts=ts or datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
        global_id=gid,
    )
    return MuxEntry(mux_seq=seq, window_id=window_id, post=post)


def _make_entries(n: int = 5, multi_channel: bool = False) -> list[MuxEntry]:
    """Create n MuxEntry objects spanning 1 hour."""
    base_ts = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    entries = []
    for i in range(n):
        cid = 1098179827 if (not multi_channel or i % 2 == 0) else 1008727276
        cname = "FactNameh" if cid == 1098179827 else "Iranwire"
        entries.append(
            _make_entry(
                seq=i + 1,
                channel_id=cid,
                channel_name=cname,
                text=f"Post {i + 1} about topic {i % 3}",
                ts=base_ts + timedelta(minutes=i * 10),
                global_id=f"post_{i + 1}",
            )
        )
    return entries


# ---------------------------------------------------------------------------
# LLMBackend tests
# ---------------------------------------------------------------------------


class TestLLMBackend:
    def test_ollama_prefix(self):
        b = LLMBackend(model="ollama:llama3.2")
        assert b._backend == "ollama"
        assert b._model_name == "llama3.2"

    def test_anthropic_prefix(self):
        b = LLMBackend(model="anthropic:claude-3-haiku")
        assert b._backend == "anthropic"
        assert b._model_name == "claude-3-haiku"

    def test_no_prefix_defaults_ollama(self):
        b = LLMBackend(model="llama3.2")
        assert b._backend == "ollama"
        assert b._model_name == "llama3.2"

    def test_complete_retries_and_returns_empty_on_failure(self):
        b = LLMBackend(model="ollama:test")
        with patch.object(b, "_ollama_complete", side_effect=RuntimeError("fail")):
            result = b.complete("sys", "usr")
        assert result == "{}"

    def test_complete_json_strips_markdown_fences(self):
        b = MockLLMBackend()
        b._response = '```json\n{"key": "val"}\n```'
        result = b.complete_json("sys", "usr")
        assert result == {"key": "val"}

    def test_complete_json_handles_invalid_json(self):
        b = MockLLMBackend()
        b._response = "not json at all"
        result = b.complete_json("sys", "usr")
        assert result == {}

    def test_complete_json_plain_json(self):
        b = MockLLMBackend()
        b._response = '{"a": 1}'
        assert b.complete_json("sys", "usr") == {"a": 1}

    def test_complete_unknown_backend(self):
        b = LLMBackend(model="ollama:test")
        b._backend = "unknown"
        result = b.complete("sys", "usr")
        assert result == "{}"


# ---------------------------------------------------------------------------
# BaseAnalysisActor tests
# ---------------------------------------------------------------------------


class TestBaseAnalysisActor:
    def test_window_meta(self):
        entries = _make_entries(3)
        actor = BaseAnalysisActor("test-actor", llm=MockLLMBackend())
        meta = actor._window_meta(entries)
        assert meta["window_id"] == "w1"
        assert meta["window_start"] == entries[0].timestamp
        assert meta["window_end"] == entries[-1].timestamp

    def test_format_posts(self):
        entries = _make_entries(2)
        actor = BaseAnalysisActor("test-actor", llm=MockLLMBackend())
        text = actor._format_posts(entries)
        assert "[1]" in text
        assert "[2]" in text
        assert "FactNameh" in text

    def test_format_posts_max_posts(self):
        entries = _make_entries(5)
        actor = BaseAnalysisActor("test-actor", llm=MockLLMBackend())
        text = actor._format_posts(entries, max_posts=2)
        assert "[1]" in text
        assert "[2]" in text
        assert "[3]" not in text

    def test_default_llm_creation(self):
        actor = BaseAnalysisActor("test-actor", model="ollama:test-model")
        assert actor.llm.model == "ollama:test-model"

    def test_now(self):
        actor = BaseAnalysisActor("test-actor", llm=MockLLMBackend())
        now = actor._now()
        assert now.tzinfo == UTC


# ---------------------------------------------------------------------------
# TrendAnalyzer tests
# ---------------------------------------------------------------------------


class TestTrendAnalyzer:
    def test_empty_entries(self):
        llm = MockLLMBackend({"trends": []})
        analyzer = TrendAnalyzer("trend-1", llm=llm)
        assert analyzer.analyze([]) == []

    def test_basic_trend_detection(self):
        llm = MockLLMBackend(
            {
                "trends": [
                    {
                        "topic_label": "earthquake",
                        "topic_label_fa": "زلزله",
                        "description": "Reports of earthquake damage",
                        "channels_present": ["FactNameh"],
                        "post_indices": [1, 2],
                        "keywords": ["earthquake", "damage"],
                        "sentiment": "negative",
                        "severity": "high",
                    }
                ]
            }
        )
        entries = _make_entries(3)
        analyzer = TrendAnalyzer("trend-1", llm=llm)
        signals = analyzer.analyze(entries)
        assert len(signals) == 1
        assert signals[0].topic_label == "earthquake"
        assert signals[0].analysis_type == AnalysisType.TREND
        assert signals[0].severity == Severity.HIGH
        assert signals[0].actor_id == "trend-1"
        assert len(signals[0].exemplar_post_ids) == 2

    def test_invalid_post_indices_filtered(self):
        llm = MockLLMBackend(
            {
                "trends": [
                    {
                        "topic_label": "test",
                        "description": "test",
                        "channels_present": [],
                        "post_indices": [1, 999],
                        "keywords": [],
                        "sentiment": "neutral",
                        "severity": "low",
                    }
                ]
            }
        )
        entries = _make_entries(2)
        analyzer = TrendAnalyzer("trend-1", llm=llm)
        signals = analyzer.analyze(entries)
        assert len(signals) == 1
        assert len(signals[0].exemplar_post_ids) == 1

    def test_malformed_trend_skipped(self):
        llm = MockLLMBackend(
            {
                "trends": [
                    {
                        "topic_label": "good",
                        "description": "ok",
                        "channels_present": [],
                        "post_indices": [],
                        "keywords": [],
                        "sentiment": "neutral",
                        "severity": "low",
                    },
                    {"severity": "INVALID_ENUM_VALUE"},
                ]
            }
        )
        entries = _make_entries(2)
        analyzer = TrendAnalyzer("trend-1", llm=llm)
        signals = analyzer.analyze(entries)
        assert len(signals) == 1


# ---------------------------------------------------------------------------
# CorroborationFinder tests
# ---------------------------------------------------------------------------


class TestCorroborationFinder:
    def test_too_few_entries(self):
        llm = MockLLMBackend()
        finder = CorroborationFinder("corr-1", llm=llm)
        assert finder.analyze(_make_entries(2)) == []

    def test_single_channel_rejected(self):
        llm = MockLLMBackend()
        finder = CorroborationFinder("corr-1", llm=llm)
        assert finder.analyze(_make_entries(5, multi_channel=False)) == []

    def test_basic_corroboration(self):
        llm = MockLLMBackend(
            {
                "corroborations": [
                    {
                        "claim": "Earthquake struck southern province",
                        "claim_fa": "زلزله در استان جنوبی",
                        "supporting_channels": ["FactNameh", "Iranwire"],
                        "contradicting_channels": [],
                        "corroboration_score": 0.85,
                        "notes": "Both channels report the same event",
                    }
                ]
            }
        )
        entries = _make_entries(5, multi_channel=True)
        finder = CorroborationFinder("corr-1", llm=llm)
        matches = finder.analyze(entries)
        assert len(matches) == 1
        assert matches[0].claim == "Earthquake struck southern province"
        assert matches[0].corroboration_score == 0.85
        assert matches[0].analysis_type == AnalysisType.CORROBORATION

    def test_malformed_corroboration_skipped(self):
        llm = MockLLMBackend(
            {
                "corroborations": [
                    {
                        "claim": "good",
                        "supporting_channels": [],
                        "contradicting_channels": [],
                        "corroboration_score": 0.5,
                        "notes": "ok",
                    },
                    {"corroboration_score": "NOT_A_NUMBER"},
                ]
            }
        )
        entries = _make_entries(5, multi_channel=True)
        finder = CorroborationFinder("corr-1", llm=llm)
        matches = finder.analyze(entries)
        assert len(matches) == 1


# ---------------------------------------------------------------------------
# AnomalyDetector tests
# ---------------------------------------------------------------------------


class TestAnomalyDetector:
    def test_empty_entries(self):
        llm = MockLLMBackend({"anomalies": []})
        detector = AnomalyDetector("anom-1", llm=llm)
        assert detector.analyze([]) == []

    def test_semantic_anomaly_detection(self):
        llm = MockLLMBackend(
            {
                "anomalies": [
                    {
                        "anomaly_type": "narrative_break",
                        "description": "Sudden shift in narrative",
                        "affected_channels": ["FactNameh"],
                        "severity": "medium",
                        "recommendation": "Investigate further",
                    }
                ]
            }
        )
        entries = _make_entries(3)
        detector = AnomalyDetector("anom-1", llm=llm)
        flags = detector.analyze(entries)
        assert len(flags) == 1
        assert flags[0].anomaly_type == AnomalyType.NARRATIVE_BREAK
        assert flags[0].severity == Severity.MEDIUM
        assert flags[0].analysis_type == AnalysisType.ANOMALY

    def test_volume_spike_detection(self):
        """Volume spike is statistical (no LLM) — detected when rate > 3x baseline."""
        llm = MockLLMBackend({"anomalies": []})
        entries = _make_entries(10)
        # All entries are channel 1098179827, spanning ~90 minutes
        # 10 posts in 1.5 hours = ~6.7/hr. Baseline of 1/hr should trigger spike.
        detector = AnomalyDetector(
            "anom-1",
            llm=llm,
            baseline_hourly_rate={1098179827: 1.0},
        )
        flags = detector.analyze(entries)
        volume_flags = [f for f in flags if f.anomaly_type == AnomalyType.VOLUME_SPIKE]
        assert len(volume_flags) == 1
        assert volume_flags[0].severity in (Severity.MEDIUM, Severity.HIGH)
        assert volume_flags[0].model_used == "statistical"

    def test_volume_spike_high_severity(self):
        """Rate > 5x baseline should be HIGH severity."""
        llm = MockLLMBackend({"anomalies": []})
        entries = _make_entries(20)
        detector = AnomalyDetector(
            "anom-1",
            llm=llm,
            baseline_hourly_rate={1098179827: 1.0},
        )
        flags = detector.analyze(entries)
        volume_flags = [f for f in flags if f.anomaly_type == AnomalyType.VOLUME_SPIKE]
        assert len(volume_flags) >= 1
        assert volume_flags[0].severity == Severity.HIGH

    def test_no_spike_when_no_baseline(self):
        llm = MockLLMBackend({"anomalies": []})
        entries = _make_entries(10)
        detector = AnomalyDetector("anom-1", llm=llm, baseline_hourly_rate={})
        flags = detector.analyze(entries)
        volume_flags = [f for f in flags if f.anomaly_type == AnomalyType.VOLUME_SPIKE]
        assert len(volume_flags) == 0

    def test_malformed_anomaly_skipped(self):
        llm = MockLLMBackend(
            {
                "anomalies": [
                    {
                        "anomaly_type": "linguistic",
                        "description": "ok",
                        "affected_channels": [],
                        "severity": "low",
                        "recommendation": "none",
                    },
                    {"anomaly_type": "INVALID_TYPE"},
                ]
            }
        )
        entries = _make_entries(3)
        detector = AnomalyDetector("anom-1", llm=llm)
        flags = detector.analyze(entries)
        semantic = [f for f in flags if f.model_used != "statistical"]
        assert len(semantic) == 1


# ---------------------------------------------------------------------------
# DataExtractor tests
# ---------------------------------------------------------------------------


class TestDataExtractor:
    def test_basic_extraction(self):
        llm = MockLLMBackend(
            {
                "data": [
                    {
                        "datum_type": "statistic",
                        "value": "1200",
                        "value_normalized": "1200",
                        "unit": "people",
                        "entity": "displaced population",
                        "source_post_index": 1,
                        "context_snippet": "1200 people displaced",
                        "confidence": 0.9,
                    }
                ]
            }
        )
        entries = _make_entries(3)
        extractor = DataExtractor("data-1", llm=llm)
        result = extractor.analyze(entries)
        assert result.analysis_type == AnalysisType.DATA_EXTRACT
        assert len(result.data) == 1
        assert result.data[0].value == "1200"
        assert result.data[0].entity == "displaced population"

    def test_low_confidence_filtered(self):
        llm = MockLLMBackend(
            {
                "data": [
                    {
                        "datum_type": "statistic",
                        "value": "100",
                        "source_post_index": 1,
                        "context_snippet": "x",
                        "confidence": 0.3,
                    },
                ]
            }
        )
        entries = _make_entries(2)
        extractor = DataExtractor("data-1", llm=llm)
        result = extractor.analyze(entries, confidence_floor=0.5)
        assert len(result.data) == 0

    def test_invalid_post_index_uses_fallback(self):
        llm = MockLLMBackend(
            {
                "data": [
                    {
                        "datum_type": "date_event",
                        "value": "2025-01-15",
                        "source_post_index": 999,
                        "context_snippet": "test",
                        "confidence": 0.8,
                    },
                ]
            }
        )
        entries = _make_entries(2)
        extractor = DataExtractor("data-1", llm=llm)
        result = extractor.analyze(entries)
        assert len(result.data) == 1
        assert result.data[0].source_global_id == "unknown"

    def test_malformed_datum_skipped(self):
        llm = MockLLMBackend(
            {
                "data": [
                    {
                        "datum_type": "statistic",
                        "value": "ok",
                        "source_post_index": 1,
                        "context_snippet": "ok",
                        "confidence": 0.9,
                    },
                    {"datum_type": "INVALID_TYPE", "confidence": 0.9},
                ]
            }
        )
        entries = _make_entries(2)
        extractor = DataExtractor("data-1", llm=llm)
        result = extractor.analyze(entries)
        assert len(result.data) == 1

    def test_multiple_data_types(self):
        llm = MockLLMBackend(
            {
                "data": [
                    {
                        "datum_type": "person",
                        "value": "Ali Khamenei",
                        "entity": "Supreme Leader",
                        "source_post_index": 1,
                        "context_snippet": "test",
                        "confidence": 0.95,
                    },
                    {
                        "datum_type": "location",
                        "value": "Tehran",
                        "entity": "Capital",
                        "source_post_index": 2,
                        "context_snippet": "test",
                        "confidence": 0.9,
                    },
                    {
                        "datum_type": "price",
                        "value": "50000 IRR",
                        "unit": "IRR",
                        "entity": "bread price",
                        "source_post_index": 1,
                        "context_snippet": "test",
                        "confidence": 0.8,
                    },
                ]
            }
        )
        entries = _make_entries(3)
        extractor = DataExtractor("data-1", llm=llm)
        result = extractor.analyze(entries)
        assert len(result.data) == 3
