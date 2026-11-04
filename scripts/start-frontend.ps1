# Start the Orion React frontend (Vite dev server).
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\windows-common.ps1"

$RepoRoot = Get-RepoRoot
$frontendDir = Join-Path $RepoRoot "frontend"
Set-Location $frontendDir

Refresh-Path
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) {
    Write-Error "Node.js/npm required. Install with: winget install OpenJS.NodeJS.LTS"
}

if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    npm install
}

Write-Host "Starting Orion frontend on http://localhost:5173 (also reachable on your Tailscale IP)"
npm run dev
