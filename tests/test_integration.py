"""
Integration test: submit task -> router -> worker -> result.

Run with:  pytest tests/test_integration.py -v
Requires:  NATS running on localhost:4222 AND a summarizer worker running:
           loom worker --config configs/workers/summarizer.yaml --tier local \
                       --nats-url nats://localhost:4222

NOTE: This test will FAIL if no worker is subscribed to loom.tasks.summarizer.local.
      The task message will be published but nobody will process it, so results
      will be empty after the 5-second wait. This is expected behavior when
      running `pytest tests/` without infrastructure — only unit tests pass.

TODO: Add a pytest marker (e.g., @pytest.mark.integration) so this test can be
      excluded from default test runs: pytest tests/ -v -m "not integration"

TODO: Consider increasing the sleep or using a polling loop with timeout instead
      of a fixed 5-second wait. On slow machines or cold Ollama starts, 5 seconds
      may not be enough for the model to respond.
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
