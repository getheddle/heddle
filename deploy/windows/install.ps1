# Install Loom as Windows background services using NSSM.
#
# Prerequisites:
#   - Python 3.11+ with loom installed (pip install loom[workshop])
#   - NSSM (Non-Sucking Service Manager): choco install nssm
#   - NATS server running (choco install nats-server, or Docker)
#
# Usage:
#   .\deploy\windows\install.ps1
#   .\deploy\windows\install.ps1 -Host "0.0.0.0"  # LAN access
#
# Services:
#   - LoomWorkshop: Web UI on port 8080
#   - LoomRouter: Deterministic task router
#
# Uninstall: .\deploy\windows\uninstall.ps1

param(
    [string]$Host = "127.0.0.1",
    [int]$WorkshopPort = 8080,
    [string]$NatsUrl = "nats://localhost:4222"
)

$ErrorActionPreference = "Stop"

# Check NSSM
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Error "NSSM not found. Install with: choco install nssm"
    exit 1
}

# Find loom binary
$LoomBin = (Get-Command loom -ErrorAction SilentlyContinue).Source
if (-not $LoomBin) {
    $LoomBin = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\Scripts\loom.exe"
    if (-not (Test-Path $LoomBin)) {
        Write-Error "loom not found in PATH. Install with: pip install loom[workshop]"
        exit 1
    }
}

Write-Host "Using loom binary: $LoomBin"
Write-Host "NATS URL: $NatsUrl"

# Create log directory
$LogDir = Join-Path $env:LOCALAPPDATA "loom\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# --- Workshop service ---
nssm install LoomWorkshop "$LoomBin" "workshop --host $Host --port $WorkshopPort"
nssm set LoomWorkshop AppStdout (Join-Path $LogDir "workshop.log")
nssm set LoomWorkshop AppStderr (Join-Path $LogDir "workshop.err")
nssm set LoomWorkshop Start SERVICE_AUTO_START
nssm set LoomWorkshop AppRestartDelay 10000

# --- Router service ---
nssm install LoomRouter "$LoomBin" "router --nats-url $NatsUrl"
nssm set LoomRouter AppStdout (Join-Path $LogDir "router.log")
nssm set LoomRouter AppStderr (Join-Path $LogDir "router.err")
nssm set LoomRouter Start SERVICE_AUTO_START
nssm set LoomRouter AppRestartDelay 10000

# Start services
nssm start LoomWorkshop
nssm start LoomRouter

Write-Host ""
Write-Host "Loom services installed and started:"
Write-Host "  Workshop: http://${Host}:${WorkshopPort}"
Write-Host "  Router:   connected to $NatsUrl"
Write-Host ""
Write-Host "Logs: $LogDir"
Write-Host "Uninstall: .\deploy\windows\uninstall.ps1"
