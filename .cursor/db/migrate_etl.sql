-- The history of every ETL run: Orion ODS -> Orion DW, Tally -> Tally ODS, Tally ODS -> Tally DW.
-- Idempotent: safe on existing databases, and applied on every API start.
--
-- One row per run, and one row per table (step) inside it. They live in orion_ods with the other
-- tables the application itself keeps (app_user, record_deleted), not in a warehouse schema, so a
-- warehouse rebuild or a Tally reset never erases the record of what was loaded and when.
-- Written only by app.etl. The ids in started_by are app_user.id with no foreign key.
--
-- rows_* use the same four words for every pipeline. A warehouse load "updates" a row by closing its
-- version and adding a new one, and "deletes" one by marking it expired; the raw counts the loader
-- reported are kept as they came in the step's stats.

CREATE TABLE IF NOT EXISTS orion_ods.etl_run (
    id                 SERIAL PRIMARY KEY,
    pipeline           TEXT NOT NULL CHECK (pipeline IN ('orion_dw', 'tally_ods', 'tally_dw')),
    scope              TEXT NOT NULL DEFAULT 'all',
    trigger            TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled')),
    started_by         INTEGER,
    status             TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    started_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_timestamp TIMESTAMPTZ,
    duration_ms        BIGINT,
    steps_total        INTEGER NOT NULL DEFAULT 0,
    steps_succeeded    INTEGER NOT NULL DEFAULT 0,
    steps_failed       INTEGER NOT NULL DEFAULT 0,
    steps_skipped      INTEGER NOT NULL DEFAULT 0,
    rows_read          BIGINT NOT NULL DEFAULT 0,
    rows_inserted      BIGINT NOT NULL DEFAULT 0,
    rows_updated       BIGINT NOT NULL DEFAULT 0,
    rows_deleted       BIGINT NOT NULL DEFAULT 0,
    rows_unchanged     BIGINT NOT NULL DEFAULT 0,
    source             JSONB,
    target             TEXT,
    source_fingerprint TEXT,
    runner_host        TEXT,
    app_env            TEXT,
    error              TEXT
);

CREATE INDEX IF NOT EXISTS ix_etl_run_pipeline ON orion_ods.etl_run (pipeline, started_timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_etl_run_started  ON orion_ods.etl_run (started_timestamp DESC);

CREATE TABLE IF NOT EXISTS orion_ods.etl_run_step (
    id                 SERIAL PRIMARY KEY,
    run_id             INTEGER NOT NULL REFERENCES orion_ods.etl_run(id) ON DELETE CASCADE,
    seq                INTEGER NOT NULL,
    name               TEXT NOT NULL,
    kind               TEXT,
    target_table       TEXT,
    status             TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')),
    started_timestamp  TIMESTAMPTZ,
    finished_timestamp TIMESTAMPTZ,
    duration_ms        BIGINT,
    rows_read          BIGINT NOT NULL DEFAULT 0,
    rows_inserted      BIGINT NOT NULL DEFAULT 0,
    rows_updated       BIGINT NOT NULL DEFAULT 0,
    rows_deleted       BIGINT NOT NULL DEFAULT 0,
    rows_unchanged     BIGINT NOT NULL DEFAULT 0,
    target_rows_before BIGINT,
    target_rows_after  BIGINT,
    stats              JSONB,
    error              TEXT,
    UNIQUE (run_id, seq)
);

CREATE INDEX IF NOT EXISTS ix_etl_run_step_name ON orion_ods.etl_run_step (name, finished_timestamp DESC);
