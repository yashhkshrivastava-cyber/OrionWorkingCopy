# Create the Orion role/database and apply the schema (Windows / PostgreSQL installer).
# The database starts empty: no reference or sample rows are inserted.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\windows-common.ps1"
. "$PSScriptRoot\load-env.ps1" -RepoRoot (Get-RepoRoot)

$RepoRoot = Get-RepoRoot
$SchemaDir = Join-Path $RepoRoot ".cursor\db"

$DbName = if ($env:ORION_DB_NAME) { $env:ORION_DB_NAME } else { "orion" }
$DbUser = if ($env:ORION_DB_USER) { $env:ORION_DB_USER } else { "orion_user" }
$DbPassword = if ($env:ORION_DB_PASSWORD) { $env:ORION_DB_PASSWORD } else { "orion_dev_password" }
$DbHost = if ($env:ORION_DB_HOST) { $env:ORION_DB_HOST } else { "localhost" }
$DbPort = if ($env:ORION_DB_PORT) { [int]$env:ORION_DB_PORT } else { 5432 }

Start-PostgresService

if (-not (Test-PostgresReady -HostName $DbHost -Port $DbPort)) {
    Write-Error @"
PostgreSQL is not accepting connections on ${DbHost}:${DbPort}.
Install PostgreSQL 18, then start the Windows service (Services -> postgresql-x64-18).
"@
}

$pgBin = Find-PostgresBin
if (-not $pgBin) {
    Write-Error "Could not find psql.exe. Re-open PowerShell after installing PostgreSQL, or add its bin folder to PATH."
}
$psql = Join-Path $pgBin "psql.exe"

$superUser = if ($env:ORION_POSTGRES_SUPERUSER) { $env:ORION_POSTGRES_SUPERUSER } else { "postgres" }
if (-not $env:PGPASSWORD) {
    if ($env:ORION_POSTGRES_SUPER_PASSWORD) {
        $env:PGPASSWORD = $env:ORION_POSTGRES_SUPER_PASSWORD
    } else {
        $secure = Read-Host "Enter PostgreSQL superuser ($superUser) password" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    }
}

function Invoke-Psql {
    param(
        [string[]]$PsqlArgs
    )
    & $psql -h $DbHost -p $DbPort -U $superUser -v ON_ERROR_STOP=1 @PsqlArgs
    if ($LASTEXITCODE -ne 0) {
        throw "psql failed (exit $LASTEXITCODE)"
    }
}

$roleExists = (& $psql -h $DbHost -p $DbPort -U $superUser -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DbUser'" 2>$null)
if ($null -eq $roleExists) { $roleExists = "" }
$roleExists = $roleExists.Trim()
if ($roleExists -ne "1") {
    Invoke-Psql -PsqlArgs @("-d", "postgres", "-c", "CREATE ROLE $DbUser LOGIN PASSWORD '$DbPassword';")
} else {
    Invoke-Psql -PsqlArgs @("-d", "postgres", "-c", "ALTER ROLE $DbUser LOGIN PASSWORD '$DbPassword';")
}

$dbExists = (& $psql -h $DbHost -p $DbPort -U $superUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DbName'" 2>$null)
if ($null -eq $dbExists) { $dbExists = "" }
$dbExists = $dbExists.Trim()
if ($dbExists -ne "1") {
    Invoke-Psql -PsqlArgs @("-d", "postgres", "-c", "CREATE DATABASE $DbName OWNER $DbUser;")
}

foreach ($file in @("schema.sql", "dw_schema.sql", "tally_ods_schema.sql", "tally_dw_schema.sql", "grants.sql", "migrate_app_user_contact.sql", "migrate_app_user_password_reset.sql", "migrate_app_user_tally_access.sql", "migrate_app_user_tally_dw_access.sql", "migrate_app_user_dashboard_access.sql", "migrate_signup_request.sql", "migrate_opportunity_tender_and_case.sql", "migrate_bill.sql", "migrate_case_transaction_bill.sql", "migrate_opportunity_fields.sql", "migrate_audit.sql", "migrate_capability_head.sql", "migrate_etl.sql", "migrate_app_user_billing_etl_access.sql", "migrate_backup.sql", "migrate_letterhead.sql", "migrate_client_group.sql", "migrate_employee_documents.sql", "migrate_documents.sql", "migrate_ai.sql", "migrate_chat.sql", "migrate_data_rules.sql", "migrate_auth_security.sql", "migrate_idempotency.sql", "migrate_bill_gst.sql", "migrate_bill_statutory.sql", "migrate_expense_payments.sql", "migrate_input_tax_credit.sql", "migrate_credit_notes.sql", "migrate_payroll.sql", "migrate_deductions.sql", "migrate_bank.sql", "migrate_tenders.sql", "migrate_contacts_emd.sql", "migrate_documents_filing.sql", "migrate_followups.sql", "migrate_attendance.sql", "migrate_gdrive.sql", "migrate_sql_lab.sql", "migrate_tasks.sql", "migrate_schema_migrations.sql")) {
    $path = Join-Path $SchemaDir $file
    if (-not (Test-Path $path)) {
        throw "Missing schema file: $path"
    }
    Invoke-Psql -PsqlArgs @("-d", $DbName, "-f", $path)
}

Write-Host "Orion database '$DbName' ready for user '$DbUser'."
