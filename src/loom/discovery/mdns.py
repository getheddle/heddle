"""
mDNS/Bonjour service advertisement for Loom.

Advertises Loom services on the local network so that MCP clients,
Workshop browsers, and other tools can auto-discover them without
manual URL configuration.

Requires the ``zeroconf`` package::

    pip install loom[mdns]

Services advertised:
    - ``_http._tcp.local.`` — Loom Workshop (web UI)
    - ``_nats._tcp.local.`` — NATS message bus
    - ``_http._tcp.local.`` — Loom MCP server (streamable-http)

Usage::

    advertiser = LoomServiceAdvertiser()
    await advertiser.start()
    advertiser.register_workshop(port=8080)
    advertiser.register_nats(port=4222)
    # ... later ...
    await advertiser.stop()
"""

from __future__ import annotations

import socket
from typing import Any

import structlog

logger = structlog.get_logger()


class LoomServiceAdvertiser:
    """Advertise Loom services via mDNS/Bonjour on the local network.

    This class wraps the ``zeroconf`` library to provide a simple interface
    for registering and unregistering Loom services. Services become visible
    to any mDNS-capable client on the LAN (e.g., ``dns-sd -B _http._tcp``
    on macOS, or Avahi on Linux).
    """

    def __init__(self) -> None:
        self._zeroconf: Any = None
        self._infos: list[Any] = []

    async def start(self) -> None:
        """Initialize the Zeroconf instance.

        Raises:
            ImportError: If ``zeroconf`` is not installed.
        """
        from zeroconf import Zeroconf

        self._zeroconf = Zeroconf()
        logger.info("mdns.started")

    def register_workshop(self, port: int = 8080, host: str | None = None) -> None:
        """Register the Workshop web UI as an HTTP service."""
        self._register_service(
            service_type="_http._tcp.local.",
            name="Loom Workshop._http._tcp.local.",
            port=port,
            host=host,
            properties={"path": "/", "version": "0.4.0"},
        )

    def register_nats(self, port: int = 4222, host: str | None = None) -> None:
        """Register the NATS message bus."""
        self._register_service(
            service_type="_nats._tcp.local.",
            name="Loom NATS._nats._tcp.local.",
            port=port,
            host=host,
            properties={"version": "0.4.0"},
        )

    def register_mcp(self, port: int = 8000, host: str | None = None) -> None:
        """Register an MCP server (streamable-http transport)."""
        self._register_service(
            service_type="_http._tcp.local.",
            name="Loom MCP._http._tcp.local.",
            port=port,
            host=host,
            properties={"path": "/mcp", "version": "0.4.0"},
        )

    def _register_service(
        self,
        service_type: str,
        name: str,
        port: int,
        host: str | None = None,
        properties: dict[str, str] | None = None,
    ) -> None:
        """Register a single mDNS service."""
        if self._zeroconf is None:
            logger.warning("mdns.not_started", hint="Call start() before registering services")
            return

        from zeroconf import ServiceInfo

        # Resolve the host address
        if host is None or host in ("0.0.0.0", ""):
            host_addr = socket.gethostbyname(socket.gethostname())
        else:
            host_addr = host

        info = ServiceInfo(
            service_type,
            name,
            addresses=[socket.inet_aton(host_addr)],
            port=port,
            properties=properties or {},
            server=f"{socket.gethostname()}.local.",
        )

        self._zeroconf.register_service(info)
        self._infos.append(info)
        logger.info(
            "mdns.service_registered",
            name=name,
            port=port,
            host=host_addr,
        )

    async def stop(self) -> None:
        """Unregister all services and close Zeroconf."""
        if self._zeroconf is None:
            return

        for info in self._infos:
            self._zeroconf.unregister_service(info)
            logger.info("mdns.service_unregistered", name=info.name)

        self._infos.clear()
        self._zeroconf.close()
        self._zeroconf = None
        logger.info("mdns.stopped")
