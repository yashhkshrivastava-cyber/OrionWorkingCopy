-- Contacts (the people we know at a client) and EMDs (the earnest money deposited for a case won), with the files kept against an EMD.
-- Idempotent and additive: safe on a database that already has data, and applied on every API start.
--
-- Both are plain business tables written through the generic record forms (entities.py "Contact" and "EMD"), so they have the codes, the
-- created_by / last_updated_by audit columns, the Excel upload and the warehouse load every other record type has. The rules a value must
-- meet are CHECK constraints with names: app/entity_service.py turns each name into a message (CONSTRAINT_MESSAGES), so keep them in step.

-- ------------------------------------------------------------------------------------------------------------------------ contacts
-- A person at a client. A contact belongs to a client and may be tied to one case (the site in-charge of that case). People move on, so a contact
-- has a start and an end and a status rather than being deleted. Phone and e-mail stay here: the warehouse carries who and what role, not how to reach them.
CREATE SEQUENCE IF NOT EXISTS orion_ods.contact_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.contact (
    contact_code             TEXT PRIMARY KEY DEFAULT orion_ods.next_code('CON', 'orion_ods.contact_seq'),
    client_code              TEXT NOT NULL REFERENCES orion_ods.client (client_code),
    case_code                TEXT REFERENCES orion_ods.case (case_code),
    contact_name             TEXT NOT NULL,
    designation              TEXT,
    department               TEXT,
    contact_role             TEXT CONSTRAINT contact_role_known CHECK (contact_role IN (
        'Decision maker', 'Influencer', 'Accounts / Billing', 'Procurement / Tender', 'Site in-charge', 'Technical', 'HR / Admin', 'Escalation', 'Other')),
    contact_status           TEXT DEFAULT 'Active' CONSTRAINT contact_status_known CHECK (contact_status IN ('Active', 'Inactive', 'Left organisation')),
    is_primary_contact       TEXT DEFAULT 'No' CONSTRAINT contact_primary_known CHECK (is_primary_contact IN ('Yes', 'No')),
    contact_start_date       DATE,
    contact_end_date         DATE,
    email                    TEXT,
    phone                    TEXT,
    alternate_phone          TEXT,
    preferred_contact_method TEXT CONSTRAINT contact_method_known CHECK (preferred_contact_method IN ('Phone', 'Email', 'WhatsApp', 'In person')),
    location_state           TEXT,
    location_city            TEXT,
    address                  TEXT,
    relationship_owner_code  TEXT REFERENCES orion_ods.employee (employee_code),
    last_contacted_date      DATE,
    next_follow_up_date      DATE,
    notes                    TEXT,
    created_timestamp        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by               INTEGER,
    last_updated_by          INTEGER,
    CONSTRAINT contact_end_after_start CHECK (contact_end_date IS NULL OR contact_start_date IS NULL OR contact_end_date >= contact_start_date),
    CONSTRAINT contact_primary_must_be_active CHECK (is_primary_contact IS DISTINCT FROM 'Yes' OR contact_status IS NOT DISTINCT FROM 'Active')
);

CREATE INDEX IF NOT EXISTS ix_contact_client ON orion_ods.contact (client_code);
CREATE INDEX IF NOT EXISTS ix_contact_case ON orion_ods.contact (case_code);
CREATE INDEX IF NOT EXISTS ix_contact_follow_up ON orion_ods.contact (next_follow_up_date) WHERE next_follow_up_date IS NOT NULL;

-- ------------------------------------------------------------------------------------------------------------------------ EMDs
-- Earnest money: the security amount deposited with the authority once a tender is won and its case is opened, until it is refunded, adjusted
-- against the performance security, or forfeited. It is a record of the deposit and of how it comes back; the money itself reaches the bank book
-- as a Bank entry (money with no other record), not from here.
CREATE SEQUENCE IF NOT EXISTS orion_ods.emd_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.emd (
    emd_code                 TEXT PRIMARY KEY DEFAULT orion_ods.next_code('EMD', 'orion_ods.emd_seq'),
    case_code                TEXT NOT NULL REFERENCES orion_ods.case (case_code),
    opportunity_code         TEXT REFERENCES orion_ods.opportunity (opportunity_code),
    tender_reference         TEXT,                          -- the tender / bid number the deposit was made for
    beneficiary              TEXT,                          -- who holds it: the department or authority it was paid to
    emd_amount               NUMERIC(14, 2) NOT NULL CONSTRAINT emd_amount_positive CHECK (emd_amount > 0),
    payment_mode             TEXT CONSTRAINT emd_mode_known CHECK (payment_mode IN (
        'Online / NEFT / RTGS', 'Demand draft', 'Bank guarantee', 'Fixed deposit (FDR)', 'Cheque', 'Cash', 'Other')),
    instrument_number        TEXT,                          -- the document number: DD, FDR or bank guarantee number, cheque number, or the UTR of a transfer
    instrument_date          DATE,
    bank_name                TEXT,                          -- the bank that issued the instrument or the transfer was made from
    bank_branch              TEXT,
    deposit_date             DATE,
    valid_until              DATE,                          -- when a bank guarantee or FDR lapses
    emd_status               TEXT DEFAULT 'Deposited' CONSTRAINT emd_status_known CHECK (emd_status IN (
        'Deposited', 'Refund requested', 'Refunded', 'Adjusted against security deposit', 'Forfeited', 'Cancelled')),
    refund_due_date          DATE,                          -- when it is expected back
    refund_requested_date    DATE,
    refund_received_date     DATE,
    refund_amount            NUMERIC(14, 2) CONSTRAINT emd_refund_not_negative CHECK (refund_amount IS NULL OR refund_amount >= 0),
    deduction_amount         NUMERIC(14, 2) CONSTRAINT emd_deduction_not_negative CHECK (deduction_amount IS NULL OR deduction_amount >= 0),
    refund_reference         TEXT,                          -- the UTR or credit advice of the refund
    remarks                  TEXT,
    created_timestamp        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by               INTEGER,
    last_updated_by          INTEGER,
    CONSTRAINT emd_returned_within_amount CHECK (COALESCE(refund_amount, 0) + COALESCE(deduction_amount, 0) <= emd_amount),
    CONSTRAINT emd_valid_until_after_deposit CHECK (valid_until IS NULL OR COALESCE(instrument_date, deposit_date) IS NULL OR valid_until >= COALESCE(instrument_date, deposit_date)),
    CONSTRAINT emd_refunded_needs_date CHECK (emd_status IS DISTINCT FROM 'Refunded' OR refund_received_date IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_emd_case ON orion_ods.emd (case_code);
CREATE INDEX IF NOT EXISTS ix_emd_opportunity ON orion_ods.emd (opportunity_code);
CREATE INDEX IF NOT EXISTS ix_emd_refund_due ON orion_ods.emd (refund_due_date) WHERE emd_status IN ('Deposited', 'Refund requested');

-- One row per file kept against an EMD: the payment receipt, a copy of the demand draft or bank guarantee, the FDR receipt, the tender notice, the refund
-- request and the proof of refund. The file is kept in the database so the encrypted backup covers it (as for an employee's documents). Written only by
-- app.emd_documents; people who can see operational data can read them, people who can change it can add and delete.
CREATE TABLE IF NOT EXISTS orion_ods.emd_document (
    document_id        SERIAL PRIMARY KEY,
    emd_code           TEXT NOT NULL REFERENCES orion_ods.emd (emd_code) ON DELETE CASCADE,
    doc_type           TEXT NOT NULL,
    title              TEXT,
    file_name          TEXT NOT NULL,
    content_type       TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL,
    file_data          BYTEA NOT NULL,
    uploaded_by        INTEGER,
    uploaded_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_emd_document_emd ON orion_ods.emd_document (emd_code, document_id);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON orion_ods.contact, orion_ods.emd, orion_ods.emd_document TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.contact_seq, orion_ods.emd_seq, orion_ods.emd_document_document_id_seq TO orion_user;
    END IF;
END $$;
