-- Orion DW: SCD Type 2 dimensions and facts.
-- Dimensions version when ODS attributes change.
-- Facts version when the source transaction changes.
-- Fact dimension keys are resolved as of the transaction date (point-in-time).

CREATE SCHEMA IF NOT EXISTS orion_dw;

CREATE TABLE IF NOT EXISTS orion_dw.dim_date (
    date_sk          INTEGER PRIMARY KEY,
    date_value       DATE NOT NULL UNIQUE,
    year_number      INTEGER NOT NULL,
    quarter_number   INTEGER NOT NULL,
    month_number     INTEGER NOT NULL,
    month_name       TEXT NOT NULL,
    week_of_year     INTEGER NOT NULL,
    day_of_month     INTEGER NOT NULL,
    day_of_week      INTEGER NOT NULL,
    day_name         TEXT NOT NULL,
    is_weekend       BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS orion_dw.dim_business_domain (
    business_domain_sk            BIGSERIAL PRIMARY KEY,
    business_domain_code          TEXT NOT NULL,
    business_domain_name          TEXT NOT NULL,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_business_domain_current
    ON orion_dw.dim_business_domain (business_domain_code)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS orion_dw.dim_capability (
    capability_sk                 BIGSERIAL PRIMARY KEY,
    capability_code               TEXT NOT NULL,
    capability_name               TEXT NOT NULL,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_capability_current
    ON orion_dw.dim_capability (capability_code)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS orion_dw.dim_expense_type (
    expense_type_sk               BIGSERIAL PRIMARY KEY,
    expense_type_code             TEXT NOT NULL,
    expense_type_name             TEXT NOT NULL,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_expense_type_current
    ON orion_dw.dim_expense_type (expense_type_code)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS orion_dw.dim_client (
    client_sk                     BIGSERIAL PRIMARY KEY,
    client_code                   TEXT NOT NULL,
    client_name                   TEXT NOT NULL,
    client_status                 TEXT,
    client_start_date             DATE,
    client_end_date               DATE,
    client_location_state         TEXT,
    client_location_city          TEXT,
    client_type                   TEXT,
    firm_priority                 TEXT,
    client_onboarded              DATE,
    client_group_code             TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_client_current
    ON orion_dw.dim_client (client_code)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS orion_dw.dim_case (
    case_sk                       BIGSERIAL PRIMARY KEY,
    case_code                     TEXT NOT NULL,
    case_name                     TEXT NOT NULL,
    client_code                   TEXT,
    capability_code               TEXT,
    business_domain_code          TEXT,
    opportunity_code              TEXT,
    case_start_date               DATE,
    case_end_date                 DATE,
    case_status                   TEXT,
    monthly_expected_revenue      NUMERIC,
    monthly_allowed_km            INTEGER,
    case_onboarded                BOOLEAN,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_case_current
    ON orion_dw.dim_case (case_code)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS orion_dw.dim_opportunity (
    opportunity_sk                BIGSERIAL PRIMARY KEY,
    opportunity_code              TEXT NOT NULL,
    opportunity_name              TEXT NOT NULL,
    tender_id                     TEXT,
    opportunity_case_code         TEXT,
    opportunity_start_date        DATE,
    opportunity_end_date          DATE,
    opportunity_status            TEXT,
    required_quantity             NUMERIC,
    last_sub_stage_change_date    DATE,
    state                         TEXT,
    city                          TEXT,
    reason                        TEXT,
    workers                       NUMERIC,
    opportunity_type              TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_opportunity_current
    ON orion_dw.dim_opportunity (opportunity_code)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS orion_dw.dim_employee (
    employee_sk                   BIGSERIAL PRIMARY KEY,
    employee_code                 TEXT NOT NULL,
    employee_name                 TEXT NOT NULL,
    employee_status               TEXT,
    emp_start_date                DATE,
    emp_end_date                  DATE,
    employee_type                 TEXT,
    client_facing                 BOOLEAN,
    employee_designation          TEXT,
    manager_code                  TEXT,
    employee_case_code            TEXT,
    monthly_salary                NUMERIC(12, 2),
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_employee_current
    ON orion_dw.dim_employee (employee_code)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS orion_dw.dim_car (
    car_sk                        BIGSERIAL PRIMARY KEY,
    car_code                      TEXT NOT NULL,
    car_number                    TEXT,
    car_model                     TEXT,
    case_code                     TEXT,
    per_km_price                  NUMERIC,
    car_driven_by                 TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_car_current
    ON orion_dw.dim_car (car_code)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS orion_dw.fact_case_transaction (
    case_transaction_sk           BIGSERIAL PRIMARY KEY,
    transaction_code              TEXT NOT NULL,
    date_sk                       INTEGER,
    case_sk                       BIGINT,
    client_sk                     BIGINT,
    capability_sk                 BIGINT,
    business_domain_sk            BIGINT,
    bill_sk                       BIGINT,
    case_code                     TEXT,
    bill_code                     TEXT,
    transaction_date              DATE,
    received_date                 DATE,
    transaction_status            TEXT,
    transaction_amount            NUMERIC,
    tax                           NUMERIC,
    gst                           NUMERIC,
    amount_after_tax_gst          NUMERIC,
    transaction_description       TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_case_transaction_current
    ON orion_dw.fact_case_transaction (transaction_code)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS orion_dw.fact_expense_transaction (
    expense_transaction_sk        BIGSERIAL PRIMARY KEY,
    expense_code                  TEXT NOT NULL,
    date_sk                       INTEGER,
    case_sk                       BIGINT,
    client_sk                     BIGINT,
    capability_sk                 BIGINT,
    business_domain_sk            BIGINT,
    expense_type_sk               BIGINT,
    case_code                     TEXT,
    expense_type_code             TEXT,
    transaction_date              DATE,
    transaction_status            TEXT,
    is_regular_expense            TEXT,
    transaction_amount            NUMERIC,
    tax                           NUMERIC,
    gst                           NUMERIC,
    amount_after_tax_gst          NUMERIC,
    transaction_description       TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_expense_transaction_current
    ON orion_dw.fact_expense_transaction (expense_code)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS orion_dw.fact_employee_transaction (
    employee_transaction_sk       BIGSERIAL PRIMARY KEY,
    employee_transaction_code     TEXT NOT NULL,
    date_sk                       INTEGER,
    employee_sk                   BIGINT,
    manager_sk                    BIGINT,
    case_sk                       BIGINT,
    client_sk                     BIGINT,
    capability_sk                 BIGINT,
    business_domain_sk            BIGINT,
    employee_code                 TEXT,
    transaction_date              DATE,
    month_year                    TEXT,
    days_worked                   NUMERIC,
    salary_amount                 NUMERIC,
    salary_paid                   TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_employee_transaction_current
    ON orion_dw.fact_employee_transaction (employee_transaction_code)
    WHERE is_current = TRUE;

-- The case the salary was worked at, when an attendance register says so (the case keys above follow it); empty means the employee's own case.
ALTER TABLE orion_dw.fact_employee_transaction ADD COLUMN IF NOT EXISTS case_code TEXT;

CREATE TABLE IF NOT EXISTS orion_dw.fact_car_transaction (
    car_transaction_sk            BIGSERIAL PRIMARY KEY,
    car_transaction_code          TEXT NOT NULL,
    date_sk                       INTEGER,
    car_sk                        BIGINT,
    driver_sk                     BIGINT,
    case_sk                       BIGINT,
    client_sk                     BIGINT,
    capability_sk                 BIGINT,
    business_domain_sk            BIGINT,
    car_code                      TEXT,
    driving_date                  DATE,
    initial_reading               NUMERIC,
    final_reading                 NUMERIC,
    driven_km                     NUMERIC,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_car_transaction_current
    ON orion_dw.fact_car_transaction (car_transaction_code)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS orion_dw.fact_bill (
    bill_sk                       BIGSERIAL PRIMARY KEY,
    bill_code                     TEXT NOT NULL,
    date_sk                       INTEGER,
    case_sk                       BIGINT,
    client_sk                     BIGINT,
    capability_sk                 BIGINT,
    business_domain_sk            BIGINT,
    case_code                     TEXT,
    client_code                   TEXT,
    bill_number                   TEXT,
    version_no                    INTEGER,
    bill_date                     DATE,
    service_month                 DATE,
    status                        TEXT,
    gst_paid                      BOOLEAN,
    gst_paid_amount               NUMERIC NOT NULL DEFAULT 0,   -- 0, not empty: a bill with nothing paid must not look "changed" to the load
    epf_amount                    NUMERIC NOT NULL DEFAULT 0,   -- EPFO charged on the bill, and what has been paid of it (the same: 0, never empty)
    esic_amount                   NUMERIC NOT NULL DEFAULT 0,
    epf_paid_amount               NUMERIC NOT NULL DEFAULT 0,
    esic_paid_amount              NUMERIC NOT NULL DEFAULT 0,
    taxable_total                 NUMERIC,
    cgst_amount                   NUMERIC,
    sgst_amount                   NUMERIC,
    grand_total                   NUMERIC,
    effective_from               TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_bill_current
    ON orion_dw.fact_bill (bill_code)
    WHERE is_current = TRUE;

ALTER TABLE orion_dw.dim_opportunity ADD COLUMN IF NOT EXISTS tender_id TEXT;
ALTER TABLE orion_dw.dim_opportunity ADD COLUMN IF NOT EXISTS required_quantity NUMERIC;
ALTER TABLE orion_dw.dim_opportunity ADD COLUMN IF NOT EXISTS last_sub_stage_change_date DATE;
ALTER TABLE orion_dw.dim_opportunity ADD COLUMN IF NOT EXISTS state TEXT;
ALTER TABLE orion_dw.dim_opportunity ADD COLUMN IF NOT EXISTS city TEXT;
ALTER TABLE orion_dw.dim_opportunity ADD COLUMN IF NOT EXISTS reason TEXT;
ALTER TABLE orion_dw.dim_opportunity ADD COLUMN IF NOT EXISTS workers NUMERIC;
ALTER TABLE orion_dw.dim_opportunity ADD COLUMN IF NOT EXISTS opportunity_type TEXT;
ALTER TABLE orion_dw.dim_case ADD COLUMN IF NOT EXISTS opportunity_code TEXT;
ALTER TABLE orion_dw.fact_case_transaction ADD COLUMN IF NOT EXISTS bill_sk BIGINT;
ALTER TABLE orion_dw.fact_case_transaction ADD COLUMN IF NOT EXISTS bill_code TEXT;
ALTER TABLE orion_dw.fact_case_transaction ADD COLUMN IF NOT EXISTS received_date DATE;

-- Bills are tax invoices tagged to a case. A warehouse created before that still has the
-- first-shape columns (bill_type, bill_amount, tax, gst, amount_after_tax_gst); they are
-- no longer filled, and it gains the columns below.
ALTER TABLE orion_dw.fact_bill
    ADD COLUMN IF NOT EXISTS case_sk BIGINT,
    ADD COLUMN IF NOT EXISTS capability_sk BIGINT,
    ADD COLUMN IF NOT EXISTS business_domain_sk BIGINT,
    ADD COLUMN IF NOT EXISTS case_code TEXT,
    ADD COLUMN IF NOT EXISTS bill_number TEXT,
    ADD COLUMN IF NOT EXISTS version_no INTEGER,
    ADD COLUMN IF NOT EXISTS service_month DATE,
    ADD COLUMN IF NOT EXISTS status TEXT,
    ADD COLUMN IF NOT EXISTS gst_paid BOOLEAN,
    ADD COLUMN IF NOT EXISTS gst_paid_amount NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS epf_amount NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS esic_amount NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS epf_paid_amount NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS esic_paid_amount NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS taxable_total NUMERIC,
    ADD COLUMN IF NOT EXISTS cgst_amount NUMERIC,
    ADD COLUMN IF NOT EXISTS sgst_amount NUMERIC,
    ADD COLUMN IF NOT EXISTS grand_total NUMERIC;

-- The EPFO and ESIC a bill charged are known to the source already; give the version the warehouse holds for each bill what the source says, once, so the
-- next load does not see every bill as changed and write another version of it. (The source table may not exist yet on a new database: the bills come later.)
DO $$
BEGIN
    IF to_regclass('orion_ods.bill') IS NOT NULL THEN
        UPDATE orion_dw.fact_bill f
           SET epf_amount = b.epf_amount, esic_amount = b.esic_amount
          FROM orion_ods.bill b
         WHERE f.bill_code = b.bill_code AND f.version_no = b.version_no AND f.is_current
           AND f.epf_amount = 0 AND f.esic_amount = 0 AND (b.epf_amount <> 0 OR b.esic_amount <> 0);
    END IF;
END $$;

-- Who made each version. Copied from orion_ods.<table>.created_by / last_updated_by (for bills,
-- created_by / version_by) when a version is written; expired_by comes from
-- orion_ods.record_deleted when a record that was deleted from the ODS is marked expired.
-- These are not part of what makes a version "changed".
ALTER TABLE orion_dw.dim_business_domain      ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;
ALTER TABLE orion_dw.dim_capability           ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;
ALTER TABLE orion_dw.dim_expense_type         ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;
ALTER TABLE orion_dw.dim_client               ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;
ALTER TABLE orion_dw.dim_case                 ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;
ALTER TABLE orion_dw.dim_opportunity          ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;
ALTER TABLE orion_dw.dim_employee             ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;
ALTER TABLE orion_dw.dim_car                  ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;
ALTER TABLE orion_dw.fact_case_transaction    ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;
ALTER TABLE orion_dw.fact_expense_transaction ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;
-- The day an expense is to be paid by (the payments themselves are Orion's, in orion_ods.expense_payment, and are not loaded).
ALTER TABLE orion_dw.fact_expense_transaction ADD COLUMN IF NOT EXISTS due_date DATE;
ALTER TABLE orion_dw.fact_expense_transaction ADD COLUMN IF NOT EXISTS vendor_gstin TEXT;
ALTER TABLE orion_dw.fact_expense_transaction ADD COLUMN IF NOT EXISTS vendor_invoice_no TEXT;
-- What credit notes have taken off a bill (the bill's own figures never change): the dashboards' revenue, billed, GST and open amounts subtract them.
-- What the client held back on a payment (TDS and the like): the entry's amount is the cash plus this.
ALTER TABLE orion_dw.fact_case_transaction ADD COLUMN IF NOT EXISTS deducted_amount NUMERIC;
ALTER TABLE orion_dw.fact_bill ADD COLUMN IF NOT EXISTS credited_taxable NUMERIC;
ALTER TABLE orion_dw.fact_bill ADD COLUMN IF NOT EXISTS credited_cgst NUMERIC;
ALTER TABLE orion_dw.fact_bill ADD COLUMN IF NOT EXISTS credited_sgst NUMERIC;
ALTER TABLE orion_dw.fact_bill ADD COLUMN IF NOT EXISTS credited_amount NUMERIC;
ALTER TABLE orion_dw.fact_employee_transaction ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;
ALTER TABLE orion_dw.fact_car_transaction     ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;
ALTER TABLE orion_dw.fact_bill                ADD COLUMN IF NOT EXISTS source_created_by INTEGER, ADD COLUMN IF NOT EXISTS source_last_updated_by INTEGER, ADD COLUMN IF NOT EXISTS expired_by INTEGER;

-- What is printed for a client on a bill was not versioned before. The first time these columns
-- are added, the current versions are filled in place from the ODS, so the load does not report
-- every client's existing billing details as a change made on the day of the release.
DO $$
BEGIN
    IF to_regclass('orion_dw.dim_client') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'orion_dw' AND table_name = 'dim_client' AND column_name = 'gstin'
       ) THEN
        ALTER TABLE orion_dw.dim_client
            ADD COLUMN billing_name TEXT,
            ADD COLUMN gstin TEXT,
            ADD COLUMN billing_address TEXT;
        -- On a database being created from nothing the ODS columns arrive later (migrate_bill.sql),
        -- and there is nothing to copy yet.
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'orion_ods' AND table_name = 'client' AND column_name = 'gstin'
        ) THEN
            UPDATE orion_dw.dim_client d
               SET billing_name = c.billing_name, gstin = c.gstin, billing_address = c.billing_address
              FROM orion_ods.client c
             WHERE c.client_code = d.client_code AND d.is_current;
        END IF;
    END IF;
END $$;

-- A capability's head is an employee. The dimension keeps the employee's code, as dim_employee
-- keeps manager_code and dim_case keeps client_code: dimensions refer to each other by code, and
-- only facts hold surrogate keys, chosen for the transaction date. The old text column
-- capability_head was dropped (see below). The first time the new column is added
-- the current versions are filled in place from the ODS, so the load does not report every head
-- as a change made on the day of the release.
DO $$
BEGIN
    IF to_regclass('orion_dw.dim_capability') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'orion_dw' AND table_name = 'dim_capability' AND column_name = 'capability_head_code'
       ) THEN
        ALTER TABLE orion_dw.dim_capability ADD COLUMN capability_head_code TEXT;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'orion_ods' AND table_name = 'capability' AND column_name = 'capability_head_code'
        ) THEN
            UPDATE orion_dw.dim_capability d
               SET capability_head_code = c.capability_head_code
              FROM orion_ods.capability c
             WHERE c.capability_code = d.capability_code AND d.is_current;
        END IF;
    END IF;
END $$;

ALTER TABLE orion_dw.dim_capability ADD COLUMN IF NOT EXISTS capability_head_code TEXT;

-- The old free-text head is gone from the warehouse too. Guarded, so a database that no longer has it takes no lock.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_dw' AND table_name = 'dim_capability' AND column_name = 'capability_head'
    ) THEN
        ALTER TABLE orion_dw.dim_capability DROP COLUMN capability_head;
    END IF;
END $$;

ALTER TABLE orion_dw.dim_client
    ADD COLUMN IF NOT EXISTS billing_name TEXT,
    ADD COLUMN IF NOT EXISTS gstin TEXT,
    ADD COLUMN IF NOT EXISTS billing_address TEXT;

-- The group a client belongs to is another client. The dimension keeps that client's code, as
-- dim_capability keeps its head's and dim_case its client's. The column is new in the working copy
-- too, so no client has a group yet and there is nothing to fill in: a group shows as a change on
-- the day it is chosen.
ALTER TABLE orion_dw.dim_client ADD COLUMN IF NOT EXISTS client_group_code TEXT;

-- The monthly salary decided for an employee. It is the one private detail of an employee that is loaded (Aadhaar and PAN
-- never are), so a change of salary is kept as a version like any other change. Nothing shows it except people who can
-- change employees: the dimension's preview does not list it, and record history hides it from everyone else.
ALTER TABLE orion_dw.dim_employee ADD COLUMN IF NOT EXISTS monthly_salary NUMERIC(12, 2);

-- One row per warehouse load, whether started by a person or by the automatic loader. The last
-- successful full load is what the dashboards show as "warehouse last loaded". source_fingerprint
-- is what the working copy looked like when that load started; the automatic loader skips a load
-- when it is unchanged.
-- No longer written: ETL runs are recorded in orion_ods.etl_run (migrate_etl.sql). Kept so a rollback still has the
-- table; drop it in a later release.
CREATE TABLE IF NOT EXISTS orion_dw.load_run (
    id                 SERIAL PRIMARY KEY,
    scope              TEXT NOT NULL,
    trigger            TEXT NOT NULL CHECK (trigger IN ('manual', 'auto')),
    started_by         INTEGER,
    started_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_timestamp TIMESTAMPTZ,
    status             TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    stats              JSONB,
    error              TEXT,
    source_fingerprint TEXT
);
CREATE INDEX IF NOT EXISTS ix_load_run_finished ON orion_dw.load_run (scope, status, finished_timestamp DESC);

-- Contacts: who we know at a client, as of each change. How to reach them (e-mail, phone, address) and the notes are not loaded: the warehouse carries who they
-- are, their role and whether they are current, which is what the dashboards count.
CREATE TABLE IF NOT EXISTS orion_dw.dim_contact (
    contact_sk                    BIGSERIAL PRIMARY KEY,
    contact_code                  TEXT NOT NULL,
    client_code                   TEXT,
    case_code                     TEXT,
    contact_name                  TEXT,
    designation                   TEXT,
    department                    TEXT,
    contact_role                  TEXT,
    contact_status                TEXT,
    is_primary_contact            TEXT,
    contact_start_date            DATE,
    contact_end_date              DATE,
    preferred_contact_method      TEXT,
    location_state                TEXT,
    location_city                 TEXT,
    relationship_owner_code       TEXT,
    last_contacted_date           DATE,
    next_follow_up_date           DATE,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    source_created_by             INTEGER,
    source_last_updated_by        INTEGER,
    expired_by                    INTEGER,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_contact_current
    ON orion_dw.dim_contact (contact_code)
    WHERE is_current = TRUE;

-- EMDs: the earnest money deposited for a case, and how it comes back, as of each change.
CREATE TABLE IF NOT EXISTS orion_dw.fact_emd (
    emd_sk                        BIGSERIAL PRIMARY KEY,
    emd_code                      TEXT NOT NULL,
    date_sk                       INTEGER,
    case_sk                       BIGINT,
    client_sk                     BIGINT,
    capability_sk                 BIGINT,
    business_domain_sk            BIGINT,
    case_code                     TEXT,
    opportunity_code              TEXT,
    tender_reference              TEXT,
    beneficiary                   TEXT,
    payment_mode                  TEXT,
    instrument_number             TEXT,
    instrument_date               DATE,
    deposit_date                  DATE,
    valid_until                   DATE,
    emd_status                    TEXT,
    refund_due_date               DATE,
    refund_requested_date         DATE,
    refund_received_date          DATE,
    emd_amount                    NUMERIC,
    refund_amount                 NUMERIC,
    deduction_amount              NUMERIC,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    source_created_by             INTEGER,
    source_last_updated_by        INTEGER,
    expired_by                    INTEGER,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_emd_current
    ON orion_dw.fact_emd (emd_code)
    WHERE is_current = TRUE;

-- The cost the dashboards read. It is the expenses, plus two things recorded on a bill that are real money paid out or lost, and are not typed in as an expense:
--   * EPFO and ESIC PAID over to the authorities (migrate_bill_statutory.sql): charged to the client they are revenue, paid to the authority they are a cost, on the day
--     they were paid, against the bill's case and client. This is independent of salary: it does not depend on payroll or attendance being entered at all;
--   * what a client held back from a payment that is not TDS (migrate_deductions.sql): a penalty, a short payment ('Other') or rounding. The bill was for more and
--     the money will never come, so it is a cost on the day of the payment. TDS is not: it is tax already paid on the company's behalf and is claimed back.
-- A payment or deduction that has been reversed is not here. Every expense and margin figure reads this view, never the fact table, so none can leave them out.
-- These rows have no expense type of their own (expense_type_code is STATUTORY or SHORTFALL) and are never regular expenses entered by hand; they cannot be opened
-- as an expense (the bank already has the money, or never had it, from the payment itself, so nothing is entered twice). Rebuilt on every start; it holds no data.
DO $do$
BEGIN
    IF to_regclass('orion_ods.bill_statutory_payment') IS NOT NULL AND to_regclass('orion_ods.bill_payment_deduction') IS NOT NULL THEN
        DROP VIEW IF EXISTS orion_dw.expense_cost;
        EXECUTE $v$
        CREATE VIEW orion_dw.expense_cost AS
        SELECT e.expense_transaction_sk, e.expense_code, e.date_sk, e.case_sk, e.client_sk, e.capability_sk, e.business_domain_sk, e.expense_type_sk,
               e.case_code, e.expense_type_code, e.transaction_date, e.due_date, e.vendor_gstin, e.vendor_invoice_no, e.transaction_status,
               e.is_regular_expense, e.transaction_amount, e.tax, e.gst, e.amount_after_tax_gst, e.transaction_description, e.is_current, e.is_expired
          FROM orion_dw.fact_expense_transaction e
        UNION ALL
        SELECT -p.statutory_payment_sk, 'STAT-' || p.statutory_payment_sk::text, to_char(p.paid_date, 'YYYYMMDD')::integer,
               b.case_sk, b.client_sk, b.capability_sk, b.business_domain_sk, NULL::bigint,
               b.case_code, 'STATUTORY', p.paid_date, NULL::date, NULL::text, NULL::text, 'Committed',
               'No', p.amount, 0::numeric, 0::numeric, p.amount, p.component || ' paid on bill ' || COALESCE(b.bill_number, p.bill_code), TRUE, FALSE
          FROM orion_ods.bill_statutory_payment p
          JOIN orion_dw.fact_bill b ON b.bill_code = p.bill_code AND b.is_current AND NOT b.is_expired
         WHERE p.reversed_timestamp IS NULL
        UNION ALL
        SELECT -1000000000 - d.deduction_id, 'SHORT-' || d.deduction_id::text, to_char(d.received_date, 'YYYYMMDD')::integer,
               b.case_sk, b.client_sk, b.capability_sk, b.business_domain_sk, NULL::bigint,
               b.case_code, 'SHORTFALL', d.received_date, NULL::date, NULL::text, NULL::text, 'Committed',
               'No', d.amount, 0::numeric, 0::numeric, d.amount,
               d.kind || ' held back by the client on bill ' || COALESCE(b.bill_number, d.bill_code) || COALESCE(': ' || NULLIF(BTRIM(d.reason), ''), ''), TRUE, FALSE
          FROM orion_ods.bill_payment_deduction d
          JOIN orion_dw.fact_bill b ON b.bill_code = d.bill_code AND b.is_current AND NOT b.is_expired
         WHERE d.reversed_timestamp IS NULL AND d.kind <> 'TDS'
        $v$;
    END IF;
END
$do$;
