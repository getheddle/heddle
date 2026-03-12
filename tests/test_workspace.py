"""Tests for WorkspaceManager (file-ref resolution, path safety, JSON I/O)."""
import json

import pytest

from loom.core.workspace import WorkspaceManager


@pytest.fixture
def workspace(tmp_path):
    """Provide an isolated temporary workspace directory."""
    return tmp_path


@pytest.fixture
def ws(workspace):
    """Create a WorkspaceManager pointing at the temporary workspace."""
    return WorkspaceManager(workspace)


# --- resolve() ---

class TestResolve:
    def test_resolve_valid_file(self, ws, workspace):
        """resolve() returns an absolute path for a valid file."""
        (workspace / "report.pdf").write_bytes(b"fake pdf")
        path = ws.resolve("report.pdf")
        assert path.is_absolute()
        assert path.name == "report.pdf"

    def test_resolve_subdirectory(self, ws, workspace):
        """resolve() works with files in subdirectories."""
        subdir = workspace / "subdir"
        subdir.mkdir()
        (subdir / "data.json").write_text("{}")
        path = ws.resolve("subdir/data.json")
        assert path.name == "data.json"

    def test_resolve_path_traversal_rejected(self, ws):
        """resolve() rejects path traversal attempts."""
        with pytest.raises(ValueError, match="Path traversal"):
            ws.resolve("../../etc/passwd")

    def test_resolve_file_not_found(self, ws):
        """resolve() raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError, match="File not found"):
            ws.resolve("nonexistent.pdf")


# --- read_json() ---

class TestReadJson:
    def test_read_json(self, ws, workspace):
        """read_json() reads and parses a JSON file."""
        data = {"key": "value", "count": 42}
        (workspace / "data.json").write_text(json.dumps(data))
        result = ws.read_json("data.json")
        assert result == data

    def test_read_json_invalid(self, ws, workspace):
        """read_json() raises JSONDecodeError for invalid JSON."""
        (workspace / "bad.json").write_text("not json")
        with pytest.raises(json.JSONDecodeError):
            ws.read_json("bad.json")

    def test_read_json_missing_file(self, ws):
        """read_json() raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            ws.read_json("missing.json")


# --- read_text() ---

class TestReadText:
    def test_read_text(self, ws, workspace):
        """read_text() returns file contents as string."""
        (workspace / "note.txt").write_text("hello world")
        assert ws.read_text("note.txt") == "hello world"


# --- write_json() ---

class TestWriteJson:
    def test_write_json(self, ws, workspace):
        """write_json() writes JSON and returns the path."""
        data = {"result": "success"}
        path = ws.write_json("output.json", data)
        assert path == workspace / "output.json"
        assert json.loads(path.read_text()) == data

    def test_write_json_pretty_printed(self, ws, workspace):
        """write_json() writes indented JSON."""
        ws.write_json("formatted.json", {"a": 1})
        text = (workspace / "formatted.json").read_text()
        assert "  " in text  # indented
