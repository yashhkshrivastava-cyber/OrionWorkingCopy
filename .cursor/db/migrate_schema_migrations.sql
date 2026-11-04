-- What has been applied to this database, and how it went. One row per schema step (a migrate_*.sql file, or one of the
-- warehouse schemas), kept by app/migrate.py: the checksum of the file as it was last applied, whether that worked, when, how long
-- it took, and the error if it did not. A file is applied when it is new or its checksum has changed, and skipped when it has not;
-- a failed one is recorded and stops a deploy. This file is the one step that always runs: it is what makes the rest trackable.
-- Idempotent and additive: safe on a database that already has data, and applied on every API start.

CREATE TABLE IF NOT EXISTS orion_ods.schema_migrations (
    name                   TEXT PRIMARY KEY,
    -- Hash of the file's text with line endings normalised, so Windows and Git checkouts agree.
    checksum               TEXT NOT NULL,
    status                 TEXT NOT NULL CHECK (status IN ('applied', 'failed')),
    applied_timestamp      TIMESTAMPTZ,
    last_attempt_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration_ms            INTEGER,
    attempts               INTEGER NOT NULL DEFAULT 1,
    error                  TEXT
);
