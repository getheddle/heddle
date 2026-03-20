#!/usr/bin/env bash
# Uninstall Loom background services from macOS launchd.
set -euo pipefail

PLIST_DIR="$HOME/Library/LaunchAgents"

for service in com.loom.workshop com.loom.router; do
    plist="$PLIST_DIR/${service}.plist"
    if [ -f "$plist" ]; then
        launchctl unload "$plist" 2>/dev/null || true
        rm -f "$plist"
        echo "Removed: $service"
    else
        echo "Not found: $service (skipped)"
    fi
done

echo ""
echo "Loom services uninstalled."
echo "Logs remain at: ~/Library/Logs/loom/"
