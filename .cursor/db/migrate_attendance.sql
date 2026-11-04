-- Attendance: who worked at a case in a month, and the pay that follows. One register (sheet) per case and month, with a line for each person; posting a
-- register enters the pay: a salary line (employee_transaction) for each employee, an expense (expense_transaction) for each person who is not an employee.
-- Idempotent and additive: safe on a database that already has data, and applied on every API start, after migrate_payroll.sql and migrate_bank.sql.
--
-- Written only by app.attendance. Nothing here is loaded into the warehouse; the salary lines and expenses it enters are.

-- Attendance is its own area, with a view flag and a change flag like Tenders. The first time the pair is added, admins and editors get both, which is what a
-- new user of those roles gets by default; after that each person's access is set in Admin. (The API also adds these columns at start, with the same
-- backfill; this is for new databases.)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_ods' AND table_name = 'app_user' AND column_name = 'attendance_access'
    ) THEN
        ALTER TABLE orion_ods.app_user
            ADD COLUMN IF NOT EXISTS attendance_access BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS attendance_write  BOOLEAN NOT NULL DEFAULT FALSE;
        UPDATE orion_ods.app_user
           SET attendance_access = role IN ('admin', 'editor'),
               attendance_write  = role IN ('admin', 'editor');
    END IF;
END $$;

CREATE SEQUENCE IF NOT EXISTS orion_ods.attendance_sheet_seq START 1;
CREATE SEQUENCE IF NOT EXISTS orion_ods.attendance_worker_seq START 1;

-- People who work at a case but are not employees (casual labour, contractors' staff). Saved so the next register finds them; they are not in the employee table
-- and never appear in Operational Data's employees.
CREATE TABLE IF NOT EXISTS orion_ods.attendance_worker (
    worker_code            TEXT PRIMARY KEY DEFAULT orion_ods.next_code('WRK', 'orion_ods.attendance_worker_seq'),
    worker_name            TEXT NOT NULL,
    phone                  TEXT,
    designation            TEXT,
    default_rate           NUMERIC(14, 4) CHECK (default_rate IS NULL OR default_rate >= 0),
    case_code              TEXT REFERENCES orion_ods."case"(case_code),
    worker_status          TEXT NOT NULL DEFAULT 'Active' CHECK (worker_status IN ('Active', 'Inactive')),
    notes                  TEXT,
    created_by             INTEGER,
    last_updated_by        INTEGER,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- The same person is not saved twice (same name and phone, ignoring case).
CREATE UNIQUE INDEX IF NOT EXISTS ux_attendance_worker_person ON orion_ods.attendance_worker (lower(worker_name), COALESCE(phone, ''));
CREATE INDEX IF NOT EXISTS ix_attendance_worker_case ON orion_ods.attendance_worker (case_code) WHERE case_code IS NOT NULL;

-- One register for a case and a month. Draft can be changed; Posted has entered the pay and is changed only by reopening it (which takes the entries back, unless
-- any has been paid).
CREATE TABLE IF NOT EXISTS orion_ods.attendance_sheet (
    sheet_id               SERIAL PRIMARY KEY,
    sheet_code             TEXT NOT NULL UNIQUE DEFAULT orion_ods.next_code('ATT', 'orion_ods.attendance_sheet_seq'),
    case_code              TEXT NOT NULL REFERENCES orion_ods."case"(case_code),
    month_year             TEXT NOT NULL CHECK (month_year ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    sheet_status           TEXT NOT NULL DEFAULT 'Draft' CHECK (sheet_status IN ('Draft', 'Posted')),
    expense_type_code      TEXT REFERENCES orion_ods.expense_type(expense_type_code),
    remarks                TEXT,
    posted_by              INTEGER,
    posted_timestamp       TIMESTAMPTZ,
    created_by             INTEGER,
    last_updated_by        INTEGER,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (case_code, month_year),
    CONSTRAINT attendance_posted_has_time CHECK ((sheet_status = 'Posted') = (posted_timestamp IS NOT NULL))
);

-- One person's line: an employee or a saved worker, never both. The amount is what is paid (it starts as the rate times the days, plus the extra, less the
-- deduction, and may be changed); the name and designation are kept as they were when the register was made.
CREATE TABLE IF NOT EXISTS orion_ods.attendance_line (
    line_id          SERIAL PRIMARY KEY,
    sheet_id         INTEGER NOT NULL REFERENCES orion_ods.attendance_sheet(sheet_id) ON DELETE CASCADE,
    line_no          INTEGER NOT NULL DEFAULT 0,
    employee_code    TEXT REFERENCES orion_ods.employee(employee_code),
    worker_code      TEXT REFERENCES orion_ods.attendance_worker(worker_code),
    person_name      TEXT NOT NULL,
    designation      TEXT,
    days_present     NUMERIC(4, 1) NOT NULL DEFAULT 0 CHECK (days_present >= 0 AND days_present <= 31),
    rate_per_day     NUMERIC(14, 4) NOT NULL DEFAULT 0 CHECK (rate_per_day >= 0),
    extra_amount     NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (extra_amount >= 0),
    deduction_amount NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (deduction_amount >= 0),
    amount           NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (amount >= 0),
    remarks          TEXT,
    CONSTRAINT attendance_line_one_person CHECK ((employee_code IS NOT NULL) <> (worker_code IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_attendance_line_employee ON orion_ods.attendance_line (sheet_id, employee_code) WHERE employee_code IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_attendance_line_worker ON orion_ods.attendance_line (sheet_id, worker_code) WHERE worker_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_attendance_line_employee ON orion_ods.attendance_line (employee_code) WHERE employee_code IS NOT NULL;

-- What was done to a register and when: made, changed, posted, reopened. Never changed or deleted by the app.
CREATE TABLE IF NOT EXISTS orion_ods.attendance_event (
    id       SERIAL PRIMARY KEY,
    sheet_id INTEGER NOT NULL REFERENCES orion_ods.attendance_sheet(sheet_id) ON DELETE CASCADE,
    action   TEXT NOT NULL,
    note     TEXT,
    by_user  INTEGER,
    at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_attendance_event ON orion_ods.attendance_event (sheet_id, id);

-- What posting a register enters, and where it came from. The case a salary line was worked at (it may not be the employee's own case), and the register line behind a
-- salary line or an expense, so they can be found, locked while the register stands, and taken back when it is reopened.
ALTER TABLE orion_ods.employee_transaction ADD COLUMN IF NOT EXISTS case_code TEXT REFERENCES orion_ods."case"(case_code);
ALTER TABLE orion_ods.employee_transaction ADD COLUMN IF NOT EXISTS attendance_line_id INTEGER REFERENCES orion_ods.attendance_line(line_id);
ALTER TABLE orion_ods.expense_transaction ADD COLUMN IF NOT EXISTS attendance_line_id INTEGER REFERENCES orion_ods.attendance_line(line_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_employee_transaction_attendance ON orion_ods.employee_transaction (attendance_line_id) WHERE attendance_line_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_expense_transaction_attendance ON orion_ods.expense_transaction (attendance_line_id) WHERE attendance_line_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_employee_transaction_case ON orion_ods.employee_transaction (case_code) WHERE case_code IS NOT NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON orion_ods.attendance_worker, orion_ods.attendance_sheet, orion_ods.attendance_line, orion_ods.attendance_event TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.attendance_sheet_seq, orion_ods.attendance_worker_seq, orion_ods.attendance_sheet_sheet_id_seq,
                              orion_ods.attendance_line_line_id_seq, orion_ods.attendance_event_id_seq TO orion_user;
    END IF;
END $$;
