-- Credit notes and bad-debt write-offs against an issued bill. A credit note takes money off what a client still owes (and the revenue and the GST that
-- go with it) without touching the bill as it was issued: the bill keeps its figures and its number, and carries the running total of what has been
-- credited. A credit note is made, then approved by another person (or by an admin), and only then takes effect. Safe to run again.

-- What has been credited against a bill so far (approved credit notes that have not been reversed). Kept by credit_notes.py through billing.py, the way
-- gst_paid_amount is kept: the bill's own figures never change.
ALTER TABLE orion_ods.bill
    ADD COLUMN IF NOT EXISTS credited_taxable NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS credited_cgst    NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS credited_sgst    NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS credited_amount  NUMERIC(14, 2) NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bill_credited_not_negative') THEN
        ALTER TABLE orion_ods.bill ADD CONSTRAINT bill_credited_not_negative
            CHECK (credited_taxable >= 0 AND credited_cgst >= 0 AND credited_sgst >= 0 AND credited_amount >= 0);
    END IF;
END $$;

-- A credit note's number is CN, the financial year and a sequence, given when it is approved (so a note that is refused or withdrawn leaves no gap in the
-- numbering) and never used again.
CREATE TABLE IF NOT EXISTS orion_ods.credit_note_counter (
    fy_start_year INTEGER PRIMARY KEY,
    last_no       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orion_ods.credit_note (
    credit_note_id       BIGSERIAL PRIMARY KEY,
    bill_code            TEXT NOT NULL REFERENCES orion_ods.bill (bill_code),
    kind                 TEXT NOT NULL CHECK (kind IN ('Credit note', 'Bad debt write-off')),
    status               TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending', 'Approved', 'Rejected', 'Withdrawn', 'Reversed')),
    note_date            DATE NOT NULL,           -- the date of the note: the month its GST is adjusted in
    total                NUMERIC(14, 2) NOT NULL CHECK (total > 0),   -- the amount credited, GST included
    taxable              NUMERIC(14, 2) NOT NULL DEFAULT 0,           -- worked out when the note is approved, from what is still open on the bill
    cgst                 NUMERIC(14, 2) NOT NULL DEFAULT 0,
    sgst                 NUMERIC(14, 2) NOT NULL DEFAULT 0,
    reason               TEXT NOT NULL,
    cn_number            TEXT UNIQUE,             -- CN 2026-27/1, given on approval
    fy_start_year        INTEGER NOT NULL,
    cn_seq               INTEGER,
    created_by           INTEGER,
    created_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_by           INTEGER,                 -- who approved, rejected or withdrew it
    decided_timestamp    TIMESTAMPTZ,
    decision_note        TEXT,                    -- why it was refused or withdrawn
    reversed_by          INTEGER,
    reversed_timestamp   TIMESTAMPTZ,
    reversal_reason      TEXT,
    CHECK (status <> 'Approved' OR (cn_number IS NOT NULL AND decided_timestamp IS NOT NULL)),
    CHECK (status <> 'Rejected' OR NULLIF(BTRIM(decision_note), '') IS NOT NULL),
    CHECK ((reversed_timestamp IS NULL) = (reversal_reason IS NULL)),
    CHECK (taxable >= 0 AND cgst >= 0 AND sgst >= 0)
);

CREATE INDEX IF NOT EXISTS credit_note_bill_idx ON orion_ods.credit_note (bill_code, created_timestamp);
CREATE INDEX IF NOT EXISTS credit_note_status_idx ON orion_ods.credit_note (status, created_timestamp);
CREATE UNIQUE INDEX IF NOT EXISTS credit_note_number_uidx ON orion_ods.credit_note (fy_start_year, cn_seq) WHERE cn_seq IS NOT NULL;

-- A credit note is kept for ever, and once decided what it says never changes: only a pending note may be decided, and only an approved one reversed.
CREATE OR REPLACE FUNCTION orion_ods.credit_note_kept() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'A credit note is kept for ever. Withdraw it, or reverse it with a reason.' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.bill_code IS DISTINCT FROM OLD.bill_code OR NEW.kind IS DISTINCT FROM OLD.kind OR NEW.total IS DISTINCT FROM OLD.total
       OR NEW.note_date IS DISTINCT FROM OLD.note_date OR NEW.reason IS DISTINCT FROM OLD.reason OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN
        RAISE EXCEPTION 'A credit note cannot be changed. Withdraw it and make another.' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
           (OLD.status = 'Pending' AND NEW.status IN ('Approved', 'Rejected', 'Withdrawn'))
        OR (OLD.status = 'Approved' AND NEW.status = 'Reversed')) THEN
        RAISE EXCEPTION 'A credit note that is % cannot become %.', OLD.status, NEW.status USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status <> 'Pending' AND (NEW.taxable IS DISTINCT FROM OLD.taxable OR NEW.cgst IS DISTINCT FROM OLD.cgst OR NEW.sgst IS DISTINCT FROM OLD.sgst
       OR NEW.cn_number IS DISTINCT FROM OLD.cn_number) THEN
        RAISE EXCEPTION 'A decided credit note cannot change its figures or its number.' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS credit_note_kept ON orion_ods.credit_note;
CREATE TRIGGER credit_note_kept
    BEFORE UPDATE OR DELETE ON orion_ods.credit_note
    FOR EACH ROW EXECUTE FUNCTION orion_ods.credit_note_kept();
