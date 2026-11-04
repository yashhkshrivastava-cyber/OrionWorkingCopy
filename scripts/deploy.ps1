# Deploy a released version of Orion into THIS folder (the production clone), safely.
# Usage:  .\scripts\deploy.ps1                      # latest origin/main
#         .\scripts\deploy.ps1 -Ref v1.0.0          # a tag (use this to roll back by hand, too)
#         .\scripts\deploy.ps1 -NoRestart           # prepare everything, do not switch the running server
#         .\scripts\deploy.ps1 -SkipBackup          # emergencies only: no safety dump of the database first
#         .\scripts\deploy.ps1 -Verify              # after starting prod from the shortcut: prove the new version is healthy
#
# What it does, in this order (the running server keeps serving until step 6):
#   1. remembers what is running now, so it can go back
#   2. checks out the new version (and, if this script itself changed, carries on with the new copy of it)
#   3. installs the pinned packages, then takes a safety dump of the production database and checks it reads back
#      (stops if it cannot). Nothing has touched the database yet, so the dump is the database as it was
#   4. checks the production settings, then applies the database schema (python -m app.migrate).
#      A failed migration STOPS the deploy here, with production untouched
#   5. builds the web app into a side folder, then swaps it in (the old one is kept for an instant rollback)
#   6. stops the old server, starts the new one, and runs a smoke test that proves the NEW code is answering and healthy
#   7. if the smoke test fails: puts the previous version back, restarts it and checks it, then exits with an error.
# Rolling back is code only. The database is not rolled back (migrations are additive, so the old code runs on the new schema);
# the safety dump from step 3 is the way back if data was damaged.
#Requires -Version 5.1
param(
    [string]$Ref = "origin/main",
    [switch]$NoRestart,
    [switch]$SkipBackup,
    [switch]$Verify,
    [string]$BackupDir = "C:\orion-backups",
    [int]$KeepBackups = 5,
    [int]$SmokeSeconds = 120,
    # Used only when this script starts itself again from the new version's copy (see "Resumed" below).
    [switch]$Resumed,
    [string]$PreviousSha = ""
)
$ErrorActionPreference = "Stop"

# Windows PowerShell 5.1 turns native-command stderr (git/npm/pip progress and warnings) into
# terminating errors under $ErrorActionPreference = "Stop". Judge success by exit code instead.
function Invoke-Native {
    param([scriptblock]$Command, [string]$What)
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command 2>&1 | ForEach-Object { Write-Host "$_" } } finally { $ErrorActionPreference = $old }
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}

# Like Invoke-Native, but answers $true or $false instead of throwing.
function Test-Native {
    param([scriptblock]$Command)
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command 2>&1 | ForEach-Object { Write-Host "$_" } } finally { $ErrorActionPreference = $old }
    return ($LASTEXITCODE -eq 0)
}

. "$PSScriptRoot\windows-common.ps1"
. "$PSScriptRoot\load-env.ps1" -RepoRoot (Get-RepoRoot)

$RepoRoot = Get-RepoRoot
Set-Location $RepoRoot
$Backend = Join-Path $RepoRoot "backend"
$Frontend = Join-Path $RepoRoot "frontend"
$port = if ($env:ORION_API_PORT) { [int]$env:ORION_API_PORT } else { 8100 }
$baseUrl = "http://127.0.0.1:$port"

# Safety: this script checks out a detached ref, which would clobber a dev working tree.
if ($env:ORION_ENV -ne "production") {
    Write-Error "ORION_ENV is not 'production' in $RepoRoot\.env. Refusing to deploy here (is this your dev folder?)."
}
if (git status --porcelain --untracked-files=no) {
    Write-Error "Production folder has local changes. Production must match GitHub; discard them (git restore .) and retry."
}

# ------------------------------------------------------------------------------------------------------------- helpers

function Get-Python {
    $python = Get-VenvPython -RepoRoot $RepoRoot
    if (-not $python) {
        Write-Host "==> Creating virtualenv"
        $sys = Get-PythonExe
        if (-not $sys) { throw "Python 3 not found" }
        Invoke-Native { & $sys -m venv (Join-Path $RepoRoot ".venv") } "venv creation"
        $python = Get-VenvPython -RepoRoot $RepoRoot
    }
    return $python
}

# Run a module of the application ("app.migrate", "app.deploy_tools backup ...") from the backend folder; throws on a non-zero exit.
function Invoke-Module {
    param([string[]]$ModuleArgs, [string]$What)
    Push-Location $Backend
    try { Invoke-Native { & $script:python -m @ModuleArgs } $What } finally { Pop-Location }
}

function Test-Module {
    param([string[]]$ModuleArgs)
    Push-Location $Backend
    try { return (Test-Native { & $script:python -m @ModuleArgs }) } finally { Pop-Location }
}

function Install-Packages {
    # -c pins every package, direct and transitive, to the versions the tests ran against (backend/constraints.txt).
    Invoke-Native { & $script:python -m pip install -q -r (Join-Path $Backend "requirements.txt") -c (Join-Path $Backend "constraints.txt") } "pip install"
}

function Stop-ProdServer {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $listener) { return }
    Write-Host "==> Stopping the current server (pid $($listener.OwningProcess)) on port $port"
    Stop-Process -Id $listener.OwningProcess -Force
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        if (-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) { return }
    }
    throw "The old server did not release port $port."
}

function Start-ProdServer {
    Write-Host "==> Starting the server in a new window"
    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "start-prod.ps1"))
}

function Test-Smoke {
    param([string]$Commit)
    Write-Host "==> Smoke test against $baseUrl (waits up to $SmokeSeconds s for the server)"
    return (Test-Module @("app.deploy_tools", "smoke", "--url", $baseUrl, "--commit", $Commit, "--timeout", "$SmokeSeconds"))
}

function Restore-Frontend {
    $dist = Join-Path $Frontend "dist"
    $previous = Join-Path $Frontend "dist.previous"
    if (Test-Path $previous) {
        if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
        Move-Item $previous $dist
        Write-Host "==> Restored the previous web app"
    }
}

# Put the previous version back. $SwitchedServer says whether the running server had already been replaced.
function Invoke-Rollback {
    param([string]$Sha, [bool]$SwitchedServer, [bool]$SwappedFrontend)
    Write-Warning "ROLLING BACK to $Sha"
    try {
        if ($SwitchedServer) { Stop-ProdServer }
        Invoke-Native { git checkout --detach $Sha } "git checkout $Sha"
        if ($SwappedFrontend) { Restore-Frontend }
        Install-Packages
        if ($SwitchedServer) {
            Start-ProdServer
            if (Test-Smoke $Sha) { Write-Host "==> Rolled back: $Sha is running again and passed its smoke test." }
            else { Write-Warning "The previous version was restored but its smoke test failed too. Look at the server window and Admin > System." }
        } else {
            Write-Host "==> Rolled back the files to $Sha. The server was never switched, so it is still running it."
        }
    } catch {
        Write-Warning "The rollback itself failed: $($_.Exception.Message). Run .\scripts\deploy.ps1 -Ref $Sha by hand."
    }
}

# ------------------------------------------------------------------------------------------------------------- -Verify
# For when prod is started by the desktop shortcut (deploy.ps1 -NoRestart, then the Orion PROD shortcut): the script never started the
# server, so it cannot test it. Run this afterwards: it proves the server now answering is the code in this folder and is healthy,
# and records the release. It changes nothing; on failure it says which version to go back to.
if ($Verify) {
    $script:python = Get-Python
    $head = (git rev-parse HEAD).Trim()
    $recordFile = Join-Path $RepoRoot "data\release.json"
    $recorded = if (Test-Path $recordFile) { Get-Content $recordFile -Raw | ConvertFrom-Json } else { $null }
    $before = if ($recorded -and $recorded.commit -and $recorded.commit -ne $head) { $recorded.commit } elseif ($recorded) { $recorded.previous } else { "" }
    if (Test-Smoke $head) {
        $label = (git describe --tags --exact-match HEAD 2>$null)
        if (-not $label) { $label = $head.Substring(0, 12) }
        Invoke-Module @("app.deploy_tools", "release", "--ref", "$label", "--commit", $head, "--previous=$before") "release record"
        Write-Host "==> Verified: the server on port $port is running $label and passed its smoke test."
        exit 0
    }
    Write-Host "VERIFICATION FAILED: the server on port $port is not healthy running $($head.Substring(0, 12))." -ForegroundColor Red
    if ($before) { Write-Host "To go back: stop the server, then .\scripts\deploy.ps1 -Ref $before -NoRestart, and start it again." }
    exit 1
}

# ------------------------------------------------------------------------------------------------------------ the deploy

$previousSha = if ($Resumed -and $PreviousSha) { $PreviousSha } else { (git rev-parse HEAD).Trim() }
$newSha = (git rev-parse HEAD).Trim()
$checkedOut = [bool]$Resumed
$swappedFrontend = $false
$switchedServer = $false
$dumpPath = $null
$script:python = $null

try {
    Write-Host "==> Running now: $previousSha ($(git log -1 --oneline $previousSha))"

    if (-not $Resumed) {
        Write-Host "==> Fetching $Ref"
        Invoke-Native { git fetch --tags origin } "git fetch"
        $target = (git rev-parse "$Ref^{commit}").Trim()
        if ($LASTEXITCODE -ne 0 -or -not $target) { throw "Cannot find $Ref. Is the tag or branch pushed?" }

        $scriptBefore = (Get-FileHash $PSCommandPath).Hash
        Write-Host "==> Checking out $Ref ($($target.Substring(0, 12)))"
        Invoke-Native { git checkout --detach $target } "git checkout $Ref"
        $checkedOut = $true
        $newSha = (git rev-parse HEAD).Trim()

        # This file is the one that was on disk BEFORE the checkout. If the new version changed it, carry on with the new copy, so a
        # release can improve the deploy it is deployed with (otherwise every improvement would only take effect one deploy late).
        if ((Get-FileHash $PSCommandPath).Hash -ne $scriptBefore) {
            Write-Host "==> deploy.ps1 changed in this version: continuing with the new copy"
            $again = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath, "-Ref", $Ref, "-Resumed", "-PreviousSha", $previousSha,
                "-BackupDir", $BackupDir, "-KeepBackups", "$KeepBackups", "-SmokeSeconds", "$SmokeSeconds")
            if ($NoRestart) { $again += "-NoRestart" }
            if ($SkipBackup) { $again += "-SkipBackup" }
            & powershell @again
            exit $LASTEXITCODE
        }
    }
    Invoke-Native { git log -1 --oneline } "git log"

    $script:python = Get-Python
    Write-Host "==> Installing backend dependencies"
    Install-Packages

    # After the packages (the dump uses the new version's own tools) and before anything touches the database.
    if (-not $SkipBackup) {
        Write-Host "==> Safety dump of the database (the way back if a release damages data)"
        Invoke-Module @("app.deploy_tools", "backup", "--dir", $BackupDir, "--label", ($Ref -replace '[^A-Za-z0-9._-]', '-'), "--keep", "$KeepBackups") "safety dump"
        $dumpPath = (Get-ChildItem $BackupDir -Filter "orion_*_before_*.dump" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
    } else {
        Write-Warning "-SkipBackup: no safety dump was taken."
    }

    # Stop here, before anything is stopped or built, if this machine's .env still holds development secrets.
    Write-Host "==> Checking production settings"
    Invoke-Module @("app.startup_checks") "production settings check"

    # The database schema. Applied BEFORE the server is touched: a migration that fails stops the deploy here and production is
    # exactly as it was. Migrations are additive, so the old code that is still running works on the new schema.
    Write-Host "==> Applying the database schema"
    Invoke-Module @("app.migrate") "database migration"

    Write-Host "==> Building the web app (into a side folder, so the running one is not disturbed)"
    Refresh-Path
    $fresh = Join-Path $Frontend "dist.new"
    if (Test-Path $fresh) { Remove-Item $fresh -Recurse -Force }
    Push-Location $Frontend
    try {
        Invoke-Native { npm ci } "npm ci"
        Invoke-Native { npm run build -- --outDir dist.new --emptyOutDir } "npm run build"
    } finally { Pop-Location }
    if (-not (Test-Path (Join-Path $fresh "index.html"))) { throw "The build finished but produced no index.html." }
    $dist = Join-Path $Frontend "dist"
    $previousDist = Join-Path $Frontend "dist.previous"
    if (Test-Path $previousDist) { Remove-Item $previousDist -Recurse -Force }
    if (Test-Path $dist) { Move-Item $dist $previousDist }
    Move-Item $fresh $dist
    $swappedFrontend = $true

    if ($NoRestart) {
        Write-Host "==> Done (-NoRestart). Nothing was stopped. Switch with scripts\start-prod.ps1 after stopping the server."
        return
    }

    Stop-ProdServer
    $switchedServer = $true
    Start-ProdServer
    if (-not (Test-Smoke $newSha)) { throw "The new version failed its smoke test." }

    Invoke-Module @("app.deploy_tools", "release", "--ref", $Ref, "--commit", $newSha, "--previous", $previousSha) "release record"
    Write-Host ""
    Write-Host "==> Deployed $Ref ($($newSha.Substring(0, 12))). Check Admin > System."
    if ($dumpPath) { Write-Host "    Safety dump (delete it when you are satisfied): $dumpPath" }
} catch {
    Write-Host ""
    Write-Host "DEPLOY FAILED: $($_.Exception.Message)" -ForegroundColor Red
    if ($checkedOut -and $newSha -ne $previousSha) {
        Invoke-Rollback -Sha $previousSha -SwitchedServer $switchedServer -SwappedFrontend $swappedFrontend
    } elseif ($switchedServer) {
        Invoke-Rollback -Sha $previousSha -SwitchedServer $true -SwappedFrontend $swappedFrontend
    }
    if ($dumpPath) {
        Write-Host "If data was damaged (the code rollback does not undo data), the database as it was before this deploy is in:"
        Write-Host "    $dumpPath"
    }
    exit 1
}
