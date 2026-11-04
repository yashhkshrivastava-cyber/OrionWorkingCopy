-- Personal details and documents kept on an employee. Idempotent: safe on existing databases, and applied on
-- every API start.
--
-- Aadhaar number, PAN and the monthly decided salary are plain columns of the employee. They are private: the
-- table preview and the Excel export leave them out for people who can only view operational data, and they are
-- not loaded into the warehouse, so dashboards and record history never carry them.

ALTER TABLE orion_ods.employee
    ADD COLUMN IF NOT EXISTS aadhaar_no     TEXT,
    ADD COLUMN IF NOT EXISTS pan_no         TEXT,
    ADD COLUMN IF NOT EXISTS monthly_salary NUMERIC(12, 2);

-- One row per file uploaded for an employee: the Aadhaar and PAN scans, and anything else worth keeping (bank
-- passbook, address proof, police verification, certificates, the appointment letter). The file itself is kept in
-- the database so the daily backup, which is encrypted, covers it; a folder on disk would not be. Written only by
-- app.employee_documents, and only people who can change operational data can read or write it.
CREATE TABLE IF NOT EXISTS orion_ods.employee_document (
    document_id        SERIAL PRIMARY KEY,
    employee_code      TEXT NOT NULL REFERENCES orion_ods.employee(employee_code) ON DELETE CASCADE,
    doc_type           TEXT NOT NULL,
    title              TEXT,
    file_name          TEXT NOT NULL,
    content_type       TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL,
    file_data          BYTEA NOT NULL,
    uploaded_by        INTEGER,
    uploaded_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_employee_document_employee ON orion_ods.employee_document (employee_code, document_id);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON orion_ods.employee_document TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.employee_document_document_id_seq TO orion_user;
    END IF;
END $$;
