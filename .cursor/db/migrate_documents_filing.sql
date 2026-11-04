-- Documents that other parts of Orion produce or collect are filed in the Document Center by themselves: a tax invoice's PDF, an
-- employee's papers, an EMD's receipts. Idempotent: safe on existing databases, applied on every API start, after migrate_documents.sql.
--
-- Written only by app.documents_filing (and read by app.documents). Nothing here is loaded into the warehouse.

-- A document that was filed automatically names where it came from. The pair (source_type, source_ref) is unique, so the same bill
-- or the same uploaded file can never be filed twice, however often the filing runs. source_version says which state of the source
-- the stored file shows (a bill's version and status), so the file is replaced by a new version only when the source changed.
ALTER TABLE orion_ods.document ADD COLUMN IF NOT EXISTS source_type    TEXT;
ALTER TABLE orion_ods.document ADD COLUMN IF NOT EXISTS source_ref     TEXT;
ALTER TABLE orion_ods.document ADD COLUMN IF NOT EXISTS source_version TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_document_source
    ON orion_ods.document (source_type, source_ref) WHERE source_type IS NOT NULL;

-- A folder made by the filing has a key that says what it is for (for example 'billing/invoices/FY2026'). The filing finds its folders by
-- key, so a rename of a case or client is followed, and a folder a person made with the same name is taken over rather than doubled.
ALTER TABLE orion_ods.doc_folder ADD COLUMN IF NOT EXISTS system_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_folder_system_key
    ON orion_ods.doc_folder (scope, COALESCE(case_code, ''), COALESCE(client_code, ''), system_key) WHERE system_key IS NOT NULL;

-- A document has one home (its scope, case or client, and folder) and may also be filed in other places: a case's tax invoice is also
-- in its client's Billing folder. A placement is the same document shown again, not a copy: opening it, its versions and its history
-- are those of the one document, and deleting the document removes its placements.
CREATE TABLE IF NOT EXISTS orion_ods.document_placement (
    placement_id SERIAL PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES orion_ods.document(document_id) ON DELETE CASCADE,
    scope        TEXT NOT NULL CHECK (scope IN ('company', 'case', 'client')),
    case_code    TEXT REFERENCES orion_ods.case(case_code) ON DELETE CASCADE,
    client_code  TEXT REFERENCES orion_ods.client(client_code) ON DELETE CASCADE,
    folder_id    INTEGER REFERENCES orion_ods.doc_folder(folder_id) ON DELETE SET NULL,
    CONSTRAINT document_placement_scope_ok CHECK (
        (scope = 'company' AND case_code IS NULL AND client_code IS NULL)
        OR (scope = 'case' AND case_code IS NOT NULL AND client_code IS NULL)
        OR (scope = 'client' AND client_code IS NOT NULL AND case_code IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_document_placement
    ON orion_ods.document_placement (document_id, scope, COALESCE(case_code, ''), COALESCE(client_code, ''));
CREATE INDEX IF NOT EXISTS ix_document_placement_case ON orion_ods.document_placement (case_code) WHERE case_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_document_placement_client ON orion_ods.document_placement (client_code) WHERE client_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_document_placement_folder ON orion_ods.document_placement (folder_id) WHERE folder_id IS NOT NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON orion_ods.document_placement TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.document_placement_placement_id_seq TO orion_user;
    END IF;
END $$;

-- Where a person chose to keep a filed document. Without a row a document is filed where documents_filing puts it by itself (a bill in its
-- case's Billing and payments, and its client's Billing); with one, the chosen folder (or the root of the chosen company, case or client) is
-- its home and the places the filing would have used in other spaces stay as placements. It follows the document's source, not its file, so
-- it survives a new version, and it goes with the folder if that is deleted. Written only by app.documents_filing.
CREATE TABLE IF NOT EXISTS orion_ods.document_filing_choice (
    source_type      TEXT NOT NULL,
    source_ref       TEXT NOT NULL,
    scope            TEXT NOT NULL CHECK (scope IN ('company', 'case', 'client')),
    case_code        TEXT REFERENCES orion_ods.case(case_code) ON DELETE CASCADE,
    client_code      TEXT REFERENCES orion_ods.client(client_code) ON DELETE CASCADE,
    folder_id        INTEGER REFERENCES orion_ods.doc_folder(folder_id) ON DELETE CASCADE,
    chosen_by        INTEGER,
    chosen_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_type, source_ref),
    CONSTRAINT document_filing_choice_scope_ok CHECK (
        (scope = 'company' AND case_code IS NULL AND client_code IS NULL)
        OR (scope = 'case' AND case_code IS NOT NULL AND client_code IS NULL)
        OR (scope = 'client' AND client_code IS NOT NULL AND case_code IS NULL)
    )
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON orion_ods.document_filing_choice TO orion_user;
    END IF;
END $$;
