"""
Integration test: submit task -> router -> worker -> result.
Run with: pytest tests/test_integration.py -v
Requires NATS on localhost:4222
"""
import asyncio
import json

import pytest
import nats as nats_lib

from loom.core.messages import TaskMessage, TaskResult, ModelTier

NATS_URL = "nats://localhost:4222"


@pytest.mark.asyncio
async def test_roundtrip():
    nc = await nats_lib.connect(NATS_URL)
    results = []

    # Subscribe to results
    async def on_result(msg):
        results.append(json.loads(msg.data.decode()))

    await nc.subscribe("loom.results.*", cb=on_result)

    # Publish a task directly to a worker subject (bypasses router for test isolation)
    task = TaskMessage(
        worker_type="summarizer",
        payload={"text": "This is a test document with several sentences about testing."},
        model_tier=ModelTier.LOCAL,
    )
    await nc.publish(
        "loom.tasks.summarizer.local",
        json.dumps(task.model_dump(mode="json")).encode(),
    )

    # Wait for result
    await asyncio.sleep(5)
    await nc.drain()

    assert len(results) == 1
    result = TaskResult(**results[0])
    assert result.status.value in ("completed", "failed")
