"""
MCP server assembly — wires config, discovery, bridge, and resources.

Creates a fully configured ``mcp.server.lowlevel.Server`` from a LOOM
MCP gateway config YAML.  The server exposes LOOM workers, pipelines,
and query backends as MCP tools, and workspace files as MCP resources.

Usage::

    from loom.mcp.server import create_server, run_stdio

    server = create_server("configs/mcp/docman.yaml")
    run_stdio(server)

See also:
    loom.mcp.config    — config loading and validation
    loom.mcp.discovery — tool definition generation
    loom.mcp.bridge    — NATS call dispatch
    loom.mcp.resources — workspace resource exposure
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import structlog

from loom.bus.nats_adapter import NATSBus
from loom.mcp.bridge import BridgeError, BridgeTimeoutError, MCPBridge
from loom.mcp.config import load_mcp_config
from loom.mcp.discovery import (
    discover_pipeline_tools,
    discover_query_tools,
    discover_worker_tools,
)
from loom.mcp.resources import WorkspaceResources

logger = structlog.get_logger()


@dataclass
class ToolEntry:
    """Registry entry linking an MCP tool name to its dispatch info."""

    name: str
    kind: str  # "worker", "pipeline", "query"
    tool_def: dict[str, Any]  # MCP Tool shape
    loom_meta: dict[str, Any]  # _loom metadata from discovery


@dataclass
class MCPGateway:
    """Holds all state for a running MCP gateway."""

    config: dict[str, Any]
    bridge: MCPBridge
    tool_registry: dict[str, ToolEntry] = field(default_factory=dict)
    tool_defs: list[dict[str, Any]] = field(default_factory=list)
    resources: WorkspaceResources | None = None


def create_server(config_path: str) -> tuple[Any, MCPGateway]:
    """Create an MCP Server and MCPGateway from a config file.

    Returns:
        Tuple of (mcp.server.lowlevel.Server, MCPGateway).
        The gateway must be connected before the server can handle calls.
    """
    from mcp.server.lowlevel import Server
    import mcp.types as types

    config = load_mcp_config(config_path)

    # --- Discover tools ---
    tools_config = config.get("tools", {})

    all_tools: list[dict[str, Any]] = []
    all_tools.extend(discover_worker_tools(tools_config.get("workers", [])))
    all_tools.extend(discover_pipeline_tools(tools_config.get("pipelines", [])))
    all_tools.extend(discover_query_tools(tools_config.get("queries", [])))

    # Build registry.
    registry: dict[str, ToolEntry] = {}
    mcp_tool_defs: list[dict[str, Any]] = []

    for tool in all_tools:
        loom_meta = tool.pop("_loom", {})
        entry = ToolEntry(
            name=tool["name"],
            kind=loom_meta.get("kind", "unknown"),
            tool_def=tool,
            loom_meta=loom_meta,
        )
        registry[tool["name"]] = entry
        mcp_tool_defs.append(tool)

    logger.info(
        "mcp.server.tools_discovered",
        count=len(registry),
        tools=sorted(registry.keys()),
    )

    # --- Set up bridge ---
    nats_url = config.get("nats_url", "nats://nats:4222")
    bus = NATSBus(nats_url)
    bridge = MCPBridge(bus)

    # --- Set up resources ---
    resources_config = config.get("resources")
    workspace_resources: WorkspaceResources | None = None
    if resources_config:
        workspace_resources = WorkspaceResources(
            workspace_dir=resources_config["workspace_dir"],
            patterns=resources_config.get("patterns"),
        )

    gateway = MCPGateway(
        config=config,
        bridge=bridge,
        tool_registry=registry,
        tool_defs=mcp_tool_defs,
        resources=workspace_resources,
    )

    # --- Build MCP Server ---
    server = Server(config["name"])

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=t["name"],
                description=t.get("description"),
                inputSchema=t["inputSchema"],
            )
            for t in gateway.tool_defs
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None,
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        arguments = arguments or {}

        entry = gateway.tool_registry.get(name)
        if entry is None:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"Unknown tool: {name}"}),
            )]

        # Snapshot workspace before call (for change detection).
        if gateway.resources:
            gateway.resources.snapshot()

        try:
            result = await _dispatch_tool(gateway, entry, arguments)
        except BridgeTimeoutError as exc:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"Timeout: {exc}"}),
            )]
        except BridgeError as exc:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": str(exc)}),
            )]
        except Exception as exc:
            logger.error("mcp.server.call_error", tool=name, error=str(exc))
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"Internal error: {exc}"}),
            )]

        # Detect workspace changes and notify (best-effort).
        if gateway.resources:
            changed = gateway.resources.detect_changes()
            if changed:
                logger.info("mcp.server.resources_changed", uris=changed)
                # MCP resource notifications require a session, which we
                # don't have access to in the low-level call_tool handler.
                # The notifications are handled by the transport layer.

        return [types.TextContent(
            type="text",
            text=json.dumps(result, default=str),
        )]

    # --- Resource handlers ---
    if workspace_resources:
        @server.list_resources()
        async def handle_list_resources() -> list[types.Resource]:
            items = gateway.resources.list_resources()
            return [
                types.Resource(
                    uri=item["uri"],
                    name=item["name"],
                    description=item.get("description"),
                    mimeType=item.get("mimeType"),
                )
                for item in items
            ]

        @server.read_resource()
        async def handle_read_resource(
            uri: str,
        ) -> list[types.TextResourceContents | types.BlobResourceContents]:
            content, mime = gateway.resources.read_resource(uri)
            if mime and (mime.startswith("text/") or mime in ("application/json", "application/xml")):
                return [types.TextResourceContents(uri=uri, text=content, mimeType=mime)]
            else:
                return [types.BlobResourceContents(uri=uri, blob=content, mimeType=mime)]

    return server, gateway


async def _dispatch_tool(
    gateway: MCPGateway,
    entry: ToolEntry,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch an MCP tool call to the appropriate bridge method."""
    meta = entry.loom_meta

    if entry.kind == "worker":
        return await gateway.bridge.call_worker(
            worker_type=meta["worker_type"],
            tier=meta.get("tier", "local"),
            payload=arguments,
            timeout=meta.get("timeout", 60),
        )

    if entry.kind == "pipeline":
        # TODO: Pass a progress_callback that emits MCP progress notifications
        #   so clients can track per-stage pipeline progress. Requires access to
        #   the MCP session context (not available in low-level call_tool handler).
        return await gateway.bridge.call_pipeline(
            goal_context=arguments,
            timeout=meta.get("timeout", 300),
        )

    if entry.kind == "query":
        return await gateway.bridge.call_query(
            worker_type=meta["worker_type"],
            action=meta["action"],
            payload=arguments,
            timeout=meta.get("timeout", 30),
        )

    raise BridgeError(f"Unknown tool kind: {entry.kind}")


# ---------------------------------------------------------------------------
# Transport runners
# ---------------------------------------------------------------------------


def run_stdio(server: Any, gateway: MCPGateway) -> None:
    """Run the MCP server on stdio transport (blocking)."""

    async def _run():
        import mcp.server.stdio

        await gateway.bridge.connect()
        logger.info("mcp.gateway.connected", nats_url=gateway.config.get("nats_url"))

        if gateway.resources:
            gateway.resources.snapshot()

        try:
            async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )
        finally:
            await gateway.bridge.close()

    asyncio.run(_run())


def run_streamable_http(
    server: Any, gateway: MCPGateway, host: str = "127.0.0.1", port: int = 8000,
) -> None:
    """Run the MCP server on streamable HTTP transport (blocking).

    Requires ``uvicorn`` to be installed.  Uses the MCP SDK's
    ``StreamableHTTPSessionManager`` to handle MCP protocol messages
    over HTTP, with a ``/health`` convenience endpoint.
    """

    async def _run():
        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import JSONResponse
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

        await gateway.bridge.connect()
        logger.info("mcp.gateway.connected", nats_url=gateway.config.get("nats_url"))

        if gateway.resources:
            gateway.resources.snapshot()

        # Session manager wraps the low-level MCP server and handles
        # session lifecycle, transport creation, and request dispatch.
        session_manager = StreamableHTTPSessionManager(
            app=server,
            stateless=True,
        )

        # Thin ASGI callable that delegates to the session manager.
        async def mcp_asgi_handler(scope, receive, send):
            await session_manager.handle_request(scope, receive, send)

        async def health(request):
            return JSONResponse({"status": "ok", "name": gateway.config["name"]})

        async def lifespan(app):
            async with session_manager.run():
                yield

        starlette_app = Starlette(
            routes=[
                Route("/health", health),
                Route("/mcp", endpoint=mcp_asgi_handler, methods=["GET", "POST", "DELETE"]),
            ],
            lifespan=lifespan,
        )

        config = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
        uv_server = uvicorn.Server(config)

        try:
            await uv_server.serve()
        finally:
            await gateway.bridge.close()

    asyncio.run(_run())
