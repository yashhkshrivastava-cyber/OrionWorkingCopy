-- Who created and who last changed each business record, and who deleted one.
-- Idempotent: safe on existing databases, and applied on every API start.
--
-- The ODS stays a working copy of current values. History lives in the warehouse, which copies
-- these columns into each version it keeps (orion_dw.*.source_created_by, source_last_updated_by).
-- The ids are app_user.id with no foreign key, so removing a user never blocks anything; a
-- history entry whose user is gone is shown as a former user. Rows saved before this file was
-- applied have no user.
--
-- orion_ods.bill is not listed: it already carries created_by and version_by, and keeps every
-- version in bill_version.

ALTER TABLE orion_ods.business_domain       ADD COLUMN IF NOT EXISTS created_by INTEGER, ADD COLUMN IF NOT EXISTS last_updated_by INTEGER;
ALTER TABLE orion_ods.capability            ADD COLUMN IF NOT EXISTS created_by INTEGER, ADD COLUMN IF NOT EXISTS last_updated_by INTEGER;
ALTER TABLE orion_ods.expense_type          ADD COLUMN IF NOT EXISTS created_by INTEGER, ADD COLUMN IF NOT EXISTS last_updated_by INTEGER;
ALTER TABLE orion_ods.client                ADD COLUMN IF NOT EXISTS created_by INTEGER, ADD COLUMN IF NOT EXISTS last_updated_by INTEGER;
ALTER TABLE orion_ods.case                  ADD COLUMN IF NOT EXISTS created_by INTEGER, ADD COLUMN IF NOT EXISTS last_updated_by INTEGER;
ALTER TABLE orion_ods.opportunity           ADD COLUMN IF NOT EXISTS created_by INTEGER, ADD COLUMN IF NOT EXISTS last_updated_by INTEGER;
ALTER TABLE orion_ods.employee              ADD COLUMN IF NOT EXISTS created_by INTEGER, ADD COLUMN IF NOT EXISTS last_updated_by INTEGER;
ALTER TABLE orion_ods.car                   ADD COLUMN IF NOT EXISTS created_by INTEGER, ADD COLUMN IF NOT EXISTS last_updated_by INTEGER;
ALTER TABLE orion_ods.case_transaction      ADD COLUMN IF NOT EXISTS created_by INTEGER, ADD COLUMN IF NOT EXISTS last_updated_by INTEGER;
ALTER TABLE orion_ods.expense_transaction   ADD COLUMN IF NOT EXISTS created_by INTEGER, ADD COLUMN IF NOT EXISTS last_updated_by INTEGER;
ALTER TABLE orion_ods.employee_transaction  ADD COLUMN IF NOT EXISTS created_by INTEGER, ADD COLUMN IF NOT EXISTS last_updated_by INTEGER;
ALTER TABLE orion_ods.car_transaction       ADD COLUMN IF NOT EXISTS created_by INTEGER, ADD COLUMN IF NOT EXISTS last_updated_by INTEGER;

-- A deleted row leaves nothing behind, so who removed it is written here. The warehouse reads it
-- when it marks the record expired. Codes come from sequences and are never reused.
CREATE TABLE IF NOT EXISTS orion_ods.record_deleted (
    id                SERIAL PRIMARY KEY,
    table_name        TEXT NOT NULL,
    record_code       TEXT NOT NULL,
    deleted_by        INTEGER,
    deleted_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_record_deleted_record
    ON orion_ods.record_deleted (table_name, record_code, deleted_timestamp DESC);
