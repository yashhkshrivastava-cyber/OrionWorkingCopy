-- Messages: replies, edits, deletes, reactions, pinned messages, and each person's own choices for a conversation.
-- Idempotent and additive: safe on a database that already has chat data, and applied on every API start.
-- The base tables (direct_chat, chat_message, chat_read, chat_attachment) are in schema.sql.

-- A reply points at the message it answers. If that message is ever removed the reply simply loses its quote.
ALTER TABLE orion_ods.chat_message ADD COLUMN IF NOT EXISTS reply_to_id INTEGER REFERENCES orion_ods.chat_message(id) ON DELETE SET NULL;
ALTER TABLE orion_ods.chat_message ADD COLUMN IF NOT EXISTS edited_timestamp TIMESTAMPTZ;
-- Deleting a message blanks it and sets this; the row stays so the order of the chat and replies to it still make sense.
ALTER TABLE orion_ods.chat_message ADD COLUMN IF NOT EXISTS deleted_timestamp TIMESTAMPTZ;
ALTER TABLE orion_ods.chat_message ADD COLUMN IF NOT EXISTS forwarded BOOLEAN NOT NULL DEFAULT FALSE;
-- Chosen by the browser for each send, so the same send arriving twice (a retry) is stored once.
ALTER TABLE orion_ods.chat_message ADD COLUMN IF NOT EXISTS client_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS chat_message_client_idx
    ON orion_ods.chat_message (chat_id, sender_id, client_id) WHERE client_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS orion_ods.chat_reaction (
    message_id INTEGER NOT NULL REFERENCES orion_ods.chat_message(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    emoji TEXT NOT NULL,
    created_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (message_id, user_id, emoji)
);

-- Messages pinned in a conversation (visible to both people).
CREATE TABLE IF NOT EXISTS orion_ods.chat_pin (
    chat_id INTEGER NOT NULL REFERENCES orion_ods.direct_chat(id) ON DELETE CASCADE,
    message_id INTEGER NOT NULL REFERENCES orion_ods.chat_message(id) ON DELETE CASCADE,
    pinned_by INTEGER REFERENCES orion_ods.app_user(id) ON DELETE SET NULL,
    created_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, message_id)
);

-- One person's own choices for one conversation: kept at the top, muted, archived.
CREATE TABLE IF NOT EXISTS orion_ods.chat_member_setting (
    chat_id INTEGER NOT NULL REFERENCES orion_ods.direct_chat(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    pinned BOOLEAN NOT NULL DEFAULT FALSE,
    muted BOOLEAN NOT NULL DEFAULT FALSE,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (chat_id, user_id)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON orion_ods.chat_reaction, orion_ods.chat_pin, orion_ods.chat_member_setting TO orion_user;

-- Voice and video calls between the two people of a conversation. A call is kept for ever as the line it leaves in the chat
-- ("Missed voice call", "Video call, 12 min"); the audio and video themselves go straight between the two browsers and are never stored.
-- Only calls.py writes this table.
CREATE TABLE IF NOT EXISTS orion_ods.chat_call (
    id SERIAL PRIMARY KEY,
    chat_id INTEGER NOT NULL REFERENCES orion_ods.direct_chat(id) ON DELETE CASCADE,
    caller_id INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    callee_id INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('voice', 'video')),
    outcome TEXT NOT NULL DEFAULT 'ringing' CHECK (outcome IN ('ringing', 'answered', 'ended', 'missed', 'declined', 'cancelled', 'failed')),
    started_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    answered_timestamp TIMESTAMPTZ,
    ended_timestamp TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS chat_call_chat_idx ON orion_ods.chat_call (chat_id, id);
-- The line a finished call leaves in its conversation is an ordinary message that points at the call.
ALTER TABLE orion_ods.chat_message ADD COLUMN IF NOT EXISTS call_id INTEGER REFERENCES orion_ods.chat_call(id) ON DELETE SET NULL;

-- A voice note is an attachment of kind 'audio': how long it is and a small picture of its loudness (up to 64 numbers, 0 to 100) to draw it by.
ALTER TABLE orion_ods.chat_attachment ADD COLUMN IF NOT EXISTS duration_ms INTEGER;
ALTER TABLE orion_ods.chat_attachment ADD COLUMN IF NOT EXISTS waveform TEXT;

GRANT SELECT, INSERT, UPDATE, DELETE ON orion_ods.chat_call TO orion_user;
GRANT USAGE, SELECT ON SEQUENCE orion_ods.chat_call_id_seq TO orion_user;

-- Group chats. A group is a conversation with kind 'group', a title and its members in chat_member (who is an admin is kept there).
-- A direct conversation keeps its two people in user_low / user_high and has no chat_member rows, so it works exactly as before.
ALTER TABLE orion_ods.direct_chat ALTER COLUMN user_low DROP NOT NULL;
ALTER TABLE orion_ods.direct_chat ALTER COLUMN user_high DROP NOT NULL;
ALTER TABLE orion_ods.direct_chat ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'direct';
ALTER TABLE orion_ods.direct_chat ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE orion_ods.direct_chat ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES orion_ods.app_user(id) ON DELETE SET NULL;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'direct_chat_kind_check' AND conrelid = 'orion_ods.direct_chat'::regclass) THEN
        ALTER TABLE orion_ods.direct_chat ADD CONSTRAINT direct_chat_kind_check
            CHECK ((kind = 'direct' AND user_low IS NOT NULL AND user_high IS NOT NULL) OR (kind = 'group' AND title IS NOT NULL));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS orion_ods.chat_member (
    chat_id INTEGER NOT NULL REFERENCES orion_ods.direct_chat(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES orion_ods.app_user(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    added_by INTEGER REFERENCES orion_ods.app_user(id) ON DELETE SET NULL,
    joined_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS chat_member_user_idx ON orion_ods.chat_member (user_id);

-- "Priya added Rahul", "Anita left", "Priya renamed the group": a line of the conversation that nobody wrote and nobody can change.
ALTER TABLE orion_ods.chat_message ADD COLUMN IF NOT EXISTS system BOOLEAN NOT NULL DEFAULT FALSE;

GRANT SELECT, INSERT, UPDATE, DELETE ON orion_ods.chat_member TO orion_user;
