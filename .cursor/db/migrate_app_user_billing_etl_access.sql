-- Billing and ETL are their own segments, each with a view flag and a change flag (re-runnable).
--
-- Billing used to follow operational data access, and loading the warehouses followed the write flags of the
-- warehouse and the two Tally copies. The first time each column pair is added, it is filled from what the
-- person could already do, so nobody loses access. After that, grant each segment in Admin.
-- (The API also adds these columns at start, with the same backfill; this file is for new databases.)

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_ods' AND table_name = 'app_user' AND column_name = 'billing_access'
    ) THEN
        ALTER TABLE orion_ods.app_user
            ADD COLUMN IF NOT EXISTS billing_access BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS billing_write  BOOLEAN NOT NULL DEFAULT FALSE;
        UPDATE orion_ods.app_user
           SET billing_access = COALESCE(ods_access, FALSE) OR COALESCE(ods_write, FALSE),
               billing_write  = COALESCE(ods_write, FALSE);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_ods' AND table_name = 'app_user' AND column_name = 'etl_access'
    ) THEN
        ALTER TABLE orion_ods.app_user
            ADD COLUMN IF NOT EXISTS etl_access BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS etl_write  BOOLEAN NOT NULL DEFAULT FALSE;
        UPDATE orion_ods.app_user
           SET etl_access = COALESCE(dw_access, FALSE) OR COALESCE(tally_access, FALSE)
                         OR COALESCE(tally_dw_access, FALSE) OR COALESCE(dw_write, FALSE)
                         OR COALESCE(tally_write, FALSE) OR COALESCE(tally_dw_write, FALSE),
               etl_write  = COALESCE(dw_write, FALSE) OR COALESCE(tally_write, FALSE)
                         OR COALESCE(tally_dw_write, FALSE);
    END IF;
END $$;
