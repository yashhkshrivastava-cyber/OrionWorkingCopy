-- Independent Orion / Tally dashboard flags (run once as postgres superuser).
-- Existing users keep the Orion dashboard they already use.
-- Tally dashboard is granted to people who already browse the Tally warehouse.
-- After that, grant each dashboard independently in Admin. Re-running is a no-op.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'orion_ods'
      AND table_name = 'app_user'
      AND column_name = 'orion_dashboard_access'
  ) THEN
    ALTER TABLE orion_ods.app_user
      ADD COLUMN orion_dashboard_access BOOLEAN NOT NULL DEFAULT TRUE;
    UPDATE orion_ods.app_user
      SET orion_dashboard_access = TRUE;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'orion_ods'
      AND table_name = 'app_user'
      AND column_name = 'tally_dashboard_access'
  ) THEN
    ALTER TABLE orion_ods.app_user
      ADD COLUMN tally_dashboard_access BOOLEAN NOT NULL DEFAULT FALSE;
    UPDATE orion_ods.app_user
      SET tally_dashboard_access = COALESCE(tally_dw_access, FALSE)
                                OR COALESCE(tally_dw_write, FALSE);
  END IF;
END $$;
