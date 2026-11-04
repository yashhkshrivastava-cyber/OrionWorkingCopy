-- Orion ODS schema for local development.
-- Idempotent: safe to run repeatedly.

CREATE SCHEMA IF NOT EXISTS orion_ods;

-- Business codes look like BD-0007 and stay four digits until the sequence
-- passes 9999, after which they simply grow (BD-10000). Padding with LPAD alone
-- truncates on the right, which silently produces duplicate codes.
CREATE OR REPLACE FUNCTION orion_ods.next_code(prefix TEXT, seq TEXT)
RETURNS TEXT
LANGUAGE sql
VOLATILE
AS $$
    SELECT prefix || '-' || CASE WHEN v < 10000 THEN LPAD(v::TEXT, 4, '0') ELSE v::TEXT END
    FROM (SELECT nextval(seq::regclass) AS v) s
$$;

CREATE SEQUENCE IF NOT EXISTS orion_ods.business_domain_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.business_domain (
    business_domain_code   TEXT PRIMARY KEY DEFAULT orion_ods.next_code('BD', 'orion_ods.business_domain_seq'),
    business_domain_name   TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS orion_ods.capability_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.capability (
    capability_code        TEXT PRIMARY KEY DEFAULT orion_ods.next_code('CAP', 'orion_ods.capability_seq'),
    capability_name        TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS orion_ods.expense_type_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.expense_type (
    expense_type_code      TEXT PRIMARY KEY DEFAULT orion_ods.next_code('EXP', 'orion_ods.expense_type_seq'),
    expense_type_name      TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS orion_ods.client_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.client (
    client_code            TEXT PRIMARY KEY DEFAULT orion_ods.next_code('CL', 'orion_ods.client_seq'),
    client_name            TEXT NOT NULL,
    client_status          TEXT CHECK (client_status IN ('Active', 'Inactive')),
    client_start_date      DATE,
    client_end_date        DATE,
    client_location_state  TEXT,
    client_location_city   TEXT,
    client_type            TEXT,
    firm_priority          TEXT,
    client_onboarded       DATE,
    billing_name           TEXT,
    gstin                  TEXT,
    billing_address        TEXT,
    client_group_code      TEXT REFERENCES orion_ods.client(client_code),
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orion_ods.app_user (
    id                 SERIAL PRIMARY KEY,
    username           TEXT NOT NULL UNIQUE,
    display_name       TEXT NOT NULL,
    password_hash      TEXT NOT NULL,
    role               TEXT NOT NULL DEFAULT 'admin',
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    ods_access         BOOLEAN NOT NULL DEFAULT FALSE,
    ods_write          BOOLEAN NOT NULL DEFAULT FALSE,
    dw_access          BOOLEAN NOT NULL DEFAULT FALSE,
    dw_write           BOOLEAN NOT NULL DEFAULT FALSE,
    tally_access       BOOLEAN NOT NULL DEFAULT FALSE,
    tally_write        BOOLEAN NOT NULL DEFAULT FALSE,
    tally_dw_access    BOOLEAN NOT NULL DEFAULT FALSE,
    tally_dw_write     BOOLEAN NOT NULL DEFAULT FALSE,
    orion_dashboard_access BOOLEAN NOT NULL DEFAULT TRUE,
    tally_dashboard_access BOOLEAN NOT NULL DEFAULT FALSE,
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    preferred_theme    TEXT CHECK (preferred_theme IN ('light', 'dark')),
    appearance         TEXT,
    avatar_ext         TEXT,
    avatar_version     INTEGER NOT NULL DEFAULT 0,
    email              TEXT,
    phone              TEXT,
    password_reset_token   TEXT,
    password_reset_expires TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS orion_ods.signup_request (
    id                 SERIAL PRIMARY KEY,
    username           TEXT NOT NULL,
    display_name       TEXT NOT NULL,
    password_hash      TEXT NOT NULL,
    email              TEXT NOT NULL,
    phone              TEXT,
    status             TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_timestamp TIMESTAMPTZ,
    reviewed_by        INTEGER REFERENCES orion_ods.app_user(id) ON DELETE SET NULL,
    created_user_id    INTEGER REFERENCES orion_ods.app_user(id) ON DELETE SET NULL,
    rejection_reason   TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS signup_request_pending_username_idx
    ON orion_ods.signup_request (LOWER(username))
    WHERE status = 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS signup_request_pending_email_idx
    ON orion_ods.signup_request (LOWER(email))
    WHERE status = 'pending';

CREATE SEQUENCE IF NOT EXISTS orion_ods.case_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.case (
    case_code                TEXT PRIMARY KEY DEFAULT orion_ods.next_code('CS', 'orion_ods.case_seq'),
    case_name                TEXT NOT NULL,
    client_code              TEXT REFERENCES orion_ods.client(client_code),
    case_start_date          DATE,
    case_status              TEXT CHECK (case_status IN ('Active', 'Inactive')),
    case_end_date            DATE,
    capability_code          TEXT REFERENCES orion_ods.capability(capability_code),
    monthly_expected_revenue NUMERIC,
    monthly_allowed_km       INTEGER,
    business_domain_code     TEXT REFERENCES orion_ods.business_domain(business_domain_code),
    case_onboarded           BOOLEAN DEFAULT FALSE,
    created_timestamp        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS orion_ods.employee_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.employee (
    employee_code        TEXT PRIMARY KEY DEFAULT orion_ods.next_code('EMP', 'orion_ods.employee_seq'),
    employee_name        TEXT NOT NULL,
    employee_status      TEXT CHECK (employee_status IN ('Active', 'Inactive')),
    emp_start_date       DATE,
    emp_end_date         DATE,
    employee_type        TEXT,
    client_facing        BOOLEAN DEFAULT FALSE,
    employee_designation TEXT,
    manager_code         TEXT REFERENCES orion_ods.employee(employee_code),
    employee_case_code   TEXT REFERENCES orion_ods.case(case_code),
    created_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS orion_ods.car_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.car (
    car_code               TEXT PRIMARY KEY DEFAULT orion_ods.next_code('CAR', 'orion_ods.car_seq'),
    car_number             TEXT NOT NULL,
    car_model              TEXT NOT NULL,
    case_code              TEXT REFERENCES orion_ods.case(case_code),
    per_km_price           NUMERIC,
    car_driven_by          TEXT REFERENCES orion_ods.employee(employee_code),
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS orion_ods.transaction_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.case_transaction (
    transaction_code         TEXT PRIMARY KEY DEFAULT orion_ods.next_code('TRA', 'orion_ods.transaction_seq'),
    case_code                TEXT REFERENCES orion_ods.case(case_code),
    transaction_date         DATE,
    transaction_amount       NUMERIC,
    transaction_status       TEXT CHECK (transaction_status IN ('Committed', 'Prospective', 'Cancelled')),
    tax                      NUMERIC,
    gst                      NUMERIC,
    amount_after_tax_gst     NUMERIC,
    transaction_description  TEXT,
    created_timestamp        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS orion_ods.expense_transaction_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.expense_transaction (
    expense_code             TEXT PRIMARY KEY DEFAULT orion_ods.next_code('EXT', 'orion_ods.expense_transaction_seq'),
    case_code                TEXT REFERENCES orion_ods.case(case_code),
    transaction_date         DATE,
    transaction_amount       NUMERIC,
    tax                      NUMERIC,
    gst                      NUMERIC,
    amount_after_tax_gst     NUMERIC,
    transaction_status       TEXT CHECK (transaction_status IN ('Committed', 'Prospective', 'Cancelled')),
    expense_type_code        TEXT REFERENCES orion_ods.expense_type(expense_type_code),
    is_regular_expense       TEXT CHECK (is_regular_expense IN ('Yes', 'No')),
    transaction_description  TEXT,
    created_timestamp        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS orion_ods.car_transaction_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.car_transaction (
    car_transaction_code     TEXT PRIMARY KEY DEFAULT orion_ods.next_code('CTR', 'orion_ods.car_transaction_seq'),
    car_code                 TEXT REFERENCES orion_ods.car(car_code),
    driving_date             DATE,
    initial_reading          NUMERIC,
    final_reading            NUMERIC,
    driven_km                NUMERIC,
    created_timestamp        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS orion_ods.opportunity_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.opportunity (
    opportunity_code         TEXT PRIMARY KEY DEFAULT orion_ods.next_code('OPP', 'orion_ods.opportunity_seq'),
    opportunity_name         TEXT NOT NULL,
    tender_id                TEXT,
    opportunity_case_code    TEXT REFERENCES orion_ods.case(case_code),
    opportunity_start_date   DATE,
    opportunity_end_date     DATE,
    opportunity_status       TEXT CHECK (opportunity_status IN (
        'Proposal', 'Financial Bid', 'Technical Bid',
        'Closed Won', 'Closed Lost', 'Disqualified', 'Qualified'
    )),
    required_quantity        NUMERIC,
    last_sub_stage_change_date DATE,
    state                    TEXT,
    city                     TEXT,
    reason                   TEXT,
    workers                  NUMERIC,
    opportunity_type         TEXT,
    created_timestamp        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE orion_ods.opportunity
    ADD COLUMN IF NOT EXISTS tender_id TEXT,
    ADD COLUMN IF NOT EXISTS required_quantity NUMERIC,
    ADD COLUMN IF NOT EXISTS last_sub_stage_change_date DATE,
    ADD COLUMN IF NOT EXISTS state TEXT,
    ADD COLUMN IF NOT EXISTS city TEXT,
    ADD COLUMN IF NOT EXISTS reason TEXT,
    ADD COLUMN IF NOT EXISTS workers NUMERIC,
    ADD COLUMN IF NOT EXISTS opportunity_type TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_opportunity_tender_id
    ON orion_ods.opportunity (lower(btrim(tender_id)))
    WHERE tender_id IS NOT NULL AND btrim(tender_id) <> '';

CREATE OR REPLACE FUNCTION orion_ods.opportunity_touch_sub_stage_date()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.opportunity_status IS NOT NULL AND NEW.last_sub_stage_change_date IS NULL THEN
            NEW.last_sub_stage_change_date := CURRENT_DATE;
        END IF;
    ELSIF TG_OP = 'UPDATE' THEN
        IF NEW.opportunity_status IS DISTINCT FROM OLD.opportunity_status THEN
            NEW.last_sub_stage_change_date := CURRENT_DATE;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_opportunity_sub_stage_date ON orion_ods.opportunity;
CREATE TRIGGER trg_opportunity_sub_stage_date
    BEFORE INSERT OR UPDATE OF opportunity_status
    ON orion_ods.opportunity
    FOR EACH ROW
    EXECUTE PROCEDURE orion_ods.opportunity_touch_sub_stage_date();

ALTER TABLE orion_ods.case
    ADD COLUMN IF NOT EXISTS opportunity_code TEXT REFERENCES orion_ods.opportunity(opportunity_code);

CREATE SEQUENCE IF NOT EXISTS orion_ods.employee_transaction_seq START 1;

CREATE TABLE IF NOT EXISTS orion_ods.employee_transaction (
    employee_transaction_code TEXT PRIMARY KEY DEFAULT orion_ods.next_code('ETR', 'orion_ods.employee_transaction_seq'),
    employee_code             TEXT REFERENCES orion_ods.employee(employee_code),
    transaction_date          DATE,
    month_year                TEXT,
    days_worked               NUMERIC,
    salary_amount             NUMERIC,
    salary_paid               TEXT CHECK (salary_paid IN ('Yes', 'No')),
    created_timestamp         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- orion_ods.bill and its companion tables are created by migrate_bill.sql, and
-- case_transaction.bill_code by migrate_case_transaction_bill.sql. Both run after this file.

-- Dashboard aggregates group the fact tables by case and by date, and join up to
-- client, capability, and business domain through the case.
CREATE INDEX IF NOT EXISTS ix_case_client                ON orion_ods.case (client_code);
CREATE INDEX IF NOT EXISTS ix_case_capability            ON orion_ods.case (capability_code);
CREATE INDEX IF NOT EXISTS ix_case_business_domain       ON orion_ods.case (business_domain_code);
CREATE INDEX IF NOT EXISTS ix_case_opportunity           ON orion_ods.case (opportunity_code);
CREATE INDEX IF NOT EXISTS ix_opportunity_tender_id      ON orion_ods.opportunity (tender_id);
CREATE INDEX IF NOT EXISTS ix_employee_case              ON orion_ods.employee (employee_case_code);
CREATE INDEX IF NOT EXISTS ix_employee_manager           ON orion_ods.employee (manager_code);
CREATE INDEX IF NOT EXISTS ix_car_case                   ON orion_ods.car (case_code);
CREATE INDEX IF NOT EXISTS ix_opportunity_case           ON orion_ods.opportunity (opportunity_case_code);
CREATE INDEX IF NOT EXISTS ix_case_transaction_case      ON orion_ods.case_transaction (case_code);
CREATE INDEX IF NOT EXISTS ix_case_transaction_date      ON orion_ods.case_transaction (transaction_date);
CREATE INDEX IF NOT EXISTS ix_expense_transaction_case   ON orion_ods.expense_transaction (case_code);
CREATE INDEX IF NOT EXISTS ix_expense_transaction_date   ON orion_ods.expense_transaction (transaction_date);
CREATE INDEX IF NOT EXISTS ix_expense_transaction_type   ON orion_ods.expense_transaction (expense_type_code);
CREATE INDEX IF NOT EXISTS ix_car_transaction_car        ON orion_ods.car_transaction (car_code);
CREATE INDEX IF NOT EXISTS ix_car_transaction_date       ON orion_ods.car_transaction (driving_date);
CREATE INDEX IF NOT EXISTS ix_employee_transaction_emp   ON orion_ods.employee_transaction (employee_code);
CREATE INDEX IF NOT EXISTS ix_employee_transaction_month ON orion_ods.employee_transaction (month_year);

-- Re-point code defaults at next_code() for databases created before it existed.
ALTER TABLE orion_ods.business_domain    ALTER COLUMN business_domain_code      SET DEFAULT orion_ods.next_code('BD',  'orion_ods.business_domain_seq');
ALTER TABLE orion_ods.capability         ALTER COLUMN capability_code           SET DEFAULT orion_ods.next_code('CAP', 'orion_ods.capability_seq');
ALTER TABLE orion_ods.expense_type       ALTER COLUMN expense_type_code         SET DEFAULT orion_ods.next_code('EXP', 'orion_ods.expense_type_seq');
ALTER TABLE orion_ods.client             ALTER COLUMN client_code               SET DEFAULT orion_ods.next_code('CL',  'orion_ods.client_seq');
ALTER TABLE orion_ods.case               ALTER COLUMN case_code                 SET DEFAULT orion_ods.next_code('CS',  'orion_ods.case_seq');
ALTER TABLE orion_ods.employee           ALTER COLUMN employee_code             SET DEFAULT orion_ods.next_code('EMP', 'orion_ods.employee_seq');
ALTER TABLE orion_ods.car                ALTER COLUMN car_code                  SET DEFAULT orion_ods.next_code('CAR', 'orion_ods.car_seq');
ALTER TABLE orion_ods.case_transaction   ALTER COLUMN transaction_code          SET DEFAULT orion_ods.next_code('TRA', 'orion_ods.transaction_seq');
ALTER TABLE orion_ods.expense_transaction ALTER COLUMN expense_code             SET DEFAULT orion_ods.next_code('EXT', 'orion_ods.expense_transaction_seq');
ALTER TABLE orion_ods.car_transaction    ALTER COLUMN car_transaction_code      SET DEFAULT orion_ods.next_code('CTR', 'orion_ods.car_transaction_seq');
ALTER TABLE orion_ods.opportunity        ALTER COLUMN opportunity_code          SET DEFAULT orion_ods.next_code('OPP', 'orion_ods.opportunity_seq');
ALTER TABLE orion_ods.employee_transaction ALTER COLUMN employee_transaction_code SET DEFAULT orion_ods.next_code('ETR', 'orion_ods.employee_transaction_seq');

CREATE TABLE IF NOT EXISTS orion_ods.direct_chat (
    id SERIAL PRIMARY KEY,
    user_low INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    user_high INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    created_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (user_low < user_high),
    UNIQUE (user_low, user_high)
);

CREATE TABLE IF NOT EXISTS orion_ods.chat_message (
    id SERIAL PRIMARY KEY,
    chat_id INTEGER NOT NULL REFERENCES orion_ods.direct_chat(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS chat_message_chat_id_id_idx ON orion_ods.chat_message (chat_id, id);

CREATE TABLE IF NOT EXISTS orion_ods.chat_read (
    chat_id INTEGER NOT NULL REFERENCES orion_ods.direct_chat(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    last_read_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS orion_ods.chat_attachment (
    message_id INTEGER PRIMARY KEY REFERENCES orion_ods.chat_message(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    ext TEXT NOT NULL,
    original_name TEXT NOT NULL,
    content_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL DEFAULT 0
);

GRANT SELECT, INSERT, UPDATE, DELETE ON orion_ods.direct_chat, orion_ods.chat_message, orion_ods.chat_read, orion_ods.chat_attachment TO orion_user;
GRANT USAGE, SELECT ON SEQUENCE orion_ods.direct_chat_id_seq, orion_ods.chat_message_id_seq TO orion_user;
