# Install the "Orion PROD" desktop shortcut (native window around production).
# Run once in the production folder, after the first deploy:
#   cd C:\orion-prod; .\scripts\install-prod-desktop-app.ps1
#Requires -Version 5.1
param(
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\windows-common.ps1"
. "$PSScriptRoot\load-env.ps1" -RepoRoot (Get-RepoRoot)

$RepoRoot = Get-RepoRoot
Set-Location $RepoRoot

if ($env:ORION_ENV -ne "production") {
    Write-Error "ORION_ENV is not 'production' in $RepoRoot\.env. Run this in the production folder. For development use install-desktop-app.ps1."
}

$venvPython = Get-VenvPython -RepoRoot $RepoRoot
if (-not $venvPython) {
    Write-Error "Virtualenv missing. Run: .\scripts\deploy.ps1"
}

Write-Host "Installing the Orion window helper..."
& $venvPython -m pip install -q -r (Join-Path $RepoRoot "desktop\requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Could not install desktop/requirements.txt"
}

$pythonw = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"
$appPy = Join-Path $RepoRoot "desktop\prod_app.py"
$ico = Join-Path $RepoRoot "desktop\OrionProd.ico"

if (-not (Test-Path $pythonw)) {
    Write-Error "pythonw.exe is missing from .venv\Scripts. Re-run .\scripts\deploy.ps1"
}
if (-not (Test-Path $appPy)) {
    Write-Error "desktop\prod_app.py is missing. Deploy a version that includes it."
}

# The shortcut must point only at files in this folder. Anything under AppData can be
# invisible to Explorer when it was written by a packaged (Microsoft Store) app.
$desktopLink = Join-Path ([Environment]::GetFolderPath("Desktop")) "Orion PROD.lnk"
if (Test-Path $desktopLink) {
    Remove-Item $desktopLink -Force
}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($desktopLink)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "`"$appPy`""
$shortcut.WorkingDirectory = $RepoRoot
$shortcut.WindowStyle = 7
$shortcut.Description = "Orion (production)"
if (Test-Path $ico) {
    $shortcut.IconLocation = "$ico,0"
}
$shortcut.Save()

Write-Host ""
Write-Host "Orion PROD is ready. Double-click the Orion PROD icon on the Desktop."
Write-Host "  Desktop: $desktopLink"
Write-Host "  Logs:    $RepoRoot\data\prod-desktop.log and prod-server.log"

if (-not $NoLaunch) {
    Write-Host ""
    Write-Host "Opening Orion PROD now..."
    Start-Process -FilePath $pythonw -ArgumentList "`"$appPy`"" -WorkingDirectory $RepoRoot
}
