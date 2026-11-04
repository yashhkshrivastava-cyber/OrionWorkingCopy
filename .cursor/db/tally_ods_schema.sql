-- Tally Prime working copy (SCD Type 1).
-- Surrogate keys stay stable across loads. Natural keys come from Tally GUID / REMOTEID / name.
-- Idempotent: safe to run repeatedly.

CREATE SCHEMA IF NOT EXISTS tally_ods;

CREATE TABLE IF NOT EXISTS tally_ods.company (
    company_sk             BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    starting_from          DATE,
    books_from             DATE,
    state_name             TEXT,
    country_name           TEXT,
    gst_on                 BOOLEAN,
    gst_tax_unit_count     INTEGER,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.account_group (
    account_group_sk       BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    tally_alter_id         TEXT,
    name                   TEXT NOT NULL,
    parent_name            TEXT,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.ledger (
    ledger_sk              BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    tally_alter_id         TEXT,
    name                   TEXT NOT NULL,
    parent_name            TEXT,
    mailing_name           TEXT,
    opening_balance        NUMERIC,
    closing_balance        NUMERIC,
    is_bill_wise           BOOLEAN,
    is_revenue             BOOLEAN,
    tax_type               TEXT,
    country_name           TEXT,
    pincode                TEXT,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.cost_category (
    cost_category_sk       BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    tally_alter_id         TEXT,
    name                   TEXT NOT NULL,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.cost_centre (
    cost_centre_sk         BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    tally_alter_id         TEXT,
    name                   TEXT NOT NULL,
    parent_name            TEXT,
    category_name          TEXT,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.voucher_type (
    voucher_type_sk        BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    tally_alter_id         TEXT,
    name                   TEXT NOT NULL,
    parent_name            TEXT,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.currency (
    currency_sk            BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    name                   TEXT NOT NULL,
    original_name          TEXT,
    mailing_name           TEXT,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.unit (
    unit_sk                BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    name                   TEXT NOT NULL,
    original_name          TEXT,
    decimal_places         INTEGER,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.godown (
    godown_sk              BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    tally_alter_id         TEXT,
    name                   TEXT NOT NULL,
    parent_name            TEXT,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.stock_group (
    stock_group_sk         BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    tally_alter_id         TEXT,
    name                   TEXT NOT NULL,
    parent_name            TEXT,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.stock_category (
    stock_category_sk      BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    tally_alter_id         TEXT,
    name                   TEXT NOT NULL,
    parent_name            TEXT,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.stock_item (
    stock_item_sk          BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    tally_alter_id         TEXT,
    name                   TEXT NOT NULL,
    parent_name            TEXT,
    base_units             TEXT,
    closing_balance        NUMERIC,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.gst_classification (
    gst_classification_sk  BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    name                   TEXT NOT NULL,
    hsn_code               TEXT,
    gst_rate               NUMERIC,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.tax_unit (
    tax_unit_sk            BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    name                   TEXT NOT NULL,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.attendance_type (
    attendance_type_sk     BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    tally_master_id        TEXT,
    name                   TEXT NOT NULL,
    parent_name            TEXT,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.voucher (
    voucher_sk             BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    company_name           TEXT NOT NULL,
    tally_guid             TEXT,
    remote_id              TEXT,
    vch_key                TEXT,
    voucher_type_name      TEXT,
    voucher_number         TEXT,
    voucher_date           DATE,
    effective_date         DATE,
    party_ledger_name      TEXT,
    narration              TEXT,
    reference              TEXT,
    persisted_view         TEXT,
    is_invoice             BOOLEAN,
    is_optional            BOOLEAN,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.voucher_ledger_entry (
    voucher_ledger_entry_sk BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    voucher_sk             BIGINT REFERENCES tally_ods.voucher (voucher_sk) ON DELETE CASCADE,
    company_name           TEXT NOT NULL,
    line_no                INTEGER NOT NULL,
    ledger_name            TEXT,
    amount                 NUMERIC,
    is_deemed_positive     BOOLEAN,
    is_party_ledger        BOOLEAN,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.voucher_inventory_entry (
    voucher_inventory_entry_sk BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    voucher_sk             BIGINT REFERENCES tally_ods.voucher (voucher_sk) ON DELETE CASCADE,
    company_name           TEXT NOT NULL,
    line_no                INTEGER NOT NULL,
    stock_item_name        TEXT,
    godown_name            TEXT,
    actual_qty             TEXT,
    billed_qty             TEXT,
    rate                   NUMERIC,
    amount                 NUMERIC,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.voucher_bill_allocation (
    voucher_bill_allocation_sk BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    voucher_sk             BIGINT REFERENCES tally_ods.voucher (voucher_sk) ON DELETE CASCADE,
    voucher_ledger_entry_sk BIGINT REFERENCES tally_ods.voucher_ledger_entry (voucher_ledger_entry_sk) ON DELETE CASCADE,
    company_name           TEXT NOT NULL,
    line_no                INTEGER NOT NULL,
    bill_name              TEXT,
    bill_type              TEXT,
    amount                 NUMERIC,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tally_ods.voucher_cost_centre_allocation (
    voucher_cost_centre_allocation_sk BIGSERIAL PRIMARY KEY,
    natural_key            TEXT NOT NULL UNIQUE,
    voucher_sk             BIGINT REFERENCES tally_ods.voucher (voucher_sk) ON DELETE CASCADE,
    voucher_ledger_entry_sk BIGINT REFERENCES tally_ods.voucher_ledger_entry (voucher_ledger_entry_sk) ON DELETE CASCADE,
    company_name           TEXT NOT NULL,
    line_no                INTEGER NOT NULL,
    category_name          TEXT,
    cost_centre_name       TEXT,
    amount                 NUMERIC,
    source_hash            TEXT NOT NULL,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE tally_ods.godown ADD COLUMN IF NOT EXISTS tally_alter_id TEXT;
ALTER TABLE tally_ods.stock_group ADD COLUMN IF NOT EXISTS tally_alter_id TEXT;
ALTER TABLE tally_ods.stock_category ADD COLUMN IF NOT EXISTS tally_alter_id TEXT;
ALTER TABLE tally_ods.stock_item ADD COLUMN IF NOT EXISTS tally_alter_id TEXT;

-- Client details used when raising bills in the application (address, state, GSTIN).
ALTER TABLE tally_ods.ledger ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE tally_ods.ledger ADD COLUMN IF NOT EXISTS state_name TEXT;
ALTER TABLE tally_ods.ledger ADD COLUMN IF NOT EXISTS gstin TEXT;
ALTER TABLE tally_ods.ledger ADD COLUMN IF NOT EXISTS gst_registration_type TEXT;
