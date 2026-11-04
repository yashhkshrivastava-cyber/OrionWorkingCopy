# Start Orion in production mode: one process serves the built UI and the API. No --reload.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\windows-common.ps1"
. "$PSScriptRoot\load-env.ps1" -RepoRoot (Get-RepoRoot)

$RepoRoot = Get-RepoRoot
Set-Location $RepoRoot

if ($env:ORION_ENV -ne "production") {
    Write-Error "ORION_ENV is not 'production' in $RepoRoot\.env. Refusing to start. Use start-modern.ps1 for development."
}

$DbHost = if ($env:ORION_DB_HOST) { $env:ORION_DB_HOST } else { "localhost" }
$DbPort = if ($env:ORION_DB_PORT) { [int]$env:ORION_DB_PORT } else { 5432 }

Start-PostgresService
if (-not (Test-PostgresReady -HostName $DbHost -Port $DbPort)) {
    Write-Error "PostgreSQL is not running."
}

$venvPython = Get-VenvPython -RepoRoot $RepoRoot
if (-not $venvPython) { Write-Error "Virtualenv missing. Run scripts\deploy.ps1 first." }

$env:ORION_SERVE_FRONTEND = "1"
$port = if ($env:ORION_API_PORT) { $env:ORION_API_PORT } else { "8100" }
Write-Host "Starting Orion (production) on http://127.0.0.1:$port"
& $venvPython -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $port
