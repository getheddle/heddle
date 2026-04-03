#!/usr/bin/env bash
# Install Heddle as a background service on macOS using launchd.
#
# This script creates launchd plist files for:
#   - heddle-workshop (web UI on port 8080)
#   - heddle-router (deterministic task router)
#
# Prerequisites:
#   - Python 3.11+ with heddle installed (pip install heddle-ai[workshop])
#   - NATS server running (brew install nats-server, or Docker)
#
# Usage:
#   bash deploy/macos/install.sh
#   bash deploy/macos/install.sh --host 0.0.0.0  # bind to all interfaces (LAN access)
#
# Services are started automatically and survive reboots.
# Logs: ~/Library/Logs/heddle/
# Uninstall: bash deploy/macos/uninstall.sh
set -euo pipefail

HOST="${1:-127.0.0.1}"
WORKSHOP_PORT="${2:-8080}"
NATS_URL="${NATS_URL:-nats://localhost:4222}"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

echo "=== Heddle Service Installer (macOS) ==="
echo ""

# Check for existing services
if launchctl list 2>/dev/null | grep -q "com.heddle.workshop"; then
    echo "Warning: Heddle Workshop service already exists."
    echo "  Run 'bash deploy/macos/uninstall.sh' first to remove the old installation."
    echo "  Continuing will replace the existing services."
    echo ""
fi

# Detect heddle binary
HEDDLE_BIN=$(which heddle 2>/dev/null || echo "")
if [ -z "$HEDDLE_BIN" ]; then
    # Try uv-managed path
    HEDDLE_BIN="$HOME/.local/bin/heddle"
    if [ ! -f "$HEDDLE_BIN" ]; then
        echo "Error: 'heddle' not found in PATH."
        echo ""
        echo "  Install with one of:"
        echo "    pip install heddle-ai[workshop]"
        echo "    uv pip install heddle-ai[workshop]"
        echo ""
        echo "  Or specify the full path to the heddle binary:"
        echo "    HEDDLE_BIN=/path/to/heddle bash deploy/macos/install.sh"
        exit 1
    fi
fi

# Allow override via env var
HEDDLE_BIN="${HEDDLE_BIN:-$HEDDLE_BIN}"

# Verify heddle binary works
if ! "$HEDDLE_BIN" --help >/dev/null 2>&1; then
    echo "Error: '$HEDDLE_BIN' exists but is not executable or has errors."
    echo "  Try running: $HEDDLE_BIN --help"
    exit 1
fi

# Check Python version (heddle requires 3.11+)
PYTHON_VERSION=$("$HEDDLE_BIN" --version 2>/dev/null || echo "unknown")
echo "Heddle: $PYTHON_VERSION"

# Check NATS availability (non-blocking warning)
NATS_HOST=$(echo "$NATS_URL" | sed 's|nats://||' | cut -d: -f1)
NATS_PORT=$(echo "$NATS_URL" | sed 's|nats://||' | cut -d: -f2)
if command -v nc >/dev/null 2>&1; then
    if nc -z -w2 "$NATS_HOST" "$NATS_PORT" 2>/dev/null; then
        echo "NATS: reachable at $NATS_URL"
    else
        echo "Warning: NATS not reachable at $NATS_URL"
        echo "  The router service will retry connecting automatically."
        echo "  To start NATS: docker run -d -p 4222:4222 nats:latest"
        echo ""
    fi
else
    echo "NATS: $NATS_URL (connectivity check skipped — nc not available)"
fi

echo "Binary: $HEDDLE_BIN"
echo "Workshop: ${HOST}:${WORKSHOP_PORT}"
echo ""

# ---------------------------------------------------------------------------
# Install services
# ---------------------------------------------------------------------------

# Create log directory
LOG_DIR="$HOME/Library/Logs/heddle"
mkdir -p "$LOG_DIR"

# Create plist directory
PLIST_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$PLIST_DIR"

# Unload existing services (if any) before replacing
launchctl unload "$PLIST_DIR/com.heddle.workshop.plist" 2>/dev/null || true
launchctl unload "$PLIST_DIR/com.heddle.router.plist" 2>/dev/null || true

# --- Workshop plist ---
cat > "$PLIST_DIR/com.heddle.workshop.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.heddle.workshop</string>
    <key>ProgramArguments</key>
    <array>
        <string>${HEDDLE_BIN}</string>
        <string>workshop</string>
        <string>--host</string>
        <string>${HOST}</string>
        <string>--port</string>
        <string>${WORKSHOP_PORT}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/workshop.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/workshop.err</string>
    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
EOF

# --- Router plist ---
cat > "$PLIST_DIR/com.heddle.router.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.heddle.router</string>
    <key>ProgramArguments</key>
    <array>
        <string>${HEDDLE_BIN}</string>
        <string>router</string>
        <string>--nats-url</string>
        <string>${NATS_URL}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/router.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/router.err</string>
    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
EOF

# Load services
launchctl load "$PLIST_DIR/com.heddle.workshop.plist" 2>/dev/null || true
launchctl load "$PLIST_DIR/com.heddle.router.plist" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Post-install health check
# ---------------------------------------------------------------------------

echo "Heddle services installed and started."
echo ""

# Wait briefly for Workshop to start, then health check
sleep 2
if command -v curl >/dev/null 2>&1; then
    if curl -sf "http://${HOST}:${WORKSHOP_PORT}/health" >/dev/null 2>&1; then
        echo "  Workshop: http://${HOST}:${WORKSHOP_PORT} [healthy]"
    else
        echo "  Workshop: http://${HOST}:${WORKSHOP_PORT} [starting...]"
        echo "    Check logs if it doesn't come up: cat ${LOG_DIR}/workshop.err"
    fi
else
    echo "  Workshop: http://${HOST}:${WORKSHOP_PORT}"
fi
echo "  Router:   connected to ${NATS_URL}"
echo ""
echo "Logs: ${LOG_DIR}/"
echo "Uninstall: bash deploy/macos/uninstall.sh"
echo "Update: bash deploy/macos/uninstall.sh && bash deploy/macos/install.sh"
