"""Tests for loom.mcp.workshop_discovery — Workshop MCP tool definitions."""

from loom.mcp.workshop_discovery import discover_workshop_tools


class TestDiscoverWorkshopTools:
    def test_default_tools_exclude_deadletter(self):
        """Default config enables all groups except deadletter (not wired to live NATS)."""
        tools = discover_workshop_tools({})
        names = {t["name"] for t in tools}

        assert "workshop.worker.list" in names
        assert "workshop.worker.get" in names
        assert "workshop.worker.update" in names
        assert "workshop.worker.test" in names
        assert "workshop.eval.run" in names
        assert "workshop.eval.compare" in names
        assert "workshop.impact.analyze" in names
        # Dead-letter tools require explicit opt-in.
        assert "workshop.deadletter.list" not in names
        assert "workshop.deadletter.replay" not in names

    def test_all_tools_with_explicit_enable(self):
        """All groups including deadletter when explicitly enabled."""
        tools = discover_workshop_tools(
            {"enable": ["worker", "test", "eval", "impact", "deadletter"]}
        )
        names = {t["name"] for t in tools}
        assert "workshop.deadletter.list" in names
        assert "workshop.deadletter.replay" in names
        assert len(tools) == 9

    def test_selective_enable(self):
        """Only requested tool groups are included."""
        tools = discover_workshop_tools({"enable": ["worker", "impact"]})
        names = {t["name"] for t in tools}

        assert "workshop.worker.list" in names
        assert "workshop.worker.get" in names
        assert "workshop.impact.analyze" in names
        # These should NOT be present.
        assert "workshop.worker.test" not in names
        assert "workshop.eval.run" not in names
        assert "workshop.deadletter.list" not in names

    def test_empty_enable_produces_no_tools(self):
        tools = discover_workshop_tools({"enable": []})
        assert tools == []

    def test_loom_metadata_present(self):
        tools = discover_workshop_tools({"enable": ["worker"]})
        for tool in tools:
            assert "_loom" in tool
            assert tool["_loom"]["kind"] == "workshop"
            assert "action" in tool["_loom"]

    def test_deadletter_replay_marked_destructive(self):
        tools = discover_workshop_tools({"enable": ["deadletter"]})
        replay = next(t for t in tools if t["name"] == "workshop.deadletter.replay")
        assert replay["_loom"]["destructive"] is True

    def test_deadletter_list_not_destructive(self):
        tools = discover_workshop_tools({"enable": ["deadletter"]})
        dl_list = next(t for t in tools if t["name"] == "workshop.deadletter.list")
        assert "destructive" not in dl_list["_loom"]

    def test_tool_schemas_are_valid(self):
        """All tools have proper JSON Schema structure."""
        tools = discover_workshop_tools({})
        for tool in tools:
            schema = tool["inputSchema"]
            assert schema["type"] == "object"
            assert isinstance(schema.get("properties", {}), dict)

    def test_required_fields_present_in_schemas(self):
        """Tools that need arguments have 'required' in their schema."""
        tools = discover_workshop_tools({})
        by_name = {t["name"]: t for t in tools}

        # worker.get requires 'name'
        assert "name" in by_name["workshop.worker.get"]["inputSchema"]["required"]
        # worker.update requires 'name' and 'config_yaml'
        assert "name" in by_name["workshop.worker.update"]["inputSchema"]["required"]
        assert "config_yaml" in by_name["workshop.worker.update"]["inputSchema"]["required"]
        # eval.run requires 'name' and 'test_suite'
        assert "name" in by_name["workshop.eval.run"]["inputSchema"]["required"]
        assert "test_suite" in by_name["workshop.eval.run"]["inputSchema"]["required"]
        # worker.list has no required fields
        assert "required" not in by_name["workshop.worker.list"]["inputSchema"]

    def test_read_only_flags(self):
        """Read-only tools have read_only=True in _loom metadata."""
        all_groups = ["worker", "test", "eval", "impact", "deadletter"]
        tools = discover_workshop_tools({"enable": all_groups})
        by_name = {t["name"]: t for t in tools}

        read_only_tools = [
            "workshop.worker.list",
            "workshop.worker.get",
            "workshop.worker.test",
            "workshop.eval.compare",
            "workshop.impact.analyze",
            "workshop.deadletter.list",
        ]
        for name in read_only_tools:
            assert by_name[name]["_loom"].get("read_only") is True, f"{name} should be read_only"

        # These should NOT be read_only.
        assert "read_only" not in by_name["workshop.worker.update"]["_loom"]
        assert "read_only" not in by_name["workshop.eval.run"]["_loom"]
        assert "read_only" not in by_name["workshop.deadletter.replay"]["_loom"]

    def test_eval_run_marked_long_running(self):
        """eval.run has long_running=True in _loom metadata."""
        tools = discover_workshop_tools({"enable": ["eval"]})
        eval_run = next(t for t in tools if t["name"] == "workshop.eval.run")
        assert eval_run["_loom"]["long_running"] is True

    def test_tool_count_per_group(self):
        """Verify expected tool counts per group."""
        assert len(discover_workshop_tools({"enable": ["worker"]})) == 3
        assert len(discover_workshop_tools({"enable": ["test"]})) == 1
        assert len(discover_workshop_tools({"enable": ["eval"]})) == 2
        assert len(discover_workshop_tools({"enable": ["impact"]})) == 1
        assert len(discover_workshop_tools({"enable": ["deadletter"]})) == 2
