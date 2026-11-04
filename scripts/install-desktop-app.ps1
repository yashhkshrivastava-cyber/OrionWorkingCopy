# Install the Orion Windows app (native window around the local site).
#Requires -Version 5.1
param(
    [switch]$Startup
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\windows-common.ps1"

$RepoRoot = Get-RepoRoot
Set-Location $RepoRoot

$venvPython = Get-VenvPython -RepoRoot $RepoRoot
if (-not $venvPython) {
    Write-Error "Virtualenv missing. Run: .\scripts\install-windows.ps1"
}

Write-Host "Installing the Orion window helper..."
& $venvPython -m pip install -q -r (Join-Path $RepoRoot "desktop\requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Could not install desktop/requirements.txt"
}

& $venvPython (Join-Path $RepoRoot "desktop\make_icon.py")
if ($LASTEXITCODE -ne 0) {
    throw "Could not build the Orion icon"
}

$pythonw = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"
$appPy = Join-Path $RepoRoot "desktop\app.py"
$ico = Join-Path $RepoRoot "desktop\Orion.ico"

if (-not (Test-Path $pythonw)) {
    Write-Error "pythonw.exe is missing from .venv\Scripts. Re-run .\scripts\install-windows.ps1"
}
if (-not (Test-Path $appPy)) {
    Write-Error "desktop\app.py is missing."
}

$supportDir = Join-Path $env:LOCALAPPDATA "Orion"
New-Item -ItemType Directory -Force -Path $supportDir | Out-Null
Set-Content -Path (Join-Path $supportDir "repo_root") -Value $RepoRoot -Encoding UTF8

function New-OrionShortcut {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    $folder = Split-Path $Path -Parent
    if (-not (Test-Path $folder)) {
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = "`"$appPy`""
    $shortcut.WorkingDirectory = $RepoRoot
    $shortcut.WindowStyle = 7
    $shortcut.Description = "Orion"
    if (Test-Path $ico) {
        $shortcut.IconLocation = "$ico,0"
    }
    $shortcut.Save()
}

$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = [Environment]::GetFolderPath("Programs")
$startupFolder = [Environment]::GetFolderPath("Startup")

$desktopLink = Join-Path $desktop "Orion.lnk"
$startMenuLink = Join-Path $startMenu "Orion.lnk"

New-OrionShortcut -Path $desktopLink
New-OrionShortcut -Path $startMenuLink

if ($Startup) {
    New-OrionShortcut -Path (Join-Path $startupFolder "Orion.lnk")
    Write-Host "Orion will also open when you sign in to Windows."
}

Write-Host ""
Write-Host "Orion is ready. Double-click the Orion icon on the Desktop or in the Start menu."
Write-Host "  Desktop:    $desktopLink"
Write-Host "  Start menu: $startMenuLink"
if (-not $Startup) {
    Write-Host ""
    Write-Host "To open Orion automatically when Windows starts:"
    Write-Host "  .\scripts\install-desktop-app.ps1 -Startup"
}
Write-Host ""
Write-Host "Opening Orion now..."
Start-Process -FilePath $pythonw -ArgumentList "`"$appPy`"" -WorkingDirectory $RepoRoot
