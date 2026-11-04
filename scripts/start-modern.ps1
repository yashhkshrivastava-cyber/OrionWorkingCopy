# Start both Orion API and React frontend in separate PowerShell windows.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\load-env.ps1" -RepoRoot (Split-Path $PSScriptRoot -Parent)

$apiPort = if ($env:ORION_API_PORT) { $env:ORION_API_PORT } else { "8000" }

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $PSScriptRoot "start-api.ps1")
)

Start-Sleep -Seconds 2

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $PSScriptRoot "start-frontend.ps1")
)

Write-Host ""
Write-Host "Orion modern stack starting in two windows:"
Write-Host "  Frontend: http://localhost:5173"
Write-Host "  API:      http://127.0.0.1:$apiPort"
Write-Host ""
Write-Host "Close each window to stop that service."
