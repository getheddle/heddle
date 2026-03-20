"""Tests for loom.discovery.mdns — mDNS service advertisement."""

from unittest.mock import MagicMock

import pytest

from loom.discovery.mdns import LoomServiceAdvertiser


class TestLoomServiceAdvertiser:
    @pytest.mark.asyncio
    async def test_register_and_stop(self):
        """Register services and stop should unregister all."""
        import sys

        mock_zc_instance = MagicMock()
        mock_service_info = MagicMock()

        # Create a mock zeroconf module so the import inside _register_service works
        mock_zeroconf_module = MagicMock()
        mock_zeroconf_module.ServiceInfo.return_value = mock_service_info

        advertiser = LoomServiceAdvertiser()
        advertiser._zeroconf = mock_zc_instance

        # Temporarily inject mock zeroconf module
        original = sys.modules.get("zeroconf")
        sys.modules["zeroconf"] = mock_zeroconf_module
        try:
            advertiser.register_workshop(port=8080, host="127.0.0.1")
            advertiser.register_nats(port=4222, host="127.0.0.1")
            advertiser.register_mcp(port=8000, host="127.0.0.1")
        finally:
            if original is not None:
                sys.modules["zeroconf"] = original
            else:
                del sys.modules["zeroconf"]

        assert len(advertiser._infos) == 3
        assert mock_zc_instance.register_service.call_count == 3

        await advertiser.stop()
        assert mock_zc_instance.unregister_service.call_count == 3
        assert mock_zc_instance.close.call_count == 1
        assert advertiser._zeroconf is None

    def test_register_without_start_logs_warning(self):
        """Registering before start() should not crash."""
        from loom.discovery.mdns import LoomServiceAdvertiser

        advertiser = LoomServiceAdvertiser()
        # Should log a warning but not raise
        advertiser.register_workshop(port=8080)
        assert len(advertiser._infos) == 0

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """Stopping before start should be a no-op."""
        from loom.discovery.mdns import LoomServiceAdvertiser

        advertiser = LoomServiceAdvertiser()
        await advertiser.stop()  # should not raise
