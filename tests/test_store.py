"""Tests for InMemoryCheckpointStore."""
from __future__ import annotations

import pytest

from loom.orchestrator.store import InMemoryCheckpointStore


@pytest.fixture
def store():
    return InMemoryCheckpointStore()


@pytest.mark.asyncio
async def test_set_get_roundtrip(store):
    """Basic set/get returns the stored value."""
    await store.set("k1", "hello")
    assert await store.get("k1") == "hello"


@pytest.mark.asyncio
async def test_get_missing_key(store):
    """Getting a key that was never set returns None."""
    assert await store.get("nonexistent") is None


@pytest.mark.asyncio
async def test_get_before_expiry(store, monkeypatch):
    """Value is returned when TTL has not elapsed."""
    t = 1000.0
    monkeypatch.setattr("time.monotonic", lambda: t)
    await store.set("k", "val", ttl_seconds=60)

    # Advance 30 s — still within TTL
    monkeypatch.setattr("time.monotonic", lambda: t + 30)
    assert await store.get("k") == "val"


@pytest.mark.asyncio
async def test_get_after_expiry(store, monkeypatch):
    """Value returns None once TTL has elapsed."""
    t = 1000.0
    monkeypatch.setattr("time.monotonic", lambda: t)
    await store.set("k", "val", ttl_seconds=60)

    # Advance 61 s — past TTL
    monkeypatch.setattr("time.monotonic", lambda: t + 61)
    assert await store.get("k") is None


@pytest.mark.asyncio
async def test_no_ttl_never_expires(store, monkeypatch):
    """A key set without TTL survives arbitrarily long."""
    t = 1000.0
    monkeypatch.setattr("time.monotonic", lambda: t)
    await store.set("k", "forever")

    # Jump far into the future
    monkeypatch.setattr("time.monotonic", lambda: t + 999_999)
    assert await store.get("k") == "forever"


@pytest.mark.asyncio
async def test_overwrite_existing_key(store):
    """Setting a key twice returns the latest value."""
    await store.set("k", "old")
    await store.set("k", "new")
    assert await store.get("k") == "new"


@pytest.mark.asyncio
async def test_expired_key_deleted_from_data(store, monkeypatch):
    """Lazy cleanup: expired key is removed from _data on get()."""
    t = 1000.0
    monkeypatch.setattr("time.monotonic", lambda: t)
    await store.set("k", "val", ttl_seconds=10)

    # Advance past TTL
    monkeypatch.setattr("time.monotonic", lambda: t + 11)
    result = await store.get("k")

    assert result is None
    assert "k" not in store._data
