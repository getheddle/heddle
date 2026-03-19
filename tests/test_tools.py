"""Tests for ToolProvider abstraction and dynamic loading."""

import json

import pytest

from loom.worker.tools import (
    MAX_TOOL_ROUNDS,
    SyncToolProvider,
    ToolProvider,
    load_tool_provider,
)

# ---------------------------------------------------------------------------
# Concrete test implementations
# ---------------------------------------------------------------------------


class DummyTool(ToolProvider):
    """Async tool for testing."""

    def __init__(self, name: str = "dummy", description: str = "A dummy tool"):
        self._name = name
        self._description = description

    def get_definition(self) -> dict:
        return {
            "name": self._name,
            "description": self._description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        }

    async def execute(self, arguments: dict) -> str:
        return json.dumps({"result": f"found: {arguments.get('query', '')}"})


class DummySyncTool(SyncToolProvider):
    """Synchronous tool for testing thread pool offloading."""

    def __init__(self, name: str = "sync_dummy"):
        self._name = name

    def get_definition(self) -> dict:
        return {
            "name": self._name,
            "description": "Sync dummy tool",
            "parameters": {"type": "object", "properties": {}},
        }

    def execute_sync(self, arguments: dict) -> str:
        return json.dumps({"sync": True, "args": arguments})


# ---------------------------------------------------------------------------
# ToolProvider ABC tests
# ---------------------------------------------------------------------------


class TestToolProvider:
    """Tests for the ToolProvider interface."""

    def test_cannot_instantiate_abc(self):
        """ToolProvider is abstract — can't instantiate directly."""
        with pytest.raises(TypeError):
            ToolProvider()

    def test_get_definition_returns_dict(self):
        tool = DummyTool()
        defn = tool.get_definition()
        assert isinstance(defn, dict)
        assert "name" in defn
        assert "description" in defn
        assert "parameters" in defn

    @pytest.mark.asyncio
    async def test_execute_returns_string(self):
        tool = DummyTool()
        result = await tool.execute({"query": "test"})
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["result"] == "found: test"

    def test_constructor_kwargs_passed(self):
        tool = DummyTool(name="custom", description="Custom tool")
        defn = tool.get_definition()
        assert defn["name"] == "custom"
        assert defn["description"] == "Custom tool"


# ---------------------------------------------------------------------------
# SyncToolProvider tests
# ---------------------------------------------------------------------------


class TestSyncToolProvider:
    """Tests for the synchronous tool convenience base."""

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            SyncToolProvider()

    @pytest.mark.asyncio
    async def test_execute_offloads_to_thread_pool(self):
        """execute() should call execute_sync() in a thread pool."""
        tool = DummySyncTool()
        result = await tool.execute({"key": "value"})
        parsed = json.loads(result)
        assert parsed["sync"] is True
        assert parsed["args"] == {"key": "value"}

    def test_execute_sync_is_callable(self):
        tool = DummySyncTool()
        result = tool.execute_sync({})
        parsed = json.loads(result)
        assert parsed["sync"] is True


# ---------------------------------------------------------------------------
# Dynamic loading tests
# ---------------------------------------------------------------------------


class TestLoadToolProvider:
    """Tests for load_tool_provider() dynamic import."""

    def test_load_valid_tool(self):
        """Load a tool from this test module by class path."""
        tool = load_tool_provider(
            "tests.test_tools.DummyTool",
            {"name": "loaded", "description": "Loaded tool"},
        )
        assert isinstance(tool, ToolProvider)
        assert tool.get_definition()["name"] == "loaded"

    def test_load_sync_tool(self):
        tool = load_tool_provider(
            "tests.test_tools.DummySyncTool",
            {"name": "sync_loaded"},
        )
        assert isinstance(tool, SyncToolProvider)

    def test_load_no_dot_raises(self):
        with pytest.raises(ImportError, match="fully qualified"):
            load_tool_provider("NoDots", {})

    def test_load_bad_module_raises(self):
        with pytest.raises(ImportError):
            load_tool_provider("nonexistent.module.Tool", {})

    def test_load_bad_class_raises(self):
        with pytest.raises(AttributeError, match="not found"):
            load_tool_provider("tests.test_tools.NonexistentClass", {})

    def test_load_non_tool_raises(self):
        """Loading a class that isn't a ToolProvider should raise TypeError."""
        with pytest.raises(TypeError, match="not a ToolProvider"):
            load_tool_provider("tests.test_tools.NotATool", {})


# A non-ToolProvider class for the test above
class NotATool:
    pass


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    def test_max_tool_rounds_is_reasonable(self):
        assert MAX_TOOL_ROUNDS >= 5
        assert MAX_TOOL_ROUNDS <= 50
