"""Typed outputs for each analysis actor.

All analysis results inherit from AnalysisBlock which carries common provenance
metadata (which window produced it, which actor, confidence, etc.).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AnalysisType(StrEnum):
    """Type of analysis block."""

    TREND = "trend"
    CORROBORATION = "corroboration"
    ANOMALY = "anomaly"
    DATA_EXTRACT = "data_extract"
    SUMMARY = "summary"


class Severity(StrEnum):
    """Severity level for analysis signals."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(tz=UTC)


class AnalysisBlock(BaseModel):
    """Base for all analysis actor outputs."""

    analysis_type: AnalysisType
    window_id: str
    window_start: datetime
    window_end: datetime
    produced_at: datetime = Field(default_factory=_utcnow)
    actor_id: str  # NATS actor identifier
    source_entry_ids: list[str]  # MuxEntry global_ids that fed this block
    confidence: float = Field(ge=0.0, le=1.0)
    model_used: str  # LLM model name
    raw_llm_response: str | None = None  # for audit / debugging


# ---------------------------------------------------------------------------
# TrendSignal
# ---------------------------------------------------------------------------


class TrendSignal(AnalysisBlock):
    """A recurring topic or narrative pattern detected across channels.

    Detected within a time window across one or more channels.
    """

    analysis_type: AnalysisType = AnalysisType.TREND
    topic_label: str  # short English label
    topic_label_fa: str | None = None  # Persian label if detected
    description: str  # 2-3 sentence summary
    channels_present: list[str]  # channel names mentioning this trend
    post_count: int  # number of posts contributing
    exemplar_post_ids: list[str]  # up to 3 best-representative global_ids
    keywords: list[str]  # key terms (bilingual)
    sentiment: str | None = None  # positive / negative / neutral / mixed
    severity: Severity = Severity.LOW


# ---------------------------------------------------------------------------
# CorroborationMatch
# ---------------------------------------------------------------------------


class CorroborationMatch(AnalysisBlock):
    """A factual claim reported by multiple independent sources.

    Weighted by channel trust_weight.
    """

    analysis_type: AnalysisType = AnalysisType.CORROBORATION
    claim: str  # normalized claim text
    claim_fa: str | None = None
    supporting_channels: list[str]
    contradicting_channels: list[str] = Field(default_factory=list)
    corroboration_score: float = Field(ge=0.0, le=1.0)
    # weighted sum of trust_weights of supporting channels / total possible
    notes: str = ""


# ---------------------------------------------------------------------------
# AnomalyFlag
# ---------------------------------------------------------------------------


class AnomalyType(StrEnum):
    """Type of anomaly detected in the stream."""

    VOLUME_SPIKE = "volume_spike"  # unusual posting frequency
    NARRATIVE_BREAK = "narrative_break"  # topic suddenly absent or inverted
    CROSS_CHANNEL_CONFLICT = "cross_channel_conflict"  # contradictory claims
    SINGLE_SOURCE = "single_source"  # claim from only one channel, esp. state
    TIMING_ANOMALY = "timing_anomaly"  # unusual time-of-day or gap in posting
    LINGUISTIC = "linguistic"  # language / tone shift


class AnomalyFlag(AnalysisBlock):
    """Something statistically or semantically unusual in the stream."""

    analysis_type: AnalysisType = AnalysisType.ANOMALY
    anomaly_type: AnomalyType
    description: str
    affected_channels: list[str]
    reference_value: float | None = None  # baseline metric
    observed_value: float | None = None  # observed metric
    severity: Severity = Severity.MEDIUM
    recommendation: str = ""  # suggested follow-up action


# ---------------------------------------------------------------------------
# ExtractedDatum
# ---------------------------------------------------------------------------


class ExtractedDataType(StrEnum):
    """Type of extracted data point."""

    STATISTIC = "statistic"  # numerical claim with unit
    DATE_EVENT = "date_event"  # event + date
    PERSON = "person"  # named individual + role
    ORGANIZATION = "organization"
    LOCATION = "location"
    PRICE = "price"  # economic figure
    CASUALTY = "casualty"  # deaths / injuries / arrests
    LEGAL = "legal"  # law, sentence, verdict
    QUOTE = "quote"  # attributed direct quote


class ExtractedDatum(BaseModel):
    """A single structured data point extracted from a post."""

    datum_type: ExtractedDataType
    value: str  # raw extracted string
    value_normalized: Any | None = None  # parsed value (float, date, etc.)
    unit: str | None = None
    entity: str | None = None  # who/what this datum is about
    source_global_id: str  # which post it came from
    source_channel: str
    timestamp_unix: int
    context_snippet: str  # <=150 chars surrounding context
    confidence: float = Field(ge=0.0, le=1.0, default=0.7)


class ExtractedData(AnalysisBlock):
    """Collection of ExtractedDatum objects from a window."""

    analysis_type: AnalysisType = AnalysisType.DATA_EXTRACT
    data: list[ExtractedDatum] = Field(default_factory=list)

    def by_type(self) -> dict[ExtractedDataType, list[ExtractedDatum]]:
        """Group extracted data by datum type."""
        result: dict[ExtractedDataType, list[ExtractedDatum]] = {}
        for d in self.data:
            result.setdefault(d.datum_type, []).append(d)
        return result
