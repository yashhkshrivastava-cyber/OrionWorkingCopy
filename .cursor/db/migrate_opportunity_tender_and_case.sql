-- Opportunity tender ID, and case.opportunity_code pointing at the source opportunity.
-- Idempotent: safe on existing databases.

ALTER TABLE orion_ods.opportunity
    ADD COLUMN IF NOT EXISTS tender_id TEXT;

CREATE INDEX IF NOT EXISTS ix_opportunity_tender_id
    ON orion_ods.opportunity (tender_id);

ALTER TABLE orion_ods.case
    ADD COLUMN IF NOT EXISTS opportunity_code TEXT REFERENCES orion_ods.opportunity(opportunity_code);

CREATE INDEX IF NOT EXISTS ix_case_opportunity
    ON orion_ods.case (opportunity_code);

ALTER TABLE orion_dw.dim_opportunity
    ADD COLUMN IF NOT EXISTS tender_id TEXT;

ALTER TABLE orion_dw.dim_case
    ADD COLUMN IF NOT EXISTS opportunity_code TEXT;
