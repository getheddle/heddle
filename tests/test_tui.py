"""Tests for the TUI dashboard module.

Tests the domain models, event handling logic, and widget composition
without requiring a running NATS server.
"""

from heddle.tui.app import (
    DashboardState,
    HeddleDashboard,
    NatsConnected,
    NatsDisconnected,
    NatsEvent,
    TrackedGoal,
    TrackedStage,
    TrackedTask,
)

# ---------------------------------------------------------------------------
# Domain model tests
# ---------------------------------------------------------------------------


class TestTrackedGoal:
    def test_defaults(self):
        goal = TrackedGoal(goal_id="g1")
        assert goal.status == "received"
        assert goal.subtask_count == 0
        assert goal.collected == 0
        assert goal.started_at > 0

    def test_custom_fields(self):
        goal = TrackedGoal(goal_id="g2", instruction="test", status="completed", subtask_count=3)
        assert goal.instruction == "test"
        assert goal.status == "completed"
        assert goal.subtask_count == 3


class TestTrackedTask:
    def test_defaults(self):
        task = TrackedTask(task_id="t1")
        assert task.status == "dispatched"
        assert task.worker_type == ""
        assert task.tier == ""

    def test_custom_fields(self):
        task = TrackedTask(task_id="t2", worker_type="summarizer", tier="local")
        assert task.worker_type == "summarizer"
        assert task.tier == "local"


class TestTrackedStage:
    def test_defaults(self):
        stage = TrackedStage(stage_name="extract")
        assert stage.status == "running"
        assert stage.wall_time_ms == 0


class TestDashboardState:
    def test_empty_state(self):
        state = DashboardState()
        assert len(state.goals) == 0
        assert len(state.tasks) == 0
        assert len(state.stages) == 0
        assert state.event_count == 0
        assert state.message_count == 0

    def test_add_goal(self):
        state = DashboardState()
        state.goals["g1"] = TrackedGoal(goal_id="g1", instruction="test goal")
        assert "g1" in state.goals
        assert state.goals["g1"].instruction == "test goal"

    def test_add_task(self):
        state = DashboardState()
        state.tasks["t1"] = TrackedTask(task_id="t1", goal_id="g1", worker_type="summarizer")
        assert "t1" in state.tasks


# ---------------------------------------------------------------------------
# Status icon tests
# ---------------------------------------------------------------------------


class TestStatusIcon:
    def test_known_statuses(self):
        assert HeddleDashboard._status_icon("completed") == "✅"
        assert HeddleDashboard._status_icon("COMPLETED") == "✅"
        assert HeddleDashboard._status_icon("failed") == "❌"
        assert HeddleDashboard._status_icon("FAILED") == "❌"
        assert HeddleDashboard._status_icon("dispatched") == "📤"
        assert HeddleDashboard._status_icon("received") == "📥"

    def test_unknown_status_returns_raw(self):
        assert HeddleDashboard._status_icon("custom_status") == "custom_status"


# ---------------------------------------------------------------------------
# Event summary tests
# ---------------------------------------------------------------------------


class TestSummarizeEvent:
    def test_basic_event(self):
        summary = HeddleDashboard._summarize_event(
            "heddle.goals.incoming",
            {"goal_id": "g1", "instruction": "analyze this"},
        )
        assert "heddle.goals.incoming" in summary
        assert "goal_id=g1" in summary
        assert "instruction=analyze this" in summary

    def test_long_values_truncated(self):
        summary = HeddleDashboard._summarize_event(
            "heddle.tasks.incoming",
            {"task_id": "t1", "instruction": "x" * 100},
        )
        assert "..." in summary

    def test_missing_keys_skipped(self):
        summary = HeddleDashboard._summarize_event("heddle.test", {"custom_key": "val"})
        assert "heddle.test" in summary
        assert "custom_key" not in summary


# ---------------------------------------------------------------------------
# Event handler logic tests (unit-test the state mutations)
# ---------------------------------------------------------------------------


class TestEventHandlers:
    def _make_app(self):
        return HeddleDashboard(nats_url="nats://test:4222")

    def test_handle_goal_received(self):
        app = self._make_app()
        data = {"goal_id": "g1", "instruction": "test instruction"}
        app._handle_goal_received(data)
        assert "g1" in app.state.goals
        assert app.state.goals["g1"].instruction == "test instruction"

    def test_handle_task_dispatched(self):
        app = self._make_app()
        # Add parent goal first
        app.state.goals["g1"] = TrackedGoal(goal_id="g1")
        data = {
            "task_id": "t1",
            "parent_task_id": "g1",
            "worker_type": "summarizer",
            "model_tier": "local",
        }
        app._handle_task_dispatched(data)
        assert "t1" in app.state.tasks
        assert app.state.tasks["t1"].worker_type == "summarizer"
        assert app.state.goals["g1"].subtask_count == 1

    def test_handle_task_routed(self):
        app = self._make_app()
        app.state.tasks["t1"] = TrackedTask(task_id="t1")
        app._handle_task_routed("heddle.tasks.summarizer.local", {"task_id": "t1"})
        assert app.state.tasks["t1"].tier == "local"
        assert app.state.tasks["t1"].status == "routed"

    def test_handle_result_updates_task(self):
        app = self._make_app()
        app.state.tasks["t1"] = TrackedTask(task_id="t1")
        app.state.goals["g1"] = TrackedGoal(goal_id="g1")
        data = {
            "task_id": "t1",
            "status": "COMPLETED",
            "processing_time_ms": 1500,
            "model_used": "llama3",
        }
        app._handle_result("heddle.results.g1", data)
        assert app.state.tasks["t1"].status == "COMPLETED"
        assert app.state.tasks["t1"].elapsed_ms == 1500
        assert app.state.tasks["t1"].model_used == "llama3"
        assert app.state.goals["g1"].collected == 1

    def test_handle_final_result_marks_goal(self):
        app = self._make_app()
        app.state.goals["g1"] = TrackedGoal(goal_id="g1")
        data = {
            "task_id": "g1",  # Same as goal_id → final result
            "status": "COMPLETED",
            "processing_time_ms": 3000,
        }
        app._handle_result("heddle.results.g1", data)
        assert app.state.goals["g1"].status == "COMPLETED"
        assert app.state.goals["g1"].elapsed_ms == 3000

    def test_handle_timeline(self):
        app = self._make_app()
        timeline = [
            {"stage": "extract", "worker_type": "extractor", "wall_time_ms": 500},
            {"stage": "classify", "worker_type": "classifier", "wall_time_ms": 300},
        ]
        app._handle_timeline("g1", timeline)
        assert len(app.state.stages) == 2
        assert app.state.stages[0].stage_name == "extract"
        assert app.state.stages[1].wall_time_ms == 300


# ---------------------------------------------------------------------------
# Message model tests
# ---------------------------------------------------------------------------


class TestMessages:
    def test_nats_event(self):
        event = NatsEvent("heddle.test", {"key": "value"})
        assert event.subject == "heddle.test"
        assert event.data == {"key": "value"}

    def test_nats_connected(self):
        event = NatsConnected("nats://localhost:4222")
        assert event.url == "nats://localhost:4222"

    def test_nats_disconnected(self):
        event = NatsDisconnected("timeout")
        assert event.reason == "timeout"

    def test_nats_disconnected_default(self):
        event = NatsDisconnected()
        assert event.reason == ""


# ---------------------------------------------------------------------------
# App construction tests
# ---------------------------------------------------------------------------


class TestAppConstruction:
    def test_default_nats_url(self):
        app = HeddleDashboard()
        assert app.nats_url == "nats://localhost:4222"

    def test_custom_nats_url(self):
        app = HeddleDashboard(nats_url="nats://custom:4222")
        assert app.nats_url == "nats://custom:4222"

    def test_initial_state_empty(self):
        app = HeddleDashboard()
        assert len(app.state.goals) == 0
        assert len(app.state.tasks) == 0
        assert app.state.message_count == 0
