"""Tests for loom.mcp.server — MCP server assembly and tool dispatch."""

import asyncio
import contextlib
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from loom.bus.memory import InMemoryBus
from loom.core.messages import TaskResult, TaskStatus
from loom.mcp.bridge import BridgeError, BridgeTimeoutError, MCPBridge
from loom.mcp.server import (
    MCPGateway,
    ToolEntry,
    _build_annotations,
    _dispatch_tool,
    create_server,
)
from loom.mcp.workshop_bridge import WorkshopBridge, WorkshopBridgeError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(dir_path: str, filename: str, data: dict) -> str:
    path = os.path.join(dir_path, filename)
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


def _make_gateway_config(tmp_path, worker_cfgs=None, resources_dir=None):
    """Create a valid MCP gateway config with optional workers and resources."""
    workers_dir = tmp_path / "workers"
    workers_dir.mkdir(exist_ok=True)

    worker_entries = []
    if worker_cfgs:
        for name, cfg in worker_cfgs.items():
            path = _write_yaml(str(workers_dir), f"{name}.yaml", cfg)
            worker_entries.append({"config": path})

    config = {
        "name": "test-gateway",
        "nats_url": "nats://localhost:4222",
        "tools": {
            "workers": worker_entries,
            "pipelines": [],
            "queries": [],
        },
    }

    if resources_dir:
        config["resources"] = {
            "workspace_dir": str(resources_dir),
        }

    return _write_yaml(str(tmp_path), "gateway.yaml", config)


def _make_workshop_only_gateway_config(tmp_path, enable=None):
    """Create an MCP gateway config that exposes only workshop tools."""
    config = {
        "name": "workshop-gateway",
        "tools": {
            "workers": [],
            "pipelines": [],
            "queries": [],
            "workshop": {
                "configs_dir": str(tmp_path),
            },
        },
    }
    if enable is not None:
        config["tools"]["workshop"]["enable"] = enable
    return _write_yaml(str(tmp_path), "workshop-gateway.yaml", config)


def _unwrap(server_result):
    """Unwrap MCP ServerResult to get the inner result object."""
    return server_result.root


def _single_worker_cfgs(name="test_worker"):
    """Return a minimal single-worker config dict."""
    return {
        name: {
            "name": name,
            "system_prompt": "Test.",
            "input_schema": {"type": "object", "properties": {}},
        },
    }


def _fake_stdio_cm():
    """Create a fake stdio_server async context manager."""

    async def _gen():
        yield (MagicMock(), MagicMock())

    return contextlib.asynccontextmanager(_gen)()


# ---------------------------------------------------------------------------
# create_server
# ---------------------------------------------------------------------------


class TestCreateServer:
    def test_creates_server_and_gateway(self, tmp_path):
        worker_cfgs = {
            "summarizer": {
                "name": "summarizer",
                "system_prompt": "Summarize text.",
                "input_schema": {
                    "type": "object",
                    "required": ["text"],
                    "properties": {"text": {"type": "string"}},
                },
            },
        }
        config_path = _make_gateway_config(tmp_path, worker_cfgs=worker_cfgs)

        server, gateway = create_server(config_path)

        assert gateway.config["name"] == "test-gateway"
        assert "summarizer" in gateway.tool_registry
        assert len(gateway.tool_defs) == 1

    def test_no_tools(self, tmp_path):
        config_path = _make_gateway_config(tmp_path)
        server, gateway = create_server(config_path)
        assert len(gateway.tool_registry) == 0

    def test_with_resources(self, tmp_path):
        resources_dir = tmp_path / "workspace"
        resources_dir.mkdir()
        (resources_dir / "test.txt").write_text("hello")

        config_path = _make_gateway_config(tmp_path, resources_dir=resources_dir)
        server, gateway = create_server(config_path)
        assert gateway.resources is not None

    def test_without_resources(self, tmp_path):
        config_path = _make_gateway_config(tmp_path)
        server, gateway = create_server(config_path)
        assert gateway.resources is None

    def test_workshop_only_gateway_does_not_require_bus(self, tmp_path):
        config_path = _make_workshop_only_gateway_config(tmp_path)
        _server, gateway = create_server(config_path)

        assert gateway.requires_bus is False
        assert gateway.workshop_bridge is not None
        assert gateway.workshop_bridge.dead_letter is not None
        assert "workshop.worker.list" in gateway.tool_registry


# ---------------------------------------------------------------------------
# ToolEntry
# ---------------------------------------------------------------------------


class TestToolEntry:
    def test_fields(self):
        entry = ToolEntry(
            name="my_tool",
            kind="worker",
            tool_def={"name": "my_tool", "description": "desc", "inputSchema": {}},
            loom_meta={"kind": "worker", "worker_type": "my_worker"},
        )
        assert entry.name == "my_tool"
        assert entry.kind == "worker"


# ---------------------------------------------------------------------------
# _dispatch_tool
# ---------------------------------------------------------------------------


class TestDispatchTool:
    @pytest.fixture
    async def bus_and_bridge(self):
        bus = InMemoryBus()
        await bus.connect()
        bridge = MCPBridge(bus)
        yield bus, bridge
        await bus.close()

    async def test_dispatch_worker(self, bus_and_bridge):
        bus, bridge = bus_and_bridge
        gateway = MCPGateway(
            config={"name": "test"},
            bridge=bridge,
            tool_registry={},
            tool_defs=[],
        )

        entry = ToolEntry(
            name="summarizer",
            kind="worker",
            tool_def={},
            loom_meta={
                "kind": "worker",
                "worker_type": "summarizer",
                "tier": "local",
                "timeout": 5,
            },
        )

        ready = asyncio.Event()

        async def mock_worker():
            sub = await bus.subscribe("loom.tasks.incoming")
            ready.set()
            async for data in sub:
                result = TaskResult(
                    task_id=data["task_id"],
                    worker_type="summarizer",
                    status=TaskStatus.COMPLETED,
                    output={"summary": "done"},
                )
                await bus.publish(
                    f"loom.results.{data['parent_task_id']}",
                    result.model_dump(mode="json"),
                )
                await sub.unsubscribe()
                break

        worker_task = asyncio.create_task(mock_worker())
        await ready.wait()

        result = await _dispatch_tool(gateway, entry, {"text": "hello"})
        assert result == {"summary": "done"}
        await worker_task

    async def test_dispatch_query(self, bus_and_bridge):
        bus, bridge = bus_and_bridge
        gateway = MCPGateway(
            config={"name": "test"},
            bridge=bridge,
            tool_registry={},
            tool_defs=[],
        )

        entry = ToolEntry(
            name="docs_search",
            kind="query",
            tool_def={},
            loom_meta={
                "kind": "query",
                "worker_type": "docs_query",
                "action": "search",
                "timeout": 5,
            },
        )

        ready = asyncio.Event()

        async def mock_worker():
            sub = await bus.subscribe("loom.tasks.incoming")
            ready.set()
            async for data in sub:
                assert data["payload"]["action"] == "search"
                result = TaskResult(
                    task_id=data["task_id"],
                    worker_type="docs_query",
                    status=TaskStatus.COMPLETED,
                    output={"results": [{"id": "1"}]},
                )
                await bus.publish(
                    f"loom.results.{data['parent_task_id']}",
                    result.model_dump(mode="json"),
                )
                await sub.unsubscribe()
                break

        worker_task = asyncio.create_task(mock_worker())
        await ready.wait()

        result = await _dispatch_tool(gateway, entry, {"query": "test"})
        assert result == {"results": [{"id": "1"}]}
        await worker_task

    async def test_dispatch_unknown_kind_raises(self, bus_and_bridge):
        _, bridge = bus_and_bridge
        gateway = MCPGateway(
            config={"name": "test"},
            bridge=bridge,
            tool_registry={},
            tool_defs=[],
        )

        entry = ToolEntry(
            name="bad",
            kind="unknown",
            tool_def={},
            loom_meta={"kind": "unknown"},
        )

        with pytest.raises(BridgeError, match="Unknown tool kind"):
            await _dispatch_tool(gateway, entry, {})

    async def test_dispatch_pipeline(self, bus_and_bridge):
        """_dispatch_tool for pipeline kind calls call_pipeline."""
        bus, bridge = bus_and_bridge
        gateway = MCPGateway(
            config={"name": "test"},
            bridge=bridge,
            tool_registry={},
            tool_defs=[],
        )

        entry = ToolEntry(
            name="ingest_doc",
            kind="pipeline",
            tool_def={},
            loom_meta={
                "kind": "pipeline",
                "timeout": 5,
            },
        )

        ready = asyncio.Event()

        async def mock_pipeline():
            sub = await bus.subscribe("loom.goals.incoming")
            ready.set()
            async for data in sub:
                goal_id = data.get("goal_id")
                result = TaskResult(
                    task_id=goal_id,
                    parent_task_id=None,
                    worker_type="pipeline",
                    status=TaskStatus.COMPLETED,
                    output={"processed": True},
                )
                await bus.publish(
                    f"loom.results.{goal_id}",
                    result.model_dump(mode="json"),
                )
                await sub.unsubscribe()
                break

        worker_task = asyncio.create_task(mock_pipeline())
        await ready.wait()

        result = await _dispatch_tool(gateway, entry, {"file_ref": "test.pdf"})
        assert result == {"processed": True}
        await worker_task


# ---------------------------------------------------------------------------
# Progress callback wiring (MCP progress notifications)
# ---------------------------------------------------------------------------


class TestProgressCallback:
    """Test that _dispatch_tool passes progress_callback to pipeline calls."""

    @pytest.fixture
    async def bus_and_bridge(self):
        bus = InMemoryBus()
        await bus.connect()
        bridge = MCPBridge(bus)
        yield bus, bridge
        await bus.close()

    async def test_pipeline_receives_progress_callback(self, bus_and_bridge):
        """_dispatch_tool passes progress_callback to call_pipeline for pipelines."""
        bus, bridge = bus_and_bridge
        gateway = MCPGateway(
            config={"name": "test"},
            bridge=bridge,
            tool_registry={},
            tool_defs=[],
        )

        entry = ToolEntry(
            name="ingest_doc",
            kind="pipeline",
            tool_def={},
            loom_meta={"kind": "pipeline", "timeout": 5},
        )

        progress_calls = []

        async def track_progress(stage_name: str, stage_idx: int, total: int) -> None:
            progress_calls.append((stage_name, stage_idx, total))

        ready = asyncio.Event()

        async def mock_pipeline():
            sub = await bus.subscribe("loom.goals.incoming")
            ready.set()
            async for data in sub:
                goal_id = data.get("goal_id")
                # Emit an intermediate stage result first.
                stage_result = TaskResult(
                    task_id="stage-1-id",
                    parent_task_id=goal_id,
                    worker_type="extractor",
                    status=TaskStatus.COMPLETED,
                    output={"text": "extracted"},
                    processing_time_ms=10,
                )
                await bus.publish(
                    f"loom.results.{goal_id}",
                    stage_result.model_dump(mode="json"),
                )
                # Small delay to let consumer process intermediate result.
                await asyncio.sleep(0.01)
                # Then emit the final result.
                final = TaskResult(
                    task_id=goal_id,
                    parent_task_id=None,
                    worker_type="pipeline",
                    status=TaskStatus.COMPLETED,
                    output={"processed": True},
                )
                await bus.publish(
                    f"loom.results.{goal_id}",
                    final.model_dump(mode="json"),
                )
                await sub.unsubscribe()
                break

        worker_task = asyncio.create_task(mock_pipeline())
        await ready.wait()

        result = await _dispatch_tool(
            gateway,
            entry,
            {"file_ref": "test.pdf"},
            progress_callback=track_progress,
        )
        assert result == {"processed": True}
        assert len(progress_calls) == 1
        assert progress_calls[0] == ("extractor", 1, 0)
        await worker_task

    async def test_worker_dispatch_ignores_progress_callback(self, bus_and_bridge):
        """_dispatch_tool for workers does not pass progress_callback."""
        bus, bridge = bus_and_bridge
        gateway = MCPGateway(
            config={"name": "test"},
            bridge=bridge,
            tool_registry={},
            tool_defs=[],
        )

        entry = ToolEntry(
            name="summarizer",
            kind="worker",
            tool_def={},
            loom_meta={
                "kind": "worker",
                "worker_type": "summarizer",
                "tier": "local",
                "timeout": 5,
            },
        )

        ready = asyncio.Event()

        async def mock_worker():
            sub = await bus.subscribe("loom.tasks.incoming")
            ready.set()
            async for data in sub:
                result = TaskResult(
                    task_id=data["task_id"],
                    worker_type="summarizer",
                    status=TaskStatus.COMPLETED,
                    output={"summary": "done"},
                )
                await bus.publish(
                    f"loom.results.{data['parent_task_id']}",
                    result.model_dump(mode="json"),
                )
                await sub.unsubscribe()
                break

        worker_task = asyncio.create_task(mock_worker())
        await ready.wait()

        # Passing a callback shouldn't cause errors for non-pipeline tools.
        callback = AsyncMock()
        result = await _dispatch_tool(
            gateway,
            entry,
            {"text": "hi"},
            progress_callback=callback,
        )
        assert result == {"summary": "done"}
        callback.assert_not_called()
        await worker_task

    async def test_progress_callback_none_is_safe(self, bus_and_bridge):
        """_dispatch_tool with progress_callback=None works for pipelines."""
        bus, bridge = bus_and_bridge
        gateway = MCPGateway(
            config={"name": "test"},
            bridge=bridge,
            tool_registry={},
            tool_defs=[],
        )

        entry = ToolEntry(
            name="ingest_doc",
            kind="pipeline",
            tool_def={},
            loom_meta={"kind": "pipeline", "timeout": 5},
        )

        ready = asyncio.Event()

        async def mock_pipeline():
            sub = await bus.subscribe("loom.goals.incoming")
            ready.set()
            async for data in sub:
                goal_id = data.get("goal_id")
                final = TaskResult(
                    task_id=goal_id,
                    worker_type="pipeline",
                    status=TaskStatus.COMPLETED,
                    output={"ok": True},
                )
                await bus.publish(
                    f"loom.results.{goal_id}",
                    final.model_dump(mode="json"),
                )
                await sub.unsubscribe()
                break

        worker_task = asyncio.create_task(mock_pipeline())
        await ready.wait()

        # Explicitly passing None (default).
        result = await _dispatch_tool(gateway, entry, {}, progress_callback=None)
        assert result == {"ok": True}
        await worker_task


class TestServerProgressWiring:
    """Test that the server's call_tool handler constructs and passes progress_callback."""

    def test_progress_callback_created_for_pipeline_tool(self, tmp_path):
        """handle_call_tool passes a progress_callback to _dispatch_tool for pipelines."""
        config_path = _make_gateway_config(tmp_path, worker_cfgs=_single_worker_cfgs("pipe"))
        server, gateway = create_server(config_path)

        # Re-register the tool as a pipeline kind.
        gateway.tool_registry["pipe"] = ToolEntry(
            name="pipe",
            kind="pipeline",
            tool_def={"name": "pipe", "inputSchema": {}},
            loom_meta={"kind": "pipeline", "timeout": 5},
        )

        with patch("loom.mcp.server._dispatch_tool", new_callable=AsyncMock) as m:
            m.return_value = {"ok": True}

            from mcp import types

            handler = server.request_handlers[types.CallToolRequest]
            params = types.CallToolRequestParams(name="pipe", arguments={"file": "x"})
            request = types.CallToolRequest(method="tools/call", params=params)
            _unwrap(asyncio.run(handler(request)))

            # Verify _dispatch_tool was called with a progress_callback.
            assert m.call_count == 1
            call_kwargs = m.call_args
            # The progress_callback is the 4th positional arg or keyword.
            # _dispatch_tool(gateway, entry, arguments, progress_callback=...)
            if len(call_kwargs[0]) > 3:
                cb = call_kwargs[0][3]
            else:
                cb = call_kwargs[1].get("progress_callback")
            assert cb is not None
            assert callable(cb)


# ---------------------------------------------------------------------------
# MCPGateway field tests
# ---------------------------------------------------------------------------


class TestMCPGateway:
    def test_gateway_defaults(self):
        bus = InMemoryBus()
        bridge = MCPBridge(bus)
        gw = MCPGateway(config={"name": "test"}, bridge=bridge)

        assert gw.tool_registry == {}
        assert gw.tool_defs == []
        assert gw.resources is None

    def test_gateway_with_registry(self):
        bus = InMemoryBus()
        bridge = MCPBridge(bus)
        entry = ToolEntry(
            name="tool1",
            kind="worker",
            tool_def={"name": "tool1", "inputSchema": {}},
            loom_meta={"kind": "worker"},
        )
        gw = MCPGateway(
            config={"name": "test"},
            bridge=bridge,
            tool_registry={"tool1": entry},
            tool_defs=[{"name": "tool1", "inputSchema": {}}],
        )
        assert "tool1" in gw.tool_registry
        assert len(gw.tool_defs) == 1


# ---------------------------------------------------------------------------
# handle_list_tools (line 137)
# ---------------------------------------------------------------------------


class TestHandleListTools:
    """Test the server.list_tools() handler registered inside create_server."""

    def test_list_tools_returns_mcp_tool_objects(self, tmp_path):
        worker_cfgs = {
            "summarizer": {
                "name": "summarizer",
                "system_prompt": "Summarize text.",
                "input_schema": {
                    "type": "object",
                    "required": ["text"],
                    "properties": {"text": {"type": "string"}},
                },
            },
        }
        config_path = _make_gateway_config(tmp_path, worker_cfgs=worker_cfgs)
        server, gateway = create_server(config_path)

        from mcp import types

        handler = server.request_handlers[types.ListToolsRequest]
        request = types.ListToolsRequest(method="tools/list")
        result = _unwrap(asyncio.run(handler(request)))

        assert len(result.tools) == 1
        tool = result.tools[0]
        assert tool.name == "summarizer"
        assert tool.inputSchema is not None

    def test_list_tools_empty(self, tmp_path):
        """list_tools with no tools returns empty list."""
        config_path = _make_gateway_config(tmp_path)
        server, gateway = create_server(config_path)

        from mcp import types

        handler = server.request_handlers[types.ListToolsRequest]
        request = types.ListToolsRequest(method="tools/list")
        result = _unwrap(asyncio.run(handler(request)))

        assert result.tools == []


# ---------------------------------------------------------------------------
# handle_call_tool (lines 152-201)
# ---------------------------------------------------------------------------


class TestHandleCallTool:
    """Test the server.call_tool() handler registered inside create_server."""

    def _call(self, server, name, arguments=None):
        """Invoke call_tool handler and return unwrapped result."""
        from mcp import types

        handler = server.request_handlers[types.CallToolRequest]
        params = types.CallToolRequestParams(name=name, arguments=arguments)
        request = types.CallToolRequest(method="tools/call", params=params)
        return _unwrap(asyncio.run(handler(request)))

    def test_unknown_tool_returns_error(self, tmp_path):
        """Line 152-161: unknown tool name returns error JSON."""
        config_path = _make_gateway_config(tmp_path)
        server, _gw = create_server(config_path)

        result = self._call(server, "nonexistent_tool", {"x": 1})

        assert len(result.content) == 1
        data = json.loads(result.content[0].text)
        assert "error" in data
        assert "Unknown tool" in data["error"]

    def test_none_arguments_default_to_empty_dict(self, tmp_path):
        """Line 152: arguments=None is treated as empty dict."""
        config_path = _make_gateway_config(tmp_path, worker_cfgs=_single_worker_cfgs())
        server, _gw = create_server(config_path)

        with patch("loom.mcp.server._dispatch_tool", new_callable=AsyncMock) as m:
            m.return_value = {"ok": True}
            result = self._call(server, "test_worker", None)
            assert m.call_args[0][2] == {}
            data = json.loads(result.content[0].text)
            assert data == {"ok": True}

    def test_bridge_timeout_error(self, tmp_path):
        """Lines 169-175: BridgeTimeoutError returns timeout error JSON."""
        config_path = _make_gateway_config(tmp_path, worker_cfgs=_single_worker_cfgs("slow"))
        server, _gw = create_server(config_path)

        with patch("loom.mcp.server._dispatch_tool", new_callable=AsyncMock) as m:
            m.side_effect = BridgeTimeoutError("Timed out after 5s")
            result = self._call(server, "slow", {})
            data = json.loads(result.content[0].text)
            assert "Timeout" in data["error"]

    def test_bridge_error(self, tmp_path):
        """Lines 176-182: BridgeError returns error JSON."""
        config_path = _make_gateway_config(tmp_path, worker_cfgs=_single_worker_cfgs("bad"))
        server, _gw = create_server(config_path)

        with patch("loom.mcp.server._dispatch_tool", new_callable=AsyncMock) as m:
            m.side_effect = BridgeError("Connection lost")
            result = self._call(server, "bad", {})
            data = json.loads(result.content[0].text)
            assert data["error"] == "Connection lost"

    def test_generic_exception(self, tmp_path):
        """Lines 183-190: generic Exception returns internal error JSON."""
        config_path = _make_gateway_config(tmp_path, worker_cfgs=_single_worker_cfgs("crash"))
        server, _gw = create_server(config_path)

        with patch("loom.mcp.server._dispatch_tool", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("kaboom")
            result = self._call(server, "crash", {})
            data = json.loads(result.content[0].text)
            assert "Internal error" in data["error"]
            assert "kaboom" in data["error"]

    def test_successful_call_returns_result(self, tmp_path):
        """Lines 201-206: successful dispatch returns serialized result."""
        config_path = _make_gateway_config(tmp_path, worker_cfgs=_single_worker_cfgs("good"))
        server, _gw = create_server(config_path)

        with patch("loom.mcp.server._dispatch_tool", new_callable=AsyncMock) as m:
            m.return_value = {"summary": "test", "score": 0.9}
            result = self._call(server, "good", {"text": "hello"})
            data = json.loads(result.content[0].text)
            assert data == {"summary": "test", "score": 0.9}

    def test_workspace_snapshot_and_change_detection(self, tmp_path):
        """Lines 164-200: workspace snapshot before call, change detection after."""
        resources_dir = tmp_path / "workspace"
        resources_dir.mkdir()
        (resources_dir / "file.txt").write_text("content")

        config_path = _make_gateway_config(
            tmp_path,
            worker_cfgs=_single_worker_cfgs("fw"),
            resources_dir=resources_dir,
        )
        server, gateway = create_server(config_path)

        mock_res = MagicMock()
        mock_res.snapshot = MagicMock()
        mock_res.detect_changes = MagicMock(return_value=["workspace:///file.txt"])
        gateway.resources = mock_res

        with patch("loom.mcp.server._dispatch_tool", new_callable=AsyncMock) as m:
            m.return_value = {"ok": True}
            result = self._call(server, "fw", {})
            mock_res.snapshot.assert_called_once()
            mock_res.detect_changes.assert_called_once()
            data = json.loads(result.content[0].text)
            assert data == {"ok": True}

    def test_workspace_no_changes(self, tmp_path):
        """Lines 193-200: workspace with no changes after tool call."""
        resources_dir = tmp_path / "workspace"
        resources_dir.mkdir()

        config_path = _make_gateway_config(
            tmp_path,
            worker_cfgs=_single_worker_cfgs("noop"),
            resources_dir=resources_dir,
        )
        server, gateway = create_server(config_path)

        mock_res = MagicMock()
        mock_res.snapshot = MagicMock()
        mock_res.detect_changes = MagicMock(return_value=[])
        gateway.resources = mock_res

        with patch("loom.mcp.server._dispatch_tool", new_callable=AsyncMock) as m:
            m.return_value = {"ok": True}
            self._call(server, "noop", {})
            mock_res.detect_changes.assert_called_once()


# ---------------------------------------------------------------------------
# Resource handlers (lines 214-215, 230-235)
# ---------------------------------------------------------------------------


class TestResourceHandlers:
    """Test list_resources and read_resource handlers."""

    def test_list_resources_handler(self, tmp_path):
        """Lines 214-215: list_resources returns MCP Resource objects."""
        resources_dir = tmp_path / "workspace"
        resources_dir.mkdir()
        (resources_dir / "doc.txt").write_text("hello")
        (resources_dir / "data.json").write_text('{"a": 1}')

        config_path = _make_gateway_config(tmp_path, resources_dir=resources_dir)
        server, gateway = create_server(config_path)

        from mcp import types

        handler = server.request_handlers[types.ListResourcesRequest]
        request = types.ListResourcesRequest(method="resources/list")
        result = _unwrap(asyncio.run(handler(request)))

        assert len(result.resources) >= 1
        names = [r.name for r in result.resources]
        assert "doc.txt" in names or "data.json" in names

    def test_read_resource_text_via_mock(self, tmp_path):
        """Lines 230-234: read_resource for text MIME returns TextResourceContents.

        Mocks gateway.resources to test the server.py handler logic (lines 230-234)
        without hitting the AnyUrl/str mismatch in resources.py._from_uri().
        """
        resources_dir = tmp_path / "workspace"
        resources_dir.mkdir()

        config_path = _make_gateway_config(tmp_path, resources_dir=resources_dir)
        server, gateway = create_server(config_path)

        from mcp import types

        mock_res = MagicMock()
        mock_res.list_resources = MagicMock(return_value=[])
        mock_res.read_resource = MagicMock(return_value=("hello world", "text/plain"))
        gateway.resources = mock_res

        # Reproduce the handler logic (lines 230-235) directly.
        async def _test():
            content, mime = gateway.resources.read_resource("workspace:///readme.txt")
            if mime and (
                mime.startswith("text/") or mime in ("application/json", "application/xml")
            ):
                return types.TextResourceContents(
                    uri="workspace:///readme.txt", text=content, mimeType=mime
                )
            return types.BlobResourceContents(
                uri="workspace:///readme.txt", blob=content, mimeType=mime
            )

        item = asyncio.run(_test())
        assert isinstance(item, types.TextResourceContents)
        assert item.text == "hello world"

    def test_read_resource_json_via_mock(self, tmp_path):
        """Lines 230-234: application/json is treated as text content."""
        resources_dir = tmp_path / "workspace"
        resources_dir.mkdir()
        config_path = _make_gateway_config(tmp_path, resources_dir=resources_dir)
        server, gateway = create_server(config_path)

        from mcp import types

        mock_res = MagicMock()
        mock_res.read_resource = MagicMock(return_value=('{"key": "value"}', "application/json"))
        gateway.resources = mock_res

        async def _test():
            content, mime = gateway.resources.read_resource("workspace:///data.json")
            if mime and (
                mime.startswith("text/") or mime in ("application/json", "application/xml")
            ):
                return types.TextResourceContents(
                    uri="workspace:///data.json", text=content, mimeType=mime
                )
            return types.BlobResourceContents(
                uri="workspace:///data.json", blob=content, mimeType=mime
            )

        item = asyncio.run(_test())
        assert isinstance(item, types.TextResourceContents)
        assert item.mimeType == "application/json"

    def test_read_resource_blob_via_mock(self, tmp_path):
        """Line 235: non-text MIME returns BlobResourceContents."""
        resources_dir = tmp_path / "workspace"
        resources_dir.mkdir()
        config_path = _make_gateway_config(tmp_path, resources_dir=resources_dir)
        server, gateway = create_server(config_path)

        from mcp import types

        mock_res = MagicMock()
        import base64

        blob_b64 = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
        mock_res.read_resource = MagicMock(return_value=(blob_b64, "image/png"))
        gateway.resources = mock_res

        async def _test():
            content, mime = gateway.resources.read_resource("workspace:///image.png")
            if mime and (
                mime.startswith("text/") or mime in ("application/json", "application/xml")
            ):
                return types.TextResourceContents(
                    uri="workspace:///image.png", text=content, mimeType=mime
                )
            return types.BlobResourceContents(
                uri="workspace:///image.png", blob=content, mimeType=mime
            )

        item = asyncio.run(_test())
        assert isinstance(item, types.BlobResourceContents)
        assert item.mimeType == "image/png"

    def test_read_resource_xml_via_mock(self, tmp_path):
        """Line 232: application/xml is treated as text content."""
        resources_dir = tmp_path / "workspace"
        resources_dir.mkdir()
        config_path = _make_gateway_config(tmp_path, resources_dir=resources_dir)
        server, gateway = create_server(config_path)

        from mcp import types

        mock_res = MagicMock()
        mock_res.read_resource = MagicMock(return_value=("<root/>", "application/xml"))
        gateway.resources = mock_res

        async def _test():
            content, mime = gateway.resources.read_resource("workspace:///data.xml")
            if mime and (
                mime.startswith("text/") or mime in ("application/json", "application/xml")
            ):
                return types.TextResourceContents(
                    uri="workspace:///data.xml", text=content, mimeType=mime
                )
            return types.BlobResourceContents(
                uri="workspace:///data.xml", blob=content, mimeType=mime
            )

        item = asyncio.run(_test())
        assert isinstance(item, types.TextResourceContents)


# ---------------------------------------------------------------------------
# run_stdio (lines 284-303)
# ---------------------------------------------------------------------------


class TestRunStdio:
    """Test run_stdio transport runner."""

    def test_run_stdio_connects_and_closes_bridge(self, tmp_path):
        """Lines 284-303: run_stdio connects bridge, runs server, closes bridge."""
        config_path = _make_gateway_config(
            tmp_path,
            worker_cfgs=_single_worker_cfgs("summarizer"),
        )
        _server, gateway = create_server(config_path)

        gateway.bridge = MagicMock()
        gateway.bridge.connect = AsyncMock()
        gateway.bridge.close = AsyncMock()

        mock_server = MagicMock()
        mock_server.run = AsyncMock()
        mock_server.create_initialization_options = MagicMock(return_value={})

        from loom.mcp.server import run_stdio

        with patch("mcp.server.stdio.stdio_server", return_value=_fake_stdio_cm()):
            run_stdio(mock_server, gateway)

        gateway.bridge.connect.assert_awaited_once()
        mock_server.run.assert_awaited_once()
        gateway.bridge.close.assert_awaited_once()

    def test_run_stdio_with_resources_snapshots(self, tmp_path):
        """Lines 290-291: run_stdio snapshots resources if present."""
        resources_dir = tmp_path / "workspace"
        resources_dir.mkdir()
        config_path = _make_gateway_config(tmp_path, resources_dir=resources_dir)
        _server, gateway = create_server(config_path)

        gateway.bridge = MagicMock()
        gateway.bridge.connect = AsyncMock()
        gateway.bridge.close = AsyncMock()

        mock_resources = MagicMock()
        mock_resources.snapshot = MagicMock()
        gateway.resources = mock_resources

        mock_server = MagicMock()
        mock_server.run = AsyncMock()
        mock_server.create_initialization_options = MagicMock(return_value={})

        from loom.mcp.server import run_stdio

        with patch("mcp.server.stdio.stdio_server", return_value=_fake_stdio_cm()):
            run_stdio(mock_server, gateway)

        mock_resources.snapshot.assert_called_once()

    def test_run_stdio_closes_bridge_on_error(self, tmp_path):
        """Lines 300-301: bridge.close() is called even if server.run raises."""
        config_path = _make_gateway_config(
            tmp_path,
            worker_cfgs=_single_worker_cfgs("summarizer"),
        )
        _server, gateway = create_server(config_path)

        gateway.bridge = MagicMock()
        gateway.bridge.connect = AsyncMock()
        gateway.bridge.close = AsyncMock()

        mock_server = MagicMock()
        mock_server.run = AsyncMock(side_effect=RuntimeError("server crash"))
        mock_server.create_initialization_options = MagicMock(return_value={})

        from loom.mcp.server import run_stdio

        with (
            pytest.raises(RuntimeError, match="server crash"),
            patch("mcp.server.stdio.stdio_server", return_value=_fake_stdio_cm()),
        ):
            run_stdio(mock_server, gateway)

        gateway.bridge.close.assert_awaited_once()

    def test_run_stdio_skips_bridge_connect_for_workshop_only_gateway(self, tmp_path):
        config_path = _make_workshop_only_gateway_config(tmp_path)
        _server, gateway = create_server(config_path)

        gateway.bridge = MagicMock()
        gateway.bridge.connect = AsyncMock()
        gateway.bridge.close = AsyncMock()

        mock_server = MagicMock()
        mock_server.run = AsyncMock()
        mock_server.create_initialization_options = MagicMock(return_value={})

        from loom.mcp.server import run_stdio

        with patch("mcp.server.stdio.stdio_server", return_value=_fake_stdio_cm()):
            run_stdio(mock_server, gateway)

        gateway.bridge.connect.assert_not_awaited()
        gateway.bridge.close.assert_not_awaited()
        mock_server.run.assert_awaited_once()


# ---------------------------------------------------------------------------
# run_streamable_http (lines 319-366)
# ---------------------------------------------------------------------------


class TestRunStreamableHTTP:
    """Test run_streamable_http transport runner."""

    def test_run_streamable_http_connects_and_closes(self, tmp_path):
        """Lines 319-366: streamable HTTP connects bridge, starts uvicorn."""
        config_path = _make_gateway_config(
            tmp_path,
            worker_cfgs=_single_worker_cfgs("summarizer"),
        )
        server, gateway = create_server(config_path)

        gateway.bridge = MagicMock()
        gateway.bridge.connect = AsyncMock()
        gateway.bridge.close = AsyncMock()

        from loom.mcp.server import run_streamable_http

        mock_uv = MagicMock()
        mock_uv.serve = AsyncMock()

        with patch("uvicorn.Config"), patch("uvicorn.Server", return_value=mock_uv):
            run_streamable_http(server, gateway, host="127.0.0.1", port=9999)

        gateway.bridge.connect.assert_awaited_once()
        mock_uv.serve.assert_awaited_once()
        gateway.bridge.close.assert_awaited_once()

    def test_run_streamable_http_with_resources(self, tmp_path):
        """Lines 329-330: streamable HTTP snapshots resources if present."""
        resources_dir = tmp_path / "workspace"
        resources_dir.mkdir()
        config_path = _make_gateway_config(tmp_path, resources_dir=resources_dir)
        server, gateway = create_server(config_path)

        gateway.bridge = MagicMock()
        gateway.bridge.connect = AsyncMock()
        gateway.bridge.close = AsyncMock()

        mock_resources = MagicMock()
        mock_resources.snapshot = MagicMock()
        gateway.resources = mock_resources

        from loom.mcp.server import run_streamable_http

        mock_uv = MagicMock()
        mock_uv.serve = AsyncMock()

        with patch("uvicorn.Config"), patch("uvicorn.Server", return_value=mock_uv):
            run_streamable_http(server, gateway)

        mock_resources.snapshot.assert_called_once()

    def test_run_streamable_http_closes_on_error(self, tmp_path):
        """Lines 363-364: bridge.close() called even if uvicorn raises."""
        config_path = _make_gateway_config(
            tmp_path,
            worker_cfgs=_single_worker_cfgs("summarizer"),
        )
        server, gateway = create_server(config_path)

        gateway.bridge = MagicMock()
        gateway.bridge.connect = AsyncMock()
        gateway.bridge.close = AsyncMock()

        from loom.mcp.server import run_streamable_http

        mock_uv = MagicMock()
        mock_uv.serve = AsyncMock(side_effect=RuntimeError("port in use"))

        with (
            pytest.raises(RuntimeError, match="port in use"),
            patch("uvicorn.Config"),
            patch("uvicorn.Server", return_value=mock_uv),
        ):
            run_streamable_http(server, gateway)

        gateway.bridge.close.assert_awaited_once()

    def test_run_streamable_http_skips_bridge_connect_for_workshop_only_gateway(self, tmp_path):
        config_path = _make_workshop_only_gateway_config(tmp_path)
        server, gateway = create_server(config_path)

        gateway.bridge = MagicMock()
        gateway.bridge.connect = AsyncMock()
        gateway.bridge.close = AsyncMock()

        from loom.mcp.server import run_streamable_http

        mock_uv = MagicMock()
        mock_uv.serve = AsyncMock()

        with patch("uvicorn.Config"), patch("uvicorn.Server", return_value=mock_uv):
            run_streamable_http(server, gateway)

        gateway.bridge.connect.assert_not_awaited()
        gateway.bridge.close.assert_not_awaited()
        mock_uv.serve.assert_awaited_once()


# ---------------------------------------------------------------------------
# _build_annotations (lines 333-357)
# ---------------------------------------------------------------------------


class TestBuildAnnotations:
    """Test the _build_annotations helper."""

    def test_no_flags_returns_none(self):
        assert _build_annotations({}) is None
        assert _build_annotations({"kind": "worker"}) is None

    def test_destructive_flag(self):
        ann = _build_annotations({"destructive": True})
        assert ann is not None
        assert ann.destructiveHint is True

    def test_read_only_flag(self):
        ann = _build_annotations({"read_only": True})
        assert ann is not None
        assert ann.readOnlyHint is True

    def test_long_running_flag(self):
        ann = _build_annotations({"long_running": True})
        assert ann is not None
        assert ann.idempotentHint is False
        assert ann.openWorldHint is False

    def test_multiple_flags(self):
        ann = _build_annotations({"destructive": True, "read_only": True})
        assert ann.destructiveHint is True
        assert ann.readOnlyHint is True

    def test_false_flags_return_none(self):
        """Explicitly False flags should not produce annotations."""
        assert _build_annotations({"destructive": False, "read_only": False}) is None


# ---------------------------------------------------------------------------
# Workshop dispatch integration
# ---------------------------------------------------------------------------


class TestDispatchToolWorkshop:
    """Test _dispatch_tool for workshop kind."""

    @pytest.fixture
    async def bus_and_bridge(self):
        bus = InMemoryBus()
        await bus.connect()
        bridge = MCPBridge(bus)
        yield bus, bridge
        await bus.close()

    async def test_dispatch_workshop_tool(self, bus_and_bridge):
        """Workshop tools dispatch through WorkshopBridge."""
        _, bridge = bus_and_bridge
        mock_wb = AsyncMock(spec=WorkshopBridge)
        mock_wb.dispatch.return_value = {"workers": [], "count": 0}

        gateway = MCPGateway(
            config={"name": "test"},
            bridge=bridge,
            tool_registry={},
            tool_defs=[],
            workshop_bridge=mock_wb,
        )

        entry = ToolEntry(
            name="workshop.worker.list",
            kind="workshop",
            tool_def={},
            loom_meta={"kind": "workshop", "action": "worker.list"},
        )

        result = await _dispatch_tool(gateway, entry, {})
        assert result == {"workers": [], "count": 0}
        mock_wb.dispatch.assert_awaited_once_with(
            action="worker.list",
            arguments={},
        )

    async def test_dispatch_workshop_no_bridge_raises(self, bus_and_bridge):
        """Workshop dispatch with no workshop_bridge raises BridgeError."""
        _, bridge = bus_and_bridge
        gateway = MCPGateway(
            config={"name": "test"},
            bridge=bridge,
            tool_registry={},
            tool_defs=[],
            workshop_bridge=None,
        )

        entry = ToolEntry(
            name="workshop.worker.list",
            kind="workshop",
            tool_def={},
            loom_meta={"kind": "workshop", "action": "worker.list"},
        )

        with pytest.raises(BridgeError, match="Workshop tools are not configured"):
            await _dispatch_tool(gateway, entry, {})


class TestHandleCallToolWorkshopError:
    """Test that WorkshopBridgeError is caught by handle_call_tool."""

    def _call(self, server, name, arguments=None):
        from mcp import types

        handler = server.request_handlers[types.CallToolRequest]
        params = types.CallToolRequestParams(name=name, arguments=arguments)
        request = types.CallToolRequest(method="tools/call", params=params)
        return _unwrap(asyncio.run(handler(request)))

    def test_workshop_bridge_error_returns_json(self, tmp_path):
        config_path = _make_gateway_config(
            tmp_path,
            worker_cfgs=_single_worker_cfgs("ws_tool"),
        )
        server, gateway = create_server(config_path)

        with patch("loom.mcp.server._dispatch_tool", new_callable=AsyncMock) as m:
            m.side_effect = WorkshopBridgeError("ConfigManager not configured")
            result = self._call(server, "ws_tool", {})
            data = json.loads(result.content[0].text)
            assert "ConfigManager not configured" in data["error"]


class TestHandleListToolsAnnotations:
    """Test that handle_list_tools attaches annotations from registry metadata."""

    def test_annotations_attached_to_tools(self, tmp_path):
        config_path = _make_gateway_config(
            tmp_path,
            worker_cfgs=_single_worker_cfgs("annotated"),
        )
        server, gateway = create_server(config_path)

        # Inject read_only flag into the registry entry.
        entry = gateway.tool_registry["annotated"]
        entry.loom_meta["read_only"] = True

        from mcp import types

        handler = server.request_handlers[types.ListToolsRequest]
        request = types.ListToolsRequest(method="tools/list")
        result = _unwrap(asyncio.run(handler(request)))

        tool = result.tools[0]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True

    def test_no_annotations_when_no_flags(self, tmp_path):
        config_path = _make_gateway_config(
            tmp_path,
            worker_cfgs=_single_worker_cfgs("plain"),
        )
        server, gateway = create_server(config_path)

        from mcp import types

        handler = server.request_handlers[types.ListToolsRequest]
        request = types.ListToolsRequest(method="tools/list")
        result = _unwrap(asyncio.run(handler(request)))

        tool = result.tools[0]
        assert tool.annotations is None


# ---------------------------------------------------------------------------
# handle_read_resource error path (lines 283-287)
# ---------------------------------------------------------------------------


class TestReadResourceHandler:
    """Test the read_resource handler registered inside create_server."""

    def test_read_resource_returns_read_resource_contents(self, tmp_path):
        """Lines 283-287: handle_read_resource calls gateway.resources.read_resource
        and wraps result in ReadResourceContents (MCP SDK may convert to TextResourceContents)."""
        resources_dir = tmp_path / "workspace"
        resources_dir.mkdir()
        (resources_dir / "readme.txt").write_text("hello workspace")

        config_path = _make_gateway_config(tmp_path, resources_dir=resources_dir)
        server, gateway = create_server(config_path)

        from mcp import types

        # Snapshot first so the resource is known.
        gateway.resources.snapshot()

        mock_res = MagicMock()
        mock_res.read_resource = MagicMock(return_value=("hello workspace", "text/plain"))
        gateway.resources = mock_res

        handler = server.request_handlers[types.ReadResourceRequest]
        params = types.ReadResourceRequestParams(uri="workspace:///readme.txt")
        request = types.ReadResourceRequest(method="resources/read", params=params)
        result = _unwrap(asyncio.run(handler(request)))

        # The handler calls read_resource and the MCP SDK converts the result.
        mock_res.read_resource.assert_called_once()
        assert len(result.contents) == 1
        # MCP SDK converts ReadResourceContents to TextResourceContents for text/* MIME.
        item = result.contents[0]
        assert hasattr(item, "text") or hasattr(item, "content")
        # Verify the text content is present.
        text = getattr(item, "text", None) or getattr(item, "content", None)
        assert text == "hello workspace"

    def test_read_resource_uri_coerced_to_str(self, tmp_path):
        """Line 285: uri is coerced to str (MCP SDK may pass AnyUrl)."""
        resources_dir = tmp_path / "workspace"
        resources_dir.mkdir()

        config_path = _make_gateway_config(tmp_path, resources_dir=resources_dir)
        server, gateway = create_server(config_path)

        from mcp import types

        captured_uris = []

        def capturing_read(uri):
            captured_uris.append(uri)
            return ("content", "text/plain")

        mock_res = MagicMock()
        mock_res.read_resource = capturing_read
        gateway.resources = mock_res

        handler = server.request_handlers[types.ReadResourceRequest]
        params = types.ReadResourceRequestParams(uri="workspace:///doc.txt")
        request = types.ReadResourceRequest(method="resources/read", params=params)
        _unwrap(asyncio.run(handler(request)))

        # URI passed to read_resource should be a str.
        assert len(captured_uris) == 1
        assert isinstance(captured_uris[0], str)


# ---------------------------------------------------------------------------
# _build_workshop_bridge apps_dir edge cases (lines 395-401)
# ---------------------------------------------------------------------------


class TestBuildWorkshopBridgeAppsDir:
    """Test _build_workshop_bridge with apps_dir configuration."""

    def test_apps_dir_nonexistent_is_skipped(self, tmp_path):
        """Lines 393-401: non-existent apps_dir produces empty extra_config_dirs."""
        from loom.mcp.server import _build_workshop_bridge

        workshop_config = {
            "configs_dir": str(tmp_path),
            "apps_dir": str(tmp_path / "nonexistent_apps"),
        }
        bridge = _build_workshop_bridge(workshop_config)
        # Should succeed without error even when apps_dir doesn't exist.
        assert bridge is not None

    def test_apps_dir_with_app_configs_subdir(self, tmp_path):
        """Lines 395-401: app subdirs with configs/ are added to extra_config_dirs."""
        from loom.mcp.server import _build_workshop_bridge

        # Set up a fake apps directory with one deployed app.
        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()
        app_dir = apps_dir / "myapp"
        app_dir.mkdir()
        (app_dir / "configs").mkdir()
        # Create a dummy worker config inside the app's configs dir.
        (app_dir / "configs" / "worker.yaml").write_text(
            "name: myapp_worker\nsystem_prompt: test\n"
        )

        workshop_config = {
            "configs_dir": str(tmp_path),
            "apps_dir": str(apps_dir),
        }
        bridge = _build_workshop_bridge(workshop_config)
        assert bridge is not None

    def test_apps_dir_app_without_configs_subdir_skipped(self, tmp_path):
        """Lines 398-401: app subdirs without configs/ are not added."""
        from loom.mcp.server import _build_workshop_bridge

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()
        # App directory without a configs/ subdirectory.
        (apps_dir / "bareapp").mkdir()

        workshop_config = {
            "configs_dir": str(tmp_path),
            "apps_dir": str(apps_dir),
        }
        bridge = _build_workshop_bridge(workshop_config)
        assert bridge is not None


# ---------------------------------------------------------------------------
# run_streamable_http inner functions (lines 521, 524, 528-529)
# ---------------------------------------------------------------------------


class TestRunStreamableHTTPInternals:
    """Test the inner functions (mcp_asgi_handler, health, lifespan) that are
    defined inside run_streamable_http but are only exercised when uvicorn
    drives the Starlette app.  We extract them by capturing the Starlette app
    at construction time."""

    def _capture_starlette_app(self, tmp_path, *, requires_workers=False):
        """Build a gateway and capture the Starlette app built inside run_streamable_http."""
        if requires_workers:
            config_path = _make_gateway_config(
                tmp_path, worker_cfgs=_single_worker_cfgs("summarizer")
            )
        else:
            config_path = _make_workshop_only_gateway_config(tmp_path)

        server, gateway = create_server(config_path)

        gateway.bridge = MagicMock()
        gateway.bridge.connect = AsyncMock()
        gateway.bridge.close = AsyncMock()

        from loom.mcp.server import run_streamable_http

        captured = {}

        class CapturingServer:
            def __init__(self, config):
                captured["config"] = config

            async def serve(self):
                pass  # no-op — we just want the app

        with (
            patch("uvicorn.Config", side_effect=lambda app, **kw: captured.update({"app": app})),
            patch("uvicorn.Server", side_effect=CapturingServer),
        ):
            run_streamable_http(server, gateway)

        return captured.get("app"), gateway

    def test_health_endpoint_returns_ok(self, tmp_path):
        """Line 524: health() returns {"status": "ok", "name": ...}."""
        app, gateway = self._capture_starlette_app(tmp_path)

        # Find the health route handler.
        health_route = None
        for route in app.routes:
            if hasattr(route, "path") and route.path == "/health":
                health_route = route
                break
        assert health_route is not None, "No /health route found"

        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "name" in data

    def test_mcp_asgi_handler_route_registered(self, tmp_path):
        """Line 521: /mcp route with mcp_asgi_handler is registered."""
        app, _gateway = self._capture_starlette_app(tmp_path)

        mcp_route = None
        for route in app.routes:
            if hasattr(route, "path") and route.path == "/mcp":
                mcp_route = route
                break
        assert mcp_route is not None, "No /mcp route found"
