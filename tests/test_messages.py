"""Test message schema validation and serialization."""

from loom.core.messages import ModelTier, OrchestratorGoal, TaskMessage, TaskResult, TaskStatus


def test_task_message_defaults():
    msg = TaskMessage(worker_type="summarizer", payload={"text": "hello"})
    assert msg.task_id  # Auto-generated
    assert msg.model_tier == ModelTier.STANDARD
    assert msg.retry_count == 0


def test_task_message_custom_fields():
    msg = TaskMessage(
        worker_type="classifier",
        payload={"text": "test", "categories": ["a", "b"]},
        model_tier=ModelTier.LOCAL,
        priority="high",
        max_retries=5,
    )
    assert msg.model_tier == ModelTier.LOCAL
    assert msg.max_retries == 5
    assert msg.worker_type == "classifier"


def test_task_result_serialization():
    result = TaskResult(
        task_id="abc",
        worker_type="summarizer",
        status=TaskStatus.COMPLETED,
        output={"summary": "test"},
    )
    data = result.model_dump(mode="json")
    restored = TaskResult(**data)
    assert restored.output == {"summary": "test"}


def test_task_result_failed():
    result = TaskResult(
        task_id="def",
        worker_type="extractor",
        status=TaskStatus.FAILED,
        error="Something went wrong",
    )
    assert result.status == TaskStatus.FAILED
    assert result.error == "Something went wrong"
    assert result.output is None


def test_task_message_roundtrip():
    msg = TaskMessage(
        worker_type="summarizer",
        payload={"text": "hello world"},
        model_tier=ModelTier.FRONTIER,
    )
    data = msg.model_dump(mode="json")
    restored = TaskMessage(**data)
    assert restored.task_id == msg.task_id
    assert restored.worker_type == msg.worker_type
    assert restored.model_tier == ModelTier.FRONTIER
    assert restored.payload == {"text": "hello world"}


# --- request_id field tests ---


def test_task_message_request_id_default_none():
    """request_id defaults to None for backward compatibility."""
    msg = TaskMessage(worker_type="summarizer", payload={"text": "hello"})
    assert msg.request_id is None


def test_task_message_request_id_set():
    """request_id can be explicitly set."""
    msg = TaskMessage(
        worker_type="summarizer",
        payload={"text": "hello"},
        request_id="req-123",
    )
    assert msg.request_id == "req-123"


def test_task_message_request_id_roundtrip():
    """request_id survives serialization/deserialization."""
    msg = TaskMessage(
        worker_type="summarizer",
        payload={"text": "hello"},
        request_id="req-abc",
    )
    data = msg.model_dump(mode="json")
    restored = TaskMessage(**data)
    assert restored.request_id == "req-abc"


def test_task_message_request_id_absent_in_dict():
    """Omitting request_id from a dict still creates a valid TaskMessage."""
    data = {
        "worker_type": "summarizer",
        "payload": {"text": "hello"},
    }
    msg = TaskMessage(**data)
    assert msg.request_id is None


def test_orchestrator_goal_request_id_default_none():
    """OrchestratorGoal.request_id defaults to None for backward compatibility."""
    goal = OrchestratorGoal(instruction="do something")
    assert goal.request_id is None


def test_orchestrator_goal_request_id_set():
    """OrchestratorGoal.request_id can be explicitly set."""
    goal = OrchestratorGoal(instruction="do something", request_id="req-goal-1")
    assert goal.request_id == "req-goal-1"


def test_orchestrator_goal_request_id_roundtrip():
    """OrchestratorGoal.request_id survives serialization/deserialization."""
    goal = OrchestratorGoal(instruction="do something", request_id="req-goal-2")
    data = goal.model_dump(mode="json")
    restored = OrchestratorGoal(**data)
    assert restored.request_id == "req-goal-2"
