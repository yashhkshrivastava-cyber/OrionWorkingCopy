-- Salary reaches the bank in pay runs. A month's salary lines are paid together by one bank transfer, so a pay run is one row here, with the lines it paid
-- (employee_transaction.salary_run_id), the day, the account and the bank reference. What it came to is worked out from its lines, never stored. The bank reads
-- the runs (the view bank_movement), so one transfer on a statement matches one movement.
-- Idempotent and additive: safe on a database that already has data, and applied on every API start. Written only by app.payroll.
--
-- This file runs before migrate_bank.sql (which names the account on each run, and reads the runs in the bank view), so a run's account_id is added there,
-- beside the same column on expense payments.

-- One row per pay run. A reversed run is kept, with who, when and why; nothing here is ever deleted. Its lines go back to unpaid.
CREATE TABLE IF NOT EXISTS orion_ods.salary_run (
    run_id              BIGSERIAL PRIMARY KEY,
    month_year          TEXT NOT NULL,        -- the month the salary was for, YYYY-MM
    paid_date           DATE NOT NULL,        -- the day the money went out
    reference           TEXT,                 -- the bank transfer reference, optional
    recorded_by         INTEGER,
    recorded_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reversed_by         INTEGER,
    reversed_timestamp  TIMESTAMPTZ,
    reversal_reason     TEXT,
    CHECK ((reversed_timestamp IS NULL) = (reversal_reason IS NULL))
);

CREATE INDEX IF NOT EXISTS salary_run_month_idx ON orion_ods.salary_run (month_year);

-- The run that paid a line. A line is paid (salary_paid = 'Yes') only through a run; it is empty for a line not yet paid.
ALTER TABLE orion_ods.employee_transaction ADD COLUMN IF NOT EXISTS salary_run_id BIGINT REFERENCES orion_ods.salary_run (run_id);
CREATE INDEX IF NOT EXISTS employee_transaction_run_idx ON orion_ods.employee_transaction (salary_run_id);

-- Until now a line marked paid was only a flag: the bank never saw it. So that the flag keeps meaning what it meant, every line already marked paid is given a
-- run: one for each month and day (the line's own date), in the account that was always the default (none named). This runs once (the marker row), so a
-- line marked paid afterwards belongs to the run that paid it. What the bank holds from a run is only what falls on or after the account's opening date.
CREATE TABLE IF NOT EXISTS orion_ods.salary_run_backfill (
    done_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM orion_ods.salary_run_backfill) THEN
        WITH made AS (
            INSERT INTO orion_ods.salary_run (month_year, paid_date)
            SELECT g.month_year, g.transaction_date
              FROM (SELECT DISTINCT month_year, transaction_date
                      FROM orion_ods.employee_transaction
                     WHERE salary_paid = 'Yes' AND month_year IS NOT NULL AND transaction_date IS NOT NULL) g
            RETURNING run_id, month_year, paid_date
        )
        UPDATE orion_ods.employee_transaction t
           SET salary_run_id = made.run_id
          FROM made
         WHERE t.salary_paid = 'Yes' AND t.salary_run_id IS NULL
           AND t.month_year = made.month_year AND t.transaction_date = made.paid_date;
        INSERT INTO orion_ods.salary_run_backfill DEFAULT VALUES;
    END IF;
END $$;

-- A salary line is paid through a pay run, and what a run paid stays as it was paid. The rules cover what is NEW: a line marked paid with no run is refused,
-- and a line in a run cannot change its employee, month, amount or paid state, or be deleted, until the run is reversed (with a reason). A line marked paid
-- before this existed and left with no run (it had no date to make a run from) can still be edited where it stands. The constraint names are what
-- app/entity_service.py turns into a message (CONSTRAINT_MESSAGES).
CREATE OR REPLACE FUNCTION orion_ods.salary_line_follows_its_run() RETURNS trigger AS $$
DECLARE
    active BOOLEAN;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.salary_run_id IS NOT NULL
           AND EXISTS (SELECT 1 FROM orion_ods.salary_run WHERE run_id = OLD.salary_run_id AND reversed_timestamp IS NULL) THEN
            RAISE EXCEPTION 'A salary line that has been paid cannot be deleted'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'salary_line_paid_cannot_be_deleted';
        END IF;
        RETURN OLD;
    END IF;
    NEW.salary_paid := COALESCE(NEW.salary_paid, 'No');   -- a line with no answer is a line not yet paid: Payroll only finds lines that say No
    IF NEW.salary_paid = 'Yes' AND NEW.salary_run_id IS NULL
       AND (TG_OP = 'INSERT' OR OLD.salary_paid IS DISTINCT FROM 'Yes' OR OLD.salary_run_id IS NOT NULL) THEN
        RAISE EXCEPTION 'Salary is marked paid through a pay run'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'salary_paid_needs_run';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.salary_run_id IS NOT NULL THEN
        SELECT reversed_timestamp IS NULL INTO active FROM orion_ods.salary_run WHERE run_id = OLD.salary_run_id;
        IF COALESCE(active, FALSE)
           AND (NEW.salary_run_id IS DISTINCT FROM OLD.salary_run_id
                OR NEW.salary_paid IS DISTINCT FROM OLD.salary_paid
                OR NEW.salary_amount IS DISTINCT FROM OLD.salary_amount
                OR NEW.employee_code IS DISTINCT FROM OLD.employee_code
                OR NEW.month_year IS DISTINCT FROM OLD.month_year) THEN
            RAISE EXCEPTION 'A salary line that has been paid cannot be changed'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'salary_line_paid_is_locked';
        END IF;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS salary_line_follows_its_run ON orion_ods.employee_transaction;
CREATE TRIGGER salary_line_follows_its_run
    BEFORE INSERT OR UPDATE OR DELETE ON orion_ods.employee_transaction
    FOR EACH ROW EXECUTE FUNCTION orion_ods.salary_line_follows_its_run();

-- A salary line is paid or not: it starts as No (left out, or sent empty, it is No) and is set to Yes only by a pay run. Lines stored with no answer before this are
-- not yet paid, so they are No (they were missing from "salary pending" and could not be found by Payroll).
UPDATE orion_ods.employee_transaction SET salary_paid = 'No' WHERE salary_paid IS NULL;
ALTER TABLE orion_ods.employee_transaction ALTER COLUMN salary_paid SET DEFAULT 'No';
ALTER TABLE orion_ods.employee_transaction ALTER COLUMN salary_paid SET NOT NULL;
