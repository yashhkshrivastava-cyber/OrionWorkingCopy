-- GST on a bill is paid to the government in instalments: CGST and SGST on different days, a part now and the rest later. Each payment is a row
-- here; the bill keeps the running total (gst_paid_amount) and whether it is all paid (gst_paid, as before). Safe to run again.

ALTER TABLE orion_ods.bill
    ADD COLUMN IF NOT EXISTS gst_paid_amount NUMERIC(14, 2) NOT NULL DEFAULT 0;   -- the GST paid so far, from the payments below that have not been reversed

-- One row per component per payment. Rows recorded together (one dialog, one day, one reference) share a batch_id, and a batch is reversed as a
-- whole. A reversed row is kept, with who, when and why; nothing here is ever deleted, so taking a payment back never erases that it was recorded.
CREATE TABLE IF NOT EXISTS orion_ods.bill_gst_payment (
    gst_payment_sk      BIGSERIAL PRIMARY KEY,
    bill_code           TEXT NOT NULL REFERENCES orion_ods.bill (bill_code),
    batch_id            TEXT NOT NULL,
    component           TEXT NOT NULL CHECK (component IN ('CGST', 'SGST')),
    amount              NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    paid_date           DATE,   -- the day it was paid to the government; empty only for bills marked paid before the day was asked
    reference           TEXT,   -- challan number or payment reference, optional
    recorded_by         INTEGER,
    recorded_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reversed_by         INTEGER,
    reversed_timestamp  TIMESTAMPTZ,
    reversal_reason     TEXT,
    CHECK ((reversed_timestamp IS NULL) = (reversal_reason IS NULL))
);

CREATE INDEX IF NOT EXISTS bill_gst_payment_bill_idx ON orion_ods.bill_gst_payment (bill_code, recorded_timestamp);
CREATE INDEX IF NOT EXISTS bill_gst_payment_batch_idx ON orion_ods.bill_gst_payment (batch_id);

-- Bills already ticked as paid before this existed get the payments that tick meant: all of the CGST and all of the SGST, recorded by whoever
-- ticked it, when they did. The day it was paid was never asked, so it stays empty. Only for bills with no payment yet, so a second run adds nothing.
INSERT INTO orion_ods.bill_gst_payment (bill_code, batch_id, component, amount, paid_date, recorded_by, recorded_timestamp)
SELECT b.bill_code, 'legacy-' || b.bill_code, c.component, c.amount, NULL, b.gst_paid_by, COALESCE(b.gst_paid_timestamp, b.last_updated_timestamp)
  FROM orion_ods.bill b
 CROSS JOIN LATERAL (VALUES ('CGST', b.cgst_amount), ('SGST', b.sgst_amount)) AS c (component, amount)
 WHERE b.gst_paid
   AND c.amount > 0
   AND NOT EXISTS (SELECT 1 FROM orion_ods.bill_gst_payment p WHERE p.bill_code = b.bill_code);

UPDATE orion_ods.bill b
   SET gst_paid_amount = s.total
  FROM (SELECT bill_code, SUM(amount) AS total FROM orion_ods.bill_gst_payment WHERE reversed_timestamp IS NULL GROUP BY bill_code) s
 WHERE s.bill_code = b.bill_code
   AND b.gst_paid_amount <> s.total;
