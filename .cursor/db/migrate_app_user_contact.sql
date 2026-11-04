-- Add contact fields for app users (run as postgres superuser on existing databases).
ALTER TABLE orion_ods.app_user ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE orion_ods.app_user ADD COLUMN IF NOT EXISTS phone TEXT;
