"""Tests for audience interjection support in the council framework."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from heddle.contrib.council.protocol import (
    DelphiProtocol,
    RoundRobinProtocol,
    StructuredDebateProtocol,
    _format_interjections,
)
from heddle.contrib.council.runner import CouncilRunner
from heddle.contrib.council.schemas import AgentConfig, TranscriptEntry
from heddle.contrib.council.transcript import TranscriptStore
from heddle.mcp.council_bridge import CouncilBridge, _ActiveCouncil


def _entry(round_num, agent_name, content="test content", role="", entry_type="turn"):
    return TranscriptEntry(
        round_num=round_num,
        agent_name=agent_name,
        role=role,
        content=content,
        entry_type=entry_type,
    )


def _agent(name, sees=None):
    return AgentConfig(
        name=name,
        worker_type="w",
        sees_transcript_from=sees or ["all"],
    )


# ── TranscriptEntry.entry_type ───────────────────────────────────────


class TestTranscriptEntryType:
    def test_default_is_turn(self):
        entry = TranscriptEntry(round_num=1, agent_name="a", content="hi")
        assert entry.entry_type == "turn"

    def test_can_set_interjection(self):
        entry = TranscriptEntry(
            round_num=1, agent_name="a", content="hi", entry_type="interjection"
        )
        assert entry.entry_type == "interjection"

    def test_backward_compat_no_entry_type_kwarg(self):
        # Existing code that creates entries without entry_type still works.
        entry = TranscriptEntry(round_num=1, agent_name="a", role="analyst", content="x")
        assert entry.entry_type == "turn"


# ── TranscriptStore.inject_interjection ──────────────────────────────


class TestInjectInterjection:
    def test_creates_interjection_entry(self):
        store = TranscriptStore()
        store.start_round(1)
        store.inject_interjection("spectator", "Great point!")
        entries = store.rounds[0].entries
        assert len(entries) == 1
        assert entries[0].entry_type == "interjection"
        assert entries[0].agent_name == "spectator"
        assert entries[0].content == "Great point!"
        assert entries[0].role == "audience"

    def test_auto_starts_round_0_if_none(self):
        store = TranscriptStore()
        store.inject_interjection("spectator", "Early comment")
        assert len(store.rounds) == 1
        assert store.rounds[0].round_num == 0
        assert store.rounds[0].entries[0].entry_type == "interjection"

    def test_appends_to_current_round(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        store.inject_interjection("spectator", "Nice")
        entries = store.rounds[0].entries
        assert len(entries) == 2
        assert entries[0].entry_type == "turn"
        assert entries[1].entry_type == "interjection"

    def test_custom_role(self):
        store = TranscriptStore()
        store.start_round(1)
        store.inject_interjection("journalist", "Question?", role="press")
        assert store.rounds[0].entries[0].role == "press"


# ── TranscriptStore.get_visible_turns ────────────────────────────────


class TestGetVisibleTurns:
    def test_excludes_interjections(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1", content="turn content"))
        store.inject_interjection("spectator", "audience content")

        agent = _agent("viewer")
        turns = store.get_visible_turns(agent)
        assert len(turns) == 1
        assert turns[0].entry_type == "turn"
        assert turns[0].content == "turn content"

    def test_respects_visibility_rules(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1", content="from a1"))
        store.add_entry(_entry(1, "a2", content="from a2"))

        restricted = _agent("viewer", sees=["a1"])
        turns = store.get_visible_turns(restricted)
        assert len(turns) == 1
        assert turns[0].agent_name == "a1"

    def test_respects_up_to_round(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        store.start_round(2)
        store.add_entry(_entry(2, "a1"))

        agent = _agent("viewer")
        turns = store.get_visible_turns(agent, up_to_round=1)
        assert len(turns) == 1

    def test_returns_all_turns_when_no_interjections(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        store.add_entry(_entry(1, "a2"))

        agent = _agent("viewer")
        turns = store.get_visible_turns(agent)
        visible = store.get_visible_transcript(agent)
        assert len(turns) == len(visible)


# ── TranscriptStore.get_interjections ────────────────────────────────


class TestGetInterjections:
    def test_returns_only_interjections(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        store.inject_interjection("spectator", "Nice work")

        interjections = store.get_interjections()
        assert len(interjections) == 1
        assert interjections[0].entry_type == "interjection"

    def test_since_round_filtering(self):
        store = TranscriptStore()
        store.start_round(1)
        store.inject_interjection("s1", "round 1 comment")
        store.start_round(2)
        store.inject_interjection("s2", "round 2 comment")

        interjections = store.get_interjections(since_round=2)
        assert len(interjections) == 1
        assert interjections[0].content == "round 2 comment"

    def test_returns_all_when_no_since_round(self):
        store = TranscriptStore()
        store.start_round(1)
        store.inject_interjection("s1", "first")
        store.start_round(2)
        store.inject_interjection("s2", "second")

        interjections = store.get_interjections()
        assert len(interjections) == 2

    def test_always_public_regardless_of_visibility(self):
        """Interjections are visible to all agents, even those with restricted visibility."""
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        store.inject_interjection("spectator", "public comment")

        # get_interjections ignores agent visibility — always public.
        interjections = store.get_interjections()
        assert len(interjections) == 1

    def test_empty_when_no_interjections(self):
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        assert store.get_interjections() == []


# ── Protocol audience_reactions in context ───────────────────────────


class TestProtocolAudienceReactions:
    def test_round_robin_includes_audience_reactions(self):
        p = RoundRobinProtocol()
        agent = _agent("a1")
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1", content="position A"))
        store.inject_interjection("spectator", "interesting!")

        ctx = p.build_agent_context(agent, store, round_num=2, topic="test")
        assert "audience_reactions" in ctx
        assert "interesting!" in ctx["audience_reactions"]
        assert "[AUDIENCE REACTIONS]" in ctx["audience_reactions"]

    def test_round_robin_no_audience_when_no_interjections(self):
        p = RoundRobinProtocol()
        agent = _agent("a1")
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1", content="position A"))

        ctx = p.build_agent_context(agent, store, round_num=2, topic="test")
        assert "audience_reactions" not in ctx

    def test_structured_debate_includes_audience_reactions(self):
        p = StructuredDebateProtocol()
        agent = _agent("a1")
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        store.inject_interjection("viewer", "I disagree")

        ctx = p.build_agent_context(agent, store, round_num=2, topic="debate")
        assert "audience_reactions" in ctx
        assert "I disagree" in ctx["audience_reactions"]

    def test_delphi_includes_audience_reactions(self):
        p = DelphiProtocol()
        agent = _agent("a1")
        store = TranscriptStore()
        store.start_round(1)
        store.add_entry(_entry(1, "a1"))
        store.inject_interjection("observer", "What about X?")

        ctx = p.build_agent_context(agent, store, round_num=2, topic="delphi topic")
        assert "audience_reactions" in ctx
        assert "What about X?" in ctx["audience_reactions"]


# ── _format_interjections ────────────────────────────────────────────


class TestFormatInterjections:
    def test_empty_list_returns_empty_string(self):
        assert _format_interjections([]) == ""

    def test_single_interjection(self):
        entries = [_entry(1, "viewer", content="Nice point", entry_type="interjection")]
        result = _format_interjections(entries)
        assert "[AUDIENCE REACTIONS]" in result
        assert "viewer: Nice point" in result
        assert "You may address" in result

    def test_multiple_interjections(self):
        entries = [
            _entry(1, "viewer1", content="I agree", entry_type="interjection"),
            _entry(1, "viewer2", content="I disagree", entry_type="interjection"),
        ]
        result = _format_interjections(entries)
        assert "viewer1: I agree" in result
        assert "viewer2: I disagree" in result

    def test_non_audience_role_shown(self):
        entries = [
            _entry(
                1,
                "journalist",
                content="Question?",
                role="press",
                entry_type="interjection",
            )
        ]
        result = _format_interjections(entries)
        assert "journalist (press)" in result

    def test_audience_role_not_duplicated(self):
        """Default 'audience' role should not appear in parentheses."""
        entries = [
            _entry(
                1,
                "spectator",
                content="Hello",
                role="audience",
                entry_type="interjection",
            )
        ]
        result = _format_interjections(entries)
        assert "spectator: Hello" in result
        assert "(audience)" not in result


# ── CouncilRunner.inject ─────────────────────────────────────────────


class TestCouncilRunnerInject:
    def test_raises_when_no_council_active(self):
        runner = CouncilRunner(backends={})
        with pytest.raises(RuntimeError, match="No active council"):
            runner.inject("user", "Hello")

    def test_inject_when_active(self):
        runner = CouncilRunner(backends={})
        # Simulate an active transcript (as if run() is executing).
        runner._active_transcript = TranscriptStore()
        runner._active_transcript.start_round(1)

        runner.inject("user", "Great discussion!", role="audience")

        entries = runner._active_transcript.get_interjections()
        assert len(entries) == 1
        assert entries[0].agent_name == "user"
        assert entries[0].content == "Great discussion!"
        assert entries[0].entry_type == "interjection"

    async def test_inject_during_live_run(self):
        """Inject during an actual (mocked) run and verify it appears in transcript."""
        call_count = 0

        async def slow_complete(**kwargs):
            nonlocal call_count
            call_count += 1
            # Slow down the first call to give inject_after_start time.
            if call_count == 1:
                await asyncio.sleep(0.05)
            return {
                "content": "Agent response",
                "model": "mock",
                "prompt_tokens": 10,
                "completion_tokens": 5,
            }

        backend = AsyncMock()
        backend.complete.side_effect = slow_complete
        runner = CouncilRunner(backends={"standard": backend})

        from heddle.contrib.council.config import CouncilConfig
        from heddle.contrib.council.schemas import FacilitatorConfig

        config = CouncilConfig(
            name="test",
            protocol="round_robin",
            max_rounds=2,
            agents=[
                AgentConfig(name="a1", worker_type="w1"),
                AgentConfig(name="a2", worker_type="w2"),
            ],
            facilitator=FacilitatorConfig(),
        )

        injected = False

        async def inject_after_start():
            nonlocal injected
            # Wait until the runner has an active transcript.
            for _ in range(100):
                if runner._active_transcript is not None:
                    runner.inject("audience_member", "What about cost?")
                    injected = True
                    return
                await asyncio.sleep(0.005)

        task = asyncio.create_task(inject_after_start())
        result = await runner.run("Test topic", config=config)
        await task

        assert injected
        # The interjection should appear somewhere in the transcript.
        all_entries = [e for r in result.transcript for e in r.entries]
        interjections = [e for e in all_entries if e.entry_type == "interjection"]
        assert len(interjections) == 1
        assert interjections[0].agent_name == "audience_member"


# ── CouncilBridge._intervene with as_spectator ──────────────────────


class TestCouncilBridgeIntervene:
    async def test_as_spectator_creates_interjection(self):
        runner = CouncilRunner(backends={})
        bridge = CouncilBridge(runner=runner)

        # Set up an active council directly.
        active = _ActiveCouncil(
            council_id="test-1",
            topic="Test",
            config_name="test",
        )
        active.transcript.start_round(1)
        bridge._active["test-1"] = active

        result = await bridge.dispatch(
            "intervene",
            {
                "council_id": "test-1",
                "message": "Audience question!",
                "speaker": "viewer",
                "as_spectator": True,
            },
        )

        assert result["status"] == "interjection_added"
        assert result["speaker"] == "viewer"

        interjections = active.transcript.get_interjections()
        assert len(interjections) == 1
        assert interjections[0].entry_type == "interjection"
        assert interjections[0].content == "Audience question!"

    async def test_without_spectator_creates_turn(self):
        runner = CouncilRunner(backends={})
        bridge = CouncilBridge(runner=runner)

        active = _ActiveCouncil(
            council_id="test-2",
            topic="Test",
            config_name="test",
        )
        active.transcript.start_round(1)
        bridge._active["test-2"] = active

        result = await bridge.dispatch(
            "intervene",
            {
                "council_id": "test-2",
                "message": "Direct intervention",
                "speaker": "moderator",
            },
        )

        assert result["status"] == "intervention_added"

        entries = active.transcript.rounds[0].entries
        assert len(entries) == 1
        assert entries[0].entry_type == "turn"
        assert entries[0].agent_name == "moderator"
        assert entries[0].role == "Human intervention"

    async def test_spectator_false_explicit(self):
        runner = CouncilRunner(backends={})
        bridge = CouncilBridge(runner=runner)

        active = _ActiveCouncil(
            council_id="test-3",
            topic="Test",
            config_name="test",
        )
        active.transcript.start_round(1)
        bridge._active["test-3"] = active

        result = await bridge.dispatch(
            "intervene",
            {
                "council_id": "test-3",
                "message": "Legacy",
                "as_spectator": False,
            },
        )

        assert result["status"] == "intervention_added"
        entries = active.transcript.rounds[0].entries
        assert entries[0].entry_type == "turn"

    async def test_speaker_parameter_sets_agent_name(self):
        runner = CouncilRunner(backends={})
        bridge = CouncilBridge(runner=runner)

        active = _ActiveCouncil(
            council_id="test-4",
            topic="Test",
            config_name="test",
        )
        active.transcript.start_round(1)
        bridge._active["test-4"] = active

        await bridge.dispatch(
            "intervene",
            {
                "council_id": "test-4",
                "message": "Hi",
                "speaker": "custom_name",
                "as_spectator": True,
            },
        )

        entry = active.transcript.rounds[0].entries[0]
        assert entry.agent_name == "custom_name"

    async def test_intervene_on_completed_council(self):
        from heddle.contrib.council.schemas import CouncilResult

        runner = CouncilRunner(backends={})
        bridge = CouncilBridge(runner=runner)

        active = _ActiveCouncil(
            council_id="test-5",
            topic="Test",
            config_name="test",
        )
        active.result = CouncilResult(
            topic="Test",
            rounds_completed=1,
            converged=False,
            synthesis="Done",
        )
        bridge._active["test-5"] = active

        result = await bridge.dispatch(
            "intervene",
            {
                "council_id": "test-5",
                "message": "Too late",
                "as_spectator": True,
            },
        )
        assert "error" in result
        assert "already completed" in result["error"]
