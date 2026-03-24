"""MCP gateway for LOOM systems.

Exposes LOOM workers, pipelines, and query backends as MCP tools,
and workspace files as MCP resources.  Any system built on LOOM can
become an MCP server by adding a small YAML config.

Usage::

    from loom.mcp import create_server, run_stdio

    mcp, gateway = create_server("configs/mcp/my_system.yaml")
    run_stdio(mcp, gateway)

See Also:
    loom.mcp.config    — config loading and validation
    loom.mcp.discovery — tool definition generation
    loom.mcp.bridge    — NATS call dispatch
    loom.mcp.resources — workspace resource exposure
    loom.mcp.server    — server assembly and transport runners
"""

from loom.mcp.server import MCPGateway, create_server, run_stdio, run_streamable_http

__all__ = [
    "MCPGateway",
    "create_server",
    "run_stdio",
    "run_streamable_http",
]
