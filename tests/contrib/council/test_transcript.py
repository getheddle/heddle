"""Tests for TranscriptStore."""

import pytest

from loom.contrib.council.schemas import AgentConfig, TranscriptEntry
from loom.contrib.council.transcript import TranscriptStore


def _entry(round_num, agent_name, content="test content", role=""):
    return TranscriptEntry(
        round_num=round_num,
        agent_name=agent_name,
        role=role,
        content=content,
    )


def _agent(name, sees=None):
    return AgentConfig(
        name=name,
        worker_type="w",
        sees_transcript_from=sees or ["all"],
    )


class TestTranscriptStore:
    def test_start_round_and_add_entry(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        store.add_entry(_entry(1, "a2"))
        assert store.total_entries == 2
        assert len(store.rounds) == 1

    def test_add_entry_without_round_raises(self):
        store = TranscriptStore()
        with pytest.raises(RuntimeError, match="No round started"):
            store.add_entry(_entry(1, "a1"))

    def test_multiple_rounds(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        store.start_round(2)
        store.add_entry(_entry(2, "a1"))
        store.add_entry(_entry(2, "a2"))
        assert store.total_entries == 3
        assert len(store.rounds) == 2


class TestVisibility:
    def test_see_all(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        store.add_entry(_entry(1, "a2"))

        agent = _agent("a1", sees=["all"])
        visible = store.get_visible_transcript(agent)
        assert len(visible) == 2

    def test_see_specific_agents(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        store.add_entry(_entry(1, "a2"))
        store.add_entry(_entry(1, "a3"))

        agent = _agent("viewer", sees=["a1", "a3"])
        visible = store.get_visible_transcript(agent)
        assert len(visible) == 2
        assert {e.agent_name for e in visible} == {"a1", "a3"}

    def test_up_to_round(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        store.start_round(2)
        store.add_entry(_entry(2, "a1"))
        store.start_round(3)
        store.add_entry(_entry(3, "a1"))

        agent = _agent("a1")
        visible = store.get_visible_transcript(agent, up_to_round=2)
        assert len(visible) == 2


class TestLatestPositions:
    def test_returns_most_recent(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1", content="position 1"))
        store.start_round(2)
        store.add_entry(_entry(2, "a1", content="revised position"))

        positions = store.get_latest_positions()
        assert positions["a1"] == "revised position"

    def test_multiple_agents(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1", content="A's view"))
        store.add_entry(_entry(1, "a2", content="B's view"))

        positions = store.get_latest_positions()
        assert len(positions) == 2


class TestConvergenceScore:
    def test_set_and_read(self):
        store = TranscriptStore()
        store.start_round(1)
        store.set_convergence_score(1, 0.75)
        assert store.rounds[0].convergence_score == 0.75


class TestFormatForPayload:
    def test_empty(self):
        assert TranscriptStore.format_for_payload([]) == ""

    def test_basic_format(self):
        entries = [_entry(1, "a1", content="hello", role="analyst")]
        text = TranscriptStore.format_for_payload(entries)
        assert "Round 1" in text
        assert "a1" in text
        assert "analyst" in text
        assert "hello" in text

    def test_truncation(self):
        entries = [
            _entry(1, "a1", content="x" * 1000),
            _entry(1, "a2", content="y" * 1000),
            _entry(1, "a3", content="z" * 1000),
        ]
        text = TranscriptStore.format_for_payload(entries, max_chars=500)
        assert len(text) <= 520  # Allow for truncation marker

    def test_single_long_entry_truncated(self):
        entries = [_entry(1, "a1", content="x" * 10000)]
        text = TranscriptStore.format_for_payload(entries, max_chars=100)
        assert text.endswith("... [truncated]")
