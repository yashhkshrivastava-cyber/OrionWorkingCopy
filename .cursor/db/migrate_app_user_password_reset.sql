ALTER TABLE orion_ods.app_user ADD COLUMN IF NOT EXISTS password_reset_token TEXT;
ALTER TABLE orion_ods.app_user ADD COLUMN IF NOT EXISTS password_reset_expires TIMESTAMPTZ;
