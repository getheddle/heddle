"""Council tool discovery — generate MCP tool definitions for council operations.

Exposes council capabilities (start, status, transcript, intervene, stop)
as MCP tools under the ``council.*`` namespace.  Council tools call
:class:`CouncilBridge` directly — no NATS required.

Follows the pattern of :mod:`loom.mcp.workshop_discovery`.
"""

from __future__ import annotations

from typing import Any

from loom.mcp.discovery import make_tool


def discover_council_tools(
    council_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Generate MCP tool definitions for council operations.

    Args:
        council_config: The ``tools.council`` dict from the MCP
            gateway config.  Supported keys: ``configs_dir``,
            ``enable`` (list of tool groups).

    Returns:
        List of tool definition dicts with ``_loom`` metadata.
    """
    enabled = set(
        council_config.get(
            "enable",
            ["start", "status", "transcript", "intervene", "stop"],
        )
    )

    tools: list[dict[str, Any]] = []

    if "start" in enabled:
        tool = make_tool(
            "council.start",
            "Start a council discussion on a topic using a named config.",
            {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The discussion topic.",
                    },
                    "config_name": {
                        "type": "string",
                        "description": (
                            "Name of the council config file (without .yaml extension)."
                        ),
                    },
                },
                "required": ["topic", "config_name"],
            },
        )
        tool["_loom"] = {
            "kind": "council",
            "action": "start",
            "long_running": True,
        }
        tools.append(tool)

    if "status" in enabled:
        tool = make_tool(
            "council.status",
            "Get the current status of a council discussion.",
            {
                "type": "object",
                "properties": {
                    "council_id": {
                        "type": "string",
                        "description": "ID of the council session.",
                    },
                },
                "required": ["council_id"],
            },
        )
        tool["_loom"] = {
            "kind": "council",
            "action": "status",
            "read_only": True,
        }
        tools.append(tool)

    if "transcript" in enabled:
        tool = make_tool(
            "council.transcript",
            "Get the full or filtered transcript of a council.",
            {
                "type": "object",
                "properties": {
                    "council_id": {
                        "type": "string",
                        "description": "ID of the council session.",
                    },
                    "agent_filter": {
                        "type": "string",
                        "description": ("Optional: only show entries from this agent."),
                    },
                },
                "required": ["council_id"],
            },
        )
        tool["_loom"] = {
            "kind": "council",
            "action": "transcript",
            "read_only": True,
        }
        tools.append(tool)

    if "intervene" in enabled:
        tool = make_tool(
            "council.intervene",
            "Inject a human message into an active council.",
            {
                "type": "object",
                "properties": {
                    "council_id": {
                        "type": "string",
                        "description": "ID of the council session.",
                    },
                    "message": {
                        "type": "string",
                        "description": "The message to inject.",
                    },
                },
                "required": ["council_id", "message"],
            },
        )
        tool["_loom"] = {"kind": "council", "action": "intervene"}
        tools.append(tool)

    if "stop" in enabled:
        tool = make_tool(
            "council.stop",
            "Stop an active council and synthesize current state.",
            {
                "type": "object",
                "properties": {
                    "council_id": {
                        "type": "string",
                        "description": "ID of the council session.",
                    },
                },
                "required": ["council_id"],
            },
        )
        tool["_loom"] = {"kind": "council", "action": "stop"}
        tools.append(tool)

    return tools
