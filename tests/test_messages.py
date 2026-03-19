"""Test message schema validation and serialization."""

from loom.core.messages import ModelTier, TaskMessage, TaskResult, TaskStatus


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
