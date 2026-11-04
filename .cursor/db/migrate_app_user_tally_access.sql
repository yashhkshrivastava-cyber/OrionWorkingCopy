-- Dedicated Tally Prime browse/load flags (run once as postgres superuser).
-- First-time add copies existing ODS/DW flags so current users keep Tally.
-- After that, grant Tally independently in Admin.

ALTER TABLE orion_ods.app_user
    ADD COLUMN IF NOT EXISTS tally_access BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE orion_ods.app_user
    ADD COLUMN IF NOT EXISTS tally_write BOOLEAN NOT NULL DEFAULT FALSE;
