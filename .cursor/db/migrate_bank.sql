-- Bank: the firm's bank account, its book of money in and out, imported bank statements, and the matching between the two.
-- Idempotent and additive: safe on a database that already has data, and applied on every API start. Written only by app.bank.
--
-- The balance is never stored. It is the opening balance plus every movement since the opening date, and a movement is either
--   * a client receipt, an expense or a GST payment that Orion already holds (read through the view bank_movement, so it is never typed twice and a
--     reversal anywhere is a reversal here), or
--   * a row in bank_entry: interest, other income, bank charges, loans and anything else with no record elsewhere.
-- Orion's own records stay the one place each fact lives.

-- Its own access: a view flag and a change flag. Money is the most sensitive thing in the application, so the first time the pair is added only
-- admins get it; after that each person's access is set in Admin. (The API also adds these columns at start, with the same backfill.)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_ods' AND table_name = 'app_user' AND column_name = 'bank_access'
    ) THEN
        ALTER TABLE orion_ods.app_user
            ADD COLUMN IF NOT EXISTS bank_access BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS bank_write  BOOLEAN NOT NULL DEFAULT FALSE;
        UPDATE orion_ods.app_user
           SET bank_access = role = 'admin',
               bank_write  = role = 'admin';
    END IF;
END $$;

-- The account. The application manages one for now; nothing here stops a second.
CREATE TABLE IF NOT EXISTS orion_ods.bank_account (
    account_id              SERIAL PRIMARY KEY,
    account_name            TEXT NOT NULL,
    bank_name               TEXT,
    account_last4           TEXT,
    opening_balance         NUMERIC(16, 2) NOT NULL,   -- what the bank held on opening_date, typed in by hand
    opening_date            DATE NOT NULL,             -- movements before this day are inside the opening balance, so they are not counted again
    created_by              INTEGER,
    created_timestamp       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Several accounts, and cash. An account is a bank account or a cash box (a cash account has no statement: it is counted, not reconciled).
-- Every money event says which account it touched. A receipt or a GST payment recorded before accounts existed has no account: it belongs to the
-- first account (the one that existed), which is how the view below reads it, so no balance moves when this is applied.
ALTER TABLE orion_ods.bank_account ADD COLUMN IF NOT EXISTS account_kind TEXT NOT NULL DEFAULT 'bank';
-- A minimum the balance should not fall below (optional): Orion warns, on the Overview and in the Copilot, when the balance is below it, or when the combined
-- balance of the accounts that have one is expected to be within two weeks. Never enforced: it only warns.
ALTER TABLE orion_ods.bank_account ADD COLUMN IF NOT EXISTS low_balance_floor NUMERIC(16, 2);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bank_account_kind_check' AND conrelid = 'orion_ods.bank_account'::regclass) THEN
        ALTER TABLE orion_ods.bank_account ADD CONSTRAINT bank_account_kind_check CHECK (account_kind IN ('bank', 'cash'));
    END IF;
END $$;
ALTER TABLE orion_ods.case_transaction ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES orion_ods.bank_account (account_id);
ALTER TABLE orion_ods.bill_gst_payment ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES orion_ods.bank_account (account_id);
-- EPFO and ESIC paid on a bill (migrate_bill_statutory.sql, which runs first) name the account they were paid from too; none means the first account.
ALTER TABLE orion_ods.bill_statutory_payment ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES orion_ods.bank_account (account_id);
-- A payment of an expense (migrate_expense_payments.sql, which runs first) names the account it was paid from; none means the first account.
ALTER TABLE orion_ods.expense_payment ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES orion_ods.bank_account (account_id);
-- A salary pay run (migrate_payroll.sql, which runs first) names the account the salary was paid from; none means the first account.
ALTER TABLE orion_ods.salary_run ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES orion_ods.bank_account (account_id);

-- Money in or out that has no record elsewhere in Orion (interest, other income, bank charges, loans, owner money, refunds, tax paid ...).
-- Nothing is deleted: a wrong entry is voided with a reason and stops counting.
CREATE TABLE IF NOT EXISTS orion_ods.bank_entry (
    entry_id            BIGSERIAL PRIMARY KEY,
    account_id          INTEGER NOT NULL REFERENCES orion_ods.bank_account (account_id),
    entry_date          DATE NOT NULL,
    direction           TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    amount              NUMERIC(16, 2) NOT NULL CHECK (amount > 0),
    category            TEXT NOT NULL,
    counterparty        TEXT,
    description         TEXT,
    reference           TEXT,
    statement_line_id   BIGINT,                         -- set when the entry was made from a statement line
    created_by          INTEGER,
    created_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    voided_by           INTEGER,
    voided_timestamp    TIMESTAMPTZ,
    void_reason         TEXT,
    CHECK ((voided_timestamp IS NULL) = (void_reason IS NULL))
);

CREATE INDEX IF NOT EXISTS bank_entry_date_idx ON orion_ods.bank_entry (account_id, entry_date);

-- A file the person uploaded. The file itself is not kept: its lines are, and a hash of it, so the same file is recognised.
CREATE TABLE IF NOT EXISTS orion_ods.bank_statement_import (
    import_id                   BIGSERIAL PRIMARY KEY,
    account_id                  INTEGER NOT NULL REFERENCES orion_ods.bank_account (account_id),
    filename                    TEXT NOT NULL,
    file_sha256                 TEXT NOT NULL,
    uploaded_by                 INTEGER,
    uploaded_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    period_from                 DATE,
    period_to                   DATE,
    line_count                  INTEGER NOT NULL DEFAULT 0,
    new_count                   INTEGER NOT NULL DEFAULT 0,
    duplicate_count             INTEGER NOT NULL DEFAULT 0,
    opening_statement_balance   NUMERIC(16, 2),         -- from the file's balance column, when it has one
    closing_statement_balance   NUMERIC(16, 2)
);

-- One row per line of a statement. The fingerprint makes a line recognisable when the same period is uploaded again, or two uploads overlap,
-- so it is never counted twice.
CREATE TABLE IF NOT EXISTS orion_ods.bank_statement_line (
    line_id         BIGSERIAL PRIMARY KEY,
    import_id       INTEGER NOT NULL REFERENCES orion_ods.bank_statement_import (import_id),
    account_id      INTEGER NOT NULL REFERENCES orion_ods.bank_account (account_id),
    line_date       DATE NOT NULL,
    description     TEXT,
    reference       TEXT,
    direction       TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    amount          NUMERIC(16, 2) NOT NULL CHECK (amount > 0),
    balance_after   NUMERIC(16, 2),
    fingerprint     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'Unmatched' CHECK (status IN ('Unmatched', 'Matched', 'Ignored')),
    ignore_reason   TEXT,
    UNIQUE (account_id, fingerprint)
);

CREATE INDEX IF NOT EXISTS bank_statement_line_date_idx ON orion_ods.bank_statement_line (account_id, line_date);

-- Which movement(s) of the book a statement line is. One line can be several movements (one deposit paying three bills); a movement is on
-- one line at most. source is revenue, expense, gst or entry and source_ref is its code (the batch for gst).
CREATE TABLE IF NOT EXISTS orion_ods.bank_match (
    match_id            BIGSERIAL PRIMARY KEY,
    line_id             BIGINT NOT NULL REFERENCES orion_ods.bank_statement_line (line_id),
    source              TEXT NOT NULL CHECK (source IN ('revenue', 'expense', 'gst', 'entry', 'payroll')),
    source_ref          TEXT NOT NULL,
    amount              NUMERIC(16, 2) NOT NULL,
    method              TEXT NOT NULL CHECK (method IN ('auto', 'manual', 'created')),
    matched_by          INTEGER,
    matched_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, source_ref)
);

CREATE INDEX IF NOT EXISTS bank_match_line_idx ON orion_ods.bank_match (line_id);

-- Who did what, for good: the account and its opening balance, entries and voids, imports, matches. Append-only.
CREATE TABLE IF NOT EXISTS orion_ods.bank_audit (
    audit_id    BIGSERIAL PRIMARY KEY,
    occurred    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id     INTEGER,
    action      TEXT NOT NULL,
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS bank_audit_occurred_idx ON orion_ods.bank_audit (occurred DESC);

-- Every movement the book holds, from wherever it lives. A client receipt is a Committed revenue entry (what a bill payment makes), an expense is a
-- Committed expense entry, GST paid is the payments recorded on bills (a payment recorded in one go is one movement), EPFO and ESIC paid are recorded
-- on bills the same way, and the rest are bank_entry.
-- A client receipt is the CASH that came in: the revenue entry settles the bill for the cash plus what the client held back (TDS and the like,
-- bill_payment_deduction, which migrate_deductions.sql creates before this file runs), and the part held back never reached the account.
CREATE OR REPLACE VIEW orion_ods.bank_movement AS
SELECT 'revenue'::text AS source,
       t.transaction_code AS source_ref,
       COALESCE(t.received_date, t.transaction_date) AS move_date,
       'in'::text AS direction,
       COALESCE(t.amount_after_tax_gst, t.transaction_amount) - held.amount AS amount,
       'client_receipt'::text AS category,
       NULL::text AS detail,
       cl.client_name AS counterparty,
       COALESCE(NULLIF(t.transaction_description, ''), 'Payment received') AS description,
       b.bill_number AS reference,
       t.bill_code AS bill_code,
       COALESCE(t.account_id, (SELECT MIN(account_id) FROM orion_ods.bank_account)) AS account_id
  FROM orion_ods.case_transaction t
  LEFT JOIN orion_ods.case cs ON cs.case_code = t.case_code
  LEFT JOIN orion_ods.client cl ON cl.client_code = cs.client_code
  LEFT JOIN orion_ods.bill b ON b.bill_code = t.bill_code
 CROSS JOIN LATERAL (
        SELECT COALESCE(SUM(d.amount), 0) AS amount FROM orion_ods.bill_payment_deduction d
         WHERE d.transaction_code = t.transaction_code AND d.reversed_timestamp IS NULL
 ) held
 WHERE t.transaction_status = 'Committed'
   AND COALESCE(t.amount_after_tax_gst, t.transaction_amount) - held.amount > 0
   AND COALESCE(t.received_date, t.transaction_date) IS NOT NULL
UNION ALL
SELECT 'expense'::text,
       p.payment_id::text,
       p.paid_date,
       'out'::text,
       p.amount,
       'expense'::text,
       et.expense_type_name,
       NULL::text,
       COALESCE(NULLIF(e.transaction_description, ''), et.expense_type_name, 'Expense'),
       COALESCE(p.reference, e.case_code),
       NULL::text,
       COALESCE(p.account_id, (SELECT MIN(account_id) FROM orion_ods.bank_account))
  FROM orion_ods.expense_payment p
  JOIN orion_ods.expense_transaction e ON e.expense_code = p.expense_code
  LEFT JOIN orion_ods.expense_type et ON et.expense_type_code = e.expense_type_code
 WHERE p.reversed_timestamp IS NULL
UNION ALL
SELECT 'gst'::text,
       p.batch_id,
       COALESCE(MIN(p.paid_date), MIN(p.recorded_timestamp)::date),
       'out'::text,
       SUM(p.amount),
       'gst_payment'::text,
       NULL::text,
       NULL::text,
       'GST paid on bill ' || string_agg(DISTINCT b.bill_number, ', '),
       MAX(p.reference),
       NULL::text,
       MIN(COALESCE(p.account_id, (SELECT MIN(account_id) FROM orion_ods.bank_account)))
  FROM orion_ods.bill_gst_payment p
  JOIN orion_ods.bill b ON b.bill_code = p.bill_code
 WHERE p.reversed_timestamp IS NULL
 GROUP BY p.batch_id
UNION ALL
SELECT 'statutory'::text,
       p.batch_id,
       COALESCE(MIN(p.paid_date), MIN(p.recorded_timestamp)::date),
       'out'::text,
       SUM(p.amount),
       'statutory_payment'::text,
       NULL::text,
       NULL::text,
       string_agg(DISTINCT p.component, ' and ' ORDER BY p.component) || ' paid on bill ' || string_agg(DISTINCT b.bill_number, ', '),
       MAX(p.reference),
       NULL::text,
       MIN(COALESCE(p.account_id, (SELECT MIN(account_id) FROM orion_ods.bank_account)))
  FROM orion_ods.bill_statutory_payment p
  JOIN orion_ods.bill b ON b.bill_code = p.bill_code
 WHERE p.reversed_timestamp IS NULL
 GROUP BY p.batch_id
UNION ALL
SELECT 'entry'::text,
       n.entry_id::text,
       n.entry_date,
       n.direction,
       n.amount,
       n.category,
       NULL::text,
       n.counterparty,
       n.description,
       n.reference,
       NULL::text,
       n.account_id
  FROM orion_ods.bank_entry n
 WHERE n.voided_timestamp IS NULL
UNION ALL
-- Salary: one movement per pay run (a month's lines paid by one transfer), for what its lines came to, on the day it was paid.
SELECT 'payroll'::text,
       r.run_id::text,
       r.paid_date,
       'out'::text,
       s.total,
       'payroll'::text,
       'Salary'::text,
       NULL::text,
       'Salary for ' || r.month_year || ' (' || s.lines || CASE WHEN s.lines = 1 THEN ' employee)' ELSE ' employees)' END,
       r.reference,
       NULL::text,
       COALESCE(r.account_id, (SELECT MIN(account_id) FROM orion_ods.bank_account))
  FROM orion_ods.salary_run r
  CROSS JOIN LATERAL (
        SELECT COUNT(*) AS lines, ROUND(COALESCE(SUM(t.salary_amount), 0), 2) AS total
          FROM orion_ods.employee_transaction t WHERE t.salary_run_id = r.run_id
  ) s
 WHERE r.reversed_timestamp IS NULL
   AND s.total > 0;

-- What is expected but has not happened: money clients are still to pay and costs still to come (Prospective entries, on the day they are
-- expected), and the GST still to pay on issued bills, estimated for the 20th of the month after the bill (when the return is due).
CREATE OR REPLACE VIEW orion_ods.bank_expected AS
SELECT 'revenue'::text AS source,
       t.transaction_code AS source_ref,
       t.transaction_date AS due_date,
       'in'::text AS direction,
       COALESCE(t.amount_after_tax_gst, t.transaction_amount) AS amount,
       'client_receipt'::text AS category,
       cl.client_name AS counterparty,
       COALESCE(NULLIF(t.transaction_description, ''), 'Payment expected') AS description,
       b.bill_number AS reference
  FROM orion_ods.case_transaction t
  LEFT JOIN orion_ods.case cs ON cs.case_code = t.case_code
  LEFT JOIN orion_ods.client cl ON cl.client_code = cs.client_code
  LEFT JOIN orion_ods.bill b ON b.bill_code = t.bill_code
 WHERE t.transaction_status = 'Prospective'
   AND COALESCE(t.amount_after_tax_gst, t.transaction_amount) > 0
   AND t.transaction_date IS NOT NULL
UNION ALL
SELECT 'expense'::text,
       e.expense_code,
       COALESCE(e.due_date, e.transaction_date),
       'out'::text,
       CASE WHEN e.transaction_status = 'Committed'
            THEN ROUND(COALESCE(e.amount_after_tax_gst, e.transaction_amount), 2) - COALESCE(paid.total, 0)
            ELSE COALESCE(e.amount_after_tax_gst, e.transaction_amount) END,
       'expense'::text,
       et.expense_type_name,
       COALESCE(NULLIF(e.transaction_description, ''), et.expense_type_name, CASE WHEN e.transaction_status = 'Committed' THEN 'Expense to pay' ELSE 'Expense expected' END),
       e.case_code
  FROM orion_ods.expense_transaction e
  LEFT JOIN orion_ods.expense_type et ON et.expense_type_code = e.expense_type_code
  LEFT JOIN LATERAL (
        SELECT SUM(p.amount) AS total FROM orion_ods.expense_payment p WHERE p.expense_code = e.expense_code AND p.reversed_timestamp IS NULL
  ) paid ON TRUE
 WHERE ((e.transaction_status = 'Prospective' AND COALESCE(e.amount_after_tax_gst, e.transaction_amount) > 0)
        OR (e.transaction_status = 'Committed'   -- incurred and not yet (fully) paid: what is still to go out, on the day it is due
            AND ROUND(COALESCE(e.amount_after_tax_gst, e.transaction_amount), 2) - COALESCE(paid.total, 0) > 0))
   AND COALESCE(e.due_date, e.transaction_date) IS NOT NULL
UNION ALL
SELECT 'gst_due'::text,
       b.bill_code,
       (date_trunc('month', b.bill_date) + INTERVAL '1 month' + INTERVAL '19 days')::date,
       'out'::text,
       b.cgst_amount + b.sgst_amount - b.credited_cgst - b.credited_sgst - b.gst_paid_amount,
       'gst_payment'::text,
       NULL::text,
       'GST still to pay on bill ' || b.bill_number,
       b.bill_number
  FROM orion_ods.bill b
 WHERE b.status = 'Issued'
   AND b.cgst_amount + b.sgst_amount - b.credited_cgst - b.credited_sgst - b.gst_paid_amount > 0
UNION ALL
-- Salary still to pay: the lines of each month that no pay run has paid, on the month's last day (the date its lines carry).
SELECT 'payroll_due'::text,
       u.month_year,
       u.due_date,
       'out'::text,
       u.total,
       'payroll'::text,
       NULL::text,
       'Salary still to pay for ' || u.month_year,
       NULL::text
  FROM (
        SELECT t.month_year, MAX(t.transaction_date) AS due_date, ROUND(SUM(t.salary_amount), 2) AS total
          FROM orion_ods.employee_transaction t
         WHERE t.salary_paid = 'No' AND t.salary_run_id IS NULL AND t.month_year IS NOT NULL AND t.transaction_date IS NOT NULL AND t.salary_amount > 0
         GROUP BY t.month_year
  ) u
 WHERE u.total > 0;

-- A statement line matched to an expense, before payments existed, is matched to the one payment that stood in for the expense (the movement is now
-- the payment, not the expense). Only an expense with exactly one payment can have been matched that way. Once moved, the reference is a payment number
-- and no longer an expense code, so running this again changes nothing.
UPDATE orion_ods.bank_match m
   SET source_ref = p.payment_id::text
  FROM orion_ods.expense_payment p
 WHERE m.source = 'expense'
   AND m.source_ref = p.expense_code
   AND p.reversed_timestamp IS NULL
   AND (SELECT COUNT(*) FROM orion_ods.expense_payment q WHERE q.expense_code = p.expense_code AND q.reversed_timestamp IS NULL) = 1;

-- A statement line can be matched to a salary pay run. A bank_match table made before that accepts only the other sources, so its check is replaced (once).
DO $$
DECLARE
    old TEXT;
BEGIN
    SELECT conname INTO old
      FROM pg_constraint
     WHERE conrelid = 'orion_ods.bank_match'::regclass AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%source%' AND pg_get_constraintdef(oid) LIKE '%revenue%' AND pg_get_constraintdef(oid) NOT LIKE '%payroll%';
    IF old IS NOT NULL THEN
        EXECUTE format('ALTER TABLE orion_ods.bank_match DROP CONSTRAINT %I', old);
        ALTER TABLE orion_ods.bank_match
            ADD CONSTRAINT bank_match_source_check CHECK (source IN ('revenue', 'expense', 'gst', 'entry', 'payroll'));
    END IF;
END $$;
