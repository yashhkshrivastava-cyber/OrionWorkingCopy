# Open Orion in a Windows window (starts local servers if needed).
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\windows-common.ps1"

$RepoRoot = Get-RepoRoot
$pythonw = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"
$appPy = Join-Path $RepoRoot "desktop\app.py"
$venvPython = Get-VenvPython -RepoRoot $RepoRoot

if (-not $venvPython -or -not (Test-Path $pythonw)) {
    Write-Error "Virtualenv missing. Run: .\scripts\install-windows.ps1"
}
if (-not (Test-Path $appPy)) {
    Write-Error "desktop\app.py is missing."
}

& $venvPython -c "import webview"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Desktop helper missing. Run: .\scripts\install-desktop-app.ps1"
}

Start-Process -FilePath $pythonw -ArgumentList "`"$appPy`"" -WorkingDirectory $RepoRoot
