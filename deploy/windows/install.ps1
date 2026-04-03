# Install Heddle as Windows background services using NSSM.
#
# Prerequisites:
#   - Python 3.11+ with heddle installed (pip install heddle-ai[workshop])
#   - NSSM (Non-Sucking Service Manager): choco install nssm
#   - NATS server running (choco install nats-server, or Docker)
#
# Usage:
#   .\deploy\windows\install.ps1
#   .\deploy\windows\install.ps1 -Host "0.0.0.0"  # LAN access
#
# Services:
#   - HeddleWorkshop: Web UI on port 8080
#   - HeddleRouter: Deterministic task router
#
# Uninstall: .\deploy\windows\uninstall.ps1

param(
    [string]$Host = "127.0.0.1",
    [int]$WorkshopPort = 8080,
    [string]$NatsUrl = "nats://localhost:4222",
    [switch]$SkipChecks = $false
)

$ErrorActionPreference = "Stop"

Write-Host "=== Heddle Service Installer (Windows) ===" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

if (-not $SkipChecks) {
    # Check for admin privileges (NSSM services may need admin)
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Host "Warning: Not running as Administrator." -ForegroundColor Yellow
        Write-Host "  NSSM service installation may require admin privileges."
        Write-Host "  Try: Right-click PowerShell > 'Run as Administrator'"
        Write-Host ""
    }

    # Check for existing services
    $existingWorkshop = Get-Service -Name "HeddleWorkshop" -ErrorAction SilentlyContinue
    if ($existingWorkshop) {
        Write-Host "Warning: HeddleWorkshop service already exists (status: $($existingWorkshop.Status))." -ForegroundColor Yellow
        Write-Host "  Run '.\deploy\windows\uninstall.ps1' first to remove the old installation."
        Write-Host ""
    }
}

# Check NSSM
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Host "Error: NSSM not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Install with Chocolatey:"
    Write-Host "    choco install nssm"
    Write-Host ""
    Write-Host "  Or download from: https://nssm.cc/download"
    exit 1
}

# Find heddle binary
$HeddleBin = (Get-Command heddle -ErrorAction SilentlyContinue).Source
if (-not $HeddleBin) {
    # Try common Python script locations
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\Scripts\heddle.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\Scripts\heddle.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\heddle.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            $HeddleBin = $candidate
            break
        }
    }
    if (-not $HeddleBin) {
        Write-Host "Error: 'heddle' not found in PATH." -ForegroundColor Red
        Write-Host ""
        Write-Host "  Install with:"
        Write-Host "    pip install heddle-ai[workshop]"
        Write-Host ""
        Write-Host "  Searched paths:"
        foreach ($c in $candidates) {
            Write-Host "    $c"
        }
        exit 1
    }
}

# Verify heddle binary works
try {
    & $HeddleBin --help | Out-Null
} catch {
    Write-Host "Error: '$HeddleBin' exists but is not executable." -ForegroundColor Red
    Write-Host "  Try running: & '$HeddleBin' --help"
    exit 1
}

Write-Host "Binary: $HeddleBin"
Write-Host "NATS:   $NatsUrl"
Write-Host "Workshop: ${Host}:${WorkshopPort}"
Write-Host ""

# Check NATS availability (non-blocking warning)
if (-not $SkipChecks) {
    $natsHost = $NatsUrl -replace "nats://", "" -replace ":.*", ""
    $natsPort = ($NatsUrl -replace "nats://.*:", "") -as [int]
    if (-not $natsPort) { $natsPort = 4222 }

    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect($natsHost, $natsPort)
        $tcp.Close()
        Write-Host "NATS: reachable" -ForegroundColor Green
    } catch {
        Write-Host "Warning: NATS not reachable at $NatsUrl" -ForegroundColor Yellow
        Write-Host "  The router will retry connecting automatically."
        Write-Host "  To start NATS: docker run -d -p 4222:4222 nats:latest"
        Write-Host ""
    }
}

# ---------------------------------------------------------------------------
# Install services
# ---------------------------------------------------------------------------

# Create log directory
$LogDir = Join-Path $env:LOCALAPPDATA "heddle\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Remove existing services if present (clean reinstall)
foreach ($svc in @("HeddleWorkshop", "HeddleRouter")) {
    if (Get-Service -Name $svc -ErrorAction SilentlyContinue) {
        nssm stop $svc 2>$null
        nssm remove $svc confirm 2>$null
        Write-Host "Removed existing: $svc"
    }
}

# --- Workshop service ---
nssm install HeddleWorkshop "$HeddleBin" "workshop --host $Host --port $WorkshopPort"
nssm set HeddleWorkshop AppStdout (Join-Path $LogDir "workshop.log")
nssm set HeddleWorkshop AppStderr (Join-Path $LogDir "workshop.err")
nssm set HeddleWorkshop Start SERVICE_AUTO_START
nssm set HeddleWorkshop AppRestartDelay 10000

# --- Router service ---
nssm install HeddleRouter "$HeddleBin" "router --nats-url $NatsUrl"
nssm set HeddleRouter AppStdout (Join-Path $LogDir "router.log")
nssm set HeddleRouter AppStderr (Join-Path $LogDir "router.err")
nssm set HeddleRouter Start SERVICE_AUTO_START
nssm set HeddleRouter AppRestartDelay 10000

# Start services
nssm start HeddleWorkshop
nssm start HeddleRouter

# ---------------------------------------------------------------------------
# Post-install health check
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Heddle services installed and started." -ForegroundColor Green

Start-Sleep -Seconds 2
try {
    $response = Invoke-WebRequest -Uri "http://${Host}:${WorkshopPort}/health" -TimeoutSec 3 -ErrorAction SilentlyContinue
    if ($response.StatusCode -eq 200) {
        Write-Host "  Workshop: http://${Host}:${WorkshopPort} [healthy]" -ForegroundColor Green
    }
} catch {
    Write-Host "  Workshop: http://${Host}:${WorkshopPort} [starting...]"
    Write-Host "    Check logs if it doesn't come up: Get-Content '$LogDir\workshop.err'"
}
Write-Host "  Router:   connected to $NatsUrl"
Write-Host ""
Write-Host "Logs: $LogDir"
Write-Host "Uninstall: .\deploy\windows\uninstall.ps1"
Write-Host "Update: .\deploy\windows\uninstall.ps1; .\deploy\windows\install.ps1"
