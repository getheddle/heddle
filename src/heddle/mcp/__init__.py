"""MCP gateway for HEDDLE systems.

Exposes HEDDLE workers, pipelines, and query backends as MCP tools,
and workspace files as MCP resources.  Any system built on HEDDLE can
become an MCP server by adding a small YAML config.

Usage::

    from heddle.mcp import create_server, run_stdio

    mcp, gateway = create_server("configs/mcp/my_system.yaml")
    run_stdio(mcp, gateway)

See Also:
    heddle.mcp.config    — config loading and validation
    heddle.mcp.discovery — tool definition generation
    heddle.mcp.bridge    — NATS call dispatch
    heddle.mcp.resources — workspace resource exposure
    heddle.mcp.server    — server assembly and transport runners
"""

from heddle.mcp.server import MCPGateway, create_server, run_stdio, run_streamable_http

__all__ = [
    "MCPGateway",
    "create_server",
    "run_stdio",
    "run_streamable_http",
]
