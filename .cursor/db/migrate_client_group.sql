-- A client can belong to a group, and the group is another client.
-- Idempotent: safe on existing databases, and applied on every API start.
--
-- client_group_code holds the code of the client that stands for the group (a head office, a
-- department, a parent company). It is empty for a client that stands on its own, which is every
-- client until someone picks a group. A client is never its own group.

ALTER TABLE orion_ods.client
    ADD COLUMN IF NOT EXISTS client_group_code TEXT REFERENCES orion_ods.client(client_code);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'client_group_not_self' AND conrelid = 'orion_ods.client'::regclass
    ) THEN
        ALTER TABLE orion_ods.client
            ADD CONSTRAINT client_group_not_self CHECK (client_group_code IS NULL OR client_group_code <> client_code);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_client_group ON orion_ods.client (client_group_code);
