"""
Test checkpoint system (unit tests, no infrastructure).

Tests the CheckpointManager class from loom.orchestrator.checkpoint, which
handles orchestrator context compression via token-counted checkpointing
with pluggable storage backends.

All tests use InMemoryCheckpointStore — no external infrastructure needed.
tiktoken is used directly (it's a pure-Python encoder, no external service).
"""
import pytest
import tiktoken

from loom.core.messages import CheckpointState
from loom.orchestrator.checkpoint import CheckpointManager
from loom.orchestrator.store import InMemoryCheckpointStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(
    token_threshold: int = 50_000,
    recent_window_size: int = 5,
    ttl_seconds: int = 86400,
) -> CheckpointManager:
    """Create a CheckpointManager with an in-memory store."""
    return CheckpointManager(
        store=InMemoryCheckpointStore(),
        token_threshold=token_threshold,
        recent_window_size=recent_window_size,
        ttl_seconds=ttl_seconds,
    )


def _sample_completed_tasks(n: int = 3) -> list[dict]:
    """Generate a list of completed task dicts for testing."""
    return [
        {
            "task_id": f"task-{i}",
            "worker_type": "summarizer",
            "status": "completed",
            "summary": f"Summarized document {i}",
        }
        for i in range(n)
    ]


def _sample_pending_tasks(n: int = 2) -> list[dict]:
    """Generate a list of pending task dicts for testing."""
    return [
        {"task_id": f"pending-{i}", "worker_type": "classifier", "description": f"Classify item {i}"}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

class TestTokenCounting:
    """Verify tiktoken-based token estimation."""

    def test_estimate_tokens_returns_positive_int(self):
        """estimate_tokens returns a positive integer for non-empty text."""
        mgr = _make_manager()
        count = mgr.estimate_tokens("hello world")
        assert isinstance(count, int)
        assert count > 0

    def test_estimate_tokens_empty_string(self):
        """An empty string should produce zero tokens."""
        mgr = _make_manager()
        assert mgr.estimate_tokens("") == 0

    def test_estimate_tokens_scales_with_length(self):
        """Longer text should produce more tokens than shorter text."""
        mgr = _make_manager()
        short = mgr.estimate_tokens("hello")
        long = mgr.estimate_tokens("hello " * 100)
        assert long > short

    def test_estimate_tokens_deterministic(self):
        """The same input always produces the same token count."""
        mgr = _make_manager()
        text = "The quick brown fox jumps over the lazy dog."
        assert mgr.estimate_tokens(text) == mgr.estimate_tokens(text)


# ---------------------------------------------------------------------------
# Checkpoint trigger (should_checkpoint)
# ---------------------------------------------------------------------------

class TestCheckpointTrigger:
    """Verify that should_checkpoint fires based on token threshold."""

    def test_below_threshold_returns_false(self):
        """A small conversation history should not trigger a checkpoint."""
        mgr = _make_manager(token_threshold=50_000)
        history = [{"role": "user", "content": "Hi"}]
        assert mgr.should_checkpoint(history) is False

    def test_above_threshold_returns_true(self):
        """A conversation history exceeding the threshold should trigger."""
        mgr = _make_manager(token_threshold=10)
        # Create a message that is clearly over 10 tokens when JSON-serialized.
        history = [
            {"role": "user", "content": "This is a sufficiently long message to exceed a small threshold."},
            {"role": "assistant", "content": "And this response adds even more tokens to push us over."},
        ]
        assert mgr.should_checkpoint(history) is True

    def test_exact_threshold_does_not_trigger(self):
        """When total tokens exactly equal the threshold, should_checkpoint
        returns False (trigger is strictly greater-than)."""
        mgr = _make_manager(token_threshold=1_000_000)
        history = [{"role": "user", "content": "tiny"}]
        # With a very large threshold this definitely should not trigger.
        assert mgr.should_checkpoint(history) is False

    def test_empty_history_returns_false(self):
        """An empty conversation history should never trigger a checkpoint."""
        mgr = _make_manager(token_threshold=0)
        # Even with threshold=0, sum of empty list is 0 which is not > 0.
        assert mgr.should_checkpoint([]) is False


# ---------------------------------------------------------------------------
# Save and load (round-trip through mocked Redis)
# ---------------------------------------------------------------------------

class TestSaveAndLoad:
    """Verify that create_checkpoint persists to the store and load_latest
    reconstructs the same CheckpointState."""

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self):
        """Save a checkpoint, load it back, verify all fields match."""
        mgr = _make_manager()

        goal_id = "goal-42"
        completed = _sample_completed_tasks(3)
        pending = _sample_pending_tasks(2)
        open_issues = ["Worker timeout on task-1"]
        decisions = ["Using summarizer instead of extractor for step 2"]

        checkpoint = await mgr.create_checkpoint(
            goal_id=goal_id,
            original_instruction="Analyze the quarterly report",
            completed_tasks=completed,
            pending_tasks=pending,
            open_issues=open_issues,
            decisions_made=decisions,
            checkpoint_number=1,
        )

        # Verify the returned object is a CheckpointState.
        assert isinstance(checkpoint, CheckpointState)
        assert checkpoint.goal_id == goal_id
        assert checkpoint.checkpoint_number == 1
        assert len(checkpoint.completed_tasks) == 3
        assert len(checkpoint.pending_tasks) == 2

        # Now load it back via load_latest.
        loaded = await mgr.load_latest(goal_id)
        assert loaded is not None
        assert loaded.goal_id == checkpoint.goal_id
        assert loaded.original_instruction == checkpoint.original_instruction
        assert loaded.executive_summary == checkpoint.executive_summary
        assert loaded.checkpoint_number == checkpoint.checkpoint_number
        assert loaded.completed_tasks == checkpoint.completed_tasks
        assert loaded.pending_tasks == checkpoint.pending_tasks
        assert loaded.open_issues == checkpoint.open_issues
        assert loaded.decisions_made == checkpoint.decisions_made

    @pytest.mark.asyncio
    async def test_store_keys_follow_naming_convention(self):
        """Verify that store keys follow the documented pattern:
        loom:checkpoint:{goal_id}:{checkpoint_number} and
        loom:checkpoint:{goal_id}:latest."""
        store = InMemoryCheckpointStore()
        mgr = CheckpointManager(store=store)

        await mgr.create_checkpoint(
            goal_id="goal-99",
            original_instruction="Test",
            completed_tasks=_sample_completed_tasks(1),
            pending_tasks=[],
            open_issues=[],
            decisions_made=[],
            checkpoint_number=5,
        )

        keys_written = list(store._data.keys())
        assert "loom:checkpoint:goal-99:5" in keys_written
        assert "loom:checkpoint:goal-99:latest" in keys_written


# ---------------------------------------------------------------------------
# TTL configuration
# ---------------------------------------------------------------------------

class TestTTLConfiguration:
    """Verify that custom TTL values are forwarded to the store."""

    @pytest.mark.asyncio
    async def test_default_ttl_is_24_hours(self):
        """Default TTL should be 86400 seconds (24 hours)."""
        store = InMemoryCheckpointStore()
        mgr = CheckpointManager(store=store)

        await mgr.create_checkpoint(
            goal_id="g1",
            original_instruction="Test",
            completed_tasks=[],
            pending_tasks=[],
            open_issues=[],
            decisions_made=[],
            checkpoint_number=1,
        )

        # Both entries should have an expiry set (non-None expires_at).
        for key, (value, expires_at) in store._data.items():
            assert expires_at is not None

    @pytest.mark.asyncio
    async def test_custom_ttl_stores_with_expiry(self):
        """A non-default TTL should result in entries that expire sooner."""
        custom_ttl = 3600  # 1 hour
        mgr = _make_manager(ttl_seconds=custom_ttl)

        await mgr.create_checkpoint(
            goal_id="g2",
            original_instruction="Short-lived goal",
            completed_tasks=[],
            pending_tasks=[],
            open_issues=[],
            decisions_made=[],
            checkpoint_number=1,
        )

        # Verify data was stored (2 keys: versioned + latest pointer).
        assert len(mgr.store._data) == 2


# ---------------------------------------------------------------------------
# Missing checkpoint
# ---------------------------------------------------------------------------

class TestMissingCheckpoint:
    """Verify behavior when loading a checkpoint that does not exist."""

    @pytest.mark.asyncio
    async def test_load_latest_returns_none_for_unknown_goal(self):
        """load_latest returns None when no checkpoint has been saved for
        the given goal_id."""
        mgr = _make_manager()
        result = await mgr.load_latest("nonexistent-goal")
        assert result is None

    @pytest.mark.asyncio
    async def test_load_latest_returns_none_when_data_expired(self):
        """If the latest pointer exists but the checkpoint data has expired
        (TTL), load_latest returns None gracefully."""
        store = InMemoryCheckpointStore()
        mgr = CheckpointManager(store=store)

        # Manually insert a "latest" pointer that references a missing data key.
        await store.set("loom:checkpoint:goal-x:latest", "loom:checkpoint:goal-x:1")

        result = await mgr.load_latest("goal-x")
        assert result is None


# ---------------------------------------------------------------------------
# Context compression (executive summary construction)
# ---------------------------------------------------------------------------

class TestContextCompression:
    """Verify that the checkpoint executive summary compresses context
    appropriately: only recent outcomes are included, and the summary
    stays bounded regardless of how many tasks have completed."""

    @pytest.mark.asyncio
    async def test_executive_summary_includes_goal(self):
        """The executive summary should contain the original instruction."""
        mgr = _make_manager()
        # InMemoryCheckpointStore handles storage automatically

        checkpoint = await mgr.create_checkpoint(
            goal_id="g1",
            original_instruction="Analyze the quarterly report",
            completed_tasks=_sample_completed_tasks(2),
            pending_tasks=_sample_pending_tasks(1),
            open_issues=[],
            decisions_made=[],
            checkpoint_number=1,
        )

        assert "Analyze the quarterly report" in checkpoint.executive_summary

    @pytest.mark.asyncio
    async def test_executive_summary_includes_progress_counts(self):
        """The summary should report completed and pending task counts."""
        mgr = _make_manager()
        # InMemoryCheckpointStore handles storage automatically

        checkpoint = await mgr.create_checkpoint(
            goal_id="g1",
            original_instruction="Test",
            completed_tasks=_sample_completed_tasks(5),
            pending_tasks=_sample_pending_tasks(3),
            open_issues=[],
            decisions_made=[],
            checkpoint_number=1,
        )

        assert "5 completed" in checkpoint.executive_summary
        assert "3 pending" in checkpoint.executive_summary

    @pytest.mark.asyncio
    async def test_summary_truncates_large_task_lists(self):
        """When there are many completed tasks, only the last 10 outcomes
        appear in the executive summary (from the last 20 tasks)."""
        mgr = _make_manager()
        # InMemoryCheckpointStore handles storage automatically

        # 50 completed tasks -- only last 10 should appear in summary text.
        many_tasks = _sample_completed_tasks(50)

        checkpoint = await mgr.create_checkpoint(
            goal_id="g1",
            original_instruction="Big job",
            completed_tasks=many_tasks,
            pending_tasks=[],
            open_issues=[],
            decisions_made=[],
            checkpoint_number=1,
        )

        # The summary should mention all 50 completed in the count line.
        assert "50 completed" in checkpoint.executive_summary

        # But the rendered outcomes should be capped at 10 lines.
        outcome_lines = [
            line for line in checkpoint.executive_summary.splitlines()
            if line.startswith("- [")
        ]
        assert len(outcome_lines) == 10

    @pytest.mark.asyncio
    async def test_completed_tasks_stored_as_slim_records(self):
        """Completed tasks in the checkpoint should only contain task_id,
        worker_type, and summary -- not the full original dict."""
        mgr = _make_manager()
        # InMemoryCheckpointStore handles storage automatically

        full_tasks = [
            {
                "task_id": "t1",
                "worker_type": "summarizer",
                "status": "completed",
                "summary": "Done",
                "raw_output": {"very": "large", "nested": {"data": [1, 2, 3]}},
                "processing_time_ms": 1234,
            }
        ]

        checkpoint = await mgr.create_checkpoint(
            goal_id="g1",
            original_instruction="Test",
            completed_tasks=full_tasks,
            pending_tasks=[],
            open_issues=[],
            decisions_made=[],
            checkpoint_number=1,
        )

        stored = checkpoint.completed_tasks[0]
        assert set(stored.keys()) == {"task_id", "worker_type", "summary"}
        assert "raw_output" not in stored

    @pytest.mark.asyncio
    async def test_context_token_count_is_set(self):
        """The checkpoint should record the token count of the executive
        summary at the time of creation."""
        mgr = _make_manager()
        # InMemoryCheckpointStore handles storage automatically

        checkpoint = await mgr.create_checkpoint(
            goal_id="g1",
            original_instruction="Test",
            completed_tasks=_sample_completed_tasks(2),
            pending_tasks=[],
            open_issues=[],
            decisions_made=[],
            checkpoint_number=1,
        )

        assert checkpoint.context_token_count > 0
        # It should match what estimate_tokens returns for the summary.
        expected = mgr.estimate_tokens(checkpoint.executive_summary)
        assert checkpoint.context_token_count == expected


# ---------------------------------------------------------------------------
# format_for_injection
# ---------------------------------------------------------------------------

class TestFormatForInjection:
    """Verify that format_for_injection produces a human-readable text block
    suitable for injecting into an orchestrator's context window."""

    def _make_checkpoint(self, **overrides) -> CheckpointState:
        """Build a CheckpointState with sensible defaults, allowing overrides."""
        defaults = dict(
            goal_id="goal-1",
            original_instruction="Summarize the report",
            executive_summary="Goal: Summarize the report\nProgress: 2 completed, 1 pending.",
            completed_tasks=[{"task_id": "t1", "worker_type": "summarizer", "summary": "Done"}],
            pending_tasks=[{"task_id": "p1", "description": "Classify"}],
            open_issues=["Worker timeout on task-1"],
            decisions_made=["Using summarizer for step 2"],
            context_token_count=100,
            checkpoint_number=3,
        )
        defaults.update(overrides)
        return CheckpointState(**defaults)

    def test_includes_checkpoint_number(self):
        """Formatted output includes the checkpoint number header."""
        mgr = _make_manager()
        cp = self._make_checkpoint(checkpoint_number=3)
        text = mgr.format_for_injection(cp)
        assert "CHECKPOINT #3" in text

    def test_includes_original_goal(self):
        """Formatted output includes the original instruction."""
        mgr = _make_manager()
        cp = self._make_checkpoint(original_instruction="Analyze data")
        text = mgr.format_for_injection(cp)
        assert "Analyze data" in text

    def test_includes_decisions(self):
        """Formatted output lists all decisions made."""
        mgr = _make_manager()
        cp = self._make_checkpoint(decisions_made=["Decision A", "Decision B"])
        text = mgr.format_for_injection(cp)
        assert "Decision A" in text
        assert "Decision B" in text

    def test_includes_open_issues(self):
        """Formatted output lists open issues when present."""
        mgr = _make_manager()
        cp = self._make_checkpoint(open_issues=["Blocker X", "Risk Y"])
        text = mgr.format_for_injection(cp)
        assert "Blocker X" in text
        assert "Risk Y" in text

    def test_includes_pending_tasks(self):
        """Formatted output lists pending tasks."""
        mgr = _make_manager()
        pending = [{"task_id": "p1", "description": "Do thing"}]
        cp = self._make_checkpoint(pending_tasks=pending)
        text = mgr.format_for_injection(cp)
        assert "Pending Tasks" in text

    def test_no_open_issues_section_when_empty(self):
        """When there are no open issues, that section should be absent."""
        mgr = _make_manager()
        cp = self._make_checkpoint(open_issues=[])
        text = mgr.format_for_injection(cp)
        assert "Open Issues" not in text

    def test_has_start_and_end_markers(self):
        """Formatted output is bracketed by CHECKPOINT / END CHECKPOINT markers."""
        mgr = _make_manager()
        cp = self._make_checkpoint()
        text = mgr.format_for_injection(cp)
        assert text.startswith("=== CHECKPOINT")
        assert text.strip().endswith("=== END CHECKPOINT ===")
