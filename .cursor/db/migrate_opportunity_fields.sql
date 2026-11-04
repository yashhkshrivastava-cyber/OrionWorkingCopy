-- Opportunity pipeline fields and extra statuses.
-- Idempotent: safe on existing databases.

ALTER TABLE orion_ods.opportunity
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

DO $$
DECLARE
    conname text;
BEGIN
    FOR conname IN
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'orion_ods'
          AND t.relname = 'opportunity'
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) ILIKE '%opportunity_status%'
    LOOP
        EXECUTE format('ALTER TABLE orion_ods.opportunity DROP CONSTRAINT %I', conname);
    END LOOP;
END $$;

ALTER TABLE orion_ods.opportunity
    ADD CONSTRAINT opportunity_opportunity_status_check
    CHECK (opportunity_status IN (
        'Proposal',
        'Financial Bid',
        'Technical Bid',
        'Closed Won',
        'Closed Lost',
        'Disqualified',
        'Qualified'
    ));

UPDATE orion_ods.opportunity
SET last_sub_stage_change_date = COALESCE(
    last_sub_stage_change_date,
    opportunity_start_date,
    created_timestamp::date
)
WHERE last_sub_stage_change_date IS NULL
  AND opportunity_status IS NOT NULL;

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

ALTER TABLE orion_dw.dim_opportunity
    ADD COLUMN IF NOT EXISTS required_quantity NUMERIC,
    ADD COLUMN IF NOT EXISTS last_sub_stage_change_date DATE,
    ADD COLUMN IF NOT EXISTS state TEXT,
    ADD COLUMN IF NOT EXISTS city TEXT,
    ADD COLUMN IF NOT EXISTS reason TEXT,
    ADD COLUMN IF NOT EXISTS workers NUMERIC,
    ADD COLUMN IF NOT EXISTS opportunity_type TEXT;
