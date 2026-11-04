-- What has to be done after an opportunity is won: create the case, and record the EMD against it. One row per opportunity and kind, kept
-- by app.opportunity_followups. Idempotent: safe on existing databases, applied on every API start, after migrate_contacts_emd.sql.
--
-- A follow-up is open while the opportunity is Closed Won and no case (or EMD) exists for it, is done when one does, is dismissed by a
-- person who decided it is not needed (never by the system), and is withdrawn while the opportunity is no longer won. Every change of state
-- is kept in opportunity_followup_event for ever. Nothing here is loaded into the warehouse.

-- The first time only: every opportunity that was already won before follow-ups existed is recorded as settled, so the people who
-- can create cases are not told about all of last year's wins. Wrapped so that it never runs again, when a win that has not been
-- looked at yet must not be settled by a restart.
DO $$
BEGIN
    IF to_regclass('orion_ods.opportunity_followup') IS NULL THEN
        CREATE TABLE orion_ods.opportunity_followup (
            followup_id            SERIAL PRIMARY KEY,
            opportunity_code       TEXT NOT NULL REFERENCES orion_ods.opportunity(opportunity_code) ON DELETE CASCADE,
            kind                   TEXT NOT NULL CHECK (kind IN ('case', 'emd')),
            status                 TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'dismissed', 'withdrawn')),
            created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_changed_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_timestamp     TIMESTAMPTZ,
            resolved_by            INTEGER,
            resolution_note        TEXT,
            UNIQUE (opportunity_code, kind)
        );

        INSERT INTO orion_ods.opportunity_followup (opportunity_code, kind, status, resolved_timestamp, resolution_note)
        SELECT o.opportunity_code, k.kind, 'dismissed', CURRENT_TIMESTAMP, 'Won before follow-ups were introduced'
          FROM orion_ods.opportunity o CROSS JOIN (VALUES ('case'), ('emd')) AS k(kind)
         WHERE o.opportunity_status = 'Closed Won';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_opportunity_followup_open ON orion_ods.opportunity_followup (status) WHERE status = 'open';

-- Who did what to a follow-up and when: created, done, dismissed, reopened, withdrawn. Never changed or deleted by the app.
CREATE TABLE IF NOT EXISTS orion_ods.opportunity_followup_event (
    id          SERIAL PRIMARY KEY,
    followup_id INTEGER NOT NULL REFERENCES orion_ods.opportunity_followup(followup_id) ON DELETE CASCADE,
    action      TEXT NOT NULL,
    note        TEXT,
    by_user     INTEGER,
    at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_opportunity_followup_event ON orion_ods.opportunity_followup_event (followup_id, id);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON orion_ods.opportunity_followup, orion_ods.opportunity_followup_event TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.opportunity_followup_followup_id_seq, orion_ods.opportunity_followup_event_id_seq TO orion_user;
    END IF;
END $$;
