-- What a client held back when it paid a bill: TDS, a penalty, rounding, anything else. A bill is settled by the cash that came in PLUS what was held
-- back, so a bill paid net of TDS closes instead of staying "outstanding" for the TDS for ever. The revenue entry a payment makes carries the whole
-- amount settled (so the bill's entries still add up to its total and the revenue does not shrink); the bank sees only the cash, which is that amount less
-- the deductions below (the view bank_movement). Safe to run again.

-- One row per deduction. It belongs to the revenue entry (case_transaction) the payment made. There is no foreign key to that entry: reversing a payment
-- may merge it back into the open entry and delete it, and the deduction must stay, marked reversed, with who and why. Nothing here is ever deleted.
CREATE TABLE IF NOT EXISTS orion_ods.bill_payment_deduction (
    deduction_id          BIGSERIAL PRIMARY KEY,
    bill_code             TEXT NOT NULL REFERENCES orion_ods.bill (bill_code),
    transaction_code      TEXT NOT NULL,
    kind                  TEXT NOT NULL CHECK (kind IN ('TDS', 'Penalty', 'Rounding', 'Other')),
    amount                NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    section               TEXT,             -- TDS: the section it was deducted under, for example 194C
    rate                  NUMERIC(6, 3),    -- TDS: the percent, when the person gave it
    reason                TEXT,             -- required for a penalty and for "other"
    received_date         DATE NOT NULL,    -- the day of the payment it came with
    fy_start_year         INTEGER NOT NULL, -- the financial year of that day: what Form 26AS is matched by
    recorded_by           INTEGER,
    recorded_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reversed_by           INTEGER,
    reversed_timestamp    TIMESTAMPTZ,
    reversal_reason       TEXT,
    matched_26as_by       INTEGER,          -- a TDS deduction found in the client's Form 26AS: who ticked it and when
    matched_26as_timestamp TIMESTAMPTZ,
    certificate_ref       TEXT,             -- the TDS certificate (Form 16A) number or the 26AS line, optional
    CHECK ((reversed_timestamp IS NULL) = (reversal_reason IS NULL)),
    CHECK (kind <> 'TDS' OR section IS NOT NULL),
    CHECK (kind NOT IN ('Penalty', 'Other') OR NULLIF(BTRIM(reason), '') IS NOT NULL),
    CHECK (kind = 'TDS' OR matched_26as_timestamp IS NULL)
);

CREATE INDEX IF NOT EXISTS bill_payment_deduction_entry_idx ON orion_ods.bill_payment_deduction (transaction_code) WHERE reversed_timestamp IS NULL;
CREATE INDEX IF NOT EXISTS bill_payment_deduction_bill_idx ON orion_ods.bill_payment_deduction (bill_code);
CREATE INDEX IF NOT EXISTS bill_payment_deduction_tds_idx ON orion_ods.bill_payment_deduction (fy_start_year, received_date) WHERE kind = 'TDS';

-- A deduction is kept for ever and what it says never changes: only its reversal and its Form 26AS tick may be written.
CREATE OR REPLACE FUNCTION orion_ods.bill_payment_deduction_kept() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'A deduction on a payment is kept for ever. Reverse the payment instead.' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.bill_code IS DISTINCT FROM OLD.bill_code OR NEW.transaction_code IS DISTINCT FROM OLD.transaction_code OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.amount IS DISTINCT FROM OLD.amount OR NEW.section IS DISTINCT FROM OLD.section OR NEW.rate IS DISTINCT FROM OLD.rate
       OR NEW.reason IS DISTINCT FROM OLD.reason OR NEW.received_date IS DISTINCT FROM OLD.received_date
       OR NEW.fy_start_year IS DISTINCT FROM OLD.fy_start_year THEN
        RAISE EXCEPTION 'A deduction on a payment cannot be changed. Reverse the payment and record it again.' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.reversed_timestamp IS NOT NULL AND NEW.reversed_timestamp IS DISTINCT FROM OLD.reversed_timestamp THEN
        RAISE EXCEPTION 'That deduction was already reversed.' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS bill_payment_deduction_kept ON orion_ods.bill_payment_deduction;
CREATE TRIGGER bill_payment_deduction_kept
    BEFORE UPDATE OR DELETE ON orion_ods.bill_payment_deduction
    FOR EACH ROW EXECUTE FUNCTION orion_ods.bill_payment_deduction_kept();

-- What the client held back on the payment, kept on the revenue entry itself (the entry's amount is the cash PLUS this), so the warehouse and the
-- dashboards can tell the cash from the whole without reading this table: a trigger keeps it right on every deduction written or reversed.
ALTER TABLE orion_ods.case_transaction ADD COLUMN IF NOT EXISTS deducted_amount NUMERIC(14, 2) NOT NULL DEFAULT 0;

CREATE OR REPLACE FUNCTION orion_ods.bill_payment_deduction_totals() RETURNS trigger AS $$
BEGIN
    UPDATE orion_ods.case_transaction t
       SET deducted_amount = (SELECT COALESCE(SUM(d.amount), 0) FROM orion_ods.bill_payment_deduction d
                               WHERE d.transaction_code = t.transaction_code AND d.reversed_timestamp IS NULL)
     WHERE t.transaction_code = NEW.transaction_code;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS bill_payment_deduction_totals ON orion_ods.bill_payment_deduction;
CREATE TRIGGER bill_payment_deduction_totals
    AFTER INSERT OR UPDATE ON orion_ods.bill_payment_deduction
    FOR EACH ROW EXECUTE FUNCTION orion_ods.bill_payment_deduction_totals();

-- Entries whose payments were recorded before this column existed: bring the total in line (it changes nothing once they agree).
UPDATE orion_ods.case_transaction t
   SET deducted_amount = d.total
  FROM (SELECT transaction_code, SUM(amount) AS total FROM orion_ods.bill_payment_deduction WHERE reversed_timestamp IS NULL GROUP BY transaction_code) d
 WHERE d.transaction_code = t.transaction_code AND t.deducted_amount IS DISTINCT FROM d.total;
