-- Capability Head is an employee, picked from the employee table, not free text.
-- Idempotent: safe on existing databases, and applied on every API start.
--
-- The old column capability_head (free text) was no longer read or written for a release, and is now dropped
-- (at the end of this file, and in dw_schema.sql for the warehouse).
--
-- The first time the new column is added, a head typed as text is turned into the employee's code
-- when exactly one employee has that name. Anything else is left empty for a person to pick. That conversion
-- needs the old column, so it only runs while the old column is still there.

DO $$
BEGIN
    IF to_regclass('orion_ods.capability') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'orion_ods' AND table_name = 'capability' AND column_name = 'capability_head_code'
       ) THEN
        ALTER TABLE orion_ods.capability
            ADD COLUMN capability_head_code TEXT REFERENCES orion_ods.employee(employee_code);
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_ods' AND table_name = 'capability' AND column_name = 'capability_head'
    ) THEN
        UPDATE orion_ods.capability c
           SET capability_head_code = e.employee_code
          FROM orion_ods.employee e
         WHERE NULLIF(BTRIM(c.capability_head), '') IS NOT NULL
           AND LOWER(BTRIM(e.employee_name)) = LOWER(BTRIM(c.capability_head))
           AND (
               SELECT COUNT(*) FROM orion_ods.employee x
                WHERE LOWER(BTRIM(x.employee_name)) = LOWER(BTRIM(c.capability_head))
           ) = 1
           AND c.capability_head_code IS NULL;
    END IF;
END $$;

ALTER TABLE orion_ods.capability
    ADD COLUMN IF NOT EXISTS capability_head_code TEXT REFERENCES orion_ods.employee(employee_code);

CREATE INDEX IF NOT EXISTS ix_capability_head ON orion_ods.capability (capability_head_code);

-- Drop the old free-text column. Guarded, so a database that no longer has it takes no lock on the table.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_ods' AND table_name = 'capability' AND column_name = 'capability_head'
    ) THEN
        ALTER TABLE orion_ods.capability DROP COLUMN capability_head;
    END IF;
END $$;
