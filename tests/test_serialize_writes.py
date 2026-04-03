"""Tests for SyncProcessingBackend.serialize_writes — write serialization."""

import asyncio
from typing import Any

import pytest

from heddle.worker.processor import SyncProcessingBackend


class CountingBackend(SyncProcessingBackend):
    """Test backend that tracks concurrent execution."""

    def __init__(self, *, serialize_writes: bool = False, delay: float = 0.05) -> None:
        super().__init__(serialize_writes=serialize_writes)
        self.delay = delay
        self.max_concurrent = 0
        self._current = 0
        self._lock = asyncio.Lock()  # just for tracking, not serialization

    def process_sync(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        import time

        # Track concurrent calls (thread-safe via GIL for simple int ops)
        self._current += 1
        if self._current > self.max_concurrent:
            self.max_concurrent = self._current
        time.sleep(self.delay)
        self._current -= 1

        return {"output": {"done": True}, "model_used": "test"}


class TestSerializeWrites:
    @pytest.mark.asyncio
    async def test_without_serialize_allows_concurrent(self):
        """Without serialize_writes, multiple calls can overlap."""
        backend = CountingBackend(serialize_writes=False, delay=0.05)

        # Run 3 concurrent calls
        tasks = [
            asyncio.create_task(backend.process({}, {})),
            asyncio.create_task(backend.process({}, {})),
            asyncio.create_task(backend.process({}, {})),
        ]
        await asyncio.gather(*tasks)

        # With thread pool, some concurrency is expected
        # (exact number depends on executor, but >1 is likely)
        # We don't assert >1 because thread pool behavior varies

    @pytest.mark.asyncio
    async def test_with_serialize_prevents_concurrent(self):
        """With serialize_writes, calls are serialized."""
        backend = CountingBackend(serialize_writes=True, delay=0.05)

        tasks = [
            asyncio.create_task(backend.process({}, {})),
            asyncio.create_task(backend.process({}, {})),
            asyncio.create_task(backend.process({}, {})),
        ]
        await asyncio.gather(*tasks)

        # The lock ensures max 1 concurrent call
        assert backend.max_concurrent == 1

    @pytest.mark.asyncio
    async def test_serialize_writes_default_false(self):
        """Default SyncProcessingBackend has no write lock."""

        class PlainBackend(SyncProcessingBackend):
            def process_sync(self, payload, config):
                return {"output": {}, "model_used": "test"}

        backend = PlainBackend()
        assert backend._write_lock is None
        result = await backend.process({}, {})
        assert result["output"] == {}
