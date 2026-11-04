# Expose Orion over HTTPS on your tailnet (requires Tailscale app + login).
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\windows-common.ps1"
. "$PSScriptRoot\load-env.ps1" -RepoRoot (Get-RepoRoot)

# The React UI (Vite). It proxies /api to the API, so one port serves the whole app.
$port = if ($env:ORION_FRONTEND_PORT) { $env:ORION_FRONTEND_PORT } else { "5173" }
$tailscale = Get-TailscaleExe

if (-not $tailscale) {
    Write-Error @"
Install Tailscale first:
  winget install Tailscale.Tailscale
  Sign in from the Tailscale app in the system tray.
"@
}

& $tailscale status --peers=false | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Tailscale is not connected. Open the Tailscale app and sign in."
}

try {
    Invoke-WebRequest -Uri "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 3 | Out-Null
} catch {
    Write-Error "Orion frontend is not running on port $port. Start it with: .\scripts\start-modern.ps1"
}

$tsIp = (& $tailscale ip -4).Trim()
Write-Host "Orion tailnet URLs:"
Write-Host "  HTTP:  http://${tsIp}:$port"

$json = & $tailscale status --json 2>$null | ConvertFrom-Json
$dnsName = $json.Self.DNSName
if ($dnsName) {
    $dnsName = $dnsName.TrimEnd(".")
    Write-Host "  HTTPS: https://$dnsName"
}

Write-Host ""
Write-Host "Enabling Tailscale Serve (HTTPS on port 443)..."
& $tailscale serve --bg --https=443 "http://127.0.0.1:$port"
& $tailscale serve status

Write-Host ""
Write-Host "Install Tailscale on phones/tablets/other devices and open the HTTPS URL above."
