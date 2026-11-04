-- The record of every database backup attempt. Idempotent: safe on existing databases, applied on every API start.
--
-- One row per backup that was started. A scheduled check that finds nothing has changed since the last
-- backup writes no row. Written only by app.backup, and it holds no secrets: the bucket name, the sizes and a
-- checksum, never a key, a password or any data from the dump. Lives in orion_ods with the other tables the
-- application keeps for itself.

CREATE TABLE IF NOT EXISTS orion_ods.backup_run (
    id                 SERIAL PRIMARY KEY,
    trigger            TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled')),
    started_by         INTEGER,
    status             TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    started_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_timestamp TIMESTAMPTZ,
    duration_ms        BIGINT,
    bucket_role        TEXT,
    bucket             TEXT,
    db_name            TEXT,
    schemas            TEXT[],
    prefixes           TEXT[],
    object_keys        TEXT[],
    size_bytes         BIGINT,
    sha256             TEXT,
    source_fingerprint TEXT,
    runner_host        TEXT,
    app_env            TEXT,
    error              TEXT
);

CREATE INDEX IF NOT EXISTS ix_backup_run_started ON orion_ods.backup_run (started_timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_backup_run_status  ON orion_ods.backup_run (status, finished_timestamp DESC);
