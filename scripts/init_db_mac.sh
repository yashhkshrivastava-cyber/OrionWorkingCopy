#!/usr/bin/env bash
# Create the Orion role/database and apply the schema (macOS / Homebrew PostgreSQL).
# The database starts empty: no reference or sample rows are inserted.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA_DIR="$REPO_ROOT/.cursor/db"

DB_NAME="${ORION_DB_NAME:-orion}"
DB_USER="${ORION_DB_USER:-orion_user}"
DB_PASSWORD="${ORION_DB_PASSWORD:-orion_dev_password}"

run_pg() { psql -d postgres -v ON_ERROR_STOP=1 "$@"; }

if ! pg_isready -h "${ORION_DB_HOST:-localhost}" -p "${ORION_DB_PORT:-5432}" -q; then
  echo "PostgreSQL is not accepting connections. Start it with:" >&2
  echo "  brew services start postgresql@18" >&2
  exit 1
fi

if [ "$(run_pg -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'")" != "1" ]; then
  run_pg -c "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';"
else
  run_pg -c "ALTER ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';"
fi

if [ "$(run_pg -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'")" != "1" ]; then
  run_pg -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
fi

run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/schema.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/dw_schema.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/tally_ods_schema.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/tally_dw_schema.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/grants.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_app_user_contact.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_app_user_password_reset.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_app_user_tally_access.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_app_user_tally_dw_access.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_app_user_dashboard_access.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_signup_request.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_opportunity_tender_and_case.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_bill.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_case_transaction_bill.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_opportunity_fields.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_audit.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_capability_head.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_etl.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_app_user_billing_etl_access.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_backup.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_letterhead.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_client_group.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_employee_documents.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_documents.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_ai.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_chat.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_data_rules.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_auth_security.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_idempotency.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_bill_gst.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_bill_statutory.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_expense_payments.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_input_tax_credit.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_credit_notes.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_payroll.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_deductions.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_bank.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_tenders.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_contacts_emd.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_documents_filing.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_followups.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_attendance.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_gdrive.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_sql_lab.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_tasks.sql"
run_pg -d "${DB_NAME}" -f "${SCHEMA_DIR}/migrate_schema_migrations.sql"

echo "Orion database '${DB_NAME}' ready for user '${DB_USER}'."
