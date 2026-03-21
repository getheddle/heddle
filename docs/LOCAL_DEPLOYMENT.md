# Local Deployment Guide

**Loom — Lightweight Orchestrated Operational Mesh**

---

## Overview

Loom can run as a local background service accessible on your machine and
optionally published on your LAN. Three deployment methods are supported:

1. **Docker Compose** — recommended for most users
2. **Native process manager** — macOS (launchd) or Windows (NSSM)
3. **Kubernetes** — see [KUBERNETES.md](KUBERNETES.md)

---

## Docker Compose

The simplest way to run the full Loom stack locally.

### Prerequisites

- Docker Desktop (Mac/Windows) or Docker Engine (Linux)
- Docker Compose v2+

### Start

```bash
cd loom/
docker compose up -d
```

This starts:

- **NATS** message bus (port 4222, monitoring on 8222)
- **Redis** checkpoint store (port 6379)
- **Workshop** web UI (port 8080)
- **Router** deterministic task router

### Access

- Workshop: http://localhost:8080
- NATS monitoring: http://localhost:8222

### Add Workers

Workers connect to Ollama on the host for local LLM inference.
Uncomment the worker section in `docker-compose.yml` or add:

```yaml
  worker-summarizer:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    environment:
      - WORKER_CONFIG=configs/workers/summarizer.yaml
      - MODEL_TIER=local
      - NATS_URL=nats://nats:4222
      - OLLAMA_URL=http://host.docker.internal:11434
    depends_on:
      - nats
      - router
```

### Deploy Apps

Upload app ZIPs through the Workshop at http://localhost:8080/apps.
Deployed apps persist across container restarts via the `loom-apps` volume.

### LAN Access

Bind the Workshop to all interfaces:

```yaml
  workshop:
    ports:
      - "0.0.0.0:8080:8080"
```

Then access from other devices at `http://<your-ip>:8080`.

With mDNS enabled (install `loom[mdns]`), the Workshop auto-advertises
as `loom-workshop` on the LAN — discoverable via Bonjour/Avahi.

---

## Native Process Manager — macOS

Run Loom as launchd background services that start on login.

### Prerequisites

- Python 3.11+ with loom installed: `pip install loom[workshop]`
- NATS server: `brew install nats-server` or Docker

### Install

```bash
# Default (localhost only)
bash deploy/macos/install.sh

# LAN accessible
bash deploy/macos/install.sh 0.0.0.0
```

### Services

| Service | Description | Log |
|---------|-------------|-----|
| com.loom.workshop | Workshop UI (port 8080) | ~/Library/Logs/loom/workshop.log |
| com.loom.router | Task router | ~/Library/Logs/loom/router.log |

### Manage

```bash
# Check status
launchctl list | grep loom

# Stop workshop
launchctl stop com.loom.workshop

# Start workshop
launchctl start com.loom.workshop

# View logs
tail -f ~/Library/Logs/loom/workshop.log
```

### Uninstall

```bash
bash deploy/macos/uninstall.sh
```

---

## Native Process Manager — Windows

Run Loom as Windows services using NSSM.

### Prerequisites

- Python 3.11+ with loom installed: `pip install loom[workshop]`
- NSSM: `choco install nssm`
- NATS server: `choco install nats-server` or Docker

### Install

```powershell
# Default (localhost only)
.\deploy\windows\install.ps1

# LAN accessible
.\deploy\windows\install.ps1 -Host "0.0.0.0"
```

### Services

| Service | Description | Log |
|---------|-------------|-----|
| LoomWorkshop | Workshop UI (port 8080) | %LOCALAPPDATA%\loom\logs\workshop.log |
| LoomRouter | Task router | %LOCALAPPDATA%\loom\logs\router.log |

### Manage

```powershell
# Check status
nssm status LoomWorkshop

# Restart
nssm restart LoomWorkshop
```

### Uninstall

```powershell
.\deploy\windows\uninstall.ps1
```

---

## mDNS / Bonjour Discovery

Install the optional mDNS dependency to auto-advertise Loom on your LAN:

```bash
pip install loom[mdns]
```

When the Workshop starts, it automatically registers as a Bonjour service.
Other devices on the network can discover it without knowing the IP address.

For headless deployments (no Workshop), use the standalone advertiser:

```bash
loom mdns --workshop-port 8080 --nats-port 4222
```

### Discovery from clients

**macOS:**

```bash
dns-sd -B _http._tcp
```

**Linux (Avahi):**

```bash
avahi-browse -r _http._tcp
```

---

*For Kubernetes deployment, see [KUBERNETES.md](KUBERNETES.md).*
*For app bundle deployment, see [APP_DEPLOYMENT.md](APP_DEPLOYMENT.md).*
*For ITP analytical system setup (Baft + Framework), see [baft/docs/SETUP.md](../../baft/docs/SETUP.md).*
