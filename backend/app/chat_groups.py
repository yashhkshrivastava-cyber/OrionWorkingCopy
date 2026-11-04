"""Group chats: making one, who is in it, who runs it.

A group is a conversation (``direct_chat`` with kind 'group') whose people are the rows of ``chat_member``; this module is the only
writer of that table. Messages, reactions, pins, files, read state and the person's own choices are the same as in a direct
conversation and stay in ``chat.py``; every one of those functions asks ``chat._assert_member`` who else is in the conversation, which
for a group is read from ``chat_member`` on every call, so a person who has left or been removed can read nothing more at once.

The rules:

* Anyone signed in can make a group, and becomes its admin. A group has a name (up to 60 characters) and 2 to 50 people.
* Only an admin adds or removes people, renames the group, makes someone an admin or takes that back. Anybody can leave. The last
  admin cannot leave without handing over: the person who has been in the group longest becomes an admin. A group with nobody left
  is deleted.
* Everybody in a group sees all of its history, including from before they joined: the add dialog says so.
* Who joined, left, was removed or renamed it is said in the conversation as a line nobody wrote (``chat.add_system_message``).

Every function returns what the router needs to tell people (who else is in the group now, who was removed); what was said in a group
is never written to a log.
"""

from __future__ import annotations

from typing import Optional

from app.auth import APP_USER_TABLE
from app.chat import (
    CHAT_TABLE,
    MAX_GROUP,
    MAX_TITLE,
    MEMBER_TABLE,
    READ_TABLE,
    MESSAGE_TABLE,
    ChatError,
    Forbidden,
    NotFound,
    _membership,
    add_system_message,
    limits,
)
from app.database import db_cursor


def clean_title(raw: Optional[str]) -> str:
    title = " ".join((raw or "").replace("\x00", "").split())
    if not title:
        raise ChatError("Give the group a name.")
    if len(title) > MAX_TITLE:
        raise ChatError(f"A group name can be up to {MAX_TITLE} characters.")
    return title


def _names(ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    with db_cursor() as cur:
        cur.execute(f"SELECT id, display_name FROM {APP_USER_TABLE} WHERE id = ANY(%s)", (ids,))
        return {row[0]: row[1] for row in cur.fetchall()}


def _active_people(ids: list[int]) -> list[int]:
    """The ids that are real, active accounts, in the order given and without repeats."""
    wanted = list(dict.fromkeys(int(i) for i in ids))
    if not wanted:
        return []
    with db_cursor() as cur:
        cur.execute(f"SELECT id FROM {APP_USER_TABLE} WHERE id = ANY(%s) AND is_active = TRUE", (wanted,))
        found = {row[0] for row in cur.fetchall()}
    missing = [i for i in wanted if i not in found]
    if missing:
        raise ChatError("One of the people you chose is not available.")
    return wanted


def _role_of(chat_id: int, user_id: int) -> Optional[str]:
    with db_cursor() as cur:
        cur.execute(f"SELECT role FROM {MEMBER_TABLE} WHERE chat_id = %s AND user_id = %s", (chat_id, user_id))
        row = cur.fetchone()
    return row[0] if row else None


def _admin(chat_id: int, user_id: int) -> None:
    """The person must be in this group (else it does not exist for them) and an admin of it."""
    kind, _others = _membership(chat_id, user_id)
    if kind != "group":
        raise ChatError("That is not a group.")
    if _role_of(chat_id, user_id) != "admin":
        raise Forbidden("Only an admin of the group can do that.")


def _everyone(chat_id: int) -> list[int]:
    with db_cursor() as cur:
        cur.execute(f"SELECT user_id FROM {MEMBER_TABLE} WHERE chat_id = %s ORDER BY joined_timestamp, user_id", (chat_id,))
        return [row[0] for row in cur.fetchall()]


def _join(cur, chat_id: int, user_id: int, role: str, added_by: Optional[int]) -> None:
    cur.execute(
        f"INSERT INTO {MEMBER_TABLE} (chat_id, user_id, role, added_by) VALUES (%s, %s, %s, %s) ON CONFLICT (chat_id, user_id) DO NOTHING",
        (chat_id, user_id, role, added_by),
    )
    # What was said before a person joined is not "unread" for them: they start at the newest message.
    cur.execute(
        f"""
        INSERT INTO {READ_TABLE} (chat_id, user_id, last_read_id)
        VALUES (%s, %s, (SELECT COALESCE(MAX(id), 0) FROM {MESSAGE_TABLE} WHERE chat_id = %s))
        ON CONFLICT (chat_id, user_id) DO UPDATE SET last_read_id = GREATEST({READ_TABLE}.last_read_id, EXCLUDED.last_read_id)
        """,
        (chat_id, user_id, chat_id),
    )


def _list(names: list[str]) -> str:
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


# ---------------------------------------------------------------------------------------------------------- making one


def create_group(user_id: int, title: str, member_ids: list[int]) -> dict:
    """Makes a group with this person as its admin. Returns the new conversation's id and the system line to send."""
    limits.take(user_id, "group", 10, 60)
    title = clean_title(title)
    others = [i for i in _active_people(member_ids) if i != user_id]
    if not others:
        raise ChatError("Choose at least one other person.")
    if len(others) + 1 > MAX_GROUP:
        raise ChatError(f"A group can have up to {MAX_GROUP} people.")
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"INSERT INTO {CHAT_TABLE} (kind, title, created_by) VALUES ('group', %s, %s) RETURNING id",
            (title, user_id),
        )
        chat_id = cur.fetchone()[0]
        _join(cur, chat_id, user_id, "admin", user_id)
        for other in others:
            _join(cur, chat_id, other, "member", user_id)
    line = add_system_message(chat_id, user_id, f"{_names([user_id])[user_id]} created the group “{title}”")
    return {"chat_id": chat_id, "line": line, "everyone": [user_id] + others}


# ------------------------------------------------------------------------------------------------------ who is in it


def add_members(chat_id: int, actor_id: int, user_ids: list[int]) -> dict:
    """An admin adds people. Those already in it are left as they are."""
    limits.take(actor_id, "group", 10, 60)
    _admin(chat_id, actor_id)
    present = set(_everyone(chat_id))
    new = [i for i in _active_people(user_ids) if i not in present]
    if not new:
        raise ChatError("They are all in the group already.")
    if len(present) + len(new) > MAX_GROUP:
        raise ChatError(f"A group can have up to {MAX_GROUP} people.")
    with db_cursor(commit=True) as cur:
        for person in new:
            _join(cur, chat_id, person, "member", actor_id)
    names = _names([actor_id] + new)
    line = add_system_message(chat_id, actor_id, f"{names[actor_id]} added {_list([names[i] for i in new])}")
    return {"line": line, "added": new, "everyone": _everyone(chat_id)}


def remove_member(chat_id: int, actor_id: int, target_id: int) -> dict:
    """An admin removes someone, or a person leaves (target is the actor). Returns who is left, to tell them, and the line to send."""
    limits.take(actor_id, "group", 10, 60)
    kind, _others = _membership(chat_id, actor_id)
    if kind != "group":
        raise ChatError("That is not a group.")
    leaving = target_id == actor_id
    if not leaving:
        _admin(chat_id, actor_id)
    present = _everyone(chat_id)
    if target_id not in present:
        raise NotFound("That person is not in the group.")
    names = _names([actor_id, target_id])
    left = [i for i in present if i != target_id]
    if not left:
        # Nobody remains: the group goes with the last person.
        from app.chat import delete_chat

        delete_chat(chat_id, actor_id)
        return {"line": None, "everyone": [], "removed": target_id, "deleted": True}
    with db_cursor(commit=True) as cur:
        cur.execute(f"DELETE FROM {MEMBER_TABLE} WHERE chat_id = %s AND user_id = %s", (chat_id, target_id))
        cur.execute(f"DELETE FROM {READ_TABLE} WHERE chat_id = %s AND user_id = %s", (chat_id, target_id))
        # A group is never left without an admin: the person who has been in it longest takes over.
        cur.execute(f"SELECT COUNT(*) FROM {MEMBER_TABLE} WHERE chat_id = %s AND role = 'admin'", (chat_id,))
        if cur.fetchone()[0] == 0:
            cur.execute(
                f"""
                UPDATE {MEMBER_TABLE} SET role = 'admin'
                WHERE chat_id = %s AND user_id = (SELECT user_id FROM {MEMBER_TABLE} WHERE chat_id = %s ORDER BY joined_timestamp, user_id LIMIT 1)
                """,
                (chat_id, chat_id),
            )
    # The line is written as the person who is leaving or doing the removing; people who are no longer in the group never see it.
    text = f"{names[target_id]} left" if leaving else f"{names[actor_id]} removed {names[target_id]}"
    line = add_system_message(chat_id, actor_id, text)
    return {"line": line, "everyone": left, "removed": target_id, "deleted": False}


def set_role(chat_id: int, actor_id: int, target_id: int, role: str) -> dict:
    limits.take(actor_id, "group", 10, 60)
    if role not in ("admin", "member"):
        raise ChatError("A person is an admin or a member.")
    _admin(chat_id, actor_id)
    if target_id not in _everyone(chat_id):
        raise NotFound("That person is not in the group.")
    with db_cursor(commit=True) as cur:
        if role == "member":
            cur.execute(f"SELECT COUNT(*) FROM {MEMBER_TABLE} WHERE chat_id = %s AND role = 'admin' AND user_id <> %s", (chat_id, target_id))
            if cur.fetchone()[0] == 0:
                raise ChatError("A group needs an admin. Make someone else an admin first.")
        cur.execute(f"UPDATE {MEMBER_TABLE} SET role = %s WHERE chat_id = %s AND user_id = %s", (role, chat_id, target_id))
    names = _names([actor_id, target_id])
    text = f"{names[actor_id]} made {names[target_id]} an admin" if role == "admin" else f"{names[actor_id]} removed {names[target_id]} as an admin"
    line = add_system_message(chat_id, actor_id, text)
    return {"line": line, "everyone": _everyone(chat_id)}


def rename(chat_id: int, actor_id: int, title: str) -> dict:
    limits.take(actor_id, "group", 10, 60)
    title = clean_title(title)
    _admin(chat_id, actor_id)
    with db_cursor(commit=True) as cur:
        cur.execute(f"UPDATE {CHAT_TABLE} SET title = %s WHERE id = %s AND kind = 'group'", (title, chat_id))
    line = add_system_message(chat_id, actor_id, f"{_names([actor_id])[actor_id]} renamed the group to “{title}”")
    return {"line": line, "everyone": _everyone(chat_id)}
