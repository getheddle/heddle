"""Tests for council MCP tool discovery."""

from loom.mcp.council_discovery import discover_council_tools


class TestDiscoverCouncilTools:
    def test_all_tools_discovered(self):
        tools = discover_council_tools({})
        names = {t["name"] for t in tools}
        assert names == {
            "council.start",
            "council.status",
            "council.transcript",
            "council.intervene",
            "council.stop",
        }

    def test_enable_filter(self):
        tools = discover_council_tools({"enable": ["start", "status"]})
        names = {t["name"] for t in tools}
        assert names == {"council.start", "council.status"}

    def test_start_tool_schema(self):
        tools = discover_council_tools({"enable": ["start"]})
        tool = tools[0]
        assert tool["name"] == "council.start"
        schema = tool["inputSchema"]
        assert "topic" in schema["properties"]
        assert "config_name" in schema["properties"]
        assert schema["required"] == ["topic", "config_name"]

    def test_loom_metadata(self):
        tools = discover_council_tools({"enable": ["start"]})
        meta = tools[0]["_loom"]
        assert meta["kind"] == "council"
        assert meta["action"] == "start"
        assert meta["long_running"] is True

    def test_status_is_read_only(self):
        tools = discover_council_tools({"enable": ["status"]})
        meta = tools[0]["_loom"]
        assert meta["read_only"] is True

    def test_transcript_has_optional_filter(self):
        tools = discover_council_tools({"enable": ["transcript"]})
        schema = tools[0]["inputSchema"]
        assert "agent_filter" in schema["properties"]
        assert "agent_filter" not in schema.get("required", [])

    def test_empty_enable_returns_nothing(self):
        tools = discover_council_tools({"enable": []})
        assert tools == []
