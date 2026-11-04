-- Link case_transaction to bill. Idempotent. Runs after migrate_bill.sql.

ALTER TABLE orion_ods.case_transaction
    ADD COLUMN IF NOT EXISTS bill_code TEXT;

-- migrate_bill.sql drops this link when it retires the first-shape bill table, so it is
-- added by name here rather than inline on the column.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'orion_ods.case_transaction'::regclass
           AND confrelid = 'orion_ods.bill'::regclass
           AND contype = 'f'
    ) THEN
        ALTER TABLE orion_ods.case_transaction
            ADD CONSTRAINT case_transaction_bill_code_fkey
            FOREIGN KEY (bill_code) REFERENCES orion_ods.bill(bill_code);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_case_transaction_bill
    ON orion_ods.case_transaction (bill_code);

ALTER TABLE orion_dw.fact_case_transaction
    ADD COLUMN IF NOT EXISTS bill_sk BIGINT;

ALTER TABLE orion_dw.fact_case_transaction
    ADD COLUMN IF NOT EXISTS bill_code TEXT;

-- A bill's revenue is tracked here: one Prospective entry for what is still to be received,
-- and one Committed entry for each payment. An entry keeps the bill date in
-- transaction_date; received_date is when the money came in.
ALTER TABLE orion_ods.case_transaction
    ADD COLUMN IF NOT EXISTS received_date DATE;

-- A bill never has two open (Prospective) entries, however fast two people click.
CREATE UNIQUE INDEX IF NOT EXISTS ux_case_transaction_bill_open
    ON orion_ods.case_transaction (bill_code)
    WHERE bill_code IS NOT NULL AND transaction_status = 'Prospective';

ALTER TABLE orion_dw.fact_case_transaction
    ADD COLUMN IF NOT EXISTS received_date DATE;
