-- The Letterhead utility: letters written in the app, and the company letterhead they print on.
-- Idempotent: safe on existing databases, and applied on every API start.
--
-- Written only by app.letterhead. Nothing here is loaded into the warehouse.

-- Letterhead is its own segment, with a view flag and a change flag like Billing and ETL. The first time the
-- pair is added, admins and editors get both, which is what a new user of those roles gets by default; after
-- that each person's access is set in Admin.
-- (The API also adds these columns at start, with the same backfill; this is for new databases.)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_ods' AND table_name = 'app_user' AND column_name = 'letterhead_access'
    ) THEN
        ALTER TABLE orion_ods.app_user
            ADD COLUMN IF NOT EXISTS letterhead_access BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS letterhead_write  BOOLEAN NOT NULL DEFAULT FALSE;
        UPDATE orion_ods.app_user
           SET letterhead_access = role IN ('admin', 'editor'),
               letterhead_write  = role IN ('admin', 'editor');
    END IF;
END $$;

-- The letterhead itself: one row. An image left empty means the one shipped with the application
-- (backend/app/assets/letterhead) is used, so a new database prints the standard letterhead with no row at
-- all. settings holds the gaps and margins in millimetres (letterhead.DEFAULT_SETTINGS lists them).
-- version goes up on every change so browsers fetch the new image.
CREATE TABLE IF NOT EXISTS orion_ods.letterhead_design (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    header_image      BYTEA,
    header_type       TEXT,
    footer_image      BYTEA,
    footer_type       TEXT,
    settings          JSONB NOT NULL DEFAULT '{}'::jsonb,
    version           INTEGER NOT NULL DEFAULT 1,
    updated_by        INTEGER,
    updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One row per letter (or quotation, notice, certificate: anything typed onto the letterhead).
-- body_html is what was typed, already reduced to the few tags the editor produces
-- (letterhead.clean_html); it is never stored as it arrived. show_header and show_footer off means the
-- letter is printed on paper that already carries the letterhead, with the space left blank.
CREATE TABLE IF NOT EXISTS orion_ods.letter (
    letter_id              SERIAL PRIMARY KEY,
    title                  TEXT NOT NULL,
    ref_no                 TEXT,
    letter_date            DATE NOT NULL DEFAULT CURRENT_DATE,
    body_html              TEXT NOT NULL DEFAULT '',
    font                   TEXT NOT NULL DEFAULT 'sans' CHECK (font IN ('sans', 'serif')),
    font_size              INTEGER NOT NULL DEFAULT 11 CHECK (font_size BETWEEN 8 AND 16),
    show_header            BOOLEAN NOT NULL DEFAULT TRUE,
    show_footer            BOOLEAN NOT NULL DEFAULT TRUE,
    created_by             INTEGER,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_by        INTEGER,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_letter_date ON orion_ods.letter (letter_date DESC, letter_id DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON orion_ods.letterhead_design, orion_ods.letter TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.letter_letter_id_seq TO orion_user;
    END IF;
END $$;
