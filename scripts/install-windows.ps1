# Bootstrap Orion on Windows (PostgreSQL + Python venv + Node frontend deps).
#Requires -Version 5.1
# Run from an elevated PowerShell if winget installs fail with access denied.
param(
    [switch]$SkipWinget,
    [switch]$SkipDbInit
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\windows-common.ps1"

$RepoRoot = Get-RepoRoot
Set-Location $RepoRoot

function Install-WingetPackage {
    param(
        [string]$Id,
        [string]$Label
    )
    $installed = winget list --id $Id --accept-source-agreements 2>$null
    if ($LASTEXITCODE -eq 0 -and $installed -match [regex]::Escape($Id)) {
        Write-Host "$Label already installed."
        return
    }
    Write-Host "Installing $Label..."
    winget install --id $Id -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget install failed for $Id. Try running this script in an elevated PowerShell."
    }
}

if (-not $SkipWinget) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Error "winget is required. Install App Installer from the Microsoft Store, then re-run this script."
    }
    Install-WingetPackage -Id "Python.Python.3.12" -Label "Python 3.12"
    Install-WingetPackage -Id "OpenJS.NodeJS.LTS" -Label "Node.js LTS"
    Install-WingetPackage -Id "PostgreSQL.PostgreSQL.18" -Label "PostgreSQL 18"
    Install-WingetPackage -Id "PostgreSQL.pgAdmin" -Label "pgAdmin 4"
    Write-Host ""
    Write-Host "If PostgreSQL asked for a superuser password during install, add it to .env as:"
    Write-Host "  ORION_POSTGRES_SUPER_PASSWORD=your-postgres-password"
    Write-Host ""
}

Refresh-Path
Start-PostgresService

$python = Get-PythonExe
if (-not $python) {
    throw "Python 3 not found on PATH. Re-open PowerShell after install, or run with -SkipWinget after installing Python manually."
}

$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    if (Test-Path (Join-Path $RepoRoot ".venv")) {
        Remove-Item -Recurse -Force (Join-Path $RepoRoot ".venv")
    }
    & $python -m venv (Join-Path $RepoRoot ".venv")
}

$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $RepoRoot "backend\requirements.txt") -c (Join-Path $RepoRoot "backend\constraints.txt")

if (-not (Test-Path (Join-Path $RepoRoot ".env"))) {
    Copy-Item (Join-Path $RepoRoot ".env.example") (Join-Path $RepoRoot ".env")
    Write-Host "Created .env from .env.example - update passwords before exposing on Tailscale."
}

if (-not $SkipDbInit) {
    & (Join-Path $PSScriptRoot "init_db_windows.ps1")
}

$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) {
    Write-Warning "npm not found. Re-open PowerShell after Node.js install, then run: cd frontend; npm install"
} else {
    Push-Location (Join-Path $RepoRoot "frontend")
    npm install
    Pop-Location
}

$tailscale = Get-TailscaleExe
if (-not $tailscale) {
    Write-Host ""
    Write-Host "Optional: install Tailscale to reach Orion from other devices:"
    Write-Host "  winget install Tailscale.Tailscale"
    Write-Host "  Sign in, then run: .\scripts\tailscale-serve.ps1"
}

Write-Host ""
Write-Host "Install complete. Create a Desktop / Start menu shortcut (no terminal):"
Write-Host "  .\scripts\install-desktop-app.ps1"
Write-Host ""
Write-Host "Or start from PowerShell:"
Write-Host "  .\scripts\start-desktop.ps1"
Write-Host "  .\scripts\start-modern.ps1"
