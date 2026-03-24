"""Tests for loom.mcp.session_registry — file-based session markers."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

from loom.mcp.session_registry import (
    get_active_sessions,
    register_session,
    unregister_session,
)


class TestSessionRegistry:
    """Tests for register/unregister/get_active_sessions."""

    def test_register_creates_marker(self, tmp_path):
        with patch("loom.mcp.session_registry._SESSION_DIR", tmp_path):
            register_session("test-1", analyst="alice")

        marker = tmp_path / "test-1.json"
        assert marker.exists()
        data = json.loads(marker.read_text())
        assert data["session_id"] == "test-1"
        assert data["analyst"] == "alice"
        assert "last_active" in data

    def test_unregister_removes_marker(self, tmp_path):
        marker = tmp_path / "test-1.json"
        marker.write_text('{"session_id": "test-1"}')

        with patch("loom.mcp.session_registry._SESSION_DIR", tmp_path):
            unregister_session("test-1")

        assert not marker.exists()

    def test_unregister_missing_is_noop(self, tmp_path):
        with patch("loom.mcp.session_registry._SESSION_DIR", tmp_path):
            unregister_session("nonexistent")  # should not raise

    def test_get_active_sessions_returns_fresh(self, tmp_path):
        marker = tmp_path / "s1.json"
        marker.write_text(
            json.dumps({"session_id": "s1", "last_active": time.time()})
        )

        with patch("loom.mcp.session_registry._SESSION_DIR", tmp_path):
            active = get_active_sessions()

        assert len(active) == 1
        assert active[0]["session_id"] == "s1"

    def test_get_active_sessions_skips_stale(self, tmp_path):
        marker = tmp_path / "old.json"
        marker.write_text(
            json.dumps({"session_id": "old", "last_active": time.time() - 7200})
        )

        with patch("loom.mcp.session_registry._SESSION_DIR", tmp_path):
            active = get_active_sessions()

        assert len(active) == 0

    def test_get_active_sessions_empty_dir(self, tmp_path):
        with patch("loom.mcp.session_registry._SESSION_DIR", tmp_path):
            active = get_active_sessions()

        assert active == []

    def test_get_active_sessions_no_dir(self, tmp_path):
        missing = tmp_path / "nonexistent"
        with patch("loom.mcp.session_registry._SESSION_DIR", missing):
            active = get_active_sessions()

        assert active == []

    def test_get_active_sessions_skips_invalid_json(self, tmp_path):
        (tmp_path / "bad.json").write_text("not json")
        (tmp_path / "good.json").write_text(
            json.dumps({"session_id": "g", "last_active": time.time()})
        )

        with patch("loom.mcp.session_registry._SESSION_DIR", tmp_path):
            active = get_active_sessions()

        assert len(active) == 1
        assert active[0]["session_id"] == "g"
