-- The Document Center (Documents in the Utilities menu): the company's documents, and every case's and client's.
-- Idempotent: safe on existing databases, and applied on every API start.
--
-- Written only by app.documents. Nothing here is loaded into the warehouse.

-- Documents is its own area, with a view flag and a change flag like Letterhead. The first time the pair is added, admins
-- and editors get both, which is what a new user of those roles gets by default; after that each person's access is set in
-- Admin. (The API also adds these columns at start, with the same backfill; this is for new databases.)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_ods' AND table_name = 'app_user' AND column_name = 'documents_access'
    ) THEN
        ALTER TABLE orion_ods.app_user
            ADD COLUMN IF NOT EXISTS documents_access BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS documents_write  BOOLEAN NOT NULL DEFAULT FALSE;
        UPDATE orion_ods.app_user
           SET documents_access = role IN ('admin', 'editor'),
               documents_write  = role IN ('admin', 'editor');
    END IF;
END $$;

CREATE SEQUENCE IF NOT EXISTS orion_ods.document_seq START 1;

-- A folder belongs to the company, to one case or to one client, and may sit inside another folder of the same space.
-- The case and client are real links, so a case that has documents cannot be deleted by mistake.
CREATE TABLE IF NOT EXISTS orion_ods.doc_folder (
    folder_id         SERIAL PRIMARY KEY,
    scope             TEXT NOT NULL CHECK (scope IN ('company', 'case', 'client')),
    case_code         TEXT REFERENCES orion_ods.case(case_code),
    client_code       TEXT REFERENCES orion_ods.client(client_code),
    parent_id         INTEGER REFERENCES orion_ods.doc_folder(folder_id),
    name              TEXT NOT NULL,
    created_by        INTEGER,
    created_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT doc_folder_scope_ok CHECK (
        (scope = 'company' AND case_code IS NULL AND client_code IS NULL)
        OR (scope = 'case' AND case_code IS NOT NULL AND client_code IS NULL)
        OR (scope = 'client' AND client_code IS NOT NULL AND case_code IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_folder_name
    ON orion_ods.doc_folder (scope, COALESCE(case_code, ''), COALESCE(client_code, ''), COALESCE(parent_id, 0), lower(name));

-- One row per document. The file is in document_version; the document is what people mean when they say "the contract".
-- content_text is the words inside the current version of a PDF, Word, Excel, PowerPoint or text file, taken when the file
-- is uploaded, so a search can find a document by what is written in it as well as by its title, tags and description.
CREATE TABLE IF NOT EXISTS orion_ods.document (
    document_id            SERIAL PRIMARY KEY,
    document_code          TEXT NOT NULL UNIQUE DEFAULT orion_ods.next_code('DOC', 'orion_ods.document_seq'),
    scope                  TEXT NOT NULL CHECK (scope IN ('company', 'case', 'client')),
    case_code              TEXT REFERENCES orion_ods.case(case_code),
    client_code            TEXT REFERENCES orion_ods.client(client_code),
    folder_id              INTEGER REFERENCES orion_ods.doc_folder(folder_id),
    title                  TEXT NOT NULL,
    category               TEXT NOT NULL,
    description            TEXT,
    tags                   TEXT[] NOT NULL DEFAULT '{}',
    status                 TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Draft', 'Active', 'Superseded', 'Archived')),
    confidentiality        TEXT NOT NULL DEFAULT 'Standard' CHECK (confidentiality IN ('Standard', 'Confidential')),
    document_date          DATE,
    expiry_date            DATE,
    reminder_days          INTEGER NOT NULL DEFAULT 30 CHECK (reminder_days BETWEEN 0 AND 365),
    current_version        INTEGER NOT NULL DEFAULT 1,
    content_text           TEXT NOT NULL DEFAULT '',
    is_deleted             BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_by             INTEGER,
    deleted_timestamp      TIMESTAMPTZ,
    created_by             INTEGER,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_by        INTEGER,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT document_scope_ok CHECK (
        (scope = 'company' AND case_code IS NULL AND client_code IS NULL)
        OR (scope = 'case' AND case_code IS NOT NULL AND client_code IS NULL)
        OR (scope = 'client' AND client_code IS NOT NULL AND case_code IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_document_case ON orion_ods.document (case_code) WHERE case_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_document_client ON orion_ods.document (client_code) WHERE client_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_document_folder ON orion_ods.document (folder_id) WHERE folder_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_document_expiry ON orion_ods.document (expiry_date) WHERE expiry_date IS NOT NULL AND NOT is_deleted;
CREATE INDEX IF NOT EXISTS ix_document_live ON orion_ods.document (is_deleted, created_timestamp DESC);

-- Every version of a document, kept for good: a new file is a new version, never a replacement. The file's bytes are in
-- document_blob, keyed by their SHA-256, so the same file uploaded twice (or restored from an old version) is stored once.
CREATE TABLE IF NOT EXISTS orion_ods.document_version (
    version_id         SERIAL PRIMARY KEY,
    document_id        INTEGER NOT NULL REFERENCES orion_ods.document(document_id) ON DELETE CASCADE,
    version_no         INTEGER NOT NULL,
    file_name          TEXT NOT NULL,
    content_type       TEXT NOT NULL,
    size_bytes         BIGINT NOT NULL,
    sha256             TEXT NOT NULL,
    change_note        TEXT,
    uploaded_by        INTEGER,
    uploaded_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (document_id, version_no)
);

CREATE INDEX IF NOT EXISTS ix_document_version_sha ON orion_ods.document_version (sha256);

-- The file itself, once per distinct content. Kept in the database so the encrypted daily backup covers it.
CREATE TABLE IF NOT EXISTS orion_ods.document_blob (
    sha256     TEXT PRIMARY KEY,
    size_bytes BIGINT NOT NULL,
    data       BYTEA NOT NULL
);

-- Who did what to a document and when: uploaded, new version, edited, moved, viewed, downloaded, deleted, restored.
CREATE TABLE IF NOT EXISTS orion_ods.document_activity (
    id          SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES orion_ods.document(document_id) ON DELETE CASCADE,
    action      TEXT NOT NULL,
    detail      TEXT,
    by_user     INTEGER,
    at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_document_activity_doc ON orion_ods.document_activity (document_id, id DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON orion_ods.doc_folder, orion_ods.document, orion_ods.document_version, orion_ods.document_blob,
                     orion_ods.document_activity TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.document_seq, orion_ods.doc_folder_folder_id_seq, orion_ods.document_document_id_seq,
                              orion_ods.document_version_version_id_seq, orion_ods.document_activity_id_seq TO orion_user;
    END IF;
END $$;
