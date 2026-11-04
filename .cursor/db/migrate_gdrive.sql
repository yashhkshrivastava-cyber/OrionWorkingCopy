-- Google Drive, connected from the Document Center. Idempotent: safe on existing databases, applied on every API start.
--
-- Written only by app.gdrive. Nothing here is loaded into the warehouse. The Drive itself is read and written only by
-- app.gdrive_client (a fake one kept in data/fake-drive for development, the real one over Google's REST API).

-- The one connection of the company to a Drive (a single row). `mode` says how it was made, because a file id from the fake Drive means
-- nothing to Google: connecting in the other mode forgets the links. The refresh token is Google's, kept encrypted (gdrive.seal / unseal);
-- the fake Drive has none. oauth_state is the one-time value that proves a return from Google was started here.
CREATE TABLE IF NOT EXISTS orion_ods.gdrive_connection (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    connected           BOOLEAN NOT NULL DEFAULT FALSE,
    mode                TEXT CHECK (mode IN ('fake', 'google')),
    account_email       TEXT,
    refresh_token_enc   BYTEA,
    oauth_state         TEXT,
    oauth_state_expires TIMESTAMPTZ,
    -- Whether a new bill is also saved to Drive: never, only when the person ticks it, or always (in bills_folder_id).
    bills_mode          TEXT NOT NULL DEFAULT 'ask' CHECK (bills_mode IN ('off', 'ask', 'on')),
    bills_folder_id     TEXT,
    bills_folder_label  TEXT,
    connected_by        INTEGER,
    connected_timestamp TIMESTAMPTZ
);

-- A document or bill that is also in Drive. kind 'bill': ref is the bill code and the Drive file follows the bill (a new version of the bill
-- replaces the file's content). kind 'document': ref is the document id, and the file is a copy made once, in either direction
-- (direction says which side it came from). A bill whose upload failed has no file_id yet and state 'failed'.
CREATE TABLE IF NOT EXISTS orion_ods.drive_link (
    link_id           SERIAL PRIMARY KEY,
    kind              TEXT NOT NULL CHECK (kind IN ('bill', 'document')),
    ref               TEXT NOT NULL,
    file_id           TEXT,
    folder_id         TEXT,
    folder_label      TEXT,
    name              TEXT,
    direction         TEXT NOT NULL CHECK (direction IN ('to_drive', 'from_drive')),
    synced_version    TEXT,
    state             TEXT NOT NULL DEFAULT 'synced' CHECK (state IN ('synced', 'failed', 'stopped')),
    last_error        TEXT,
    created_by        INTEGER,
    created_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A bill has one place in Drive; a document may have several copies.
CREATE UNIQUE INDEX IF NOT EXISTS ux_drive_link_bill ON orion_ods.drive_link (ref) WHERE kind = 'bill';
CREATE UNIQUE INDEX IF NOT EXISTS ux_drive_link_file ON orion_ods.drive_link (kind, ref, file_id) WHERE file_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_drive_link_ref ON orion_ods.drive_link (kind, ref);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON orion_ods.gdrive_connection TO orion_user;
        GRANT ALL ON orion_ods.drive_link TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.drive_link_link_id_seq TO orion_user;
    END IF;
END $$;
