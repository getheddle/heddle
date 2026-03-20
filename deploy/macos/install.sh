#!/usr/bin/env bash
# Install Loom as a background service on macOS using launchd.
#
# This script creates launchd plist files for:
#   - loom-workshop (web UI on port 8080)
#   - loom-router (deterministic task router)
#
# Prerequisites:
#   - Python 3.11+ with loom installed (pip install loom[workshop])
#   - NATS server running (brew install nats-server, or Docker)
#
# Usage:
#   bash deploy/macos/install.sh
#   bash deploy/macos/install.sh --host 0.0.0.0  # bind to all interfaces (LAN access)
#
# Services are started automatically and survive reboots.
# Logs: ~/Library/Logs/loom/
# Uninstall: bash deploy/macos/uninstall.sh
set -euo pipefail

HOST="${1:-127.0.0.1}"
WORKSHOP_PORT="${2:-8080}"
NATS_URL="${NATS_URL:-nats://localhost:4222}"

# Detect loom binary
LOOM_BIN=$(which loom 2>/dev/null || echo "")
if [ -z "$LOOM_BIN" ]; then
    # Try uv-managed path
    LOOM_BIN="$HOME/.local/bin/loom"
    if [ ! -f "$LOOM_BIN" ]; then
        echo "Error: 'loom' not found in PATH. Install with: pip install loom[workshop]"
        exit 1
    fi
fi

echo "Using loom binary: $LOOM_BIN"
echo "NATS URL: $NATS_URL"
echo "Workshop host: $HOST:$WORKSHOP_PORT"

# Create log directory
LOG_DIR="$HOME/Library/Logs/loom"
mkdir -p "$LOG_DIR"

# Create plist directory
PLIST_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$PLIST_DIR"

# --- Workshop plist ---
cat > "$PLIST_DIR/com.loom.workshop.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.loom.workshop</string>
    <key>ProgramArguments</key>
    <array>
        <string>${LOOM_BIN}</string>
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
cat > "$PLIST_DIR/com.loom.router.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.loom.router</string>
    <key>ProgramArguments</key>
    <array>
        <string>${LOOM_BIN}</string>
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
launchctl load "$PLIST_DIR/com.loom.workshop.plist" 2>/dev/null || true
launchctl load "$PLIST_DIR/com.loom.router.plist" 2>/dev/null || true

echo ""
echo "Loom services installed and started:"
echo "  Workshop: http://${HOST}:${WORKSHOP_PORT}"
echo "  Router:   connected to ${NATS_URL}"
echo ""
echo "Logs: ${LOG_DIR}/"
echo "Uninstall: bash deploy/macos/uninstall.sh"
