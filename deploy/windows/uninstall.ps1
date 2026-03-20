# Uninstall Loom Windows background services.
$ErrorActionPreference = "SilentlyContinue"

foreach ($service in @("LoomWorkshop", "LoomRouter")) {
    nssm stop $service
    nssm remove $service confirm
    Write-Host "Removed: $service"
}

Write-Host ""
Write-Host "Loom services uninstalled."
Write-Host "Logs remain at: $env:LOCALAPPDATA\loom\logs\"
