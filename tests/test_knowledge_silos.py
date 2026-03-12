"""Tests for knowledge silo loading and write-back."""
import json

import pytest

from loom.core.config import validate_worker_config
from loom.worker.knowledge import (
    _is_ignored,
    _load_folder_contents,
    _load_siloignore,
    apply_silo_updates,
    load_knowledge_silos,
)


# --- Folder loading ---


class TestLoadKnowledgeSilos:
    """Tests for load_knowledge_silos()."""

    def test_loads_folder_silo(self, tmp_path):
        """Loads text files from a folder silo into formatted sections."""
        silo_dir = tmp_path / "guides"
        silo_dir.mkdir()
        (silo_dir / "intro.md").write_text("# Intro\nHello world.")
        (silo_dir / "rules.txt").write_text("Rule 1: be good.")

        silos = [{"name": "test_silo", "type": "folder", "path": str(silo_dir)}]
        result = load_knowledge_silos(silos)

        assert "--- Knowledge Silo: test_silo ---" in result
        assert "# Intro" in result
        assert "Rule 1: be good." in result

    def test_skips_tool_type_silos(self, tmp_path):
        """Tool-type silos are not loaded by load_knowledge_silos."""
        silos = [{"name": "tool", "type": "tool", "provider": "x.y.Z", "config": {}}]
        result = load_knowledge_silos(silos)
        assert result == ""

    def test_skips_missing_folder(self, tmp_path):
        """Missing folder doesn't crash — logs warning and continues."""
        silos = [{"name": "missing", "type": "folder", "path": str(tmp_path / "nope")}]
        result = load_knowledge_silos(silos)
        assert result == ""

    def test_multiple_silos(self, tmp_path):
        """Multiple folder silos produce separate sections."""
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        (dir_a / "a.md").write_text("Content A")

        dir_b = tmp_path / "b"
        dir_b.mkdir()
        (dir_b / "b.md").write_text("Content B")

        silos = [
            {"name": "silo_a", "type": "folder", "path": str(dir_a)},
            {"name": "silo_b", "type": "folder", "path": str(dir_b)},
        ]
        result = load_knowledge_silos(silos)

        assert "silo_a" in result
        assert "silo_b" in result
        assert "Content A" in result
        assert "Content B" in result

    def test_empty_folder(self, tmp_path):
        """Empty folder produces no content."""
        silo_dir = tmp_path / "empty"
        silo_dir.mkdir()
        silos = [{"name": "empty", "type": "folder", "path": str(silo_dir)}]
        result = load_knowledge_silos(silos)
        assert result == ""


class TestLoadFolderContents:
    """Tests for _load_folder_contents()."""

    def test_reads_supported_extensions(self, tmp_path):
        """Reads .md, .txt, .yaml, .json, .csv, .toml files."""
        (tmp_path / "a.md").write_text("markdown")
        (tmp_path / "b.txt").write_text("text")
        (tmp_path / "c.yaml").write_text("yaml: true")
        (tmp_path / "d.json").write_text('{"key": 1}')
        (tmp_path / "e.csv").write_text("a,b\n1,2")
        (tmp_path / "f.toml").write_text("[section]\nkey = 1")

        result = _load_folder_contents(tmp_path)
        assert "markdown" in result
        assert "text" in result
        assert "yaml: true" in result
        assert '"key": 1' in result
        assert "a,b" in result
        assert "key = 1" in result

    def test_skips_binary_extensions(self, tmp_path):
        """Skips files with unsupported extensions."""
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "data.bin").write_bytes(b"\x00\x01")
        (tmp_path / "doc.md").write_text("visible")

        result = _load_folder_contents(tmp_path)
        assert "visible" in result
        assert "PNG" not in result

    def test_nested_directories(self, tmp_path):
        """Reads files from nested subdirectories."""
        sub = tmp_path / "sub" / "deep"
        sub.mkdir(parents=True)
        (sub / "nested.md").write_text("deep content")

        result = _load_folder_contents(tmp_path)
        assert "deep content" in result
        assert "sub/deep/nested.md" in result

    def test_deterministic_ordering(self, tmp_path):
        """Files are sorted for deterministic prompt ordering."""
        (tmp_path / "z_last.md").write_text("last")
        (tmp_path / "a_first.md").write_text("first")
        (tmp_path / "m_middle.md").write_text("middle")

        result = _load_folder_contents(tmp_path)
        a_pos = result.index("a_first.md")
        m_pos = result.index("m_middle.md")
        z_pos = result.index("z_last.md")
        assert a_pos < m_pos < z_pos

    def test_siloignore(self, tmp_path):
        """Files matching .siloignore patterns are skipped."""
        (tmp_path / ".siloignore").write_text("*.log\ndrafts/*\n# comment\n")
        (tmp_path / "keep.md").write_text("kept")
        (tmp_path / "debug.log").write_text("skipped")
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        (drafts / "wip.md").write_text("also skipped")

        result = _load_folder_contents(tmp_path)
        assert "kept" in result
        assert "skipped" not in result
        assert "also skipped" not in result


class TestSiloIgnore:
    """Tests for .siloignore loading."""

    def test_loads_patterns(self, tmp_path):
        (tmp_path / ".siloignore").write_text("*.log\n*.tmp\n")
        patterns = _load_siloignore(tmp_path)
        assert patterns == ["*.log", "*.tmp"]

    def test_skips_comments_and_blanks(self, tmp_path):
        (tmp_path / ".siloignore").write_text("# comment\n\n*.log\n  \n")
        patterns = _load_siloignore(tmp_path)
        assert patterns == ["*.log"]

    def test_no_siloignore_file(self, tmp_path):
        patterns = _load_siloignore(tmp_path)
        assert patterns == []


class TestIsIgnored:
    """Tests for _is_ignored() glob matching."""

    def test_matches_glob(self):
        assert _is_ignored("debug.log", ["*.log"]) is True

    def test_no_match(self):
        assert _is_ignored("main.py", ["*.log"]) is False

    def test_directory_pattern(self):
        assert _is_ignored("drafts/wip.md", ["drafts/*"]) is True

    def test_empty_patterns(self):
        assert _is_ignored("anything.md", []) is False


# --- Silo write-back ---


class TestApplySiloUpdates:
    """Tests for apply_silo_updates()."""

    def _writable_silos(self, tmp_path):
        silo_dir = tmp_path / "silo"
        silo_dir.mkdir()
        return [
            {"name": "my_silo", "type": "folder", "path": str(silo_dir), "permissions": "read_write"},
        ]

    def test_add_file(self, tmp_path):
        """Add action creates a new file in the silo."""
        silos = self._writable_silos(tmp_path)
        updates = [{"silo": "my_silo", "action": "add", "filename": "new.md", "content": "new content"}]

        apply_silo_updates(updates, silos)

        created = tmp_path / "silo" / "new.md"
        assert created.exists()
        assert created.read_text() == "new content"

    def test_modify_file(self, tmp_path):
        """Modify action updates an existing file."""
        silos = self._writable_silos(tmp_path)
        existing = tmp_path / "silo" / "existing.md"
        existing.write_text("old content")

        updates = [{"silo": "my_silo", "action": "modify", "filename": "existing.md", "content": "updated"}]
        apply_silo_updates(updates, silos)

        assert existing.read_text() == "updated"

    def test_modify_nonexistent_skipped(self, tmp_path):
        """Modify action on missing file is silently skipped."""
        silos = self._writable_silos(tmp_path)
        updates = [{"silo": "my_silo", "action": "modify", "filename": "nope.md", "content": "x"}]

        apply_silo_updates(updates, silos)
        assert not (tmp_path / "silo" / "nope.md").exists()

    def test_delete_file(self, tmp_path):
        """Delete action removes an existing file."""
        silos = self._writable_silos(tmp_path)
        target = tmp_path / "silo" / "delete_me.md"
        target.write_text("bye")

        updates = [{"silo": "my_silo", "action": "delete", "filename": "delete_me.md"}]
        apply_silo_updates(updates, silos)

        assert not target.exists()

    def test_delete_nonexistent_ok(self, tmp_path):
        """Delete on missing file doesn't crash."""
        silos = self._writable_silos(tmp_path)
        updates = [{"silo": "my_silo", "action": "delete", "filename": "nope.md"}]
        apply_silo_updates(updates, silos)  # No error

    def test_rejects_read_only_silo(self, tmp_path):
        """Updates targeting read-only silos are rejected."""
        silo_dir = tmp_path / "readonly"
        silo_dir.mkdir()
        silos = [{"name": "locked", "type": "folder", "path": str(silo_dir), "permissions": "read"}]

        updates = [{"silo": "locked", "action": "add", "filename": "hack.md", "content": "nope"}]
        apply_silo_updates(updates, silos)

        assert not (silo_dir / "hack.md").exists()

    def test_rejects_path_traversal_dotdot(self, tmp_path):
        """Filenames with .. are rejected."""
        silos = self._writable_silos(tmp_path)
        updates = [{"silo": "my_silo", "action": "add", "filename": "../escape.md", "content": "bad"}]

        apply_silo_updates(updates, silos)
        assert not (tmp_path / "escape.md").exists()

    def test_rejects_absolute_path(self, tmp_path):
        """Filenames starting with / are rejected."""
        silos = self._writable_silos(tmp_path)
        updates = [{"silo": "my_silo", "action": "add", "filename": "/etc/passwd", "content": "bad"}]
        apply_silo_updates(updates, silos)

    def test_rejects_unknown_silo(self, tmp_path):
        """Updates targeting non-existent silos are rejected."""
        silos = self._writable_silos(tmp_path)
        updates = [{"silo": "nonexistent", "action": "add", "filename": "x.md", "content": "y"}]
        apply_silo_updates(updates, silos)  # No error

    def test_unknown_action_skipped(self, tmp_path):
        """Unknown actions are silently skipped."""
        silos = self._writable_silos(tmp_path)
        updates = [{"silo": "my_silo", "action": "explode", "filename": "x.md", "content": "y"}]
        apply_silo_updates(updates, silos)  # No error

    def test_add_creates_subdirectories(self, tmp_path):
        """Add action creates parent directories if needed."""
        silos = self._writable_silos(tmp_path)
        updates = [{"silo": "my_silo", "action": "add", "filename": "sub/deep/new.md", "content": "deep"}]

        apply_silo_updates(updates, silos)
        assert (tmp_path / "silo" / "sub" / "deep" / "new.md").read_text() == "deep"


# --- Config validation ---


class TestKnowledgeSilosValidation:
    """Tests for knowledge_silos config validation."""

    def test_valid_folder_silo(self):
        config = {
            "name": "worker",
            "system_prompt": "test",
            "knowledge_silos": [
                {"name": "docs", "type": "folder", "path": "/tmp/docs"},
            ],
        }
        errors = validate_worker_config(config)
        assert errors == []

    def test_valid_tool_silo(self):
        config = {
            "name": "worker",
            "system_prompt": "test",
            "knowledge_silos": [
                {"name": "db", "type": "tool", "provider": "x.y.Z", "config": {"key": "val"}},
            ],
        }
        errors = validate_worker_config(config)
        assert errors == []

    def test_missing_name(self):
        config = {
            "name": "worker",
            "system_prompt": "test",
            "knowledge_silos": [{"type": "folder", "path": "/tmp"}],
        }
        errors = validate_worker_config(config)
        assert any("missing required key 'name'" in e for e in errors)

    def test_missing_type(self):
        config = {
            "name": "worker",
            "system_prompt": "test",
            "knowledge_silos": [{"name": "x"}],
        }
        errors = validate_worker_config(config)
        assert any("missing required key 'type'" in e for e in errors)

    def test_folder_missing_path(self):
        config = {
            "name": "worker",
            "system_prompt": "test",
            "knowledge_silos": [{"name": "x", "type": "folder"}],
        }
        errors = validate_worker_config(config)
        assert any("missing required key 'path'" in e for e in errors)

    def test_tool_missing_provider(self):
        config = {
            "name": "worker",
            "system_prompt": "test",
            "knowledge_silos": [{"name": "x", "type": "tool"}],
        }
        errors = validate_worker_config(config)
        assert any("missing required key 'provider'" in e for e in errors)

    def test_invalid_permissions(self):
        config = {
            "name": "worker",
            "system_prompt": "test",
            "knowledge_silos": [
                {"name": "x", "type": "folder", "path": "/tmp", "permissions": "admin"},
            ],
        }
        errors = validate_worker_config(config)
        assert any("'permissions' must be" in e for e in errors)

    def test_unknown_silo_type(self):
        config = {
            "name": "worker",
            "system_prompt": "test",
            "knowledge_silos": [{"name": "x", "type": "magic"}],
        }
        errors = validate_worker_config(config)
        assert any("unknown silo type" in e for e in errors)

    def test_silos_not_a_list(self):
        config = {
            "name": "worker",
            "system_prompt": "test",
            "knowledge_silos": "not a list",
        }
        errors = validate_worker_config(config)
        assert any("should be a list" in e for e in errors)
