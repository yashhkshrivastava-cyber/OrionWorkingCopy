-- Dedicated Tally warehouse browse/refresh flags (run once as postgres superuser).
-- First-time add copies existing Tally ODS flags so current users keep warehouse.
-- After that, grant Tally DW independently in Admin. Re-running is a no-op.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'orion_ods'
      AND table_name = 'app_user'
      AND column_name = 'tally_dw_access'
  ) THEN
    ALTER TABLE orion_ods.app_user
      ADD COLUMN tally_dw_access BOOLEAN NOT NULL DEFAULT FALSE;
    UPDATE orion_ods.app_user
      SET tally_dw_access = COALESCE(tally_access, FALSE);
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'orion_ods'
      AND table_name = 'app_user'
      AND column_name = 'tally_dw_write'
  ) THEN
    ALTER TABLE orion_ods.app_user
      ADD COLUMN tally_dw_write BOOLEAN NOT NULL DEFAULT FALSE;
    UPDATE orion_ods.app_user
      SET tally_dw_write = COALESCE(tally_write, FALSE);
  END IF;
END $$;
