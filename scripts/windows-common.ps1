# Shared helpers for Orion Windows scripts.

function Refresh-Path {
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    if ($machinePath -and $userPath) {
        $env:Path = "$machinePath;$userPath"
    }
}

function Get-RepoRoot {
    return (Split-Path $PSScriptRoot -Parent)
}

function Find-PostgresBin {
    Refresh-Path
    $pgIsReady = Get-Command pg_isready.exe -ErrorAction SilentlyContinue
    if ($pgIsReady) {
        return (Split-Path $pgIsReady.Source -Parent)
    }
    $candidates = 18..14 | ForEach-Object {
        Join-Path ${env:ProgramFiles} "PostgreSQL\$_\bin"
    }
    foreach ($dir in $candidates) {
        if (Test-Path (Join-Path $dir "psql.exe")) {
            return $dir
        }
    }
    return $null
}

function Test-PostgresReady {
    param(
        [string]$HostName = "localhost",
        [int]$Port = 5432
    )
    $bin = Find-PostgresBin
    if ($bin) {
        $pgIsReady = Join-Path $bin "pg_isready.exe"
        & $pgIsReady -h $HostName -p $Port -q
        return ($LASTEXITCODE -eq 0)
    }
    try {
        $tcp = Test-NetConnection -ComputerName $HostName -Port $Port -WarningAction SilentlyContinue
        return [bool]$tcp.TcpTestSucceeded
    } catch {
        return $false
    }
}

function Start-PostgresService {
    $service = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Where-Object { $_.Status -ne "Running" } | Select-Object -First 1
    if ($service) {
        Write-Host "Starting PostgreSQL service: $($service.Name)"
        Start-Service $service.Name
        Start-Sleep -Seconds 2
    }
}

function Get-PythonExe {
    Refresh-Path
    foreach ($name in @("python", "python3", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            $version = & $cmd.Source --version 2>&1
            if ($version -match "Python 3\.(1[0-9]|[0-9])") {
                return $cmd.Source
            }
        }
    }
    return $null
}

function Get-VenvPython {
    param([string]$RepoRoot)
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    return $null
}

function Get-TailscaleExe {
    Refresh-Path
    $cmd = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $defaultPath = Join-Path ${env:ProgramFiles} "Tailscale\tailscale.exe"
    if (Test-Path $defaultPath) { return $defaultPath }
    return $null
}
