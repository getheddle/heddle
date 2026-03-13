"""Tests for loom.mcp.server — MCP server assembly and tool dispatch."""
import asyncio
import os

import pytest
import yaml

from loom.bus.memory import InMemoryBus
from loom.core.messages import TaskResult, TaskStatus
from loom.mcp.bridge import MCPBridge
from loom.mcp.server import MCPGateway, ToolEntry, _dispatch_tool, create_server


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

        # Mock worker with ready signal to avoid race condition.
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
                # Verify action was injected.
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

        from loom.mcp.bridge import BridgeError
        with pytest.raises(BridgeError, match="Unknown tool kind"):
            await _dispatch_tool(gateway, entry, {})
