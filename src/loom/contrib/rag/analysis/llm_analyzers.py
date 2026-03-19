"""LLM-backed analysis actors for the muxed stream.

Four actors:

  TrendAnalyzer         -- recurring topics across a window
  CorroborationFinder   -- cross-channel claim matching + trust weighting
  AnomalyDetector       -- statistical + semantic anomalies
  DataExtractor         -- structured entity/fact extraction

Each actor accepts a list[MuxEntry] (one time window) and returns the
appropriate AnalysisBlock subclass.

LLM backend abstraction:
  - Prefers Ollama (local) for privacy and cost
  - Falls back to Anthropic API if configured
  - All prompts are bilingual (English instructions + Persian data)
  - Responses are requested as JSON; parsed via Pydantic

Prompt philosophy:
  - Instructions in English (better LLM instruction-following)
  - Example outputs shown in English
  - Actual data passed as-is (Persian text preserved)
  - Explicit RTL + multilingual context note in system prompt
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..ingestion.telegram_ingestor import DEFAULT_PROFILES
from ..schemas.analysis import (
    AnalysisType,
    AnomalyFlag,
    AnomalyType,
    CorroborationMatch,
    ExtractedData,
    ExtractedDataType,
    ExtractedDatum,
    Severity,
    TrendSignal,
)

if TYPE_CHECKING:
    from ..schemas.mux import MuxEntry

logger = logging.getLogger(__name__)

# Maximum number of retries for LLM calls
_MAX_RETRIES = 2
_RETRY_DELAY_S = 2.0


# ---------------------------------------------------------------------------
# LLM backend shim
# ---------------------------------------------------------------------------


class LLMBackend:
    """Minimal abstraction over Ollama and Anthropic backends.

    In production this becomes a Loom actor calling rag.llm.request.
    """

    def __init__(
        self,
        model: str = "ollama:llama3.2",
        temperature: float = 0.1,
        max_tokens: int = 2048,
        ollama_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._ollama_url = ollama_url.rstrip("/")

        # Detect backend from model prefix
        if model.startswith("ollama:"):
            self._backend = "ollama"
            self._model_name = model[len("ollama:") :]
        elif model.startswith("anthropic:"):
            self._backend = "anthropic"
            self._model_name = model[len("anthropic:") :]
        else:
            self._backend = "ollama"
            self._model_name = model

        # Cache the Anthropic client so it is not re-created on every call
        self._anthropic_client: Any = None

    def complete(self, system: str, user: str) -> str:
        """Synchronous completion with basic retry logic.

        Returns raw response string.
        In actor mode this becomes an async NATS request.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                if self._backend == "ollama":
                    return self._ollama_complete(system, user)
                if self._backend == "anthropic":
                    return self._anthropic_complete(system, user)
                raise ValueError(f"Unknown backend: {self._backend}")
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "LLM call attempt %d failed (%s), retrying in %.1fs...",
                        attempt + 1,
                        exc,
                        _RETRY_DELAY_S,
                    )
                    time.sleep(_RETRY_DELAY_S)
        logger.error("LLM call failed after %d attempts: %s", _MAX_RETRIES, last_exc)
        return "{}"

    def complete_json(self, system: str, user: str) -> dict:
        """Complete and parse JSON response."""
        raw = self.complete(system, user)
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0]
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("LLM returned non-JSON: %s\nRaw: %s", e, raw[:500])
            return {}

    def _ollama_complete(self, system: str, user: str) -> str:
        import requests

        response = requests.post(
            f"{self._ollama_url}/api/chat",
            json={
                "model": self._model_name,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            },
            timeout=120,
        )
        return response.json()["message"]["content"]

    def _anthropic_complete(self, system: str, user: str) -> str:
        import anthropic

        if self._anthropic_client is None:
            self._anthropic_client = anthropic.Anthropic()
        msg = self._anthropic_client.messages.create(
            model=self._model_name,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text


# ---------------------------------------------------------------------------
# Base actor class
# ---------------------------------------------------------------------------

_SYSTEM_PREFIX = (
    "You are an expert intelligence analyst processing Persian-language Telegram posts.\n"
    "Text may be in Persian (Farsi), Arabic, or mixed Persian/English.\n"
    "Persian is RTL (right-to-left). Preserve Persian text exactly as-is in your output.\n"
    "Always respond with valid JSON only -- no prose, no markdown fences.\n"
)


class BaseAnalysisActor:
    """Base class for LLM-backed analysis actors."""

    def __init__(
        self,
        actor_id: str,
        llm: LLMBackend | None = None,
        model: str = "ollama:llama3.2",
    ) -> None:
        self.actor_id = actor_id
        self.llm = llm or LLMBackend(model=model)

    def _window_meta(self, entries: list[MuxEntry]) -> dict:
        timestamps = [e.timestamp for e in entries]
        return {
            "window_start": min(timestamps),
            "window_end": max(timestamps),
            "window_id": entries[0].window_id or "unknown",
        }

    def _format_posts(self, entries: list[MuxEntry], max_posts: int = 40) -> str:
        """Format entries as a numbered list for the LLM prompt."""
        lines: list[str] = []
        for i, e in enumerate(entries[:max_posts]):
            profile = DEFAULT_PROFILES.get(e.channel_id)
            bias = profile.bias.value if profile else "unknown"
            lines.append(
                f"[{i + 1}] channel={e.channel_name!r} bias={bias} "
                f"ts={e.timestamp.strftime('%Y-%m-%d %H:%M')}\n"
                f"TEXT: {e.text[:400]}"
            )
        return "\n\n".join(lines)

    def _now(self) -> datetime:
        return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# TrendAnalyzer
# ---------------------------------------------------------------------------


class TrendAnalyzer(BaseAnalysisActor):
    """Detect recurring topics and narrative trends across a time window.

    Operates across all channels simultaneously.
    """

    SYSTEM = (
        _SYSTEM_PREFIX
        + """
Your task: identify the top narrative TRENDS in a batch of Telegram posts
from multiple Persian news channels.
A trend is a topic that appears in >=2 posts, even if framed differently.
Return JSON with this exact structure:
{
  "trends": [
    {
      "topic_label": "short English label",
      "topic_label_fa": "Persian label (optional)",
      "description": "2-3 sentence description in English",
      "channels_present": ["channel name 1", ...],
      "post_indices": [1, 3, 7],
      "keywords": ["keyword1", "keyword2", ...],
      "sentiment": "positive|negative|neutral|mixed",
      "severity": "low|medium|high|critical"
    }
  ]
}
Return 3-8 trends. Focus on political, economic, social, and security topics.
"""
    )

    def analyze(self, entries: list[MuxEntry], confidence: float = 0.7) -> list[TrendSignal]:
        """Analyze entries and return detected trend signals."""
        if not entries:
            return []

        meta = self._window_meta(entries)
        posts_text = self._format_posts(entries)

        user_prompt = f"""Analyze these {len(entries)} posts from window {meta["window_id"]}:

{posts_text}

Identify the top trends."""

        result = self.llm.complete_json(self.SYSTEM, user_prompt)
        trends_raw = result.get("trends", [])

        signals: list[TrendSignal] = []
        for t in trends_raw:
            post_indices = t.get("post_indices", [])
            exemplar_ids = [
                entries[i - 1].post.global_id for i in post_indices if 1 <= i <= len(entries)
            ][:3]

            try:
                signals.append(
                    TrendSignal(
                        analysis_type=AnalysisType.TREND,
                        window_id=meta["window_id"],
                        window_start=meta["window_start"],
                        window_end=meta["window_end"],
                        produced_at=self._now(),
                        actor_id=self.actor_id,
                        source_entry_ids=[e.post.global_id for e in entries],
                        confidence=confidence,
                        model_used=self.llm.model,
                        topic_label=t.get("topic_label", "unknown"),
                        topic_label_fa=t.get("topic_label_fa"),
                        description=t.get("description", ""),
                        channels_present=t.get("channels_present", []),
                        post_count=len(post_indices),
                        exemplar_post_ids=exemplar_ids,
                        keywords=t.get("keywords", []),
                        sentiment=t.get("sentiment"),
                        severity=Severity(t.get("severity", "low")),
                    )
                )
            except Exception as e:
                logger.warning("Failed to parse trend: %s -- %s", t, e)

        return signals


# ---------------------------------------------------------------------------
# CorroborationFinder
# ---------------------------------------------------------------------------


class CorroborationFinder(BaseAnalysisActor):
    """Find claims reported by multiple channels and weight by trust_weight.

    Flags contradictions between state and independent media.
    """

    SYSTEM = (
        _SYSTEM_PREFIX
        + """
Your task: find CORROBORATION -- the same factual claim or event reported by multiple channels.
Also flag CONTRADICTIONS where state and independent channels report opposite facts.

Trust weights (higher = more reliable):
  fact_check: 0.9, independent: 0.85, educational: 0.6, state_media: 0.3, unknown: 0.5

Return JSON:
{
  "corroborations": [
    {
      "claim": "concise claim in English",
      "claim_fa": "claim in Persian (optional)",
      "supporting_channels": ["channel1", ...],
      "contradicting_channels": ["channel1", ...],
      "corroboration_score": 0.0-1.0,
      "notes": "brief analysis note"
    }
  ]
}
"""
    )

    def analyze(
        self, entries: list[MuxEntry], confidence: float = 0.75
    ) -> list[CorroborationMatch]:
        """Analyze entries and return corroboration matches."""
        if len(entries) < 3:  # need enough posts to find overlap
            return []

        # Only include multi-channel windows
        channel_set = {e.channel_id for e in entries}
        if len(channel_set) < 2:
            return []

        meta = self._window_meta(entries)
        posts_text = self._format_posts(entries)

        user_prompt = f"""Find corroborations across {len(channel_set)} channels in this window:

{posts_text}"""

        result = self.llm.complete_json(self.SYSTEM, user_prompt)
        raw_list = result.get("corroborations", [])

        matches: list[CorroborationMatch] = []
        for c in raw_list:
            try:
                matches.append(
                    CorroborationMatch(
                        analysis_type=AnalysisType.CORROBORATION,
                        window_id=meta["window_id"],
                        window_start=meta["window_start"],
                        window_end=meta["window_end"],
                        produced_at=self._now(),
                        actor_id=self.actor_id,
                        source_entry_ids=[e.post.global_id for e in entries],
                        confidence=confidence,
                        model_used=self.llm.model,
                        claim=c.get("claim", ""),
                        claim_fa=c.get("claim_fa"),
                        supporting_channels=c.get("supporting_channels", []),
                        contradicting_channels=c.get("contradicting_channels", []),
                        corroboration_score=float(c.get("corroboration_score", 0.5)),
                        notes=c.get("notes", ""),
                    )
                )
            except Exception as e:
                logger.warning("Failed to parse corroboration: %s -- %s", c, e)

        return matches


# ---------------------------------------------------------------------------
# AnomalyDetector
# ---------------------------------------------------------------------------


class AnomalyDetector(BaseAnalysisActor):
    """Flag statistical and semantic anomalies in the stream.

    Statistical: volume spikes (computed locally, no LLM needed).
    Semantic: narrative breaks, cross-channel conflicts (LLM).
    """

    SYSTEM = (
        _SYSTEM_PREFIX
        + """
Your task: identify ANOMALIES in a batch of Persian Telegram posts.
Anomaly types: volume_spike, narrative_break, cross_channel_conflict,
single_source, timing_anomaly, linguistic

Return JSON:
{
  "anomalies": [
    {
      "anomaly_type": "one of the types above",
      "description": "clear English description of what's anomalous",
      "affected_channels": ["channel1", ...],
      "severity": "low|medium|high|critical",
      "recommendation": "suggested follow-up action"
    }
  ]
}
Focus on: state media claiming things independent media ignores,
sudden topic silence, unusual posting bursts.
"""
    )

    def __init__(
        self,
        *args: Any,
        baseline_hourly_rate: dict[int, float] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        # channel_id -> expected posts/hour (computed from full corpus in test pipeline)
        self.baseline_hourly_rate = baseline_hourly_rate or {}

    def analyze(self, entries: list[MuxEntry], confidence: float = 0.65) -> list[AnomalyFlag]:
        """Analyze entries and return detected anomaly flags."""
        if not entries:
            return []

        meta = self._window_meta(entries)
        anomalies: list[AnomalyFlag] = []

        # 1. Statistical volume check (no LLM)
        anomalies.extend(self._check_volume_spike(entries, meta))

        # 2. Semantic anomalies (LLM)
        posts_text = self._format_posts(entries)
        user_prompt = f"""Find semantic anomalies in this window of {len(entries)} posts:

{posts_text}"""

        result = self.llm.complete_json(self.SYSTEM, user_prompt)
        for a in result.get("anomalies", []):
            try:
                anomalies.append(
                    AnomalyFlag(
                        analysis_type=AnalysisType.ANOMALY,
                        window_id=meta["window_id"],
                        window_start=meta["window_start"],
                        window_end=meta["window_end"],
                        produced_at=self._now(),
                        actor_id=self.actor_id,
                        source_entry_ids=[e.post.global_id for e in entries],
                        confidence=confidence,
                        model_used=self.llm.model,
                        anomaly_type=AnomalyType(a.get("anomaly_type", "linguistic")),
                        description=a.get("description", ""),
                        affected_channels=a.get("affected_channels", []),
                        severity=Severity(a.get("severity", "medium")),
                        recommendation=a.get("recommendation", ""),
                    )
                )
            except Exception as e:
                logger.warning("Failed to parse anomaly: %s -- %s", a, e)

        return anomalies

    def _check_volume_spike(self, entries: list[MuxEntry], meta: dict) -> list[AnomalyFlag]:
        """Flag channels posting >3x their baseline rate."""
        flags: list[AnomalyFlag] = []
        window_hours = ((meta["window_end"] - meta["window_start"]).total_seconds() / 3600) or 1.0

        # Group by channel
        by_channel: dict[int, list[MuxEntry]] = {}
        for e in entries:
            by_channel.setdefault(e.channel_id, []).append(e)

        for cid, ch_entries in by_channel.items():
            observed_rate = len(ch_entries) / window_hours
            baseline = self.baseline_hourly_rate.get(cid, 0)
            if baseline > 0 and observed_rate > 3 * baseline:
                flags.append(
                    AnomalyFlag(
                        analysis_type=AnalysisType.ANOMALY,
                        window_id=meta["window_id"],
                        window_start=meta["window_start"],
                        window_end=meta["window_end"],
                        produced_at=self._now(),
                        actor_id=self.actor_id,
                        source_entry_ids=[e.post.global_id for e in ch_entries],
                        confidence=0.9,
                        model_used="statistical",
                        anomaly_type=AnomalyType.VOLUME_SPIKE,
                        description=(
                            f"Channel '{ch_entries[0].channel_name}' posting at "
                            f"{observed_rate:.1f} posts/hr vs baseline {baseline:.1f} posts/hr"
                        ),
                        affected_channels=[ch_entries[0].channel_name],
                        reference_value=baseline,
                        observed_value=observed_rate,
                        severity=Severity.HIGH if observed_rate > 5 * baseline else Severity.MEDIUM,
                        recommendation="Investigate for coordinated messaging or breaking event",
                    )
                )

        return flags


# ---------------------------------------------------------------------------
# DataExtractor
# ---------------------------------------------------------------------------


class DataExtractor(BaseAnalysisActor):
    """Extract structured data points from Persian posts.

    Covers statistics, named entities, dates, casualties, quotes, prices.
    """

    SYSTEM = (
        _SYSTEM_PREFIX
        + """
Your task: extract STRUCTURED DATA from Persian Telegram posts.
For each factual data point found, extract it precisely.

Return JSON:
{
  "data": [
    {
      "datum_type": "statistic|date_event|person|organization|location|price|casualty|legal|quote",
      "value": "raw extracted string",
      "value_normalized": "normalized value (number, ISO date, etc.) or null",
      "unit": "unit if applicable or null",
      "entity": "who/what this is about",
      "source_post_index": 1,
      "context_snippet": "up to 100 chars of surrounding context",
      "confidence": 0.0-1.0
    }
  ]
}
Be precise. Include Persian numbers and dates. Translate statistic labels to English.
For casualties: extract deaths, injuries, arrests separately.
"""
    )

    def analyze(self, entries: list[MuxEntry], confidence_floor: float = 0.6) -> ExtractedData:
        """Analyze entries and return extracted structured data."""
        meta = self._window_meta(entries)
        posts_text = self._format_posts(entries, max_posts=30)

        user_prompt = f"""Extract all structured data from these {len(entries)} posts:

{posts_text}"""

        result = self.llm.complete_json(self.SYSTEM, user_prompt)

        data_items: list[ExtractedDatum] = []
        for d in result.get("data", []):
            post_idx = d.get("source_post_index", 1)
            if 1 <= post_idx <= len(entries):
                source_entry = entries[post_idx - 1]
                source_gid = source_entry.post.global_id
                source_ch = source_entry.channel_name
                ts_unix = source_entry.post.timestamp_unix
            else:
                source_gid = "unknown"
                source_ch = "unknown"
                ts_unix = int(meta["window_start"].timestamp())

            try:
                conf = float(d.get("confidence", 0.7))
                if conf < confidence_floor:
                    continue
                data_items.append(
                    ExtractedDatum(
                        datum_type=ExtractedDataType(d.get("datum_type", "statistic")),
                        value=str(d.get("value", "")),
                        value_normalized=d.get("value_normalized"),
                        unit=d.get("unit"),
                        entity=d.get("entity"),
                        source_global_id=source_gid,
                        source_channel=source_ch,
                        timestamp_unix=ts_unix,
                        context_snippet=str(d.get("context_snippet", ""))[:150],
                        confidence=conf,
                    )
                )
            except Exception as e:
                logger.warning("Failed to parse datum: %s -- %s", d, e)

        return ExtractedData(
            analysis_type=AnalysisType.DATA_EXTRACT,
            window_id=meta["window_id"],
            window_start=meta["window_start"],
            window_end=meta["window_end"],
            produced_at=self._now(),
            actor_id=self.actor_id,
            source_entry_ids=[e.post.global_id for e in entries],
            confidence=0.75,
            model_used=self.llm.model,
            data=data_items,
        )
