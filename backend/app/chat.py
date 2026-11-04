"""Direct messages between two people: conversations, messages, attachments, replies, reactions, pins and read state.

Every function that takes a ``user_id`` checks that this person is one of the two members of the conversation the message or
conversation belongs to, on the server, from the ids in the database. A message id from the browser is never trusted to say
which conversation it is in. A person can only change or delete their own messages.

Errors are ``ChatError`` subclasses so the router can answer 404 (``NotFound``), 403 (``Forbidden``), 429 (``RateLimited``) or
400 (anything else) without looking at a message's wording. What is said in a message is never written to a log.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Optional

from fastapi import WebSocket

from app.auth import APP_USER_TABLE, fetch_user_by_id
from app.chat_media import media_path, unlink_media, write_prepared
from app.database import db_cursor

log = logging.getLogger(__name__)

CHAT_TABLE = "orion_ods.direct_chat"
MESSAGE_TABLE = "orion_ods.chat_message"
READ_TABLE = "orion_ods.chat_read"
ATTACHMENT_TABLE = "orion_ods.chat_attachment"
REACTION_TABLE = "orion_ods.chat_reaction"
PIN_TABLE = "orion_ods.chat_pin"
SETTING_TABLE = "orion_ods.chat_member_setting"
CALL_TABLE = "orion_ods.chat_call"
MEMBER_TABLE = "orion_ods.chat_member"

MAX_BODY = 4000
PAGE = 40
MAX_PAGE = 100
MAX_PINS = 10
MAX_REACTIONS_PER_PERSON = 6
SNIPPET = 140
WAVEFORM_BARS = 64
MAX_AUDIO_MS = 10 * 60 * 1000
SEARCH_MIN, SEARCH_MAX = 2, 100
MAX_GROUP = 50
MAX_TITLE = 60


class ChatError(ValueError):
    """Something a person did that cannot be done, in words they can be shown."""


class NotFound(ChatError):
    pass


class Forbidden(ChatError):
    pass


class RateLimited(ChatError):
    pass


# --------------------------------------------------------------------------------------------------------- rate limits


class _Windows:
    """A sliding window per person and kind of action, in this process. Enough to stop a runaway client or a script."""

    def __init__(self) -> None:
        self._hits: dict[tuple[int, str], deque[float]] = defaultdict(deque)

    def take(self, user_id: int, kind: str, limit: int, seconds: float) -> None:
        now = time.monotonic()
        hits = self._hits[(user_id, kind)]
        while hits and now - hits[0] > seconds:
            hits.popleft()
        if len(hits) >= limit:
            raise RateLimited("You are doing that too quickly. Wait a moment and try again.")
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()


limits = _Windows()


# -------------------------------------------------------------------------------------------------------------- schema

DDL = (
    f"""
    CREATE TABLE IF NOT EXISTS {CHAT_TABLE} (
        id SERIAL PRIMARY KEY,
        user_low INTEGER NOT NULL REFERENCES {APP_USER_TABLE}(id) ON DELETE CASCADE,
        user_high INTEGER NOT NULL REFERENCES {APP_USER_TABLE}(id) ON DELETE CASCADE,
        created_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CHECK (user_low < user_high),
        UNIQUE (user_low, user_high)
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {MESSAGE_TABLE} (
        id SERIAL PRIMARY KEY,
        chat_id INTEGER NOT NULL REFERENCES {CHAT_TABLE}(id) ON DELETE CASCADE,
        sender_id INTEGER NOT NULL REFERENCES {APP_USER_TABLE}(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        created_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    f"CREATE INDEX IF NOT EXISTS chat_message_chat_id_id_idx ON {MESSAGE_TABLE} (chat_id, id)",
    f"""
    CREATE TABLE IF NOT EXISTS {READ_TABLE} (
        chat_id INTEGER NOT NULL REFERENCES {CHAT_TABLE}(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES {APP_USER_TABLE}(id) ON DELETE CASCADE,
        last_read_id INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (chat_id, user_id)
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {ATTACHMENT_TABLE} (
        message_id INTEGER PRIMARY KEY REFERENCES {MESSAGE_TABLE}(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        ext TEXT NOT NULL,
        original_name TEXT NOT NULL,
        content_type TEXT NOT NULL,
        byte_size INTEGER NOT NULL DEFAULT 0
    )
    """,
)


def ensure_chat_tables() -> None:
    """Creates the base chat tables when missing. Everything added since is in migrate_chat.sql (applied at startup by
    entities.ensure_bill_table as the database owner, because this role does not own the tables). A failure is logged."""
    for statement in DDL:
        try:
            with db_cursor(commit=True) as cur:
                cur.execute(statement)
        except Exception as exc:  # noqa: BLE001
            owner = "must be owner" in str(exc).lower() or "permission denied" in str(exc).lower()
            # Not owning a table that already exists is expected and harmless; anything else is worth knowing.
            (log.debug if owner else log.warning)("Could not apply chat schema statement (%s): %s", " ".join(statement.split())[:70], exc)


# ------------------------------------------------------------------------------------------------------------ payloads


def _pair(user_id: int, other_id: int) -> tuple[int, int]:
    return (user_id, other_id) if user_id < other_id else (other_id, user_id)


def _ts(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def peer_payload(row: dict, online: bool = False) -> dict:
    version = int(row.get("avatar_version") or 0)
    ext = row.get("avatar_ext") or "jpg"
    has_avatar = version > 0
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "username": row["username"],
        "role": row.get("role"),
        "has_avatar": has_avatar,
        "avatar_version": version,
        "avatar_url": f"/api/media/avatars/{row['id']}.{ext}?v={version or 1}" if has_avatar else None,
        "online": online,
    }


MESSAGE_SELECT = f"""
    SELECT m.id, m.chat_id, m.sender_id, m.body, m.created_timestamp, m.edited_timestamp, m.deleted_timestamp,
           m.forwarded, m.client_id, m.reply_to_id,
           a.kind AS media_kind, a.ext AS media_ext, a.original_name AS media_name,
           a.content_type AS media_type, a.byte_size AS media_size, a.duration_ms AS media_duration_ms, a.waveform AS media_waveform,
           su.display_name AS sender_name,
           m.system, m.call_id, k.kind AS call_kind, k.outcome AS call_outcome, k.caller_id AS call_caller_id,
           CASE WHEN k.answered_timestamp IS NOT NULL AND k.ended_timestamp IS NOT NULL
                THEN GREATEST(0, EXTRACT(EPOCH FROM (k.ended_timestamp - k.answered_timestamp))::int) END AS call_seconds,
           p.sender_id AS reply_sender_id, p.body AS reply_body, p.deleted_timestamp AS reply_deleted,
           pa.kind AS reply_media_kind, pa.original_name AS reply_media_name
    FROM {MESSAGE_TABLE} m
    LEFT JOIN {ATTACHMENT_TABLE} a ON a.message_id = m.id
    LEFT JOIN {CALL_TABLE} k ON k.id = m.call_id
    LEFT JOIN {APP_USER_TABLE} su ON su.id = m.sender_id
    LEFT JOIN {MESSAGE_TABLE} p ON p.id = m.reply_to_id
    LEFT JOIN {ATTACHMENT_TABLE} pa ON pa.message_id = p.id
"""


def _snippet(text: str) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= SNIPPET else flat[: SNIPPET - 1] + "…"


def _waveform(text: Optional[str]) -> list[int]:
    """The loudness picture stored with a voice note, as a short list of whole numbers (nothing else ever reaches a page)."""
    if not text:
        return []
    out: list[int] = []
    for part in text.split(",")[:WAVEFORM_BARS]:
        try:
            out.append(max(0, min(100, int(part))))
        except ValueError:
            return []
    return out


def clean_waveform(raw: Any) -> Optional[str]:
    """A waveform sent with a voice note, kept only when it is up to 64 whole numbers from 0 to 100."""
    if not raw:
        return None
    values = _waveform(str(raw)[:400])
    return ",".join(str(v) for v in values) if values else None


def _message_payload(row: dict, reactions: Optional[list[dict]] = None) -> dict:
    deleted = row.get("deleted_timestamp") is not None
    kind = None if deleted else row.get("media_kind")
    message_id = row["id"]
    reply = None
    if row.get("reply_to_id"):
        gone = row.get("reply_deleted") is not None or row.get("reply_sender_id") is None
        reply = {
            "id": row["reply_to_id"],
            "sender_id": row.get("reply_sender_id"),
            "body": "" if gone else _snippet(row.get("reply_body") or ""),
            "media_kind": None if gone else row.get("reply_media_kind"),
            "media_name": None if gone else row.get("reply_media_name"),
            "deleted": bool(gone),
        }
    return {
        "id": message_id,
        "chat_id": row["chat_id"],
        "sender_id": row["sender_id"],
        "body": "" if deleted else (row["body"] or ""),
        "created_timestamp": _ts(row["created_timestamp"]),
        "edited_timestamp": None if deleted else _ts(row.get("edited_timestamp")),
        "deleted": deleted,
        "forwarded": bool(row.get("forwarded")) and not deleted,
        "system": bool(row.get("system")),
        "sender_name": row.get("sender_name"),
        "client_id": row.get("client_id"),
        "reply_to": reply,
        "media_kind": kind,
        "media_name": None if deleted else row.get("media_name"),
        "media_url": f"/api/messages/media/{message_id}" if kind else None,
        "media_size": None if deleted else row.get("media_size"),
        "media_duration_ms": None if deleted or kind != "audio" else row.get("media_duration_ms"),
        "media_waveform": [] if deleted or kind != "audio" else _waveform(row.get("media_waveform")),
        "call": None
        if not row.get("call_id")
        else {
            "id": row["call_id"],
            "kind": row.get("call_kind"),
            "outcome": row.get("call_outcome"),
            "caller_id": row.get("call_caller_id"),
            "seconds": row.get("call_seconds"),
        },
        "reactions": [] if deleted else (reactions or []),
    }


def _reactions_for(cur, message_ids: list[int]) -> dict[int, list[dict]]:
    if not message_ids:
        return {}
    cur.execute(
        f"""
        SELECT message_id, emoji, user_id FROM {REACTION_TABLE}
        WHERE message_id = ANY(%s) ORDER BY created_timestamp, user_id
        """,
        (message_ids,),
    )
    grouped: dict[int, dict[str, list[int]]] = {}
    for message_id, emoji, user_id in cur.fetchall():
        grouped.setdefault(message_id, {}).setdefault(emoji, []).append(user_id)
    return {mid: [{"emoji": e, "user_ids": ids} for e, ids in by.items()] for mid, by in grouped.items()}


def _payloads(cur) -> list[dict]:
    """The messages the cursor just selected (with ``MESSAGE_SELECT``), with their reactions, in the order selected."""
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    reactions = _reactions_for(cur, [r["id"] for r in rows])
    return [_message_payload(r, reactions.get(r["id"])) for r in rows]


def _fetch_message(message_id: int) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute(f"{MESSAGE_SELECT} WHERE m.id = %s", (message_id,))
        found = _payloads(cur)
    return found[0] if found else None


# --------------------------------------------------------------------------------------------------------- membership


def _membership(chat_id: int, user_id: int) -> tuple[str, list[int]]:
    """What kind of conversation this is and everybody else in it, or ``NotFound`` when this person is not in it (or there is no such one)."""
    with db_cursor() as cur:
        cur.execute(f"SELECT kind, user_low, user_high FROM {CHAT_TABLE} WHERE id = %s", (chat_id,))
        row = cur.fetchone()
        if not row:
            raise NotFound("Chat not found.")
        if row[0] == "group":
            cur.execute(f"SELECT user_id FROM {MEMBER_TABLE} WHERE chat_id = %s", (chat_id,))
            members = [r[0] for r in cur.fetchall()]
            if user_id not in members:
                raise NotFound("Chat not found.")
            return "group", [m for m in members if m != user_id]
    if user_id not in (row[1], row[2]):
        raise NotFound("Chat not found.")
    return "direct", [row[2] if row[1] == user_id else row[1]]


def _assert_member(chat_id: int, user_id: int) -> list[int]:
    """The other people in the conversation (one in a direct one), or ``NotFound`` when this person is not in it."""
    return _membership(chat_id, user_id)[1]


def _direct_peer(chat_id: int, user_id: int) -> int:
    """The other person of a one-to-one conversation. Calls and AI help are only for those."""
    kind, others = _membership(chat_id, user_id)
    if kind != "direct":
        raise ChatError("That is only for one-to-one conversations.")
    return others[0]


def _message_chat(message_id: int) -> dict:
    """The facts about a message that decide who may touch it, from the database."""
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT m.id, m.chat_id, m.sender_id, m.deleted_timestamp, m.body,
                   EXISTS (SELECT 1 FROM {ATTACHMENT_TABLE} a WHERE a.message_id = m.id) AS has_media,
                   (m.call_id IS NOT NULL OR m.system) AS is_call
            FROM {MESSAGE_TABLE} m WHERE m.id = %s
            """,
            (message_id,),
        )
        row = cur.fetchone()
    if not row:
        raise NotFound("Message not found.")
    return {"id": row[0], "chat_id": row[1], "sender_id": row[2], "deleted": row[3] is not None, "body": row[4], "has_media": row[5], "is_call": row[6]}


def _member_message(message_id: int, user_id: int) -> tuple[dict, list[int]]:
    """A message and the other people in its conversation, for someone who is in that conversation."""
    info = _message_chat(message_id)
    others = _assert_member(info["chat_id"], user_id)
    return info, others


# ------------------------------------------------------------------------------------------------------------ people


def list_directory(user_id: int, online_ids: set[int]):
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, username, display_name, role, avatar_ext, avatar_version
            FROM {APP_USER_TABLE}
            WHERE is_active = TRUE AND id <> %s
            ORDER BY display_name
            """,
            (user_id,),
        )
        cols = [d[0] for d in cur.description]
        return [peer_payload(dict(zip(cols, row)), row[0] in online_ids) for row in cur.fetchall()]


def get_or_create_chat(user_id: int, other_id: int) -> dict:
    if user_id == other_id:
        raise ChatError("You cannot message yourself.")
    other = fetch_user_by_id(other_id)
    if not other or not other.get("is_active"):
        raise ChatError("That person is not available.")
    low, high = _pair(user_id, other_id)
    with db_cursor(commit=True) as cur:
        cur.execute(f"SELECT id FROM {CHAT_TABLE} WHERE user_low = %s AND user_high = %s", (low, high))
        row = cur.fetchone()
        if row:
            chat_id = row[0]
        else:
            cur.execute(f"INSERT INTO {CHAT_TABLE} (user_low, user_high) VALUES (%s, %s) RETURNING id", (low, high))
            chat_id = cur.fetchone()[0]
        for member in (user_id, other_id):
            cur.execute(
                f"INSERT INTO {READ_TABLE} (chat_id, user_id, last_read_id) VALUES (%s, %s, 0) ON CONFLICT (chat_id, user_id) DO NOTHING",
                (chat_id, member),
            )
    return chat_summary(chat_id, user_id, set())


# ------------------------------------------------------------------------------------------------------ conversations

_SUMMARY_SQL = f"""
    SELECT c.id,
           CASE WHEN c.kind = 'direct' THEN (CASE WHEN c.user_low = %(u)s THEN c.user_high ELSE c.user_low END) END AS peer_id,
           COALESCE(s.pinned, FALSE), COALESCE(s.muted, FALSE), COALESCE(s.archived, FALSE),
           COALESCE(r.last_read_id, 0), COALESCE(pr.last_read_id, 0),
           (SELECT COUNT(*) FROM {MESSAGE_TABLE} m
             WHERE m.chat_id = c.id AND m.id > COALESCE(r.last_read_id, 0)
               AND m.sender_id <> %(u)s AND m.deleted_timestamp IS NULL AND NOT m.system) AS unread,
           (SELECT MAX(m.id) FROM {MESSAGE_TABLE} m WHERE m.chat_id = c.id) AS last_id,
           c.kind, c.title, c.created_by
    FROM {CHAT_TABLE} c
    LEFT JOIN {SETTING_TABLE} s ON s.chat_id = c.id AND s.user_id = %(u)s
    LEFT JOIN {READ_TABLE} r ON r.chat_id = c.id AND r.user_id = %(u)s
    LEFT JOIN {READ_TABLE} pr ON pr.chat_id = c.id AND c.kind = 'direct'
         AND pr.user_id = CASE WHEN c.user_low = %(u)s THEN c.user_high ELSE c.user_low END
    WHERE (c.kind = 'direct' AND (c.user_low = %(u)s OR c.user_high = %(u)s))
       OR (c.kind = 'group' AND EXISTS (SELECT 1 FROM {MEMBER_TABLE} cm WHERE cm.chat_id = c.id AND cm.user_id = %(u)s))
"""


def _summaries(user_id: int, online_ids: set[int], chat_id: Optional[int] = None) -> list[dict]:
    # the membership test above is an OR: wrapped so that asking for one conversation is "that one AND (mine)"
    sql = f"SELECT * FROM ({_SUMMARY_SQL}) mine" + (" WHERE id = %(chat)s" if chat_id else "")
    with db_cursor() as cur:
        cur.execute(sql, {"u": user_id, "chat": chat_id})
        rows = cur.fetchall()
        if not rows:
            return []
        group_ids = [row[0] for row in rows if row[9] == "group"]
        members: dict[int, list[dict]] = {}
        if group_ids:
            cur.execute(
                f"""
                SELECT cm.chat_id, u.id, u.username, u.display_name, u.role, u.avatar_ext, u.avatar_version, cm.role AS group_role,
                       COALESCE(r.last_read_id, 0) AS last_read_id
                FROM {MEMBER_TABLE} cm
                JOIN {APP_USER_TABLE} u ON u.id = cm.user_id
                LEFT JOIN {READ_TABLE} r ON r.chat_id = cm.chat_id AND r.user_id = cm.user_id
                WHERE cm.chat_id = ANY(%s) ORDER BY cm.joined_timestamp, u.display_name
                """,
                (group_ids,),
            )
            cols = [d[0] for d in cur.description]
            for found in (dict(zip(cols, r)) for r in cur.fetchall()):
                members.setdefault(found["chat_id"], []).append(
                    {**peer_payload(found, found["id"] in online_ids), "group_role": found["group_role"], "last_read_id": found["last_read_id"], "_self": found["id"] == user_id}
                )
        peer_ids = list({row[1] for row in rows if row[1]})
        peers: dict[int, dict] = {}
        if peer_ids:
            cur.execute(
                f"SELECT id, username, display_name, role, avatar_ext, avatar_version, is_active FROM {APP_USER_TABLE} WHERE id = ANY(%s)",
                (peer_ids,),
            )
            cols = [d[0] for d in cur.description]
            peers = {r["id"]: r for r in (dict(zip(cols, row)) for row in cur.fetchall())}
        last_ids = [row[8] for row in rows if row[8]]
        last: dict[int, dict] = {}
        if last_ids:
            cur.execute(f"{MESSAGE_SELECT} WHERE m.id = ANY(%s)", (last_ids,))
            last = {m["id"]: m for m in _payloads(cur)}
    out = []
    for cid, peer_id, pinned, muted, archived, my_read, peer_read, unread, last_id, kind, title, created_by in rows:
        entry = {
            "id": cid,
            "kind": kind,
            "title": title if kind == "group" else None,
            "peer": None,
            "members": [],
            "my_role": None,
            "created_by": created_by if kind == "group" else None,
            "last_message": last.get(last_id),
            "unread": int(unread or 0),
            "settings": {"pinned": bool(pinned), "muted": bool(muted), "archived": bool(archived)},
            "my_last_read_id": my_read,
            "peer_last_read_id": peer_read,
        }
        if kind == "group":
            people = members.get(cid, [])
            others_read = [m["last_read_id"] for m in people if not m["_self"]]
            # A message in a group is "read" for its sender when everybody else has read it.
            entry["peer_last_read_id"] = min(others_read) if others_read else 0
            entry["my_role"] = next((m["group_role"] for m in people if m["_self"]), None)
            entry["members"] = [{k: v for k, v in m.items() if not k.startswith("_")} for m in people]
        else:
            peer = peers.get(peer_id)
            entry["peer"] = peer_payload(peer, peer_id in online_ids) if peer else None
        out.append(entry)
    return out


def chat_summary(chat_id: int, user_id: int, online_ids: set[int]) -> dict:
    _assert_member(chat_id, user_id)
    found = _summaries(user_id, online_ids, chat_id)
    if not found:
        raise NotFound("Chat not found.")
    return found[0]


def list_chats(user_id: int, online_ids: set[int]) -> list[dict]:
    chats = [c for c in _summaries(user_id, online_ids) if c["last_message"]]
    chats.sort(key=lambda c: c["last_message"]["created_timestamp"] or "", reverse=True)
    return chats


def get_thread(chat_id: int, user_id: int, online_ids: set[int]) -> dict:
    """The conversation, its newest page of messages, whether there are older ones, and what is pinned."""
    summary = chat_summary(chat_id, user_id, online_ids)
    page = list_messages(chat_id, user_id)
    return {**summary, **page, "pins": list_pins(chat_id, user_id)}


# -------------------------------------------------------------------------------------------------------------- reading


def list_messages(chat_id: int, user_id: int, after_id: int = 0, before_id: int = 0, limit: int = PAGE) -> dict:
    """A page of messages, oldest first. ``before_id`` pages back through history; ``after_id`` catches up after a gap."""
    _assert_member(chat_id, user_id)
    limit = max(1, min(int(limit or PAGE), MAX_PAGE))
    with db_cursor() as cur:
        if after_id:
            cur.execute(
                f"{MESSAGE_SELECT} WHERE m.chat_id = %s AND m.id > %s ORDER BY m.id LIMIT %s",
                (chat_id, after_id, 500),
            )
            return {"messages": _payloads(cur), "has_more": False}
        if before_id:
            cur.execute(
                f"{MESSAGE_SELECT} WHERE m.chat_id = %s AND m.id < %s ORDER BY m.id DESC LIMIT %s",
                (chat_id, before_id, limit + 1),
            )
        else:
            cur.execute(f"{MESSAGE_SELECT} WHERE m.chat_id = %s ORDER BY m.id DESC LIMIT %s", (chat_id, limit + 1))
        found = _payloads(cur)
    has_more = len(found) > limit
    found = found[:limit]
    found.reverse()
    return {"messages": found, "has_more": has_more}


def messages_around(chat_id: int, user_id: int, message_id: int, span: int = 20) -> dict:
    """The messages either side of one, to land on a search result or a pinned message that is not loaded."""
    _assert_member(chat_id, user_id)
    with db_cursor() as cur:
        cur.execute(f"SELECT 1 FROM {MESSAGE_TABLE} WHERE id = %s AND chat_id = %s", (message_id, chat_id))
        if not cur.fetchone():
            raise NotFound("Message not found.")
        cur.execute(
            f"""
            (SELECT id FROM {MESSAGE_TABLE} WHERE chat_id = %s AND id <= %s ORDER BY id DESC LIMIT %s)
            UNION
            (SELECT id FROM {MESSAGE_TABLE} WHERE chat_id = %s AND id > %s ORDER BY id LIMIT %s)
            """,
            (chat_id, message_id, span + 1, chat_id, message_id, span),
        )
        ids = [row[0] for row in cur.fetchall()]
        cur.execute(f"{MESSAGE_SELECT} WHERE m.id = ANY(%s) ORDER BY m.id", (ids,))
        found = _payloads(cur)
        newest = found[-1]["id"] if found else 0
        cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {MESSAGE_TABLE} WHERE chat_id = %s", (chat_id,))
        latest = cur.fetchone()[0]
        oldest = found[0]["id"] if found else 0
        cur.execute(f"SELECT EXISTS (SELECT 1 FROM {MESSAGE_TABLE} WHERE chat_id = %s AND id < %s)", (chat_id, oldest))
        older = cur.fetchone()[0]
    return {"messages": found, "has_more": bool(older), "reaches_latest": newest >= latest}


def search_messages(user_id: int, query: str, chat_id: Optional[int] = None, limit: int = 30) -> list[dict]:
    """Messages containing the text, only in conversations this person is in, newest first."""
    text = " ".join((query or "").split())
    if len(text) < SEARCH_MIN:
        raise ChatError(f"Type at least {SEARCH_MIN} characters to search.")
    if len(text) > SEARCH_MAX:
        raise ChatError("That search is too long.")
    limits.take(user_id, "search", 20, 30)
    if chat_id:
        _assert_member(chat_id, user_id)
    like = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT m.id, m.chat_id, m.sender_id, m.body, m.created_timestamp
            FROM {MESSAGE_TABLE} m
            JOIN {CHAT_TABLE} c ON c.id = m.chat_id
              AND (c.user_low = %s OR c.user_high = %s
                   OR (c.kind = 'group' AND EXISTS (SELECT 1 FROM {MEMBER_TABLE} cm WHERE cm.chat_id = c.id AND cm.user_id = %s)))
            WHERE m.deleted_timestamp IS NULL AND NOT m.system AND m.body ILIKE %s ESCAPE '\\'
              AND (%s::int IS NULL OR m.chat_id = %s::int)
            ORDER BY m.id DESC LIMIT %s
            """,
            (user_id, user_id, user_id, like, chat_id, chat_id, max(1, min(limit, 50))),
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "chat_id": r[1], "sender_id": r[2], "snippet": _snippet(r[3]), "created_timestamp": _ts(r[4])}
        for r in rows
    ]


def shared_media(chat_id: int, user_id: int, kind: Optional[str] = None, limit: int = 60) -> list[dict]:
    _assert_member(chat_id, user_id)
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT m.id, m.sender_id, m.created_timestamp, a.kind, a.original_name, a.byte_size
            FROM {ATTACHMENT_TABLE} a JOIN {MESSAGE_TABLE} m ON m.id = a.message_id
            WHERE m.chat_id = %s AND m.deleted_timestamp IS NULL AND (%s::text IS NULL OR a.kind = %s::text)
            ORDER BY m.id DESC LIMIT %s
            """,
            (chat_id, kind, kind, max(1, min(limit, 200))),
        )
        rows = cur.fetchall()
    return [
        {"message_id": r[0], "sender_id": r[1], "created_timestamp": _ts(r[2]), "kind": r[3], "name": r[4], "size": r[5], "url": f"/api/messages/media/{r[0]}"}
        for r in rows
    ]


# ------------------------------------------------------------------------------------------------------------- writing


def _clean_body(body: Optional[str]) -> str:
    text = (body or "").replace("\x00", "").replace("\r\n", "\n").strip()
    if len(text) > MAX_BODY:
        raise ChatError("Message is too long.")
    return text


def send_message(
    chat_id: int,
    sender_id: int,
    body: str,
    media: Optional[dict] = None,
    *,
    reply_to: Optional[int] = None,
    client_id: Optional[str] = None,
    forwarded: bool = False,
) -> dict:
    text = _clean_body(body)
    if not text and not media:
        raise ChatError("Type a message or attach a file.")
    others = _assert_member(chat_id, sender_id)
    client_id = (client_id or "").strip()[:64] or None
    if client_id:
        # The same send arriving twice (a retry after a dropped connection) is the same message, not a second one.
        with db_cursor() as cur:
            cur.execute(
                f"SELECT id FROM {MESSAGE_TABLE} WHERE chat_id = %s AND sender_id = %s AND client_id = %s",
                (chat_id, sender_id, client_id),
            )
            existing = cur.fetchone()
        if existing:
            payload = _fetch_message(existing[0]) or {}
            payload["other_ids"] = others
            payload["duplicate"] = True
            return payload
    limits.take(sender_id, "send", 40, 60)
    if reply_to:
        with db_cursor() as cur:
            cur.execute(f"SELECT 1 FROM {MESSAGE_TABLE} WHERE id = %s AND chat_id = %s", (reply_to, chat_id))
            if not cur.fetchone():
                raise ChatError("The message you are replying to is not in this chat.")
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            INSERT INTO {MESSAGE_TABLE} (chat_id, sender_id, body, reply_to_id, client_id, forwarded)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (chat_id, sender_id, text, reply_to or None, client_id, forwarded),
        )
        message_id = cur.fetchone()[0]
        if media:
            write_prepared(message_id, media)
            cur.execute(
                f"""
                INSERT INTO {ATTACHMENT_TABLE} (message_id, kind, ext, original_name, content_type, byte_size, duration_ms, waveform)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message_id, media["kind"], media["ext"], media["original_name"], media["content_type"], len(media["data"]),
                    media.get("duration_ms"), media.get("waveform"),
                ),
            )
        cur.execute(
            f"""
            INSERT INTO {READ_TABLE} (chat_id, user_id, last_read_id) VALUES (%s, %s, %s)
            ON CONFLICT (chat_id, user_id) DO UPDATE SET last_read_id = EXCLUDED.last_read_id
            """,
            (chat_id, sender_id, message_id),
        )
        # A new message brings an archived conversation back for both of them.
        cur.execute(f"UPDATE {SETTING_TABLE} SET archived = FALSE WHERE chat_id = %s AND archived", (chat_id,))
    payload = _fetch_message(message_id) or {"id": message_id, "chat_id": chat_id, "sender_id": sender_id, "body": text}
    payload["other_ids"] = others
    return payload


def add_system_message(chat_id: int, actor_id: int, text: str) -> dict:
    """A line of the conversation that nobody wrote ("Priya added Rahul"). It is read by its actor, never counts as unread for anyone,
    and cannot be edited, deleted, forwarded, reacted to or pinned. Only the group rules (``chat_groups``) call this."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"INSERT INTO {MESSAGE_TABLE} (chat_id, sender_id, body, system) VALUES (%s, %s, %s, TRUE) RETURNING id",
            (chat_id, actor_id, text[:300]),
        )
        message_id = cur.fetchone()[0]
        # Someone who has just left or been removed is no longer in the group, so there is no read position to keep for them.
        cur.execute(
            f"""
            INSERT INTO {READ_TABLE} (chat_id, user_id, last_read_id)
            SELECT %s, %s, %s WHERE EXISTS (SELECT 1 FROM {MEMBER_TABLE} WHERE chat_id = %s AND user_id = %s)
            ON CONFLICT (chat_id, user_id) DO UPDATE SET last_read_id = GREATEST({READ_TABLE}.last_read_id, EXCLUDED.last_read_id)
            """,
            (chat_id, actor_id, message_id, chat_id, actor_id),
        )
        cur.execute(f"SELECT user_id FROM {MEMBER_TABLE} WHERE chat_id = %s AND user_id <> %s", (chat_id, actor_id))
        others = [r[0] for r in cur.fetchall()]
    payload = _fetch_message(message_id) or {"id": message_id, "chat_id": chat_id, "sender_id": actor_id, "body": text, "system": True}
    payload["other_ids"] = others
    return payload


def add_call_message(chat_id: int, caller_id: int, call_id: int, *, seen_by_other: bool) -> dict:
    """The line a finished call leaves in its conversation (sent by whoever called). A call that was answered or turned down is
    already known to the other person, so it is not counted as unread for them; a missed one is."""
    other_id = _direct_peer(chat_id, caller_id)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"INSERT INTO {MESSAGE_TABLE} (chat_id, sender_id, body, call_id) VALUES (%s, %s, '', %s) RETURNING id",
            (chat_id, caller_id, call_id),
        )
        message_id = cur.fetchone()[0]
        for who in (caller_id, other_id) if seen_by_other else (caller_id,):
            cur.execute(
                f"""
                INSERT INTO {READ_TABLE} (chat_id, user_id, last_read_id) VALUES (%s, %s, %s)
                ON CONFLICT (chat_id, user_id) DO UPDATE SET last_read_id = GREATEST({READ_TABLE}.last_read_id, EXCLUDED.last_read_id)
                """,
                (chat_id, who, message_id),
            )
        cur.execute(f"UPDATE {SETTING_TABLE} SET archived = FALSE WHERE chat_id = %s AND archived", (chat_id,))
    payload = _fetch_message(message_id) or {"id": message_id, "chat_id": chat_id, "sender_id": caller_id, "body": ""}
    payload["other_ids"] = [other_id]
    return payload


def edit_message(message_id: int, user_id: int, body: str) -> dict:
    limits.take(user_id, "edit", 30, 60)
    info, others = _member_message(message_id, user_id)
    if info["is_call"]:
        raise ChatError("That line is a record and cannot be edited.")
    if info["sender_id"] != user_id:
        raise Forbidden("You can only edit your own messages.")
    if info["deleted"]:
        raise ChatError("That message was deleted.")
    text = _clean_body(body)
    if not text and not info["has_media"]:
        raise ChatError("A message cannot be empty. Delete it instead.")
    if text == (info["body"] or ""):
        payload = _fetch_message(message_id) or {}
        payload["other_ids"] = others
        return payload
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE {MESSAGE_TABLE} SET body = %s, edited_timestamp = CURRENT_TIMESTAMP WHERE id = %s",
            (text, message_id),
        )
    payload = _fetch_message(message_id) or {}
    payload["other_ids"] = others
    return payload


def delete_message(message_id: int, user_id: int) -> dict:
    """Deletes a message for both people, leaving a marker so replies to it and the order of the chat still make sense."""
    limits.take(user_id, "edit", 30, 60)
    info, others = _member_message(message_id, user_id)
    if info["is_call"]:
        raise ChatError("That line stays in the conversation as a record.")
    if info["sender_id"] != user_id:
        raise Forbidden("You can only delete your own messages.")
    ext = None
    if not info["deleted"]:
        with db_cursor(commit=True) as cur:
            cur.execute(f"SELECT ext FROM {ATTACHMENT_TABLE} WHERE message_id = %s", (message_id,))
            row = cur.fetchone()
            ext = row[0] if row else None
            cur.execute(f"DELETE FROM {ATTACHMENT_TABLE} WHERE message_id = %s", (message_id,))
            cur.execute(f"DELETE FROM {REACTION_TABLE} WHERE message_id = %s", (message_id,))
            cur.execute(f"DELETE FROM {PIN_TABLE} WHERE message_id = %s", (message_id,))
            cur.execute(
                f"UPDATE {MESSAGE_TABLE} SET body = '', deleted_timestamp = CURRENT_TIMESTAMP WHERE id = %s",
                (message_id,),
            )
        if ext:
            unlink_media(message_id, ext)
    payload = _fetch_message(message_id) or {}
    payload["other_ids"] = others
    return payload


def _clean_emoji(emoji: str) -> str:
    text = (emoji or "").strip()
    if not text or len(text) > 16 or any(c.isspace() for c in text) or all(ord(c) < 128 for c in text):
        raise ChatError("Pick an emoji.")
    return text


def toggle_reaction(message_id: int, user_id: int, emoji: str) -> dict:
    """Adds this person's reaction, or removes it when they had already given that one. Returns the message's reactions."""
    limits.take(user_id, "react", 60, 60)
    emoji = _clean_emoji(emoji)
    info, others = _member_message(message_id, user_id)
    if info["is_call"]:
        raise ChatError("That line cannot be reacted to.")
    if info["deleted"]:
        raise ChatError("That message was deleted.")
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"DELETE FROM {REACTION_TABLE} WHERE message_id = %s AND user_id = %s AND emoji = %s",
            (message_id, user_id, emoji),
        )
        if cur.rowcount == 0:
            cur.execute(f"SELECT COUNT(*) FROM {REACTION_TABLE} WHERE message_id = %s AND user_id = %s", (message_id, user_id))
            if cur.fetchone()[0] >= MAX_REACTIONS_PER_PERSON:
                raise ChatError("That is enough reactions on one message.")
            cur.execute(f"INSERT INTO {REACTION_TABLE} (message_id, user_id, emoji) VALUES (%s, %s, %s)", (message_id, user_id, emoji))
        reactions = _reactions_for(cur, [message_id]).get(message_id, [])
    return {"chat_id": info["chat_id"], "message_id": message_id, "reactions": reactions, "other_ids": others}


def forward_message(message_id: int, user_id: int, target_chat_id: int) -> dict:
    """Sends a copy of a message (and its file) into another conversation this person is in."""
    info, _other = _member_message(message_id, user_id)
    if info["deleted"]:
        raise ChatError("That message was deleted.")
    if info["is_call"]:
        raise ChatError("That line cannot be forwarded.")
    _assert_member(target_chat_id, user_id)
    media = None
    with db_cursor() as cur:
        cur.execute(
            f"SELECT kind, ext, original_name, content_type, duration_ms, waveform FROM {ATTACHMENT_TABLE} WHERE message_id = %s",
            (message_id,),
        )
        row = cur.fetchone()
    if row:
        source = media_path(message_id, row[1])
        if not source.is_file():
            raise ChatError("That attachment is no longer available.")
        media = {"kind": row[0], "ext": row[1], "original_name": row[2], "content_type": row[3], "data": source.read_bytes(), "duration_ms": row[4], "waveform": row[5]}
    return send_message(target_chat_id, user_id, info["body"] or "", media, forwarded=True)


# --------------------------------------------------------------------------------------------------- pins and settings


def list_pins(chat_id: int, user_id: int) -> list[dict]:
    _assert_member(chat_id, user_id)
    with db_cursor() as cur:
        cur.execute(
            f"""
            {MESSAGE_SELECT}
            JOIN {PIN_TABLE} pin ON pin.message_id = m.id
            WHERE pin.chat_id = %s AND m.deleted_timestamp IS NULL
            ORDER BY pin.created_timestamp DESC LIMIT %s
            """,
            (chat_id, MAX_PINS),
        )
        return _payloads(cur)


def set_pin(chat_id: int, message_id: int, user_id: int, pinned: bool) -> tuple[list[dict], int]:
    others = _assert_member(chat_id, user_id)
    limits.take(user_id, "edit", 30, 60)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"SELECT deleted_timestamp, system OR call_id IS NOT NULL FROM {MESSAGE_TABLE} WHERE id = %s AND chat_id = %s",
            (message_id, chat_id),
        )
        row = cur.fetchone()
        if not row:
            raise NotFound("Message not found.")
        if pinned:
            if row[0] is not None:
                raise ChatError("That message was deleted.")
            if row[1]:
                raise ChatError("That line cannot be pinned.")
            cur.execute(f"SELECT COUNT(*) FROM {PIN_TABLE} WHERE chat_id = %s", (chat_id,))
            if cur.fetchone()[0] >= MAX_PINS:
                raise ChatError(f"You can pin up to {MAX_PINS} messages. Unpin one first.")
            cur.execute(
                f"INSERT INTO {PIN_TABLE} (chat_id, message_id, pinned_by) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (chat_id, message_id, user_id),
            )
        else:
            cur.execute(f"DELETE FROM {PIN_TABLE} WHERE chat_id = %s AND message_id = %s", (chat_id, message_id))
    return list_pins(chat_id, user_id), others


def set_settings(chat_id: int, user_id: int, changes: dict[str, Any]) -> dict:
    _assert_member(chat_id, user_id)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"INSERT INTO {SETTING_TABLE} (chat_id, user_id) VALUES (%s, %s) ON CONFLICT (chat_id, user_id) DO NOTHING",
            (chat_id, user_id),
        )
        for key in ("pinned", "muted", "archived"):
            if key in changes and isinstance(changes[key], bool):
                cur.execute(f"UPDATE {SETTING_TABLE} SET {key} = %s WHERE chat_id = %s AND user_id = %s", (changes[key], chat_id, user_id))
        cur.execute(f"SELECT pinned, muted, archived FROM {SETTING_TABLE} WHERE chat_id = %s AND user_id = %s", (chat_id, user_id))
        row = cur.fetchone()
    return {"pinned": bool(row[0]), "muted": bool(row[1]), "archived": bool(row[2])}


# ------------------------------------------------------------------------------------------------ attachments and read


def _attachments_for_chat(chat_id: int) -> list[tuple[int, str]]:
    try:
        with db_cursor() as cur:
            cur.execute(
                f"""
                SELECT a.message_id, a.ext FROM {ATTACHMENT_TABLE} a
                JOIN {MESSAGE_TABLE} m ON m.id = a.message_id WHERE m.chat_id = %s
                """,
                (chat_id,),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]
    except Exception:  # noqa: BLE001
        log.exception("Could not list the attachments of chat %s, so its files may be left behind", chat_id)
        return []


def delete_chat(chat_id: int, user_id: int) -> list[int]:
    """Deletes a conversation for everybody in it and returns the others (so they can be told). A group is deleted only by one of its
    admins; anybody else leaves it instead (``chat_groups.remove_member``)."""
    kind, others = _membership(chat_id, user_id)
    if kind == "group":
        with db_cursor() as cur:
            cur.execute(f"SELECT role FROM {MEMBER_TABLE} WHERE chat_id = %s AND user_id = %s", (chat_id, user_id))
            row = cur.fetchone()
        if not row or row[0] != "admin":
            raise Forbidden("Only an admin can delete a group. You can leave it instead.")
    files = _attachments_for_chat(chat_id)
    with db_cursor(commit=True) as cur:
        cur.execute(f"DELETE FROM {CHAT_TABLE} WHERE id = %s", (chat_id,))
        if cur.rowcount == 0:
            raise NotFound("Chat not found.")
    for message_id, ext in files:
        unlink_media(message_id, ext)
    return others


def message_media(message_id: int, user_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute(f"{MESSAGE_SELECT} WHERE m.id = %s", (message_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
    if not row:
        raise NotFound("Message not found.")
    data = dict(zip(cols, row))
    _assert_member(data["chat_id"], user_id)
    if data.get("deleted_timestamp") is not None or not data.get("media_kind") or not data.get("media_ext"):
        raise NotFound("This message has no attachment.")
    path = media_path(message_id, data["media_ext"])
    if not path.is_file():
        raise NotFound("Attachment file is missing.")
    return {
        "path": path,
        "content_type": data.get("media_type") or "application/octet-stream",
        "filename": data.get("media_name") or path.name,
        "kind": data["media_kind"],
    }


def mark_read(chat_id: int, user_id: int) -> dict:
    """Marks everything in the conversation read. Returns the new total and what the other person needs to know."""
    others = _assert_member(chat_id, user_id)
    with db_cursor(commit=True) as cur:
        cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {MESSAGE_TABLE} WHERE chat_id = %s", (chat_id,))
        last_id = cur.fetchone()[0]
        cur.execute(
            f"""
            INSERT INTO {READ_TABLE} (chat_id, user_id, last_read_id) VALUES (%s, %s, %s)
            ON CONFLICT (chat_id, user_id) DO UPDATE SET last_read_id = GREATEST({READ_TABLE}.last_read_id, EXCLUDED.last_read_id)
            """,
            (chat_id, user_id, last_id),
        )
    return {"count": unread_count(user_id), "last_read_id": last_id, "other_ids": others}


def unread_count(user_id: int) -> int:
    """Unread messages in conversations that are not muted: what the badge on the rail shows."""
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT COALESCE(SUM(unread), 0) FROM (
                SELECT (
                    SELECT COUNT(*) FROM {MESSAGE_TABLE} m
                    WHERE m.chat_id = c.id AND m.sender_id <> %s AND m.deleted_timestamp IS NULL AND NOT m.system
                      AND m.id > COALESCE(r.last_read_id, 0)
                ) AS unread
                FROM {CHAT_TABLE} c
                LEFT JOIN {READ_TABLE} r ON r.chat_id = c.id AND r.user_id = %s
                LEFT JOIN {SETTING_TABLE} s ON s.chat_id = c.id AND s.user_id = %s
                WHERE (c.user_low = %s OR c.user_high = %s
                       OR (c.kind = 'group' AND EXISTS (SELECT 1 FROM {MEMBER_TABLE} cm WHERE cm.chat_id = c.id AND cm.user_id = %s)))
                  AND NOT COALESCE(s.muted, FALSE)
            ) counts
            """,
            (user_id, user_id, user_id, user_id, user_id, user_id),
        )
        return int(cur.fetchone()[0] or 0)


def is_muted(chat_id: int, user_id: int) -> bool:
    with db_cursor() as cur:
        cur.execute(f"SELECT muted FROM {SETTING_TABLE} WHERE chat_id = %s AND user_id = %s", (chat_id, user_id))
        row = cur.fetchone()
    return bool(row and row[0])


# ----------------------------------------------------------------------------------------------------------- the hub


class ChatHub:
    def __init__(self):
        self.sockets: dict[int, set[WebSocket]] = {}

    async def connect(self, user_id: int, ws: WebSocket):
        self.sockets.setdefault(user_id, set()).add(ws)

    def disconnect(self, user_id: int, ws: WebSocket):
        conns = self.sockets.get(user_id)
        if not conns:
            return
        conns.discard(ws)
        if not conns:
            self.sockets.pop(user_id, None)

    def online_ids(self) -> set[int]:
        return set(self.sockets)

    def is_online(self, user_id: int) -> bool:
        return user_id in self.sockets

    async def send_user(self, user_id: int, payload: dict):
        for ws in list(self.sockets.get(user_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                self.disconnect(user_id, ws)

    async def broadcast_presence(self):
        payload = {"type": "presence", "online": list(self.online_ids())}
        for user_id in list(self.sockets):
            await self.send_user(user_id, payload)


hub = ChatHub()
