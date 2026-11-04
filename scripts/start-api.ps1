# Start the Orion FastAPI backend.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\windows-common.ps1"
. "$PSScriptRoot\load-env.ps1" -RepoRoot (Get-RepoRoot)

$RepoRoot = Get-RepoRoot
Set-Location $RepoRoot

$DbHost = if ($env:ORION_DB_HOST) { $env:ORION_DB_HOST } else { "localhost" }
$DbPort = if ($env:ORION_DB_PORT) { [int]$env:ORION_DB_PORT } else { 5432 }

Start-PostgresService
if (-not (Test-PostgresReady -HostName $DbHost -Port $DbPort)) {
    Write-Error "PostgreSQL is not running. Start the postgresql-x64-18 Windows service, or run .\scripts\install-windows.ps1"
}

$venvPython = Get-VenvPython -RepoRoot $RepoRoot
if (-not $venvPython) {
    Write-Error "Virtualenv missing. Run: .\scripts\install-windows.ps1"
}

& $venvPython -m pip install -q -r (Join-Path $RepoRoot "backend\requirements.txt") -c (Join-Path $RepoRoot "backend\constraints.txt")

$port = if ($env:ORION_API_PORT) { $env:ORION_API_PORT } else { "8000" }
Write-Host "Starting Orion API on http://127.0.0.1:$port"
& $venvPython -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $port --reload
