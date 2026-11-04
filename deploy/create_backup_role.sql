-- Creates the read-only database role that backups run as. Run it once per database, as the postgres superuser,
-- while connected to the database to back up (orion on a dev PC, orion_prod on the office PC):
--
--   psql -U postgres -d orion_prod -v pw="'the-password-for-orion_backup'" -f deploy/create_backup_role.sql
--
-- Then put the same password in that machine's .env as ORION_BACKUP_DB_PASSWORD. Safe to run again: it sets the
-- password and re-grants, and nothing else changes.
--
-- The role can log in, read the four schemas and nothing else: it cannot write, create or drop anything, and every
-- session it opens is read-only. It is not orion_user, so a leaked backup setting cannot change data.

\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_backup') THEN
        CREATE ROLE orion_backup LOGIN;
    END IF;
END $$;

ALTER ROLE orion_backup WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :pw;
ALTER ROLE orion_backup SET default_transaction_read_only = on;

SELECT current_database() AS target_db \gset
GRANT CONNECT ON DATABASE :"target_db" TO orion_backup;

DO $$
DECLARE
    schema_name text;
    owner_role  text;
BEGIN
    FOREACH schema_name IN ARRAY ARRAY['orion_ods', 'orion_dw', 'tally_ods', 'tally_dw'] LOOP
        CONTINUE WHEN NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = schema_name);
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO orion_backup', schema_name);
        EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO orion_backup', schema_name);
        EXECUTE format('GRANT SELECT ON ALL SEQUENCES IN SCHEMA %I TO orion_backup', schema_name);
        -- Tables created later by the roles that create them are readable too.
        FOREACH owner_role IN ARRAY ARRAY['orion_user', 'postgres'] LOOP
            CONTINUE WHEN NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = owner_role);
            EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON TABLES TO orion_backup', owner_role, schema_name);
            EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON SEQUENCES TO orion_backup', owner_role, schema_name);
        END LOOP;
    END LOOP;
END $$;
