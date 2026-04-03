#!/usr/bin/env bash
# Uninstall Heddle background services from macOS launchd.
set -euo pipefail

PLIST_DIR="$HOME/Library/LaunchAgents"

for service in com.heddle.workshop com.heddle.router; do
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
echo "Heddle services uninstalled."
echo "Logs remain at: ~/Library/Logs/heddle/"
