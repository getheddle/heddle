"""
MCP server assembly — wires config, discovery, bridge, and resources.

Creates a fully configured ``mcp.server.lowlevel.Server`` from a LOOM
MCP gateway config YAML.  The server exposes LOOM workers, pipelines,
query backends, and Workshop operations as MCP tools, and workspace
files as MCP resources.

Usage::

    from loom.mcp.server import create_server, run_stdio

    server = create_server("configs/mcp/docman.yaml")
    run_stdio(server)

See Also:
    loom.mcp.config              — config loading and validation
    loom.mcp.discovery           — tool definition generation
    loom.mcp.bridge              — NATS call dispatch
    loom.mcp.resources           — workspace resource exposure
    loom.mcp.workshop_discovery  — Workshop tool definitions
    loom.mcp.workshop_bridge     — Workshop direct dispatch
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

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
from loom.mcp.workshop_bridge import WorkshopBridge, WorkshopBridgeError
from loom.mcp.workshop_discovery import discover_workshop_tools

logger = structlog.get_logger()


@dataclass
class ToolEntry:
    """Registry entry linking an MCP tool name to its dispatch info."""

    name: str
    kind: str  # "worker", "pipeline", "query", "workshop"
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
    workshop_bridge: WorkshopBridge | None = None


def create_server(config_path: str) -> tuple[Any, MCPGateway]:  # noqa: PLR0915
    """Create an MCP Server and MCPGateway from a config file.

    Returns:
        Tuple of (mcp.server.lowlevel.Server, MCPGateway).
        The gateway must be connected before the server can handle calls.
    """
    from mcp import types
    from mcp.server.lowlevel import Server

    config = load_mcp_config(config_path)

    # --- Discover tools ---
    tools_config = config.get("tools", {})

    all_tools: list[dict[str, Any]] = []
    all_tools.extend(discover_worker_tools(tools_config.get("workers", [])))
    all_tools.extend(discover_pipeline_tools(tools_config.get("pipelines", [])))
    all_tools.extend(discover_query_tools(tools_config.get("queries", [])))

    # Workshop tools (optional — only if tools.workshop is present).
    workshop_config = tools_config.get("workshop")
    workshop_bridge: WorkshopBridge | None = None
    if workshop_config is not None:
        all_tools.extend(discover_workshop_tools(workshop_config))
        workshop_bridge = _build_workshop_bridge(workshop_config)

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
        workshop_bridge=workshop_bridge,
    )

    # --- Build MCP Server ---
    server = Server(config["name"])

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """Return all registered MCP tool definitions."""
        tools = []
        for t in gateway.tool_defs:
            tool_kwargs: dict[str, Any] = {
                "name": t["name"],
                "description": t.get("description"),
                "inputSchema": t["inputSchema"],
            }
            # Attach annotations from registry metadata.
            entry = gateway.tool_registry.get(t["name"])
            if entry:
                annotations = _build_annotations(entry.loom_meta)
                if annotations:
                    tool_kwargs["annotations"] = annotations
            tools.append(types.Tool(**tool_kwargs))
        return tools

    @server.call_tool()
    async def handle_call_tool(
        name: str,
        arguments: dict[str, Any] | None,
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Dispatch an MCP tool call to the LOOM bridge."""
        arguments = arguments or {}

        entry = gateway.tool_registry.get(name)
        if entry is None:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": f"Unknown tool: {name}"}),
                )
            ]

        # Snapshot workspace before call (for change detection).
        if gateway.resources:
            gateway.resources.snapshot()

        try:
            ctx = server.request_context
        except LookupError:
            ctx = None

        async def progress_callback(_stage_name: str, stage_idx: int, total: int) -> None:
            if ctx and ctx.meta and ctx.meta.progressToken is not None:
                await ctx.session.send_progress_notification(
                    progress_token=ctx.meta.progressToken,
                    progress=stage_idx,
                    total=total if total > 0 else None,
                )

        try:
            result = await _dispatch_tool(
                gateway,
                entry,
                arguments,
                progress_callback=progress_callback,
            )
        except WorkshopBridgeError as exc:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": str(exc)}),
                )
            ]
        except BridgeTimeoutError as exc:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": f"Timeout: {exc}"}),
                )
            ]
        except BridgeError as exc:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": str(exc)}),
                )
            ]
        except Exception as exc:
            logger.error("mcp.server.call_error", tool=name, error=str(exc))
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": f"Internal error: {exc}"}),
                )
            ]

        # Detect workspace changes and notify (best-effort).
        if gateway.resources:
            changed = gateway.resources.detect_changes()
            if changed:
                logger.info("mcp.server.resources_changed", uris=changed)
                # MCP resource notifications require a session, which we
                # don't have access to in the low-level call_tool handler.
                # The notifications are handled by the transport layer.

        return [
            types.TextContent(
                type="text",
                text=json.dumps(result, default=str),
            )
        ]

    # --- Resource handlers ---
    if workspace_resources:

        @server.list_resources()
        async def handle_list_resources() -> list[types.Resource]:
            """List all workspace files as MCP resources."""
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
        ) -> list:
            """Read a workspace resource by URI."""
            from mcp.server.lowlevel.helper_types import ReadResourceContents

            uri_str = str(uri)  # MCP SDK may pass AnyUrl instead of str
            content, mime = gateway.resources.read_resource(uri_str)
            return [ReadResourceContents(content=content, mime_type=mime)]

    return server, gateway


async def _dispatch_tool(
    gateway: MCPGateway,
    entry: ToolEntry,
    arguments: dict[str, Any],
    progress_callback: Callable[[str, int, int], Any] | None = None,
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
        return await gateway.bridge.call_pipeline(
            goal_context=arguments,
            timeout=meta.get("timeout", 300),
            progress_callback=progress_callback,
        )

    if entry.kind == "query":
        return await gateway.bridge.call_query(
            worker_type=meta["worker_type"],
            action=meta["action"],
            payload=arguments,
            timeout=meta.get("timeout", 30),
        )

    if entry.kind == "workshop":
        if gateway.workshop_bridge is None:
            raise BridgeError("Workshop tools are not configured")
        return await gateway.workshop_bridge.dispatch(
            action=meta["action"],
            arguments=arguments,
        )

    raise BridgeError(f"Unknown tool kind: {entry.kind}")


# ---------------------------------------------------------------------------
# Tool annotations
# ---------------------------------------------------------------------------


def _build_annotations(loom_meta: dict[str, Any]) -> Any:
    """Build MCP ToolAnnotations from _loom metadata flags.

    Returns a ``types.ToolAnnotations`` instance if any flags are set,
    or ``None`` if no annotations are needed.
    """
    from mcp import types

    destructive = loom_meta.get("destructive", False)
    read_only = loom_meta.get("read_only", False)
    long_running = loom_meta.get("long_running", False)

    if not (destructive or read_only or long_running):
        return None

    kwargs: dict[str, Any] = {}
    if destructive:
        kwargs["destructiveHint"] = True
    if read_only:
        kwargs["readOnlyHint"] = True
    if long_running:
        # Eval runs create new DB entries — not idempotent, closed world.
        kwargs["idempotentHint"] = False
        kwargs["openWorldHint"] = False
    return types.ToolAnnotations(**kwargs)


# ---------------------------------------------------------------------------
# Workshop bridge factory
# ---------------------------------------------------------------------------


def _build_workshop_bridge(workshop_config: dict[str, Any]) -> WorkshopBridge:
    """Construct a WorkshopBridge from the MCP gateway workshop config.

    Instantiates ConfigManager, and optionally WorkerTestRunner, EvalRunner,
    and WorkshopDB based on available dependencies.
    """
    from pathlib import Path

    from loom.workshop.config_manager import ConfigManager

    configs_dir = workshop_config.get("configs_dir", "configs/")

    # Build extra config dirs from apps_dir (deployed apps).
    extra_config_dirs: list[Path] = []
    apps_dir = workshop_config.get("apps_dir")
    if apps_dir:
        apps_path = Path(apps_dir)
        if apps_path.is_dir():
            for app_dir in sorted(apps_path.iterdir()):
                if app_dir.is_dir():
                    configs_subdir = app_dir / "configs"
                    if configs_subdir.is_dir():
                        extra_config_dirs.append(configs_subdir)

    # Try to set up WorkshopDB.
    db = None
    try:
        from loom.workshop.db import WorkshopDB

        db = WorkshopDB()
    except Exception as exc:
        logger.debug("workshop_bridge.db_init_skipped", reason=str(exc))

    config_manager = ConfigManager(
        configs_dir=configs_dir,
        db=db,
        extra_config_dirs=extra_config_dirs,
    )

    # Try to set up test runner (needs LLM backends).
    test_runner = None
    try:
        from loom.worker.backends import build_backends_from_env
        from loom.workshop.test_runner import WorkerTestRunner

        backends = build_backends_from_env()
        if backends:
            test_runner = WorkerTestRunner(backends)
    except Exception as exc:
        logger.debug("workshop_bridge.test_runner_skipped", reason=str(exc))

    # Set up eval runner if we have both test runner and DB.
    eval_runner = None
    if test_runner and db:
        from loom.workshop.eval_runner import EvalRunner

        eval_runner = EvalRunner(test_runner, db)

    return WorkshopBridge(
        config_manager=config_manager,
        test_runner=test_runner,
        eval_runner=eval_runner,
        db=db,
    )


# ---------------------------------------------------------------------------
# Transport runners
# ---------------------------------------------------------------------------


def run_stdio(server: Any, gateway: MCPGateway) -> None:
    """Run the MCP server on stdio transport (blocking)."""

    async def _run() -> None:
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
    server: Any,
    gateway: MCPGateway,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Run the MCP server on streamable HTTP transport (blocking).

    Requires ``uvicorn`` to be installed.  Uses the MCP SDK's
    ``StreamableHTTPSessionManager`` to handle MCP protocol messages
    over HTTP, with a ``/health`` convenience endpoint.
    """

    async def _run() -> None:
        import uvicorn
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route

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
        async def mcp_asgi_handler(scope: Any, receive: Any, send: Any) -> None:
            await session_manager.handle_request(scope, receive, send)

        async def health(_request: Any) -> JSONResponse:
            return JSONResponse({"status": "ok", "name": gateway.config["name"]})

        async def lifespan(_app: Any) -> AsyncIterator[None]:
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
