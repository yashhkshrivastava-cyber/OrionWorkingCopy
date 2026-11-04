-- EPFO and ESIC charged on a bill are paid to the authorities, in whole or in parts, on different days, and the business needs to know which bills it has paid
-- them for, the same as it does for GST (migrate_bill_gst.sql). Each payment is a row here; the bill keeps the running total of each (epf_paid_amount,
-- esic_paid_amount). What is DUE on a bill is what it charged: its epf_amount and esic_amount. Safe to run again.
--
-- Charged to the client, EPFO and ESIC are inside the bill's taxable value, so inside Revenue, as before. A payment here is a
-- cost on the day paid (the view orion_dw.expense_cost, dw_schema.sql), against the bill's case; it does not depend on payroll or attendance.

ALTER TABLE orion_ods.bill
    ADD COLUMN IF NOT EXISTS epf_paid_amount  NUMERIC(14, 2) NOT NULL DEFAULT 0,   -- EPFO paid so far, from the payments below that have not been reversed
    ADD COLUMN IF NOT EXISTS esic_paid_amount NUMERIC(14, 2) NOT NULL DEFAULT 0;   -- ESIC paid so far, the same way

-- One row per component per payment. Rows recorded together (one dialog, one day, one reference) share a batch_id, and a batch is reversed as a whole. A
-- reversed row is kept, with who, when and why; nothing here is ever deleted, so taking a payment back never erases that it was recorded.
CREATE TABLE IF NOT EXISTS orion_ods.bill_statutory_payment (
    statutory_payment_sk BIGSERIAL PRIMARY KEY,
    bill_code            TEXT NOT NULL REFERENCES orion_ods.bill (bill_code),
    batch_id             TEXT NOT NULL,
    component            TEXT NOT NULL CHECK (component IN ('EPFO', 'ESIC')),
    amount               NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    paid_date            DATE NOT NULL,   -- the day it was paid to the authority
    reference            TEXT,            -- challan number, TRRN or payment reference, optional
    recorded_by          INTEGER,
    recorded_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reversed_by          INTEGER,
    reversed_timestamp   TIMESTAMPTZ,
    reversal_reason      TEXT,
    CHECK ((reversed_timestamp IS NULL) = (reversal_reason IS NULL))
);

CREATE INDEX IF NOT EXISTS bill_statutory_payment_bill_idx ON orion_ods.bill_statutory_payment (bill_code, recorded_timestamp);
CREATE INDEX IF NOT EXISTS bill_statutory_payment_batch_idx ON orion_ods.bill_statutory_payment (batch_id);
