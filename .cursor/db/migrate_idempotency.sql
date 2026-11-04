-- One row per submission that must happen once however many times it arrives: a double-click, a retry after a dropped
-- connection, a stale tab. The browser makes a key when the form opens and sends it with the request; the server claims it in
-- the SAME transaction as the bill or payment it protects, so either both are saved or neither is, and a request that arrives
-- again with the same key gets the first one's result instead of doing the work twice.
-- Idempotent and additive: safe on a database that already has data, and applied on every API start.

CREATE TABLE IF NOT EXISTS orion_ods.idempotency_key (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    idem_key            TEXT NOT NULL,
    -- What the key was used for ('bill.create', 'bill.payment', ...), and a hash of exactly what was asked, so the same key
    -- sent with something different is refused instead of being taken for a repeat.
    operation           TEXT NOT NULL,
    fingerprint         TEXT NOT NULL,
    -- What to answer a repeat with (the bill's code), written in the same transaction as the work.
    result              JSONB,
    created_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, idem_key)
);

CREATE INDEX IF NOT EXISTS idempotency_key_created_idx
    ON orion_ods.idempotency_key (created_timestamp);
