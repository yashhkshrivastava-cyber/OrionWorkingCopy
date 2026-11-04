-- Bills raised in Utility > Billing: one row per tax invoice, tagged to a case.
-- Idempotent: safe on existing databases, and applied on every API start.
--
-- This table replaces two older ones:
--   * orion_ods.bill in its first shape (bill_type Sales / Purchase / Loan). It is renamed
--     to orion_ods.bill_legacy and kept as a backup. Nothing reads it.
--   * tally_ods.application_bill*, where the Billing utility used to store its bills. Those
--     rows are copied here. The old tables are left in place and are no longer written.

-- What is printed for a client on a bill. Entered once on the client, copied onto each bill.
ALTER TABLE orion_ods.client
    ADD COLUMN IF NOT EXISTS billing_name TEXT,
    ADD COLUMN IF NOT EXISTS gstin TEXT,
    ADD COLUMN IF NOT EXISTS billing_address TEXT;

-- Move the first-shape bill table out of the way, once.
DO $$
DECLARE
    con RECORD;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_ods' AND table_name = 'bill' AND column_name = 'bill_type'
    ) THEN
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_ods' AND table_name = 'case_transaction' AND column_name = 'bill_code'
    ) THEN
        -- Remember which transaction pointed at which old bill, then unlink them.
        CREATE TABLE IF NOT EXISTS orion_ods.bill_legacy_transaction AS
            SELECT transaction_code, bill_code
              FROM orion_ods.case_transaction
             WHERE bill_code IS NOT NULL;
        FOR con IN
            SELECT conname FROM pg_constraint
             WHERE conrelid = 'orion_ods.case_transaction'::regclass
               AND confrelid = 'orion_ods.bill'::regclass
               AND contype = 'f'
        LOOP
            EXECUTE format('ALTER TABLE orion_ods.case_transaction DROP CONSTRAINT %I', con.conname);
        END LOOP;
        UPDATE orion_ods.case_transaction SET bill_code = NULL WHERE bill_code IS NOT NULL;
    END IF;

    -- The new table needs these names, so the old primary key and indexes give them up.
    FOR con IN
        SELECT conname FROM pg_constraint
         WHERE conrelid = 'orion_ods.bill'::regclass AND contype = 'p'
    LOOP
        EXECUTE format('ALTER TABLE orion_ods.bill RENAME CONSTRAINT %I TO bill_legacy_pkey', con.conname);
    END LOOP;
    ALTER INDEX IF EXISTS orion_ods.ix_bill_client RENAME TO ix_bill_legacy_client;
    ALTER INDEX IF EXISTS orion_ods.ix_bill_date   RENAME TO ix_bill_legacy_date;
    ALTER INDEX IF EXISTS orion_ods.ix_bill_type   RENAME TO ix_bill_legacy_type;
    ALTER TABLE orion_ods.bill ALTER COLUMN bill_code DROP DEFAULT;
    ALTER TABLE orion_ods.bill RENAME TO bill_legacy;
END $$;

CREATE SEQUENCE IF NOT EXISTS orion_ods.bill_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.bill (
    bill_code                TEXT PRIMARY KEY DEFAULT orion_ods.next_code('BILL', 'orion_ods.bill_seq'),
    bill_number              TEXT NOT NULL UNIQUE,
    fy_start_year            INTEGER NOT NULL,
    bill_seq                 INTEGER NOT NULL,
    bill_date                DATE NOT NULL,
    service_month            DATE NOT NULL,
    -- Tracking: the bill belongs to a case, and the client is the case's client when the
    -- bill is saved. case_code is empty only on bills raised before bills were tagged to cases.
    case_code                TEXT REFERENCES orion_ods.case(case_code),
    client_code              TEXT REFERENCES orion_ods.client(client_code),
    -- The party exactly as printed. A copy, so a later change to the client never alters a bill.
    party_name               TEXT NOT NULL,
    party_gstin              TEXT,
    party_address            TEXT,
    party_state              TEXT,
    ref_no                   TEXT,
    ref_date                 DATE,
    location                 TEXT,
    service_description      TEXT,
    lines                    JSONB NOT NULL,
    rates                    JSONB NOT NULL,
    lines_total              NUMERIC(14, 2) NOT NULL,
    epf_amount               NUMERIC(14, 2) NOT NULL,
    esic_amount              NUMERIC(14, 2) NOT NULL,
    sub_total                NUMERIC(14, 2) NOT NULL,
    service_amount           NUMERIC(14, 2) NOT NULL,
    taxable_total            NUMERIC(14, 2) NOT NULL,
    cgst_amount              NUMERIC(14, 2) NOT NULL,
    sgst_amount              NUMERIC(14, 2) NOT NULL,
    round_off                NUMERIC(8, 2) NOT NULL,
    grand_total              NUMERIC(14, 2) NOT NULL,
    profile                  JSONB NOT NULL,
    status                   TEXT NOT NULL DEFAULT 'Issued' CHECK (status IN ('Issued', 'Cancelled')),
    cancelled_reason         TEXT,
    cancelled_timestamp      TIMESTAMPTZ,
    gst_paid                 BOOLEAN NOT NULL DEFAULT FALSE,
    gst_paid_by              INTEGER,
    gst_paid_timestamp       TIMESTAMPTZ,
    -- The row is the current version. Earlier versions are in orion_ods.bill_version.
    version_no               INTEGER NOT NULL DEFAULT 1,
    version_reason           TEXT,
    version_by               INTEGER,
    version_timestamp        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    legacy_client_ledger     TEXT,
    created_by               INTEGER,
    created_timestamp        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (fy_start_year, bill_seq)
);

-- How a bill is customised, per bill. extra_charges are charges the user named (label, kind pct|amount,
-- value, amount) that count towards the taxable value; hidden lists the parts of the printed bill left off
-- (keys in billing.HIDEABLE); header_fields are named details (label, value) printed with the GSTIN and PAN at
-- the top of the bill, and party_fields are named details (label, value) of the client printed under its GSTIN.
-- Bills before this have none of them, which prints exactly as before.
ALTER TABLE orion_ods.bill
    ADD COLUMN IF NOT EXISTS extra_charges JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS hidden        JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS header_fields  JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS party_fields   JSONB NOT NULL DEFAULT '[]'::jsonb;

-- The tender a bill is raised under (printed with the invoice details unless hidden: keys tender_id and tender_date), and
-- how its lines are laid out and worked out: line_setup holds basis (unit | daily | monthly), qty_multiplies, month_days,
-- totals_row, labels (column names the user chose) and columns (extra named columns; each line keeps its values in
-- lines[].fields). An empty line_setup is the original layout, quantity x rate, so bills before this print exactly as before.
ALTER TABLE orion_ods.bill
    ADD COLUMN IF NOT EXISTS tender_id         TEXT,
    ADD COLUMN IF NOT EXISTS tender_start_date DATE,
    ADD COLUMN IF NOT EXISTS line_setup        JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Figures a person entered instead of the calculated ones (EPFO, ESIC, service charges, CGST, SGST): {"epf_amount": {"value": 68682,
-- "auto": 71169.41}, ...}, the entered value and what the calculation gave. A line entered by hand is marked in lines[] (manual,
-- auto_amount) and a line left out of a charge lists it in lines[].skip. Bills before this are all calculated: {}.
ALTER TABLE orion_ods.bill
    ADD COLUMN IF NOT EXISTS manual_figures    JSONB NOT NULL DEFAULT '{}'::jsonb;

-- The details of the template (company, registrations, bank, terms, signature) that this bill has its own version of: only the keys
-- that differ from the template at the time, {"bank_account": "..."}. The bill's printed copy is in profile; this is what a repeat
-- bill for the same case starts from, so a change to the template is still picked up by everything else.
ALTER TABLE orion_ods.bill
    ADD COLUMN IF NOT EXISTS profile_overrides JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS ix_bill_date   ON orion_ods.bill (bill_date DESC);
CREATE INDEX IF NOT EXISTS ix_bill_case   ON orion_ods.bill (case_code);
CREATE INDEX IF NOT EXISTS ix_bill_client ON orion_ods.bill (client_code);

-- Every version a bill had before its current one, as the whole row at that time.
CREATE TABLE IF NOT EXISTS orion_ods.bill_version (
    bill_version_sk      BIGSERIAL PRIMARY KEY,
    bill_code            TEXT NOT NULL REFERENCES orion_ods.bill(bill_code) ON DELETE CASCADE,
    version_no           INTEGER NOT NULL,
    snapshot             JSONB NOT NULL,
    replaced_by          INTEGER,
    replaced_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (bill_code, version_no)
);

CREATE TABLE IF NOT EXISTS orion_ods.bill_counter (
    fy_start_year INTEGER PRIMARY KEY,
    last_no       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orion_ods.bill_profile (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    profile           JSONB NOT NULL,
    updated_by        INTEGER,
    updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON orion_ods.bill, orion_ods.bill_version, orion_ods.bill_counter, orion_ods.bill_profile TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.bill_seq, orion_ods.bill_version_bill_version_sk_seq TO orion_user;
    END IF;
END $$;

-- Bring over the bills the Billing utility stored in tally_ods. A bill is copied once, by
-- its number. The client is filled in only when exactly one Orion client has the same name
-- as the Tally ledger; the case is left empty and is chosen by editing the bill.
DO $$
BEGIN
    IF to_regclass('tally_ods.application_bill_counter') IS NOT NULL THEN
        INSERT INTO orion_ods.bill_counter (fy_start_year, last_no)
        SELECT fy_start_year, last_no FROM tally_ods.application_bill_counter
        ON CONFLICT (fy_start_year)
        DO UPDATE SET last_no = GREATEST(orion_ods.bill_counter.last_no, EXCLUDED.last_no);
    END IF;

    IF to_regclass('tally_ods.application_bill_profile') IS NOT NULL THEN
        INSERT INTO orion_ods.bill_profile (id, profile, updated_by, updated_timestamp)
        SELECT id, profile, updated_by, updated_timestamp FROM tally_ods.application_bill_profile
        ON CONFLICT (id) DO NOTHING;
    END IF;

    IF to_regclass('tally_ods.application_bill') IS NOT NULL THEN
        INSERT INTO orion_ods.bill (
            bill_number, fy_start_year, bill_seq, bill_date, service_month, client_code,
            party_name, party_gstin, party_address, party_state, ref_no, ref_date, location,
            service_description, lines, rates, lines_total, epf_amount, esic_amount, sub_total,
            service_amount, taxable_total, cgst_amount, sgst_amount, round_off, grand_total,
            profile, status, cancelled_reason, cancelled_timestamp, version_by, version_timestamp,
            legacy_client_ledger, created_by, created_timestamp, last_updated_timestamp
        )
        SELECT a.bill_number, a.fy_start_year, a.bill_seq, a.bill_date, a.service_month,
               (SELECT MIN(c.client_code) FROM orion_ods.client c
                 WHERE LOWER(BTRIM(c.client_name)) = LOWER(BTRIM(a.client_ledger))
                HAVING COUNT(*) = 1),
               a.party_name, a.party_gstin, a.party_address, a.party_state, a.ref_no, a.ref_date,
               a.location, a.service_description, a.lines, a.rates, a.lines_total, a.epf_amount,
               a.esic_amount, a.sub_total, a.service_amount, a.taxable_total, a.cgst_amount,
               a.sgst_amount, a.round_off, a.grand_total, a.profile, a.status, a.cancelled_reason,
               a.cancelled_timestamp, a.created_by, a.created_timestamp, a.client_ledger,
               a.created_by, a.created_timestamp, a.last_updated_timestamp
          FROM tally_ods.application_bill a
         WHERE NOT EXISTS (SELECT 1 FROM orion_ods.bill b WHERE b.bill_number = a.bill_number)
         ORDER BY a.application_bill_sk;
    END IF;
END $$;

-- A record of every bill or reminder sent to a client, by email or as a WhatsApp message.
-- It shows when a client was last chased and remembers the address or number last used for
-- the client, so the next send starts filled in. Written only by app.receivables.
CREATE TABLE IF NOT EXISTS orion_ods.bill_message (
    id                SERIAL PRIMARY KEY,
    kind              TEXT NOT NULL CHECK (kind IN ('invoice', 'reminder')),
    channel           TEXT NOT NULL CHECK (channel IN ('email', 'whatsapp')),
    client_code       TEXT REFERENCES orion_ods.client(client_code),
    bill_codes        TEXT[] NOT NULL DEFAULT '{}',
    recipient         TEXT NOT NULL,
    subject           TEXT,
    outstanding_total NUMERIC(14, 2),
    sent_by           INTEGER,
    sent_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_bill_message_client ON orion_ods.bill_message (client_code, sent_timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_bill_message_bills  ON orion_ods.bill_message USING GIN (bill_codes);

-- The typeface and size a bill is printed in, when this bill's own differs from the company's (orion_ods.bill_profile
-- font_family / font_size). Empty means "follow the company's setting". Keys and sizes are in app.bill_fonts. It is how the
-- bill looks, not what it says, so changing it does not make a new version of the bill.
ALTER TABLE orion_ods.bill
    ADD COLUMN IF NOT EXISTS font_family TEXT,
    ADD COLUMN IF NOT EXISTS font_size   NUMERIC(3, 1);
