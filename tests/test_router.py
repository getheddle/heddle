"""
Unit tests for TaskRouter and TokenBucketRateLimiter (router/router.py).

Tests cover:
- TokenBucketRateLimiter: acquire, refill, unknown tier
- TaskRouter.resolve_tier: override, default, unknown
- TaskRouter.route: happy path, malformed message, rate-limited, dead-letter
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest
import yaml

from loom.bus.memory import InMemoryBus
from loom.core.messages import ModelTier, TaskMessage, TaskPriority
from loom.router.router import DEAD_LETTER_SUBJECT, TaskRouter, TokenBucketRateLimiter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_rules(rules: dict[str, Any]) -> str:
    """Write router_rules.yaml to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump(rules, f)
    return path


def _make_task_data(
    worker_type: str = "summarizer",
    tier: str = "local",
    **overrides: Any,
) -> dict[str, Any]:
    """Create a minimal valid TaskMessage dict."""
    task = TaskMessage(
        worker_type=worker_type,
        payload={"text": "hello"},
        model_tier=ModelTier(tier),
    )
    data = task.model_dump(mode="json")
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# TokenBucketRateLimiter tests
# ---------------------------------------------------------------------------


class TestTokenBucketRateLimiter:
    def test_acquire_within_capacity(self):
        limiter = TokenBucketRateLimiter({"local": {"max_concurrent": 3}})
        assert limiter.try_acquire("local") is True
        assert limiter.try_acquire("local") is True
        assert limiter.try_acquire("local") is True

    def test_acquire_exhausted(self):
        limiter = TokenBucketRateLimiter({"local": {"max_concurrent": 1}})
        assert limiter.try_acquire("local") is True
        assert limiter.try_acquire("local") is False

    def test_unknown_tier_always_passes(self):
        limiter = TokenBucketRateLimiter({"local": {"max_concurrent": 1}})
        assert limiter.try_acquire("unknown_tier") is True

    def test_default_capacity(self):
        """Missing max_concurrent defaults to 10."""
        limiter = TokenBucketRateLimiter({"local": {}})
        for _ in range(10):
            assert limiter.try_acquire("local") is True

    def test_empty_rate_limits(self):
        limiter = TokenBucketRateLimiter({})
        assert limiter.try_acquire("local") is True


# ---------------------------------------------------------------------------
# TaskRouter.resolve_tier tests
# ---------------------------------------------------------------------------


class TestResolveTier:
    def test_no_override_uses_task_tier(self):
        rules_path = _write_rules({"tier_overrides": {}})
        try:
            router = TaskRouter(rules_path, InMemoryBus())
            task = TaskMessage(worker_type="summarizer", payload={}, model_tier=ModelTier.LOCAL)
            assert router.resolve_tier(task) == ModelTier.LOCAL
        finally:
            os.unlink(rules_path)

    def test_override_takes_precedence(self):
        rules_path = _write_rules({"tier_overrides": {"summarizer": "frontier"}})
        try:
            router = TaskRouter(rules_path, InMemoryBus())
            task = TaskMessage(worker_type="summarizer", payload={}, model_tier=ModelTier.LOCAL)
            assert router.resolve_tier(task) == ModelTier.FRONTIER
        finally:
            os.unlink(rules_path)

    def test_invalid_override_raises(self):
        rules_path = _write_rules({"tier_overrides": {"summarizer": "invalid_tier"}})
        try:
            router = TaskRouter(rules_path, InMemoryBus())
            task = TaskMessage(worker_type="summarizer", payload={}, model_tier=ModelTier.LOCAL)
            with pytest.raises(ValueError):
                router.resolve_tier(task)
        finally:
            os.unlink(rules_path)


# ---------------------------------------------------------------------------
# TaskRouter.route tests
# ---------------------------------------------------------------------------


class TestRoute:
    @pytest.fixture
    def bus(self):
        return InMemoryBus()

    @pytest.fixture
    def rules_path(self):
        path = _write_rules({
            "tier_overrides": {},
            "rate_limits": {
                "local": {"max_concurrent": 10},
                "standard": {"max_concurrent": 5},
            },
        })
        yield path
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_route_happy_path(self, bus, rules_path):
        """Valid task routed to correct subject."""
        router = TaskRouter(rules_path, bus)
        await bus.connect()

        # Subscribe to the expected destination
        sub = await bus.subscribe("loom.tasks.summarizer.local")
        data = _make_task_data("summarizer", "local")

        await router.route(data)

        msg = await sub.__anext__()
        assert msg["worker_type"] == "summarizer"

    @pytest.mark.asyncio
    async def test_route_malformed_message_dead_letters(self, bus, rules_path):
        """Invalid message goes to dead letter."""
        router = TaskRouter(rules_path, bus)
        await bus.connect()

        dl_sub = await bus.subscribe(DEAD_LETTER_SUBJECT)

        await router.route({"garbage": True})  # Missing required fields

        msg = await dl_sub.__anext__()
        assert "invalid_task_message" in msg["reason"]

    @pytest.mark.asyncio
    async def test_route_rate_limited_dead_letters(self, bus):
        """Rate-limited task goes to dead letter."""
        rules_path = _write_rules({
            "tier_overrides": {},
            "rate_limits": {"local": {"max_concurrent": 1}},
        })
        try:
            router = TaskRouter(rules_path, bus)
            await bus.connect()

            dl_sub = await bus.subscribe(DEAD_LETTER_SUBJECT)
            dest_sub = await bus.subscribe("loom.tasks.summarizer.local")

            data1 = _make_task_data("summarizer", "local")
            data2 = _make_task_data("summarizer", "local")

            # First should succeed
            await router.route(data1)
            msg1 = await dest_sub.__anext__()
            assert msg1["worker_type"] == "summarizer"

            # Second should be rate limited
            await router.route(data2)
            dl_msg = await dl_sub.__anext__()
            assert "rate_limited" in dl_msg["reason"]
        finally:
            os.unlink(rules_path)

    @pytest.mark.asyncio
    async def test_route_with_tier_override(self, bus):
        """Tier override redirects task to different tier subject."""
        rules_path = _write_rules({
            "tier_overrides": {"summarizer": "frontier"},
            "rate_limits": {},
        })
        try:
            router = TaskRouter(rules_path, bus)
            await bus.connect()

            sub = await bus.subscribe("loom.tasks.summarizer.frontier")
            data = _make_task_data("summarizer", "local")  # Task says local

            await router.route(data)

            msg = await sub.__anext__()
            assert msg["worker_type"] == "summarizer"
            assert msg["model_tier"] == "local"  # Original tier preserved in message
        finally:
            os.unlink(rules_path)

    @pytest.mark.asyncio
    async def test_dead_letter_message_structure(self, bus, rules_path):
        """Verify dead-letter message contains expected fields."""
        router = TaskRouter(rules_path, bus)
        await bus.connect()

        dl_sub = await bus.subscribe(DEAD_LETTER_SUBJECT)
        await router.route({"bad": "data"})

        msg = await dl_sub.__anext__()
        assert "reason" in msg
        assert "original_task" in msg
        assert msg["original_task"] == {"bad": "data"}
