"""Tests for Workshop RAG dashboard — RAGManager and routes."""

import pytest


class TestRAGManager:
    """Test RAGManager without a real vector store."""

    def test_init_no_store(self):
        from loom.workshop.rag_manager import RAGManager

        mgr = RAGManager()
        assert mgr.store is None
        assert mgr.channel_count() == 0

    def test_stats_no_store(self):
        from loom.workshop.rag_manager import RAGManager

        mgr = RAGManager()
        stats = mgr.get_store_stats()
        assert stats["status"] == "not_configured"

    def test_search_no_store(self):
        from loom.workshop.rag_manager import RAGManager

        mgr = RAGManager()
        results = mgr.search("test query")
        assert results == []

    def test_channels_by_faction(self):
        from loom.workshop.rag_manager import ChannelInfo, RAGManager

        mgr = RAGManager()
        mgr._channels = [
            ChannelInfo(handle="@a", name_en="A", faction="regime"),
            ChannelInfo(handle="@b", name_en="B", faction="regime"),
            ChannelInfo(handle="@c", name_en="C", faction="opposition"),
        ]
        groups = mgr.get_channels_by_faction()
        assert len(groups["regime"]) == 2
        assert len(groups["opposition"]) == 1

    def test_channels_by_priority(self):
        from loom.workshop.rag_manager import ChannelInfo, RAGManager

        mgr = RAGManager()
        mgr._channels = [
            ChannelInfo(handle="@a", name_en="A", monitoring_priority="critical"),
            ChannelInfo(handle="@b", name_en="B", monitoring_priority="high"),
            ChannelInfo(handle="@c", name_en="C", monitoring_priority="critical"),
        ]
        groups = mgr.get_channels_by_priority()
        assert len(groups["critical"]) == 2
        assert len(groups["high"]) == 1

    def test_get_channel(self):
        from loom.workshop.rag_manager import ChannelInfo, RAGManager

        mgr = RAGManager()
        mgr._channels = [
            ChannelInfo(handle="@test", name_en="Test Channel"),
        ]
        ch = mgr.get_channel("@test")
        assert ch is not None
        assert ch.name_en == "Test Channel"
        assert mgr.get_channel("@nonexistent") is None

    def test_verified_channel_count(self):
        from loom.workshop.rag_manager import ChannelInfo, RAGManager

        mgr = RAGManager()
        mgr._channels = [
            ChannelInfo(handle="@a", name_en="A", status="verified"),
            ChannelInfo(handle="@b", name_en="B", status="unverified"),
            ChannelInfo(handle="@c", name_en="C", status="verified"),
        ]
        assert mgr.verified_channel_count() == 2


class TestRAGManagerWithRegistry:
    """Test loading a channel registry YAML."""

    def test_load_nonexistent_registry(self):
        from loom.workshop.rag_manager import RAGManager

        mgr = RAGManager(channel_registry_path="/nonexistent/path.yaml")
        assert mgr.channel_count() == 0

    def test_load_valid_registry(self, tmp_path):
        import yaml

        from loom.workshop.rag_manager import RAGManager

        registry = {
            "categories": [
                {
                    "name": "Test Category",
                    "faction": "test_faction",
                    "source_tier": 2,
                    "monitoring_priority": "high",
                    "channels": [
                        {"handle": "@test1", "name_en": "Test One", "language": "fa"},
                        {"handle": "@test2", "name_en": "Test Two", "language": "en"},
                    ],
                }
            ]
        }
        path = tmp_path / "channels.yaml"
        path.write_text(yaml.dump(registry))

        mgr = RAGManager(channel_registry_path=str(path))
        assert mgr.channel_count() == 2
        ch = mgr.get_channel("@test1")
        assert ch is not None
        assert ch.faction == "test_faction"
        assert ch.source_tier == 2


class TestRAGWorkshopRoutes:
    """Test Workshop RAG HTTP routes."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from loom.workshop.app import create_app

        app = create_app(configs_dir="configs/")
        return TestClient(app)

    def test_rag_dashboard(self, client):
        resp = client.get("/rag")
        assert resp.status_code == 200
        assert "RAG Pipeline" in resp.text

    def test_rag_channels(self, client):
        resp = client.get("/rag/channels")
        assert resp.status_code == 200
        assert "Telegram Channels" in resp.text

    def test_rag_search_page(self, client):
        resp = client.get("/rag/search")
        assert resp.status_code == 200
        assert "Semantic Search" in resp.text

    def test_rag_store_stats(self, client):
        resp = client.get("/rag/store/stats")
        assert resp.status_code == 200

    def test_rag_search_empty_query(self, client):
        resp = client.post("/rag/search/run", data={"query": ""})
        assert resp.status_code == 200
        assert "required" in resp.text.lower() or "error" in resp.text.lower()

    def test_rag_search_no_store(self, client):
        resp = client.post("/rag/search/run", data={"query": "test", "limit": "5"})
        assert resp.status_code == 200
        # Should show "No results" since no store is configured
        assert "No results" in resp.text or "result" in resp.text.lower()

    def test_nav_has_rag_link(self, client):
        resp = client.get("/workers")
        assert resp.status_code == 200
        assert "/rag" in resp.text
