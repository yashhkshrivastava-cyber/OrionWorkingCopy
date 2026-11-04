-- The AI Copilot: conversations, an audit trail of everything it does, actions waiting for a person's confirmation,
-- files it makes (exports and reports), reminders and tasks, and each person's AI settings.
-- Idempotent: safe on existing databases, and applied on every API start. Written only by backend/app/ai.
--
-- Nothing here is loaded into the warehouse. The business data the assistant reads stays where it is; it is fetched
-- through the permission-checked tools in backend/app/ai/tools, never copied here.

-- AI is a per-person access flag, like the other segments. The first time it is added, everyone gets it: the assistant
-- can only see and do what the person's other permissions already allow, so the flag is a switch for an admin to turn
-- someone off (cost, policy), not a grant of access.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_ods' AND table_name = 'app_user' AND column_name = 'ai_access'
    ) THEN
        ALTER TABLE orion_ods.app_user ADD COLUMN IF NOT EXISTS ai_access BOOLEAN NOT NULL DEFAULT TRUE;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS orion_ods.ai_conversation (
    id                   BIGSERIAL PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    title                TEXT NOT NULL DEFAULT 'New conversation',
    category             TEXT NOT NULL DEFAULT 'general' CHECK (category IN ('general', 'analytics', 'reports', 'records', 'tasks')),
    -- What was said before the last few turns, boiled down, so a long conversation does not grow without limit.
    summary              TEXT NOT NULL DEFAULT '',
    summarized_upto      BIGINT NOT NULL DEFAULT 0,
    created_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_ai_conversation_user ON orion_ods.ai_conversation (user_id, updated_timestamp DESC);

-- One row per message. `text` is the plain text (what is sent back to the model as history, and searched);
-- `parts` is everything the screen draws (text, tables, charts, sources, confirmation cards).
CREATE TABLE IF NOT EXISTS orion_ods.ai_message (
    id                   BIGSERIAL PRIMARY KEY,
    conversation_id      BIGINT NOT NULL REFERENCES orion_ods.ai_conversation(id) ON DELETE CASCADE,
    role                 TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text                 TEXT NOT NULL DEFAULT '',
    parts                JSONB NOT NULL DEFAULT '[]'::jsonb,
    context              JSONB,
    model                TEXT,
    tokens_in            INTEGER,
    tokens_out           INTEGER,
    created_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_ai_message_conversation ON orion_ods.ai_message (conversation_id, id);

-- Every tool the assistant ran or was refused, kept even after a conversation is deleted. No foreign keys on purpose:
-- the trail outlives the things it describes. `args` are the validated arguments (never message text).
CREATE TABLE IF NOT EXISTS orion_ods.ai_audit (
    id                    BIGSERIAL PRIMARY KEY,
    at                    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id               INTEGER,
    conversation_id       BIGINT,
    tool                  TEXT NOT NULL,
    kind                  TEXT NOT NULL,
    status                TEXT NOT NULL,
    entity                TEXT,
    args                  JSONB,
    summary               TEXT,
    confirmation_required BOOLEAN NOT NULL DEFAULT FALSE,
    confirmed_by_user     BOOLEAN,
    duration_ms           INTEGER,
    error                 TEXT
);

CREATE INDEX IF NOT EXISTS ix_ai_audit_user ON orion_ods.ai_audit (user_id, at DESC);
CREATE INDEX IF NOT EXISTS ix_ai_audit_conversation ON orion_ods.ai_audit (conversation_id, at);

-- A change the assistant has prepared and a person has not yet confirmed. The preview is worked out on the server from the
-- validated arguments, so what the person is shown is what will happen, whatever the model said.
CREATE TABLE IF NOT EXISTS orion_ods.ai_pending_action (
    id                   TEXT PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    conversation_id      BIGINT,
    tool                 TEXT NOT NULL,
    args                 JSONB NOT NULL,
    preview              JSONB NOT NULL,
    risk                 TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'cancelled', 'expired', 'failed')),
    result               JSONB,
    created_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_timestamp    TIMESTAMPTZ NOT NULL,
    resolved_timestamp   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_ai_pending_user ON orion_ods.ai_pending_action (user_id, status);

-- Exports and reports the assistant made, for the person who asked. They expire.
CREATE TABLE IF NOT EXISTS orion_ods.ai_file (
    id                   TEXT PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    name                 TEXT NOT NULL,
    content_type         TEXT NOT NULL,
    size_bytes           INTEGER NOT NULL,
    data                 BYTEA NOT NULL,
    created_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_timestamp    TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_ai_file_user ON orion_ods.ai_file (user_id, created_timestamp DESC);

-- Reminders and tasks a person asked the assistant to keep. Each is private to the person who made it.
CREATE TABLE IF NOT EXISTS orion_ods.ai_task (
    id                   SERIAL PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    kind                 TEXT NOT NULL CHECK (kind IN ('reminder', 'task')),
    title                TEXT NOT NULL,
    note                 TEXT,
    due_at               TIMESTAMPTZ,
    status               TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'dismissed')),
    link                 TEXT,
    conversation_id      BIGINT,
    created_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_timestamp  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_ai_task_user ON orion_ods.ai_task (user_id, status, due_at);

CREATE TABLE IF NOT EXISTS orion_ods.ai_user_setting (
    user_id              INTEGER PRIMARY KEY REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    enabled              BOOLEAN NOT NULL DEFAULT TRUE,
    keep_history         BOOLEAN NOT NULL DEFAULT TRUE,
    show_insights        BOOLEAN NOT NULL DEFAULT TRUE,
    updated_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Insights a person has dismissed or snoozed.
CREATE TABLE IF NOT EXISTS orion_ods.ai_insight_state (
    user_id              INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    insight_id           TEXT NOT NULL,
    hidden_until         TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, insight_id)
);

-- What each person has used each day, for the daily limit and for seeing what the assistant costs.
CREATE TABLE IF NOT EXISTS orion_ods.ai_usage (
    user_id              INTEGER NOT NULL,
    day                  DATE NOT NULL,
    requests             INTEGER NOT NULL DEFAULT 0,
    tool_calls           INTEGER NOT NULL DEFAULT 0,
    tokens_in            BIGINT NOT NULL DEFAULT 0,
    tokens_out           BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

-- Whether this person lets their questions be sent to a cloud model when the organisation's policy would allow it.
-- Off unless they turn it on: private data stays on this machine by default.
ALTER TABLE orion_ods.ai_user_setting ADD COLUMN IF NOT EXISTS allow_cloud BOOLEAN NOT NULL DEFAULT FALSE;

-- The organisation's rule for cloud models (one row, id 1). No row means the strictest rule, local_only.
--   local_only      nothing leaves this machine
--   no_app_data     a cloud model may be used for questions that need none of the application's data
--   local_first     the local model answers first; a cloud model may be tried when it fails, with minimised data
--   cloud_eligible  a cloud model may also be chosen directly for heavy analysis, with minimised data
CREATE TABLE IF NOT EXISTS orion_ods.ai_policy (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    cloud_mode           TEXT NOT NULL DEFAULT 'local_only' CHECK (cloud_mode IN ('local_only', 'no_app_data', 'local_first', 'cloud_eligible')),
    updated_by           INTEGER,
    updated_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One row per answer: how it was routed and what it cost. It never holds the question, the answer or any data.
CREATE TABLE IF NOT EXISTS orion_ods.ai_route_log (
    id                   BIGSERIAL PRIMARY KEY,
    at                   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id              INTEGER,
    conversation_id      BIGINT,
    category             TEXT NOT NULL,
    path                 TEXT NOT NULL CHECK (path IN ('app', 'local', 'cloud', 'none')),
    provider             TEXT,
    model                TEXT,
    reasons              TEXT[] NOT NULL DEFAULT '{}',
    escalated_from       TEXT,
    attempts             INTEGER NOT NULL DEFAULT 1,
    latency_ms           INTEGER,
    tokens_in            INTEGER,
    tokens_out           INTEGER,
    est_cost_usd         NUMERIC(10, 5) NOT NULL DEFAULT 0,
    outcome              TEXT NOT NULL,
    cloud_blocked        TEXT
);

CREATE INDEX IF NOT EXISTS ix_ai_route_log_at ON orion_ods.ai_route_log (at DESC);
CREATE INDEX IF NOT EXISTS ix_ai_route_log_cloud ON orion_ods.ai_route_log (path, at) WHERE path = 'cloud';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON orion_ods.ai_conversation, orion_ods.ai_message, orion_ods.ai_audit, orion_ods.ai_pending_action,
                     orion_ods.ai_file, orion_ods.ai_task, orion_ods.ai_user_setting, orion_ods.ai_insight_state,
                     orion_ods.ai_usage, orion_ods.ai_policy, orion_ods.ai_route_log TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.ai_conversation_id_seq, orion_ods.ai_message_id_seq, orion_ods.ai_audit_id_seq,
                              orion_ods.ai_task_id_seq, orion_ods.ai_route_log_id_seq TO orion_user;
    END IF;
END $$;
