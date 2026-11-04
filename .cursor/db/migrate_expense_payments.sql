-- Expenses are paid, not only incurred. A Committed expense is a cost the firm has taken on; the money leaves the bank when it is PAID, which may be later,
-- in instalments, from different accounts. Each payment is a row here; whether an expense is Unpaid, Part paid or Paid is worked out from them and never stored.
-- Idempotent and additive: safe on a database that already has data, and applied on every API start. Written only by app.payables.
--
-- This file runs before migrate_bank.sql (which names the account on each payment, and reads the payments in the bank view), so a payment's
-- account_id is added there, beside the same column on the GST payments.

-- The day the supplier is to be paid by. Empty: the transaction date stands in for it.
ALTER TABLE orion_ods.expense_transaction ADD COLUMN IF NOT EXISTS due_date DATE;

-- One row per payment. A reversed payment is kept, with who, when and why; nothing here is ever deleted, so taking a payment back never erases that it
-- was recorded. The sum of what is not reversed is what has been paid.
CREATE TABLE IF NOT EXISTS orion_ods.expense_payment (
    payment_id          BIGSERIAL PRIMARY KEY,
    expense_code        TEXT NOT NULL REFERENCES orion_ods.expense_transaction (expense_code),
    amount              NUMERIC(16, 2) NOT NULL CHECK (amount > 0),
    paid_date           DATE NOT NULL,
    reference           TEXT,   -- cheque number, UTR or other payment reference, optional
    recorded_by         INTEGER,
    recorded_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reversed_by         INTEGER,
    reversed_timestamp  TIMESTAMPTZ,
    reversal_reason     TEXT,
    CHECK ((reversed_timestamp IS NULL) = (reversal_reason IS NULL))
);

CREATE INDEX IF NOT EXISTS expense_payment_expense_idx ON orion_ods.expense_payment (expense_code);
CREATE INDEX IF NOT EXISTS expense_payment_date_idx ON orion_ods.expense_payment (paid_date) WHERE reversed_timestamp IS NULL;

-- Until now the bank counted a Committed expense as paid, in full, on its transaction date. So that no balance moves when payments begin, every such expense
-- gets the one payment that counting meant: all of it, on that date. This runs once (the marker row), so an expense entered afterwards starts unpaid
-- and is paid by recording a payment. The account is left empty, which means the first account, as it always was.
CREATE TABLE IF NOT EXISTS orion_ods.expense_payment_backfill (
    done_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM orion_ods.expense_payment_backfill) THEN
        INSERT INTO orion_ods.expense_payment (expense_code, amount, paid_date, recorded_by, recorded_timestamp)
        SELECT e.expense_code,
               ROUND(COALESCE(e.amount_after_tax_gst, e.transaction_amount), 2),
               e.transaction_date,
               e.created_by,
               e.created_timestamp
          FROM orion_ods.expense_transaction e
         WHERE e.transaction_status = 'Committed'
           AND ROUND(COALESCE(e.amount_after_tax_gst, e.transaction_amount), 2) > 0
           AND e.transaction_date IS NOT NULL;
        INSERT INTO orion_ods.expense_payment_backfill DEFAULT VALUES;
    END IF;
END $$;

-- An expense that has been paid stays a Committed expense, and is never worth less than what was paid on it. Cancelling it, or lowering its amount, has to
-- start by reversing the payments (with a reason). The constraint names are what app/entity_service.py turns into a message (CONSTRAINT_MESSAGES).
CREATE OR REPLACE FUNCTION orion_ods.expense_keeps_its_payments() RETURNS trigger AS $$
DECLARE
    paid NUMERIC;
BEGIN
    SELECT COALESCE(SUM(amount), 0) INTO paid
      FROM orion_ods.expense_payment
     WHERE expense_code = NEW.expense_code AND reversed_timestamp IS NULL;
    IF paid > 0 THEN
        IF NEW.transaction_status IS DISTINCT FROM 'Committed' THEN
            RAISE EXCEPTION 'An expense with payments on it stays committed'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'expense_paid_stays_committed';
        END IF;
        IF ROUND(COALESCE(NEW.amount_after_tax_gst, NEW.transaction_amount, 0), 2) < paid THEN
            RAISE EXCEPTION 'An expense cannot be less than what has been paid on it'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'expense_amount_covers_payments';
        END IF;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS expense_keeps_its_payments ON orion_ods.expense_transaction;
CREATE TRIGGER expense_keeps_its_payments
    BEFORE UPDATE OF transaction_status, transaction_amount, amount_after_tax_gst ON orion_ods.expense_transaction
    FOR EACH ROW EXECUTE FUNCTION orion_ods.expense_keeps_its_payments();
