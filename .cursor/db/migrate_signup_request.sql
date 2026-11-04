-- Pending self-service account requests. Admin approves with role + data access.

CREATE TABLE IF NOT EXISTS orion_ods.signup_request (
    id                 SERIAL PRIMARY KEY,
    username           TEXT NOT NULL,
    display_name       TEXT NOT NULL,
    password_hash      TEXT NOT NULL,
    email              TEXT NOT NULL,
    phone              TEXT,
    status             TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_timestamp TIMESTAMPTZ,
    reviewed_by        INTEGER REFERENCES orion_ods.app_user(id) ON DELETE SET NULL,
    created_user_id    INTEGER REFERENCES orion_ods.app_user(id) ON DELETE SET NULL,
    rejection_reason   TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS signup_request_pending_username_idx
    ON orion_ods.signup_request (LOWER(username))
    WHERE status = 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS signup_request_pending_email_idx
    ON orion_ods.signup_request (LOWER(email))
    WHERE status = 'pending';
