-- The SQL editor (Admin > SQL editor). Idempotent: safe on existing databases, applied on every API start.
--
-- Written only by app.sql_lab. Nothing here is loaded into the warehouse.

-- Where views and scratch tables made in the SQL editor live. Structure can be changed in this schema and nowhere else from the editor
-- (Orion's own schemas change through the schema files); everything made here can be dropped without touching the application.
CREATE SCHEMA IF NOT EXISTS reports;

-- The users, without anything secret: the editor cannot read orion_ods.app_user (it holds the password hashes and reset tokens).
CREATE OR REPLACE VIEW reports.users AS
SELECT id, username, display_name, role, is_active, email, phone, created_timestamp, updated_timestamp,
       ods_access, ods_write, dw_access, dw_write, tally_access, tally_write, tally_dw_access, tally_dw_write,
       orion_dashboard_access, tally_dashboard_access, billing_access, billing_write, etl_access, etl_write,
       letterhead_access, letterhead_write, documents_access, documents_write, bank_access, bank_write,
       tenders_access, tenders_write, attendance_access, attendance_write, ai_access
  FROM orion_ods.app_user;

-- A query kept by an administrator to run again. `shared` lets the other administrators see it (they can copy it, not change it).
CREATE TABLE IF NOT EXISTS orion_ods.sql_saved_query (
    query_id          SERIAL PRIMARY KEY,
    owner_id          INTEGER NOT NULL,
    title             TEXT NOT NULL,
    folder            TEXT,
    description       TEXT,
    sql_text          TEXT NOT NULL,
    shared            BOOLEAN NOT NULL DEFAULT FALSE,
    created_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_sql_saved_query_owner ON orion_ods.sql_saved_query (owner_id, lower(title));

-- Every run, kept for good: who, what, in which mode, how it ended. The editor itself cannot change or remove these rows.
CREATE TABLE IF NOT EXISTS orion_ods.sql_query_log (
    log_id         BIGSERIAL PRIMARY KEY,
    user_id        INTEGER,
    username       TEXT,
    sql_text       TEXT NOT NULL,
    mode           TEXT NOT NULL CHECK (mode IN ('read', 'write')),
    status         TEXT NOT NULL CHECK (status IN ('ok', 'error', 'blocked', 'cancelled')),
    statements     INTEGER NOT NULL DEFAULT 0,
    rows_returned  INTEGER NOT NULL DEFAULT 0,
    rows_affected  INTEGER NOT NULL DEFAULT 0,
    rolled_back    BOOLEAN NOT NULL DEFAULT FALSE,
    duration_ms    INTEGER,
    error          TEXT,
    run_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_sql_query_log_time ON orion_ods.sql_query_log (run_timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_sql_query_log_user ON orion_ods.sql_query_log (user_id, run_timestamp DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON SCHEMA reports TO orion_user;
        GRANT ALL ON ALL TABLES IN SCHEMA reports TO orion_user;
        ALTER DEFAULT PRIVILEGES IN SCHEMA reports GRANT ALL ON TABLES TO orion_user;
        GRANT ALL ON orion_ods.sql_saved_query TO orion_user;
        GRANT ALL ON orion_ods.sql_query_log TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.sql_saved_query_query_id_seq TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.sql_query_log_log_id_seq TO orion_user;
    END IF;
END $$;
