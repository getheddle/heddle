# Uninstall Heddle Windows background services.
$ErrorActionPreference = "SilentlyContinue"

foreach ($service in @("HeddleWorkshop", "HeddleRouter")) {
    nssm stop $service
    nssm remove $service confirm
    Write-Host "Removed: $service"
}

Write-Host ""
Write-Host "Heddle services uninstalled."
Write-Host "Logs remain at: $env:LOCALAPPDATA\heddle\logs\"
