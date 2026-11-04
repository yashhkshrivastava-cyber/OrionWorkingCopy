-- Tasks: projects, tasks and everything around them (a Jira-like workspace for the team), plus each person's own to-do lists.
--
-- A PROJECT has members with a role (Manager, Member, Viewer) and its own workflow of statuses. A TASK belongs to a project and is named by the
-- project's key and a running number (OPS-12). Everything that happens to a task is kept in task_activity for ever. Files are kept in the database
-- (task_file, once for each different file). Safe to run again; nothing here is ever dropped.

CREATE TABLE IF NOT EXISTS orion_ods.task_project (
    project_id         SERIAL PRIMARY KEY,
    project_key        TEXT NOT NULL UNIQUE CHECK (project_key ~ '^[A-Z][A-Z0-9]{1,9}$'),
    name               TEXT NOT NULL CHECK (BTRIM(name) <> '' AND char_length(name) <= 120),
    description        TEXT,
    lead_id            INTEGER,
    visibility         TEXT NOT NULL DEFAULT 'Company' CHECK (visibility IN ('Company', 'Private')),  -- Company: everyone may work in it; Private: its members only
    state              TEXT NOT NULL DEFAULT 'Active' CHECK (state IN ('Active', 'Archived')),
    require_review     BOOLEAN NOT NULL DEFAULT FALSE,      -- a task may be marked done only by its reviewer (or a manager) after a review
    next_no            INTEGER NOT NULL DEFAULT 1,          -- the number the next task gets
    color              TEXT,
    created_by         INTEGER,
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orion_ods.task_member (
    project_id         INTEGER NOT NULL REFERENCES orion_ods.task_project (project_id),
    user_id            INTEGER NOT NULL,
    role               TEXT NOT NULL CHECK (role IN ('Manager', 'Member', 'Viewer')),
    added_by           INTEGER,
    added_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, user_id)
);
CREATE INDEX IF NOT EXISTS task_member_user_idx ON orion_ods.task_member (user_id);

-- The workflow of a project: its columns, in order. The category says what a status MEANS (so reports and rules do not depend on its name).
CREATE TABLE IF NOT EXISTS orion_ods.task_status (
    status_id          SERIAL PRIMARY KEY,
    project_id         INTEGER NOT NULL REFERENCES orion_ods.task_project (project_id),
    name               TEXT NOT NULL CHECK (BTRIM(name) <> '' AND char_length(name) <= 40),
    category           TEXT NOT NULL CHECK (category IN ('todo', 'doing', 'review', 'done')),
    position           INTEGER NOT NULL DEFAULT 0,
    wip_limit          INTEGER CHECK (wip_limit IS NULL OR wip_limit > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS task_status_name_uidx ON orion_ods.task_status (project_id, lower(name));

CREATE TABLE IF NOT EXISTS orion_ods.task_sprint (
    sprint_id          SERIAL PRIMARY KEY,
    project_id         INTEGER NOT NULL REFERENCES orion_ods.task_project (project_id),
    name               TEXT NOT NULL CHECK (BTRIM(name) <> '' AND char_length(name) <= 80),
    goal               TEXT,
    start_date         DATE,
    end_date           DATE,
    state              TEXT NOT NULL DEFAULT 'Planned' CHECK (state IN ('Planned', 'Active', 'Completed')),
    started_timestamp  TIMESTAMPTZ,
    completed_timestamp TIMESTAMPTZ,
    created_by         INTEGER,
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);
-- one sprint at a time is Active in a project
CREATE UNIQUE INDEX IF NOT EXISTS task_sprint_one_active_uidx ON orion_ods.task_sprint (project_id) WHERE state = 'Active';

-- Templates, and with a schedule the tasks that come back by themselves (the monthly PF payment, the GST return, a licence renewal).
CREATE TABLE IF NOT EXISTS orion_ods.task_template (
    template_id        SERIAL PRIMARY KEY,
    project_id         INTEGER NOT NULL REFERENCES orion_ods.task_project (project_id),
    name               TEXT NOT NULL CHECK (BTRIM(name) <> '' AND char_length(name) <= 80),
    title              TEXT NOT NULL CHECK (BTRIM(title) <> '' AND char_length(title) <= 250),
    description        TEXT,
    task_type          TEXT NOT NULL DEFAULT 'Task' CHECK (task_type IN ('Task', 'Bug', 'Story', 'Epic', 'Sub-task', 'Follow-up')),
    priority           TEXT NOT NULL DEFAULT 'Medium' CHECK (priority IN ('Critical', 'High', 'Medium', 'Low')),
    assignee_id        INTEGER,
    reviewer_id        INTEGER,
    labels             TEXT[] NOT NULL DEFAULT '{}',
    checklist          JSONB NOT NULL DEFAULT '[]'::jsonb,   -- a list of item texts
    due_offset_days    INTEGER NOT NULL DEFAULT 0 CHECK (due_offset_days >= 0 AND due_offset_days <= 366),
    estimate_minutes   INTEGER CHECK (estimate_minutes IS NULL OR estimate_minutes >= 0),
    frequency          TEXT CHECK (frequency IS NULL OR frequency IN ('daily', 'weekly', 'monthly', 'yearly')),   -- empty: a template only, made by hand
    interval_count     INTEGER NOT NULL DEFAULT 1 CHECK (interval_count >= 1 AND interval_count <= 52),
    weekday            INTEGER CHECK (weekday IS NULL OR weekday BETWEEN 0 AND 6),        -- weekly: 0 is Monday
    day_of_month       INTEGER CHECK (day_of_month IS NULL OR day_of_month BETWEEN 1 AND 31),  -- monthly and yearly (a short month uses its last day)
    month_of_year      INTEGER CHECK (month_of_year IS NULL OR month_of_year BETWEEN 1 AND 12),
    next_run           DATE,
    end_date           DATE,
    active             BOOLEAN NOT NULL DEFAULT TRUE,
    last_run           DATE,
    created_by         INTEGER,
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS task_template_due_idx ON orion_ods.task_template (next_run) WHERE frequency IS NOT NULL AND active;

CREATE TABLE IF NOT EXISTS orion_ods.task (
    task_id            BIGSERIAL PRIMARY KEY,
    project_id         INTEGER NOT NULL REFERENCES orion_ods.task_project (project_id),
    task_no            INTEGER NOT NULL,
    task_key           TEXT NOT NULL UNIQUE,                 -- OPS-12: the project's key and the number, never reused
    title              TEXT NOT NULL CHECK (BTRIM(title) <> '' AND char_length(title) <= 250),
    description        TEXT,
    task_type          TEXT NOT NULL DEFAULT 'Task' CHECK (task_type IN ('Task', 'Bug', 'Story', 'Epic', 'Sub-task', 'Follow-up')),
    priority           TEXT NOT NULL DEFAULT 'Medium' CHECK (priority IN ('Critical', 'High', 'Medium', 'Low')),
    status_id          INTEGER NOT NULL REFERENCES orion_ods.task_status (status_id),
    assignee_id        INTEGER,
    reporter_id        INTEGER,
    reviewer_id        INTEGER,
    parent_id          BIGINT REFERENCES orion_ods.task (task_id),   -- an epic, or the task a sub-task belongs to
    sprint_id          INTEGER REFERENCES orion_ods.task_sprint (sprint_id),
    template_id        INTEGER REFERENCES orion_ods.task_template (template_id),   -- the template or schedule that made it
    start_date         DATE,
    due_date           DATE,
    estimate_minutes   INTEGER CHECK (estimate_minutes IS NULL OR estimate_minutes >= 0),
    spent_minutes      INTEGER NOT NULL DEFAULT 0 CHECK (spent_minutes >= 0),   -- the total of its time logs
    story_points       NUMERIC(5, 1) CHECK (story_points IS NULL OR story_points >= 0),
    labels             TEXT[] NOT NULL DEFAULT '{}',
    rank               DOUBLE PRECISION NOT NULL DEFAULT 0,  -- the order on a board and in the backlog (smaller is higher)
    resolution         TEXT CHECK (resolution IS NULL OR resolution IN ('Done', 'Won''t do', 'Duplicate', 'Cancelled')),
    resolved_timestamp TIMESTAMPTZ,
    is_deleted         BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_by         INTEGER,
    deleted_timestamp  TIMESTAMPTZ,
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by         INTEGER,
    UNIQUE (project_id, task_no),
    CHECK (parent_id IS NULL OR parent_id <> task_id),
    CHECK (start_date IS NULL OR due_date IS NULL OR due_date >= start_date)
);
CREATE INDEX IF NOT EXISTS task_project_status_idx ON orion_ods.task (project_id, status_id) WHERE NOT is_deleted;
CREATE INDEX IF NOT EXISTS task_assignee_idx ON orion_ods.task (assignee_id) WHERE NOT is_deleted;
CREATE INDEX IF NOT EXISTS task_reviewer_idx ON orion_ods.task (reviewer_id) WHERE NOT is_deleted;
CREATE INDEX IF NOT EXISTS task_reporter_idx ON orion_ods.task (reporter_id) WHERE NOT is_deleted;
CREATE INDEX IF NOT EXISTS task_due_idx ON orion_ods.task (due_date) WHERE NOT is_deleted;
CREATE INDEX IF NOT EXISTS task_parent_idx ON orion_ods.task (parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS task_sprint_idx ON orion_ods.task (sprint_id) WHERE sprint_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS task_labels_idx ON orion_ods.task USING GIN (labels);

-- A task is never deleted for good: it is hidden (is_deleted), with who and when.
CREATE OR REPLACE FUNCTION orion_ods.task_kept() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'A task is kept for ever. Delete it from the task (it is then hidden), not from the table.' USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS task_kept ON orion_ods.task;
CREATE TRIGGER task_kept BEFORE DELETE ON orion_ods.task FOR EACH ROW EXECUTE FUNCTION orion_ods.task_kept();

CREATE TABLE IF NOT EXISTS orion_ods.task_comment (
    comment_id         BIGSERIAL PRIMARY KEY,
    task_id            BIGINT NOT NULL REFERENCES orion_ods.task (task_id),
    author_id          INTEGER NOT NULL,
    body               TEXT NOT NULL CHECK (BTRIM(body) <> ''),
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    edited_timestamp   TIMESTAMPTZ,
    is_deleted         BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_by         INTEGER
);
CREATE INDEX IF NOT EXISTS task_comment_task_idx ON orion_ods.task_comment (task_id, created_timestamp);

-- What happened, for ever. task_id is empty for what happened to a project itself.
CREATE TABLE IF NOT EXISTS orion_ods.task_activity (
    activity_id        BIGSERIAL PRIMARY KEY,
    task_id            BIGINT REFERENCES orion_ods.task (task_id),
    project_id         INTEGER REFERENCES orion_ods.task_project (project_id),
    user_id            INTEGER,
    action             TEXT NOT NULL,
    detail             JSONB NOT NULL DEFAULT '{}'::jsonb,
    at                 TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS task_activity_task_idx ON orion_ods.task_activity (task_id, at DESC);
CREATE INDEX IF NOT EXISTS task_activity_project_idx ON orion_ods.task_activity (project_id, at DESC);

CREATE OR REPLACE FUNCTION orion_ods.task_activity_kept() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'The history of a task is kept for ever.' USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS task_activity_kept ON orion_ods.task_activity;
CREATE TRIGGER task_activity_kept BEFORE UPDATE OR DELETE ON orion_ods.task_activity FOR EACH ROW EXECUTE FUNCTION orion_ods.task_activity_kept();

-- Files: each different file is kept once (by its hash), and an attachment says which task (or comment) it is on.
CREATE TABLE IF NOT EXISTS orion_ods.task_file (
    sha256             TEXT PRIMARY KEY,
    size_bytes         INTEGER NOT NULL CHECK (size_bytes >= 0),
    data               BYTEA NOT NULL
);

CREATE TABLE IF NOT EXISTS orion_ods.task_attachment (
    attachment_id      BIGSERIAL PRIMARY KEY,
    task_id            BIGINT NOT NULL REFERENCES orion_ods.task (task_id),
    comment_id         BIGINT REFERENCES orion_ods.task_comment (comment_id),
    file_name          TEXT NOT NULL,
    content_type       TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL,
    sha256             TEXT NOT NULL,                       -- the file in task_file; its bytes go when no attachment that is not deleted uses them
    uploaded_by        INTEGER NOT NULL,
    uploaded_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_deleted         BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_by         INTEGER,
    deleted_timestamp  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS task_attachment_task_idx ON orion_ods.task_attachment (task_id) WHERE NOT is_deleted;
ALTER TABLE orion_ods.task_attachment DROP CONSTRAINT IF EXISTS task_attachment_sha256_fkey;

CREATE TABLE IF NOT EXISTS orion_ods.task_watcher (
    task_id            BIGINT NOT NULL REFERENCES orion_ods.task (task_id),
    user_id            INTEGER NOT NULL,
    added_by           INTEGER,
    added_timestamp    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (task_id, user_id)
);
CREATE INDEX IF NOT EXISTS task_watcher_user_idx ON orion_ods.task_watcher (user_id);

-- Between tasks: one blocks another, they relate, or one duplicates another.
CREATE TABLE IF NOT EXISTS orion_ods.task_link (
    link_id            BIGSERIAL PRIMARY KEY,
    from_task_id       BIGINT NOT NULL REFERENCES orion_ods.task (task_id),
    to_task_id         BIGINT NOT NULL REFERENCES orion_ods.task (task_id),
    kind               TEXT NOT NULL CHECK (kind IN ('blocks', 'relates', 'duplicates')),
    created_by         INTEGER,
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (from_task_id, to_task_id, kind),
    CHECK (from_task_id <> to_task_id)
);
CREATE INDEX IF NOT EXISTS task_link_to_idx ON orion_ods.task_link (to_task_id);

-- From a task to the records of Orion it is about: a bill, a case, a client, an employee, an opportunity, an EMD, a document.
CREATE TABLE IF NOT EXISTS orion_ods.task_record_link (
    link_id            BIGSERIAL PRIMARY KEY,
    task_id            BIGINT NOT NULL REFERENCES orion_ods.task (task_id),
    record_type        TEXT NOT NULL CHECK (record_type IN ('bill', 'case', 'client', 'employee', 'opportunity', 'emd', 'expense', 'document')),
    record_ref         TEXT NOT NULL,
    label              TEXT,
    created_by         INTEGER,
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (task_id, record_type, record_ref)
);
CREATE INDEX IF NOT EXISTS task_record_link_ref_idx ON orion_ods.task_record_link (record_type, record_ref);

CREATE TABLE IF NOT EXISTS orion_ods.task_checklist_item (
    item_id            BIGSERIAL PRIMARY KEY,
    task_id            BIGINT NOT NULL REFERENCES orion_ods.task (task_id),
    text               TEXT NOT NULL CHECK (BTRIM(text) <> '' AND char_length(text) <= 300),
    done               BOOLEAN NOT NULL DEFAULT FALSE,
    position           INTEGER NOT NULL DEFAULT 0,
    done_by            INTEGER,
    done_timestamp     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS task_checklist_task_idx ON orion_ods.task_checklist_item (task_id, position);

CREATE TABLE IF NOT EXISTS orion_ods.task_time_log (
    log_id             BIGSERIAL PRIMARY KEY,
    task_id            BIGINT NOT NULL REFERENCES orion_ods.task (task_id),
    user_id            INTEGER NOT NULL,
    minutes            INTEGER NOT NULL CHECK (minutes > 0 AND minutes <= 1440),
    work_date          DATE NOT NULL,
    note               TEXT,
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_deleted         BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS task_time_log_task_idx ON orion_ods.task_time_log (task_id) WHERE NOT is_deleted;
CREATE INDEX IF NOT EXISTS task_time_log_user_idx ON orion_ods.task_time_log (user_id, work_date) WHERE NOT is_deleted;

-- A request to review a task, and what the reviewer decided. A task can be sent for review again after changes.
CREATE TABLE IF NOT EXISTS orion_ods.task_review (
    review_id          BIGSERIAL PRIMARY KEY,
    task_id            BIGINT NOT NULL REFERENCES orion_ods.task (task_id),
    requested_by       INTEGER NOT NULL,
    reviewer_id        INTEGER NOT NULL,
    status             TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending', 'Approved', 'Changes requested', 'Withdrawn')),
    request_note       TEXT,
    decision_note      TEXT,
    requested_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_timestamp  TIMESTAMPTZ,
    CHECK (status = 'Pending' OR decided_timestamp IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS task_review_task_idx ON orion_ods.task_review (task_id, requested_timestamp DESC);
CREATE INDEX IF NOT EXISTS task_review_reviewer_idx ON orion_ods.task_review (reviewer_id) WHERE status = 'Pending';
CREATE UNIQUE INDEX IF NOT EXISTS task_review_one_pending_uidx ON orion_ods.task_review (task_id) WHERE status = 'Pending';

-- Each person's inbox. Reminders for a due date are worked out when it is read, not stored here.
CREATE TABLE IF NOT EXISTS orion_ods.task_notification (
    notification_id    BIGSERIAL PRIMARY KEY,
    user_id            INTEGER NOT NULL,
    task_id            BIGINT REFERENCES orion_ods.task (task_id),
    project_id         INTEGER REFERENCES orion_ods.task_project (project_id),
    kind               TEXT NOT NULL,
    actor_id           INTEGER,
    text               TEXT NOT NULL,
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_timestamp     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS task_notification_user_idx ON orion_ods.task_notification (user_id, created_timestamp DESC);
CREATE INDEX IF NOT EXISTS task_notification_unread_idx ON orion_ods.task_notification (user_id) WHERE read_timestamp IS NULL;

CREATE TABLE IF NOT EXISTS orion_ods.task_saved_filter (
    filter_id          SERIAL PRIMARY KEY,
    user_id            INTEGER NOT NULL,
    project_id         INTEGER REFERENCES orion_ods.task_project (project_id),
    name               TEXT NOT NULL CHECK (BTRIM(name) <> '' AND char_length(name) <= 60),
    definition         JSONB NOT NULL DEFAULT '{}'::jsonb,
    shared             BOOLEAN NOT NULL DEFAULT FALSE,
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS task_saved_filter_user_idx ON orion_ods.task_saved_filter (user_id);

-- A person's own to-do lists. Private to them: nobody else sees them, not even an admin through the application.
CREATE TABLE IF NOT EXISTS orion_ods.task_todo_list (
    list_id            SERIAL PRIMARY KEY,
    user_id            INTEGER NOT NULL,
    name               TEXT NOT NULL CHECK (BTRIM(name) <> '' AND char_length(name) <= 60),
    position           INTEGER NOT NULL DEFAULT 0,
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS task_todo_list_user_idx ON orion_ods.task_todo_list (user_id);

CREATE TABLE IF NOT EXISTS orion_ods.task_todo (
    todo_id            BIGSERIAL PRIMARY KEY,
    user_id            INTEGER NOT NULL,
    list_id            INTEGER REFERENCES orion_ods.task_todo_list (list_id),
    text               TEXT NOT NULL CHECK (BTRIM(text) <> '' AND char_length(text) <= 300),
    notes              TEXT,
    done               BOOLEAN NOT NULL DEFAULT FALSE,
    done_timestamp     TIMESTAMPTZ,
    due_date           DATE,
    my_day             DATE,                                   -- the day it is planned for ("My day")
    position           INTEGER NOT NULL DEFAULT 0,
    task_id            BIGINT REFERENCES orion_ods.task (task_id),   -- the task it became, or the one it follows
    created_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS task_todo_user_idx ON orion_ods.task_todo (user_id, done, position);
CREATE INDEX IF NOT EXISTS task_todo_day_idx ON orion_ods.task_todo (user_id, my_day) WHERE my_day IS NOT NULL;
