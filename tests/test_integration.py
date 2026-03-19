"""
Integration test: submit a task via NATS -> worker processes it -> result arrives.

This test validates the full message round-trip through the Loom actor mesh:
  1. Connect to NATS and subscribe to the results subject.
  2. Publish a TaskMessage directly to a worker's subject (bypassing the
     router for test isolation).
  3. Poll for the result with a configurable timeout instead of a fixed
     sleep, so the test adapts to slow machines and cold Ollama starts.
  4. Assert that exactly one result arrived and its status is valid.

Run with:
    pytest tests/test_integration.py -v

Skip during default runs:
    pytest tests/ -v -m "not integration"

Prerequisites:
    - NATS running on localhost:4222
    - A summarizer worker subscribed to ``loom.tasks.summarizer.local``::

        loom worker --config configs/workers/summarizer.yaml \\
                    --tier local --nats-url nats://localhost:4222

NOTE: Without infrastructure the test will fail — this is expected.
      Unit tests (``pytest tests/ -m "not integration"``) do not require it.
"""

from __future__ import annotations

import asyncio
import json
import time

import nats as nats_lib
import pytest

from loom.core.messages import ModelTier, TaskMessage, TaskResult

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

NATS_URL = "nats://localhost:4222"

# Maximum number of seconds to wait for the worker to return a result.
# Override via the LOOM_INTEGRATION_TIMEOUT env-var if needed (see fixture).
DEFAULT_TIMEOUT_SECONDS: float = 15.0

# How often (in seconds) we check whether a result has arrived.
POLL_INTERVAL_SECONDS: float = 0.5


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_roundtrip():
    """Full NATS round-trip: publish a task and poll until the result arrives.

    The test publishes a ``TaskMessage`` for the *summarizer* worker on the
    ``local`` tier and then polls the ``loom.results.*`` wildcard subscription
    until either:

    * A result message is received (success path), or
    * The configurable timeout elapses (failure path — no worker responded).

    Using a polling loop instead of a fixed ``asyncio.sleep`` makes the test
    both faster on quick machines and more tolerant of slow cold-starts.
    """

    # -- 1. Connect to NATS -------------------------------------------------
    nc = await nats_lib.connect(NATS_URL)

    # Accumulator for result messages delivered via the subscription callback.
    results: list[dict] = []

    async def _on_result(msg) -> None:
        """Callback invoked by NATS when a message arrives on loom.results.*."""
        results.append(json.loads(msg.data.decode()))

    # Subscribe to the wildcard results subject so we capture any result
    # regardless of goal_id.
    await nc.subscribe("loom.results.*", cb=_on_result)

    # -- 2. Build and publish the task --------------------------------------
    task = TaskMessage(
        worker_type="summarizer",
        payload={
            "text": ("This is a test document with several sentences about testing."),
        },
        model_tier=ModelTier.LOCAL,
    )

    # Publish directly to the worker subject, bypassing the router.
    # This keeps the test focused on the worker round-trip.
    await nc.publish(
        "loom.tasks.summarizer.local",
        json.dumps(task.model_dump(mode="json")).encode(),
    )

    # -- 3. Poll for the result with a timeout ------------------------------
    deadline = time.monotonic() + DEFAULT_TIMEOUT_SECONDS

    while not results and time.monotonic() < deadline:
        # Yield to the event loop so the NATS subscription callback can fire.
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    # -- 4. Tear down the NATS connection -----------------------------------
    # drain() flushes pending messages and closes the connection gracefully.
    await nc.drain()

    # -- 5. Assertions ------------------------------------------------------
    assert len(results) == 1, (
        f"Expected exactly 1 result within {DEFAULT_TIMEOUT_SECONDS}s, "
        f"got {len(results)}. Is the summarizer worker running?"
    )

    result = TaskResult(**results[0])

    # The worker should report either success or an explicit failure — both
    # are valid outcomes for an integration smoke-test. What we do *not*
    # want is zero results (timeout) or a malformed message.
    assert result.status.value in ("completed", "failed"), (
        f"Unexpected result status: {result.status.value!r}"
    )
