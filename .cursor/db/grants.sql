-- Grant the app user access to ODS and DW.
-- Giving a table a new owner takes an exclusive lock on it, so the ownership step below touches only objects that are not
-- already owned by orion_user, and gives up after ten seconds rather than queue behind a load or autovacuum.
SET lock_timeout = '10s';
-- Run as a superuser if DW load fails with "permission denied for schema orion_dw":
--   psql -U postgres -d orion -f .cursor/db/grants.sql

GRANT ALL ON SCHEMA orion_ods TO orion_user;
GRANT ALL ON ALL TABLES IN SCHEMA orion_ods TO orion_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA orion_ods TO orion_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA orion_ods GRANT ALL ON TABLES TO orion_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA orion_ods GRANT ALL ON SEQUENCES TO orion_user;

GRANT ALL ON SCHEMA orion_dw TO orion_user;
GRANT ALL ON ALL TABLES IN SCHEMA orion_dw TO orion_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA orion_dw TO orion_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA orion_dw GRANT ALL ON TABLES TO orion_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA orion_dw GRANT ALL ON SEQUENCES TO orion_user;

CREATE SCHEMA IF NOT EXISTS tally_ods;
GRANT ALL ON SCHEMA tally_ods TO orion_user;
GRANT ALL ON ALL TABLES IN SCHEMA tally_ods TO orion_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA tally_ods TO orion_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA tally_ods GRANT ALL ON TABLES TO orion_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA tally_ods GRANT ALL ON SEQUENCES TO orion_user;

CREATE SCHEMA IF NOT EXISTS tally_dw;
GRANT ALL ON SCHEMA tally_dw TO orion_user;
GRANT ALL ON ALL TABLES IN SCHEMA tally_dw TO orion_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA tally_dw TO orion_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA tally_dw GRANT ALL ON TABLES TO orion_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA tally_dw GRANT ALL ON SEQUENCES TO orion_user;

-- App startup creates missing warehouse tables. That only works if orion_user
-- owns the schema (init scripts often create it as postgres).
DO $$
DECLARE
  obj RECORD;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
    RETURN;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'orion_dw' AND pg_get_userbyid(nspowner) <> 'orion_user') THEN
    EXECUTE 'ALTER SCHEMA orion_dw OWNER TO orion_user';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'tally_ods' AND pg_get_userbyid(nspowner) <> 'orion_user') THEN
    EXECUTE 'ALTER SCHEMA tally_ods OWNER TO orion_user';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'tally_dw' AND pg_get_userbyid(nspowner) <> 'orion_user') THEN
    EXECUTE 'ALTER SCHEMA tally_dw OWNER TO orion_user';
  END IF;
  FOR obj IN
    SELECT c.relname, c.relkind
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'orion_dw'
      AND c.relkind IN ('r', 'v')
      AND pg_get_userbyid(c.relowner) <> 'orion_user'
  LOOP
    IF obj.relkind = 'v' THEN
      EXECUTE format('ALTER VIEW orion_dw.%I OWNER TO orion_user', obj.relname);
    ELSE
      EXECUTE format('ALTER TABLE orion_dw.%I OWNER TO orion_user', obj.relname);
    END IF;
  END LOOP;
  FOR obj IN
    SELECT c.relname, c.relkind
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'tally_ods'
      AND c.relkind IN ('r', 'v')
      AND pg_get_userbyid(c.relowner) <> 'orion_user'
  LOOP
    IF obj.relkind = 'v' THEN
      EXECUTE format('ALTER VIEW tally_ods.%I OWNER TO orion_user', obj.relname);
    ELSE
      EXECUTE format('ALTER TABLE tally_ods.%I OWNER TO orion_user', obj.relname);
    END IF;
  END LOOP;
  FOR obj IN
    SELECT c.relname, c.relkind
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'tally_dw'
      AND c.relkind IN ('r', 'v')
      AND pg_get_userbyid(c.relowner) <> 'orion_user'
  LOOP
    IF obj.relkind = 'v' THEN
      EXECUTE format('ALTER VIEW tally_dw.%I OWNER TO orion_user', obj.relname);
    ELSE
      EXECUTE format('ALTER TABLE tally_dw.%I OWNER TO orion_user', obj.relname);
    END IF;
  END LOOP;
END $$;
