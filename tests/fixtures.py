"""Internal test helpers for heddle's own test suite.

Wire-dict builders that wrap core bodies in their `WireEnvelope`, for tests
that feed a consumer's ``handle_message`` or publish onto the bus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from heddle.core.messages import OrchestratorGoal, TaskMessage, TaskResult

from heddle.core.envelope import wrap


def wrap_goal(goal: OrchestratorGoal) -> dict[str, Any]:
    """Wire dict for an OrchestratorGoal — wrapped in its WireEnvelope.

    Use when feeding a goal to a consumer's ``handle_message`` or publishing to
    ``heddle.goals.incoming``; a bare ``goal.model_dump()`` is rejected by the
    envelope-parsing consumer. See the "Wire-envelope test pattern" in
    docs/CODING_GUIDE.md.
    """
    return wrap("core.OrchestratorGoal", goal).model_dump(mode="json")


def wrap_task(task: TaskMessage) -> dict[str, Any]:
    """Wire dict for a TaskMessage — wrapped in its WireEnvelope.

    The body field is ``input`` (renamed from ``payload``). Use when feeding a
    task to a worker/router or publishing to ``heddle.tasks.*``.
    """
    return wrap("core.TaskMessage", task).model_dump(mode="json")


def wrap_result(result: TaskResult) -> dict[str, Any]:
    """Wire dict for a TaskResult — wrapped in its WireEnvelope.

    Use when simulating a worker publishing to ``heddle.results.*``.
    """
    return wrap("core.TaskResult", result).model_dump(mode="json")
