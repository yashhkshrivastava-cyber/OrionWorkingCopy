-- Sign-in security: one row per signed-in browser or device (so a session can be ended on the server), and one row per
-- sign-in style attempt (so repeated failures can be slowed down and looked at afterwards).
-- Idempotent and additive: safe on a database that already has users, and applied on every API start.
-- Cookies issued before this existed carry no session row; they are simply no longer accepted, so everyone signs in once.

CREATE TABLE IF NOT EXISTS orion_ods.app_session (
    id                  BIGSERIAL PRIMARY KEY,
    -- The random half of the cookie (the other half is its signature). Never shown to anyone; `id` is what screens use.
    token_id            TEXT NOT NULL UNIQUE,
    user_id             INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    created_timestamp   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_timestamp   TIMESTAMPTZ NOT NULL,
    -- Set when the session was ended before it expired: signed out, password changed, account disabled, ended by an administrator.
    revoked_timestamp   TIMESTAMPTZ,
    revoked_reason      TEXT,
    ip                  TEXT,
    user_agent          TEXT
);

CREATE INDEX IF NOT EXISTS app_session_user_idx
    ON orion_ods.app_session (user_id)
    WHERE revoked_timestamp IS NULL;

CREATE INDEX IF NOT EXISTS app_session_expires_idx
    ON orion_ods.app_session (expires_timestamp);

-- Sign-in, password-reset and registration attempts. `kind` is login, forgot, register or reset. `username` is stored lower-case
-- and only for the attempts that name one; passwords and tokens are never stored here.
CREATE TABLE IF NOT EXISTS orion_ods.auth_attempt (
    id                  BIGSERIAL PRIMARY KEY,
    kind                TEXT NOT NULL,
    username            TEXT,
    ip                  TEXT NOT NULL DEFAULT 'unknown',
    succeeded           BOOLEAN NOT NULL DEFAULT FALSE,
    attempted_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS auth_attempt_username_idx
    ON orion_ods.auth_attempt (kind, username, attempted_timestamp DESC);

CREATE INDEX IF NOT EXISTS auth_attempt_ip_idx
    ON orion_ods.auth_attempt (kind, ip, attempted_timestamp DESC);

CREATE INDEX IF NOT EXISTS auth_attempt_time_idx
    ON orion_ods.auth_attempt (attempted_timestamp);
