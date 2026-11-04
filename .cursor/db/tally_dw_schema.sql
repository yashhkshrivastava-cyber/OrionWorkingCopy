-- Tally DW: SCD Type 2 dimensions and facts loaded from tally_ods.
-- Dimensions version when Tally master attributes change.
-- Facts version when the source voucher or line changes.
-- Fact dimension keys are resolved as of voucher_date (point-in-time).
-- Idempotent: safe to run repeatedly.

CREATE SCHEMA IF NOT EXISTS tally_dw;

-- Shared SCD Type 2 columns on every versioned table:
--   effective_from / effective_to / is_current / is_expired
--   source_created_timestamp / source_last_updated_timestamp
--   dw_created_timestamp / dw_last_updated_timestamp
-- Natural key for versioning is source_sk (stable tally_ods surrogate), except
-- Date (calendar) and Client Month (company | client | month).

CREATE TABLE IF NOT EXISTS tally_dw.dim_date (
    date_sk            INTEGER PRIMARY KEY,
    date_value         DATE NOT NULL UNIQUE,
    year_number        INTEGER NOT NULL,
    quarter_number     INTEGER NOT NULL,
    month_number       INTEGER NOT NULL,
    month_name         TEXT NOT NULL,
    month_year         TEXT NOT NULL,
    fy_start_year      INTEGER NOT NULL,
    fy_end_year        INTEGER NOT NULL,
    fy_month_number    INTEGER NOT NULL,
    week_of_year       INTEGER NOT NULL,
    day_of_month       INTEGER NOT NULL,
    day_of_week        INTEGER NOT NULL,
    day_name           TEXT NOT NULL,
    is_weekend         BOOLEAN NOT NULL,
    is_month_end       BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS tally_dw.dim_company (
    company_dw_sk                 BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    starting_from                 DATE,
    books_from                    DATE,
    state_name                    TEXT,
    country_name                  TEXT,
    gst_on                        BOOLEAN,
    gst_tax_unit_count            INTEGER,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_company_current
    ON tally_dw.dim_company (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_account_group (
    account_group_dw_sk           BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    tally_alter_id                TEXT,
    name                          TEXT NOT NULL,
    parent_name                   TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_account_group_current
    ON tally_dw.dim_account_group (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_ledger (
    ledger_dw_sk                  BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    tally_alter_id                TEXT,
    name                          TEXT NOT NULL,
    parent_name                   TEXT,
    ledger_class                  TEXT,
    mailing_name                  TEXT,
    opening_balance               NUMERIC,
    closing_balance               NUMERIC,
    is_bill_wise                  BOOLEAN,
    is_revenue                    BOOLEAN,
    tax_type                      TEXT,
    country_name                  TEXT,
    pincode                       TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_ledger_current
    ON tally_dw.dim_ledger (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_cost_category (
    cost_category_dw_sk           BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    tally_alter_id                TEXT,
    name                          TEXT NOT NULL,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_cost_category_current
    ON tally_dw.dim_cost_category (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_cost_centre (
    cost_centre_dw_sk             BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    tally_alter_id                TEXT,
    name                          TEXT NOT NULL,
    parent_name                   TEXT,
    category_name                 TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_cost_centre_current
    ON tally_dw.dim_cost_centre (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_voucher_type (
    voucher_type_dw_sk            BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    tally_alter_id                TEXT,
    name                          TEXT NOT NULL,
    parent_name                   TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_voucher_type_current
    ON tally_dw.dim_voucher_type (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_currency (
    currency_dw_sk                BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    name                          TEXT NOT NULL,
    original_name                 TEXT,
    mailing_name                  TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_currency_current
    ON tally_dw.dim_currency (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_unit (
    unit_dw_sk                    BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    name                          TEXT NOT NULL,
    original_name                 TEXT,
    decimal_places                INTEGER,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_unit_current
    ON tally_dw.dim_unit (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_godown (
    godown_dw_sk                  BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    tally_alter_id                TEXT,
    name                          TEXT NOT NULL,
    parent_name                   TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_godown_current
    ON tally_dw.dim_godown (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_stock_group (
    stock_group_dw_sk             BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    tally_alter_id                TEXT,
    name                          TEXT NOT NULL,
    parent_name                   TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_stock_group_current
    ON tally_dw.dim_stock_group (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_stock_category (
    stock_category_dw_sk          BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    tally_alter_id                TEXT,
    name                          TEXT NOT NULL,
    parent_name                   TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_stock_category_current
    ON tally_dw.dim_stock_category (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_stock_item (
    stock_item_dw_sk              BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    tally_alter_id                TEXT,
    name                          TEXT NOT NULL,
    parent_name                   TEXT,
    base_units                    TEXT,
    closing_balance               NUMERIC,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_stock_item_current
    ON tally_dw.dim_stock_item (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_gst_classification (
    gst_classification_dw_sk      BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    name                          TEXT NOT NULL,
    hsn_code                      TEXT,
    gst_rate                      NUMERIC,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_gst_classification_current
    ON tally_dw.dim_gst_classification (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_tax_unit (
    tax_unit_dw_sk                BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    name                          TEXT NOT NULL,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_tax_unit_current
    ON tally_dw.dim_tax_unit (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.dim_attendance_type (
    attendance_type_dw_sk         BIGSERIAL PRIMARY KEY,
    source_sk                     BIGINT NOT NULL,
    natural_key                   TEXT,
    company_name                  TEXT NOT NULL,
    tally_guid                    TEXT,
    tally_master_id               TEXT,
    name                          TEXT NOT NULL,
    parent_name                   TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_attendance_type_current
    ON tally_dw.dim_attendance_type (source_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.fact_voucher (
    voucher_dw_sk                 BIGSERIAL PRIMARY KEY,
    source_voucher_sk             BIGINT NOT NULL,
    natural_key                   TEXT,
    date_sk                       INTEGER,
    company_sk                    BIGINT,
    voucher_type_sk               BIGINT,
    party_ledger_sk               BIGINT,
    company_name                  TEXT,
    voucher_type_name             TEXT,
    voucher_number                TEXT,
    voucher_date                  DATE,
    effective_date                DATE,
    party_ledger_name             TEXT,
    narration                     TEXT,
    reference                     TEXT,
    tally_guid                    TEXT,
    remote_id                     TEXT,
    is_invoice                    BOOLEAN,
    is_optional                   BOOLEAN,
    is_sales_document             BOOLEAN,
    ledger_line_count             INTEGER,
    invoice_value_incl_gst        NUMERIC,
    revenue_ex_gst                NUMERIC,
    gst                           NUMERIC,
    cgst                          NUMERIC,
    sgst                          NUMERIC,
    manpower_supply               NUMERIC,
    vehicle_rental                NUMERIC,
    service_charges               NUMERIC,
    epf_billed                    NUMERIC,
    esic_billed                   NUMERIC,
    other_income                  NUMERIC,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_voucher_current
    ON tally_dw.fact_voucher (source_voucher_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.fact_ledger_line (
    ledger_line_dw_sk             BIGSERIAL PRIMARY KEY,
    source_ledger_entry_sk        BIGINT NOT NULL,
    natural_key                   TEXT,
    source_voucher_sk             BIGINT,
    date_sk                       INTEGER,
    company_sk                    BIGINT,
    voucher_type_sk               BIGINT,
    party_ledger_sk               BIGINT,
    line_ledger_sk                BIGINT,
    account_group_sk              BIGINT,
    company_name                  TEXT,
    voucher_number                TEXT,
    voucher_date                  DATE,
    voucher_type_name             TEXT,
    party_ledger_name             TEXT,
    line_no                       INTEGER,
    ledger_name                   TEXT,
    ledger_group                  TEXT,
    ledger_class                  TEXT,
    line_role                     TEXT,
    amount                        NUMERIC,
    debit_amount                  NUMERIC,
    credit_amount                 NUMERIC,
    is_deemed_positive            BOOLEAN,
    is_party_ledger               BOOLEAN,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_ledger_line_current
    ON tally_dw.fact_ledger_line (source_ledger_entry_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.fact_inventory_line (
    inventory_line_dw_sk          BIGSERIAL PRIMARY KEY,
    source_inventory_entry_sk     BIGINT NOT NULL,
    natural_key                   TEXT,
    source_voucher_sk             BIGINT,
    date_sk                       INTEGER,
    company_sk                    BIGINT,
    voucher_type_sk               BIGINT,
    party_ledger_sk               BIGINT,
    stock_item_sk                 BIGINT,
    godown_sk                     BIGINT,
    company_name                  TEXT,
    voucher_number                TEXT,
    voucher_date                  DATE,
    party_ledger_name             TEXT,
    line_no                       INTEGER,
    stock_item_name               TEXT,
    godown_name                   TEXT,
    actual_qty                    TEXT,
    billed_qty                    TEXT,
    rate                          NUMERIC,
    amount                        NUMERIC,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_inventory_line_current
    ON tally_dw.fact_inventory_line (source_inventory_entry_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.fact_bill_allocation (
    bill_allocation_dw_sk         BIGSERIAL PRIMARY KEY,
    source_bill_allocation_sk     BIGINT NOT NULL,
    natural_key                   TEXT,
    source_voucher_sk             BIGINT,
    source_ledger_entry_sk        BIGINT,
    date_sk                       INTEGER,
    company_sk                    BIGINT,
    voucher_type_sk               BIGINT,
    party_ledger_sk               BIGINT,
    line_ledger_sk                BIGINT,
    company_name                  TEXT,
    voucher_number                TEXT,
    voucher_date                  DATE,
    party_ledger_name             TEXT,
    ledger_name                   TEXT,
    line_no                       INTEGER,
    bill_name                     TEXT,
    bill_type                     TEXT,
    amount                        NUMERIC,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_bill_allocation_current
    ON tally_dw.fact_bill_allocation (source_bill_allocation_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.fact_cost_centre_allocation (
    cost_centre_allocation_dw_sk  BIGSERIAL PRIMARY KEY,
    source_cost_centre_alloc_sk   BIGINT NOT NULL,
    natural_key                   TEXT,
    source_voucher_sk             BIGINT,
    source_ledger_entry_sk        BIGINT,
    date_sk                       INTEGER,
    company_sk                    BIGINT,
    voucher_type_sk               BIGINT,
    party_ledger_sk               BIGINT,
    line_ledger_sk                BIGINT,
    cost_centre_sk                BIGINT,
    cost_category_sk              BIGINT,
    company_name                  TEXT,
    voucher_number                TEXT,
    voucher_date                  DATE,
    party_ledger_name             TEXT,
    ledger_name                   TEXT,
    ledger_group                  TEXT,
    ledger_class                  TEXT,
    line_no                       INTEGER,
    category_name                 TEXT,
    cost_centre_name              TEXT,
    amount                        NUMERIC,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_cost_centre_allocation_current
    ON tally_dw.fact_cost_centre_allocation (source_cost_centre_alloc_sk) WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS tally_dw.fact_client_month (
    client_month_dw_sk            BIGSERIAL PRIMARY KEY,
    source_key                    TEXT NOT NULL,
    date_sk                       INTEGER,
    company_sk                    BIGINT,
    client_sk                     BIGINT,
    company_name                  TEXT,
    client_name                   TEXT,
    client_mailing_name           TEXT,
    client_pincode                TEXT,
    month_start                   DATE,
    month_year                    TEXT,
    fy_start_year                 INTEGER,
    invoice_count                 INTEGER,
    first_invoice_date            DATE,
    last_invoice_date             DATE,
    invoice_value_incl_gst        NUMERIC,
    revenue_ex_gst                NUMERIC,
    gst                           NUMERIC,
    cgst                          NUMERIC,
    sgst                          NUMERIC,
    manpower_supply               NUMERIC,
    vehicle_rental                NUMERIC,
    service_charges               NUMERIC,
    epf_billed                    NUMERIC,
    esic_billed                   NUMERIC,
    other_income                  NUMERIC,
    voucher_numbers               TEXT,
    cost_centres                  TEXT,
    effective_from                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to                  TIMESTAMPTZ,
    is_current                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_expired                    BOOLEAN NOT NULL DEFAULT FALSE,
    source_created_timestamp      TIMESTAMPTZ,
    source_last_updated_timestamp TIMESTAMPTZ,
    dw_created_timestamp          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dw_last_updated_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_client_month_current
    ON tally_dw.fact_client_month (source_key) WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS ix_dim_ledger_class
    ON tally_dw.dim_ledger (ledger_class) WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS ix_fact_voucher_date
    ON tally_dw.fact_voucher (voucher_date) WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS ix_fact_voucher_party
    ON tally_dw.fact_voucher (party_ledger_name) WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS ix_fact_ledger_line_voucher
    ON tally_dw.fact_ledger_line (source_voucher_sk) WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS ix_fact_client_month_month
    ON tally_dw.fact_client_month (month_start, client_name) WHERE is_current = TRUE;

CREATE OR REPLACE VIEW tally_dw.v_current_client AS
SELECT *
FROM tally_dw.dim_ledger
WHERE is_current = TRUE AND ledger_class = 'client';

CREATE OR REPLACE VIEW tally_dw.v_current_sales_voucher AS
SELECT *
FROM tally_dw.fact_voucher
WHERE is_current = TRUE AND COALESCE(is_sales_document, FALSE) = TRUE;
