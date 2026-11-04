"""Everything the assistant keeps: conversations, the audit trail, confirmations waiting, files, reminders, settings, usage.

Every function that touches a person's things takes their ``user_id`` and filters by it, so one person can never read or
change another's conversations, files, reminders or pending actions through this module.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from psycopg2.extras import Json

from app.ai import config
from app.database import db_cursor

CATEGORIES = ("general", "analytics", "reports", "records", "tasks")
SCHEMA = "orion_ods"


def _plain(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _rows(cur) -> list[dict[str, Any]]:
    return [{c.name: _plain(v) for c, v in zip(cur.description, row)} for row in cur.fetchall()]


def now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------------------------------------------ settings


_SETTING_KEYS = ("enabled", "keep_history", "show_insights", "allow_cloud")
_SETTING_DEFAULTS = {"enabled": True, "keep_history": True, "show_insights": True, "allow_cloud": False}


def get_settings(user_id: int) -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(f"SELECT enabled, keep_history, show_insights, allow_cloud FROM {SCHEMA}.ai_user_setting WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    return dict(zip(_SETTING_KEYS, row)) if row else dict(_SETTING_DEFAULTS)


def save_settings(user_id: int, changes: dict[str, Any]) -> dict[str, Any]:
    current = get_settings(user_id)
    for key in _SETTING_KEYS:
        if key in changes and isinstance(changes[key], bool):
            current[key] = changes[key]
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""INSERT INTO {SCHEMA}.ai_user_setting (user_id, enabled, keep_history, show_insights, allow_cloud, updated_timestamp)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET enabled = EXCLUDED.enabled, keep_history = EXCLUDED.keep_history,
                    show_insights = EXCLUDED.show_insights, allow_cloud = EXCLUDED.allow_cloud, updated_timestamp = CURRENT_TIMESTAMP""",
            (user_id, current["enabled"], current["keep_history"], current["show_insights"], current["allow_cloud"]),
        )
    return current


# ------------------------------------------------------------------------------------- the organisation's cloud policy


def get_policy() -> dict[str, Any]:
    """The organisation's rule for cloud models. With nothing saved it is the strictest: nothing leaves this machine."""
    with db_cursor() as cur:
        cur.execute(f"SELECT cloud_mode, updated_by, updated_timestamp FROM {SCHEMA}.ai_policy WHERE id = 1")
        row = cur.fetchone()
    if not row or row[0] not in config.CLOUD_POLICIES:
        return {"cloud_mode": config.DEFAULT_CLOUD_POLICY, "updated_by": None, "updated": None}
    return {"cloud_mode": row[0], "updated_by": row[1], "updated": _plain(row[2])}


def save_policy(cloud_mode: str, user_id: int) -> dict[str, Any]:
    if cloud_mode not in config.CLOUD_POLICIES:
        raise ValueError("That is not a cloud policy.")
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""INSERT INTO {SCHEMA}.ai_policy (id, cloud_mode, updated_by, updated_timestamp) VALUES (1, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET cloud_mode = EXCLUDED.cloud_mode, updated_by = EXCLUDED.updated_by, updated_timestamp = CURRENT_TIMESTAMP""",
            (cloud_mode, user_id),
        )
    return get_policy()


# ----------------------------------------------------------------------------------------------- how answers were routed


def log_route(
    user_id: int, conversation_id: int | None, *, category: str, path: str, provider: str | None, model: str | None, reasons: list[str],
    escalated_from: str | None, attempts: int, latency_ms: int, tokens_in: int, tokens_out: int, est_cost_usd: float, outcome: str, cloud_blocked: str | None,
) -> None:
    """One row per answer. It records how the answer was made, never the question or the answer."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                f"""INSERT INTO {SCHEMA}.ai_route_log (user_id, conversation_id, category, path, provider, model, reasons, escalated_from, attempts, latency_ms,
                                                         tokens_in, tokens_out, est_cost_usd, outcome, cloud_blocked)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (user_id, conversation_id, category, path, provider, model, reasons[:12], escalated_from, attempts, latency_ms, tokens_in, tokens_out, round(est_cost_usd, 5), outcome, cloud_blocked),
            )
    except Exception:  # noqa: BLE001 - not being able to note how an answer was made must not stop the answer
        import logging

        logging.getLogger(__name__).exception("Could not write the route log")


def cloud_spend_this_month() -> float:
    with db_cursor() as cur:
        cur.execute(f"SELECT COALESCE(SUM(est_cost_usd), 0) FROM {SCHEMA}.ai_route_log WHERE path = 'cloud' AND at >= date_trunc('month', CURRENT_TIMESTAMP)")
        return float(cur.fetchone()[0])


def cloud_answers_today(user_id: int) -> int:
    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.ai_route_log WHERE path = 'cloud' AND user_id = %s AND at >= CURRENT_DATE", (user_id,))
        return int(cur.fetchone()[0])


def route_overview(days: int = 7) -> list[dict[str, Any]]:
    """How answers were made over the last few days: how many by the application, the local model and the cloud, and what the cloud cost."""
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT path, COUNT(*) AS answers, COALESCE(SUM(est_cost_usd), 0) AS cost_usd, COALESCE(AVG(latency_ms), 0)::int AS avg_ms,
                       COUNT(*) FILTER (WHERE escalated_from IS NOT NULL) AS escalated, COUNT(*) FILTER (WHERE outcome <> 'ok') AS not_ok
                  FROM {SCHEMA}.ai_route_log WHERE at > CURRENT_TIMESTAMP - make_interval(days => %s) GROUP BY path ORDER BY path""",
            (days,),
        )
        return [{k: (float(v) if k == "cost_usd" else v) for k, v in row.items()} for row in _rows(cur)]


# ------------------------------------------------------------------------------------------------- conversations


def title_from(text: str) -> str:
    words = re.sub(r"\s+", " ", text).strip().split(" ")
    title = " ".join(words[:9])
    title = title[:70].rstrip(" ,.;:-")
    return (title[:1].upper() + title[1:]) or "New conversation"


def create_conversation(user_id: int, title: str = "New conversation", category: str = "general") -> dict[str, Any]:
    category = category if category in CATEGORIES else "general"
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""INSERT INTO {SCHEMA}.ai_conversation (user_id, title, category) VALUES (%s, %s, %s)
                RETURNING id, title, category, summary, summarized_upto, created_timestamp, updated_timestamp""",
            (user_id, title[:120], category),
        )
        return _rows(cur)[0]


def list_conversations(user_id: int, q: str = "", category: str = "", limit: int = 80) -> list[dict[str, Any]]:
    where, params = ["c.user_id = %s"], [user_id]
    if category in CATEGORIES:
        where.append("c.category = %s")
        params.append(category)
    if q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append(f"(c.title ILIKE %s OR EXISTS (SELECT 1 FROM {SCHEMA}.ai_message m WHERE m.conversation_id = c.id AND m.text ILIKE %s))")
        params += [like, like]
    params.append(max(1, min(limit, 200)))
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT c.id, c.title, c.category, c.created_timestamp, c.updated_timestamp,
                       (SELECT left(m.text, 120) FROM {SCHEMA}.ai_message m WHERE m.conversation_id = c.id ORDER BY m.id DESC LIMIT 1) AS preview
                  FROM {SCHEMA}.ai_conversation c WHERE {' AND '.join(where)}
                 ORDER BY c.updated_timestamp DESC LIMIT %s""",
            params,
        )
        return _rows(cur)


def get_conversation(user_id: int, conversation_id: int) -> dict[str, Any] | None:
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT id, title, category, summary, summarized_upto, created_timestamp, updated_timestamp
                  FROM {SCHEMA}.ai_conversation WHERE id = %s AND user_id = %s""",
            (conversation_id, user_id),
        )
        rows = _rows(cur)
    return rows[0] if rows else None


def rename_conversation(user_id: int, conversation_id: int, title: str | None, category: str | None) -> bool:
    sets, params = [], []
    if title is not None:
        sets.append("title = %s")
        params.append(title.strip()[:120] or "Untitled")
    if category in CATEGORIES:
        sets.append("category = %s")
        params.append(category)
    if not sets:
        return get_conversation(user_id, conversation_id) is not None
    with db_cursor(commit=True) as cur:
        cur.execute(f"UPDATE {SCHEMA}.ai_conversation SET {', '.join(sets)} WHERE id = %s AND user_id = %s", (*params, conversation_id, user_id))
        return cur.rowcount > 0


def delete_conversation(user_id: int, conversation_id: int) -> bool:
    with db_cursor(commit=True) as cur:
        cur.execute(f"DELETE FROM {SCHEMA}.ai_conversation WHERE id = %s AND user_id = %s", (conversation_id, user_id))
        return cur.rowcount > 0


def delete_all_conversations(user_id: int) -> int:
    with db_cursor(commit=True) as cur:
        cur.execute(f"DELETE FROM {SCHEMA}.ai_conversation WHERE user_id = %s", (user_id,))
        return cur.rowcount


def touch(conversation_id: int) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(f"UPDATE {SCHEMA}.ai_conversation SET updated_timestamp = CURRENT_TIMESTAMP WHERE id = %s", (conversation_id,))


def set_summary(conversation_id: int, summary: str, upto: int) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE {SCHEMA}.ai_conversation SET summary = %s, summarized_upto = %s WHERE id = %s",
            (summary[:4000], upto, conversation_id),
        )


def mark_category(conversation_id: int, category: str) -> None:
    """Files a conversation under what it turned out to be about, if it is still just 'general'."""
    if category not in CATEGORIES:
        return
    with db_cursor(commit=True) as cur:
        cur.execute(f"UPDATE {SCHEMA}.ai_conversation SET category = %s WHERE id = %s AND category = 'general'", (category, conversation_id))


def set_title_if_new(conversation_id: int, title: str) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE {SCHEMA}.ai_conversation SET title = %s WHERE id = %s AND title = 'New conversation'",
            (title[:120], conversation_id),
        )


# ----------------------------------------------------------------------------------------------------- messages


def add_message(
    conversation_id: int,
    role: str,
    text: str,
    parts: list[dict[str, Any]] | None = None,
    *,
    context: dict[str, Any] | None = None,
    model: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> int:
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""INSERT INTO {SCHEMA}.ai_message (conversation_id, role, text, parts, context, model, tokens_in, tokens_out)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (conversation_id, role, text, Json(parts or []), Json(context) if context else None, model, tokens_in, tokens_out),
        )
        message_id = cur.fetchone()[0]
        cur.execute(f"UPDATE {SCHEMA}.ai_conversation SET updated_timestamp = CURRENT_TIMESTAMP WHERE id = %s", (conversation_id,))
    return message_id


def update_message(message_id: int, text: str, parts: list[dict[str, Any]]) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(f"UPDATE {SCHEMA}.ai_message SET text = %s, parts = %s WHERE id = %s", (text, Json(parts), message_id))


def list_messages(user_id: int, conversation_id: int) -> list[dict[str, Any]] | None:
    """The conversation's messages for the screen, or None when it is not this person's."""
    if get_conversation(user_id, conversation_id) is None:
        return None
    with db_cursor() as cur:
        cur.execute(
            f"SELECT id, role, text, parts, created_timestamp FROM {SCHEMA}.ai_message WHERE conversation_id = %s ORDER BY id",
            (conversation_id,),
        )
        return _rows(cur)


def history_rows(conversation_id: int) -> list[dict[str, Any]]:
    """Plain text of every message, oldest first, for building what the model is shown."""
    with db_cursor() as cur:
        cur.execute(f"SELECT id, role, text FROM {SCHEMA}.ai_message WHERE conversation_id = %s ORDER BY id", (conversation_id,))
        return _rows(cur)


def last_message_id(conversation_id: int) -> int:
    with db_cursor() as cur:
        cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {SCHEMA}.ai_message WHERE conversation_id = %s", (conversation_id,))
        return int(cur.fetchone()[0])


def delete_message(user_id: int, conversation_id: int, message_id: int) -> bool:
    if get_conversation(user_id, conversation_id) is None:
        return False
    with db_cursor(commit=True) as cur:
        cur.execute(f"DELETE FROM {SCHEMA}.ai_message WHERE id = %s AND conversation_id = %s", (message_id, conversation_id))
        return cur.rowcount > 0


# ------------------------------------------------------------------------------------------------------- audit


def audit(
    user_id: int | None,
    conversation_id: int | None,
    tool: str,
    kind: str,
    status: str,
    *,
    entity: str | None = None,
    args: dict[str, Any] | None = None,
    summary: str | None = None,
    confirmation_required: bool = False,
    confirmed_by_user: bool | None = None,
    duration_ms: int | None = None,
    error: str | None = None,
) -> int:
    """One line in the trail. Never raises: losing a log line must not stop the person's request."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                f"""INSERT INTO {SCHEMA}.ai_audit (user_id, conversation_id, tool, kind, status, entity, args, summary,
                        confirmation_required, confirmed_by_user, duration_ms, error)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (user_id, conversation_id, tool[:80], kind, status, entity, Json(args or {}), (summary or "")[:500], confirmation_required,
                 confirmed_by_user, duration_ms, (error or "")[:800] or None),
            )
            return cur.fetchone()[0]
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("Could not write an AI audit line")
        return 0


def list_audit(user_id: int | None, limit: int = 100) -> list[dict[str, Any]]:
    where, params = ("WHERE a.user_id = %s", [user_id]) if user_id is not None else ("", [])
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT a.id, a.at, a.user_id, u.username, a.conversation_id, a.tool, a.kind, a.status, a.entity, a.args, a.summary,
                       a.confirmation_required, a.confirmed_by_user, a.duration_ms
                  FROM {SCHEMA}.ai_audit a LEFT JOIN {SCHEMA}.app_user u ON u.id = a.user_id {where}
                 ORDER BY a.id DESC LIMIT %s""",
            (*params, max(1, min(limit, 500))),
        )
        return _rows(cur)


# --------------------------------------------------------------------------------------------- pending actions


def create_pending(user_id: int, conversation_id: int | None, tool: str, args: dict[str, Any], preview: dict[str, Any], risk: str) -> str:
    action_id = uuid.uuid4().hex
    expires = now() + timedelta(minutes=config.PENDING_ACTION_MINUTES)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""INSERT INTO {SCHEMA}.ai_pending_action (id, user_id, conversation_id, tool, args, preview, risk, expires_timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (action_id, user_id, conversation_id, tool, Json(args), Json(preview), risk, expires),
        )
    return action_id


def get_pending(user_id: int, action_id: str) -> dict[str, Any] | None:
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT id, user_id, conversation_id, tool, args, preview, risk, status, result, created_timestamp, expires_timestamp
                  FROM {SCHEMA}.ai_pending_action WHERE id = %s AND user_id = %s""",
            (action_id, user_id),
        )
        rows = _rows(cur)
    return rows[0] if rows else None


def claim_pending(user_id: int, action_id: str) -> dict[str, Any] | None:
    """Takes a pending action for execution, once. None when it is not this person's, not pending, or has expired."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""UPDATE {SCHEMA}.ai_pending_action SET status = 'confirmed', resolved_timestamp = CURRENT_TIMESTAMP
                 WHERE id = %s AND user_id = %s AND status = 'pending' AND expires_timestamp > CURRENT_TIMESTAMP
             RETURNING id, conversation_id, tool, args, preview, risk""",
            (action_id, user_id),
        )
        rows = _rows(cur)
    return rows[0] if rows else None


def resolve_pending(action_id: str, status: str, result: dict[str, Any] | None = None) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE {SCHEMA}.ai_pending_action SET status = %s, result = %s, resolved_timestamp = CURRENT_TIMESTAMP WHERE id = %s",
            (status, Json(result or {}), action_id),
        )


def cancel_pending(user_id: int, action_id: str) -> bool:
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""UPDATE {SCHEMA}.ai_pending_action SET status = 'cancelled', resolved_timestamp = CURRENT_TIMESTAMP
                 WHERE id = %s AND user_id = %s AND status = 'pending'""",
            (action_id, user_id),
        )
        return cur.rowcount > 0


def purge_expired() -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(f"UPDATE {SCHEMA}.ai_pending_action SET status = 'expired' WHERE status = 'pending' AND expires_timestamp <= CURRENT_TIMESTAMP")
        cur.execute(f"DELETE FROM {SCHEMA}.ai_file WHERE expires_timestamp <= CURRENT_TIMESTAMP")


# ------------------------------------------------------------------------------------------------------ files


def save_file(user_id: int, name: str, content_type: str, data: bytes) -> str:
    file_id = uuid.uuid4().hex
    expires = now() + timedelta(hours=config.FILE_LIFETIME_HOURS)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""INSERT INTO {SCHEMA}.ai_file (id, user_id, name, content_type, size_bytes, data, expires_timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (file_id, user_id, name[:150], content_type, len(data), data, expires),
        )
    return file_id


def get_file(user_id: int, file_id: str) -> dict[str, Any] | None:
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT name, content_type, data, size_bytes FROM {SCHEMA}.ai_file
                 WHERE id = %s AND user_id = %s AND expires_timestamp > CURRENT_TIMESTAMP""",
            (file_id, user_id),
        )
        row = cur.fetchone()
    return {"name": row[0], "content_type": row[1], "data": bytes(row[2]), "size_bytes": row[3]} if row else None


# ------------------------------------------------------------------------------------------------------ tasks


def create_task(user_id: int, kind: str, title: str, note: str | None, due_at: datetime | None, link: str | None, conversation_id: int | None) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""INSERT INTO {SCHEMA}.ai_task (user_id, kind, title, note, due_at, link, conversation_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
             RETURNING id, kind, title, note, due_at, status, link, created_timestamp""",
            (user_id, kind, title[:200], (note or "")[:1000] or None, due_at, link, conversation_id),
        )
        return _rows(cur)[0]


def list_tasks(user_id: int, status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT id, kind, title, note, due_at, status, link, created_timestamp, completed_timestamp
                  FROM {SCHEMA}.ai_task WHERE user_id = %s AND (%s = 'all' OR status = %s)
                 ORDER BY (due_at IS NULL), due_at, id DESC LIMIT %s""",
            (user_id, status, status, limit),
        )
        return _rows(cur)


def update_task(user_id: int, task_id: int, status: str) -> bool:
    if status not in ("open", "done", "dismissed"):
        return False
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""UPDATE {SCHEMA}.ai_task SET status = %s,
                       completed_timestamp = CASE WHEN %s = 'open' THEN NULL ELSE CURRENT_TIMESTAMP END
                 WHERE id = %s AND user_id = %s""",
            (status, status, task_id, user_id),
        )
        return cur.rowcount > 0


def due_tasks(user_id: int) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT id, kind, title, note, due_at, link FROM {SCHEMA}.ai_task
                 WHERE user_id = %s AND status = 'open' AND due_at IS NOT NULL AND due_at <= CURRENT_TIMESTAMP + interval '5 minutes'
                 ORDER BY due_at LIMIT 20""",
            (user_id,),
        )
        return _rows(cur)


# --------------------------------------------------------------------------------------------------- insights


def hidden_insights(user_id: int) -> set[str]:
    with db_cursor() as cur:
        cur.execute(f"SELECT insight_id FROM {SCHEMA}.ai_insight_state WHERE user_id = %s AND hidden_until > CURRENT_TIMESTAMP", (user_id,))
        return {row[0] for row in cur.fetchall()}


def hide_insight(user_id: int, insight_id: str, days: int) -> None:
    until = now() + timedelta(days=max(1, min(days, 365)))
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""INSERT INTO {SCHEMA}.ai_insight_state (user_id, insight_id, hidden_until) VALUES (%s, %s, %s)
                ON CONFLICT (user_id, insight_id) DO UPDATE SET hidden_until = EXCLUDED.hidden_until""",
            (user_id, insight_id[:80], until),
        )


# ------------------------------------------------------------------------------------------------------- usage


def add_usage(user_id: int, *, requests: int = 0, tool_calls: int = 0, tokens_in: int = 0, tokens_out: int = 0) -> None:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                f"""INSERT INTO {SCHEMA}.ai_usage (user_id, day, requests, tool_calls, tokens_in, tokens_out)
                    VALUES (%s, CURRENT_DATE, %s, %s, %s, %s)
                    ON CONFLICT (user_id, day) DO UPDATE SET requests = {SCHEMA}.ai_usage.requests + EXCLUDED.requests,
                        tool_calls = {SCHEMA}.ai_usage.tool_calls + EXCLUDED.tool_calls,
                        tokens_in = {SCHEMA}.ai_usage.tokens_in + EXCLUDED.tokens_in,
                        tokens_out = {SCHEMA}.ai_usage.tokens_out + EXCLUDED.tokens_out""",
                (user_id, requests, tool_calls, tokens_in, tokens_out),
            )
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("Could not record AI usage")


def usage_today(user_id: int) -> dict[str, int]:
    with db_cursor() as cur:
        cur.execute(
            f"SELECT requests, tool_calls, tokens_in, tokens_out FROM {SCHEMA}.ai_usage WHERE user_id = %s AND day = CURRENT_DATE",
            (user_id,),
        )
        row = cur.fetchone()
    return {"requests": row[0], "tool_calls": row[1], "tokens_in": int(row[2]), "tokens_out": int(row[3])} if row else {"requests": 0, "tool_calls": 0, "tokens_in": 0, "tokens_out": 0}


def usage_overview(days: int = 7) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT u.day, COUNT(DISTINCT u.user_id) AS people, SUM(u.requests) AS requests, SUM(u.tool_calls) AS tool_calls,
                       SUM(u.tokens_in) AS tokens_in, SUM(u.tokens_out) AS tokens_out
                  FROM {SCHEMA}.ai_usage u WHERE u.day > CURRENT_DATE - %s GROUP BY u.day ORDER BY u.day DESC""",
            (days,),
        )
        return _rows(cur)


def today() -> date:
    return date.today()


def dumps(value: Any) -> str:
    return json.dumps(value, default=str)
