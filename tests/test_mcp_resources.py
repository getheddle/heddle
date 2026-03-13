"""Tests for loom.mcp.resources — workspace resource exposure."""
import os

import pytest

from loom.mcp.resources import WorkspaceResources


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace directory with some test files."""
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4 fake pdf content")
    (tmp_path / "data.json").write_text('{"key": "value"}')
    (tmp_path / "notes.txt").write_text("Some notes here.")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n fake png")
    # Also a subdirectory (should be excluded from listing).
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.txt").write_text("nested")
    return tmp_path


# ---------------------------------------------------------------------------
# list_resources
# ---------------------------------------------------------------------------


class TestListResources:
    def test_lists_all_files(self, workspace):
        wr = WorkspaceResources(workspace)
        resources = wr.list_resources()
        names = {r["name"] for r in resources}
        assert names == {"report.pdf", "data.json", "notes.txt", "image.png"}

    def test_excludes_directories(self, workspace):
        wr = WorkspaceResources(workspace)
        resources = wr.list_resources()
        for r in resources:
            assert "subdir" not in r["name"]

    def test_pattern_filter(self, workspace):
        wr = WorkspaceResources(workspace, patterns=["*.json", "*.txt"])
        resources = wr.list_resources()
        names = {r["name"] for r in resources}
        assert names == {"data.json", "notes.txt"}

    def test_uri_format(self, workspace):
        wr = WorkspaceResources(workspace, patterns=["*.json"])
        resources = wr.list_resources()
        assert resources[0]["uri"] == "workspace:///data.json"

    def test_mime_type_detection(self, workspace):
        wr = WorkspaceResources(workspace)
        resources = wr.list_resources()
        by_name = {r["name"]: r for r in resources}
        assert by_name["data.json"]["mimeType"] == "application/json"
        assert by_name["notes.txt"]["mimeType"] == "text/plain"

    def test_nonexistent_directory(self, tmp_path):
        wr = WorkspaceResources(tmp_path / "nonexistent")
        assert wr.list_resources() == []


# ---------------------------------------------------------------------------
# read_resource
# ---------------------------------------------------------------------------


class TestReadResource:
    def test_read_text_file(self, workspace):
        wr = WorkspaceResources(workspace)
        content, mime = wr.read_resource("workspace:///data.json")
        assert '"key"' in content
        assert mime == "application/json"

    def test_read_binary_file(self, workspace):
        wr = WorkspaceResources(workspace)
        content, mime = wr.read_resource("workspace:///image.png")
        # Binary files are base64-encoded.
        import base64
        decoded = base64.b64decode(content)
        assert decoded.startswith(b"\x89PNG")

    def test_path_traversal_blocked(self, workspace):
        wr = WorkspaceResources(workspace)
        with pytest.raises(ValueError, match="[Pp]ath traversal"):
            wr.read_resource("workspace:///../../etc/passwd")

    def test_nonexistent_file(self, workspace):
        wr = WorkspaceResources(workspace)
        with pytest.raises(FileNotFoundError):
            wr.read_resource("workspace:///missing.txt")

    def test_invalid_uri_scheme(self, workspace):
        wr = WorkspaceResources(workspace)
        with pytest.raises(ValueError, match="Invalid workspace URI"):
            wr.read_resource("file:///data.json")


# ---------------------------------------------------------------------------
# detect_changes / snapshot
# ---------------------------------------------------------------------------


class TestChangeDetection:
    def test_snapshot_then_no_changes(self, workspace):
        wr = WorkspaceResources(workspace)
        wr.snapshot()
        changed = wr.detect_changes()
        assert changed == []

    def test_new_file_detected(self, workspace):
        wr = WorkspaceResources(workspace)
        wr.snapshot()

        # Add a new file.
        (workspace / "new.txt").write_text("new content")

        changed = wr.detect_changes()
        assert "workspace:///new.txt" in changed

    def test_modified_file_detected(self, workspace):
        wr = WorkspaceResources(workspace)
        wr.snapshot()

        # Modify an existing file (touch to bump mtime).
        import time
        time.sleep(0.05)  # Ensure mtime changes.
        (workspace / "notes.txt").write_text("Updated notes.")

        changed = wr.detect_changes()
        assert "workspace:///notes.txt" in changed

    def test_pattern_filter_applies_to_changes(self, workspace):
        wr = WorkspaceResources(workspace, patterns=["*.json"])
        wr.snapshot()

        (workspace / "new.txt").write_text("should be ignored")
        (workspace / "new.json").write_text('{"new": true}')

        changed = wr.detect_changes()
        uris = set(changed)
        assert "workspace:///new.json" in uris
        assert "workspace:///new.txt" not in uris

    def test_first_detect_returns_all(self, workspace):
        """First call to detect_changes (no prior snapshot) returns all files."""
        wr = WorkspaceResources(workspace)
        changed = wr.detect_changes()
        assert len(changed) == 4  # All 4 files.


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------


class TestPatternMatching:
    def test_none_patterns_matches_all(self, workspace):
        wr = WorkspaceResources(workspace, patterns=None)
        resources = wr.list_resources()
        assert len(resources) == 4

    def test_multiple_patterns(self, workspace):
        wr = WorkspaceResources(workspace, patterns=["*.pdf", "*.png"])
        resources = wr.list_resources()
        names = {r["name"] for r in resources}
        assert names == {"report.pdf", "image.png"}

    def test_no_match(self, workspace):
        wr = WorkspaceResources(workspace, patterns=["*.xml"])
        resources = wr.list_resources()
        assert resources == []
