"""Voice and video calls between the two people of a conversation.

The sound and picture go straight from one browser to the other (WebRTC) and never touch the server. This module is only the
switchboard: it rings the other person, says who answered, passes the two browsers' set-up messages (offer, answer, network
candidates) along the WebSocket that chat already uses, and writes what happened as one line in the conversation. It is the only
writer of ``orion_ods.chat_call``; the line in the chat is written by ``chat.add_call_message``.

Who may call whom is the same rule as who may message whom, checked from the database: the two members of a conversation. A set-up
message is relayed only between the two people of a call that is live, and only when it looks like one. Calls that are ringing or
under way live in this process (the application is one process on one computer); a restart ends them, and a call that was ringing
is recorded as missed by the person who rang giving up, never left open.

Nothing that is said or shown is recorded. What is kept is who called, who was called, which kind, how it ended and for how long.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from app import chat
from app.chat import ChatError, NotFound, hub
from app.config import env
from app.database import db_cursor

log = logging.getLogger(__name__)

RING_SECONDS = 40
MAX_SIGNAL_BYTES = 16_000
# "state" is the small note each side sends about itself (microphone, camera and screen on or off), so the other can draw it right.
SIGNAL_KINDS = {"offer", "answer", "candidate", "state"}
CALL_KINDS = {"voice", "video"}


@dataclass
class Live:
    id: int
    chat_id: int
    caller_id: int
    callee_id: int
    kind: str
    state: str = "ringing"  # ringing, then active
    timer: Optional[asyncio.Task] = None

    def other(self, user_id: int) -> int:
        return self.callee_id if user_id == self.caller_id else self.caller_id


# ------------------------------------------------------------------------------------------------------ the network


def ice_servers() -> list[dict]:
    """The servers the browsers use to find a way to each other. Nothing is needed on one network or over Tailscale (the two
    devices can reach each other directly); a STUN server and a relay (TURN) are for people outside it. They are chosen in
    ``.env`` and never named by the browser."""
    servers: list[dict] = []
    stun = [u.strip() for u in env("ORION_CALL_STUN_URLS").split(",") if u.strip()]
    if stun:
        servers.append({"urls": stun})
    turn = [u.strip() for u in env("ORION_CALL_TURN_URLS").split(",") if u.strip()]
    if turn and env("ORION_CALL_TURN_USER") and env("ORION_CALL_TURN_PASSWORD"):
        servers.append({"urls": turn, "username": env("ORION_CALL_TURN_USER"), "credential": env("ORION_CALL_TURN_PASSWORD")})
    return servers


# -------------------------------------------------------------------------------------------------------- the records


def _create(chat_id: int, caller_id: int, callee_id: int, kind: str) -> int:
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"INSERT INTO {chat.CALL_TABLE} (chat_id, caller_id, callee_id, kind) VALUES (%s, %s, %s, %s) RETURNING id",
            (chat_id, caller_id, callee_id, kind),
        )
        return cur.fetchone()[0]


def _answered(call_id: int) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE {chat.CALL_TABLE} SET outcome = 'answered', answered_timestamp = CURRENT_TIMESTAMP WHERE id = %s AND outcome = 'ringing'",
            (call_id,),
        )


def _close(call_id: int, outcome: str) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE {chat.CALL_TABLE} SET outcome = %s, ended_timestamp = CURRENT_TIMESTAMP WHERE id = %s",
            (outcome, call_id),
        )


def _person(user_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute(
            f"SELECT id, username, display_name, role, avatar_ext, avatar_version FROM {chat.APP_USER_TABLE} WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
    return chat.peer_payload(dict(zip(cols, row)), online=True) if row else {"id": user_id, "display_name": "Someone"}


# ------------------------------------------------------------------------------------------------------ the switchboard


class CallDesk:
    def __init__(self) -> None:
        self.live: dict[int, Live] = {}

    # -- who is where -------------------------------------------------------------------------------------------------

    def of(self, user_id: int) -> Optional[Live]:
        return next((c for c in self.live.values() if user_id in (c.caller_id, c.callee_id)), None)

    def ringing_for(self, user_id: int) -> Optional[Live]:
        return next((c for c in self.live.values() if c.state == "ringing" and c.callee_id == user_id), None)

    async def ring_payload(self, call: Live) -> dict:
        caller = await asyncio.to_thread(_person, call.caller_id)
        return {"id": call.id, "chat_id": call.chat_id, "kind": call.kind, "caller": caller, "callee_id": call.callee_id}

    def _mine(self, user_id: int, call_id: Any) -> Live:
        """A live call this person is one of the two of, or ``NotFound`` (the same answer for a call that does not exist)."""
        try:
            call = self.live.get(int(call_id))
        except (TypeError, ValueError):
            call = None
        if call is None or user_id not in (call.caller_id, call.callee_id):
            raise NotFound("That call is not in progress.")
        return call

    # -- the person who rings ----------------------------------------------------------------------------------------

    async def invite(self, user: dict, chat_id: Any, kind: Any) -> None:
        if kind not in CALL_KINDS:
            raise ChatError("Choose a voice or a video call.")
        chat_id = int(chat_id)
        chat.limits.take(user["id"], "call", 6, 60)
        other_id = await asyncio.to_thread(chat._direct_peer, chat_id, user["id"])
        if self.of(user["id"]):
            raise ChatError("You are already in a call.")
        call_id = await asyncio.to_thread(_create, chat_id, user["id"], other_id, kind)
        call = Live(call_id, chat_id, user["id"], other_id, kind)
        if not hub.is_online(other_id) or self.of(other_id):
            # Nobody to ring: it is recorded as missed (so they see it), and the caller is told why.
            await self._finish(call, "missed", reason="busy" if hub.is_online(other_id) else "offline", caller_name=user["display_name"])
            return
        self.live[call_id] = call
        call.timer = asyncio.create_task(self._ring_out(call, user["display_name"]))
        await hub.send_user(user["id"], {"type": "call_started", "call": await self.ring_payload(call), "peer": await asyncio.to_thread(_person, other_id)})
        await hub.send_user(other_id, {"type": "call_ring", "call": await self.ring_payload(call)})

    async def _ring_out(self, call: Live, caller_name: str) -> None:
        await asyncio.sleep(RING_SECONDS)
        if self.live.get(call.id) is call and call.state == "ringing":
            await self._finish(call, "missed", reason="no_answer", caller_name=caller_name)

    # -- the person who is rung --------------------------------------------------------------------------------------

    async def accept(self, user: dict, call_id: Any) -> None:
        call = self._mine(user["id"], call_id)
        if call.callee_id != user["id"] or call.state != "ringing":
            raise ChatError("That call is no longer ringing.")
        call.state = "active"
        if call.timer and call.timer is not asyncio.current_task():
            call.timer.cancel()
        await asyncio.to_thread(_answered, call.id)
        event = {"type": "call_accepted", "call_id": call.id, "by": user["id"]}
        await hub.send_user(call.caller_id, event)
        await hub.send_user(call.callee_id, event)  # the person's other devices stop ringing

    async def end(self, user: dict, call_id: Any) -> None:
        """Turning a call down, giving up ringing, or hanging up: what it is called depends on who does it and when."""
        call = self._mine(user["id"], call_id)
        if call.state == "ringing":
            outcome = "cancelled" if user["id"] == call.caller_id else "declined"
        else:
            outcome = "ended"
        await self._finish(call, outcome, caller_name=None)

    # -- the set-up messages ------------------------------------------------------------------------------------------

    async def signal(self, user: dict, call_id: Any, data: Any) -> None:
        call = self._mine(user["id"], call_id)
        if call.state != "active":
            raise ChatError("That call is not connected yet.")
        if not isinstance(data, dict) or data.get("type") not in SIGNAL_KINDS:
            return
        if len(json.dumps(data, separators=(",", ":"))) > MAX_SIGNAL_BYTES:
            raise ChatError("That message is too large.")
        chat.limits.take(user["id"], "call_signal", 200, 10)
        await hub.send_user(call.other(user["id"]), {"type": "call_signal", "call_id": call.id, "from": user["id"], "data": data})

    # -- people leaving -----------------------------------------------------------------------------------------------

    async def on_disconnect(self, user_id: int) -> None:
        """The last browser of a person closed: a call they were in cannot go on. A call that is ringing for them keeps ringing,
        because they may be back in a moment (a reload); one they were making is given up."""
        call = self.of(user_id)
        if call is None:
            return
        if call.state == "ringing" and user_id == call.callee_id:
            return
        outcome = "cancelled" if call.state == "ringing" else "ended"
        await self._finish(call, outcome, caller_name=None)

    # -- the end ------------------------------------------------------------------------------------------------------

    async def _finish(self, call: Live, outcome: str, *, reason: Optional[str] = None, caller_name: Optional[str]) -> None:
        if self.live.pop(call.id, None) is not None and call.timer and call.timer is not asyncio.current_task():
            call.timer.cancel()
        await asyncio.to_thread(_close, call.id, outcome)
        # The line in the conversation. An answered or turned-down call is already known to the other person, so only a call
        # that nobody answered counts as unread for them.
        unanswered = outcome in {"missed", "cancelled"}
        try:
            message = await asyncio.to_thread(chat.add_call_message, call.chat_id, call.caller_id, call.id, seen_by_other=not unanswered)
        except ChatError:
            log.debug("The conversation of call %s is gone", call.id)
            message = None
        end = {"type": "call_ended", "call_id": call.id, "chat_id": call.chat_id, "outcome": outcome, "reason": reason}
        # Each side is told who the other was, so "Ben is offline" can be said even when the call never got as far as ringing.
        await hub.send_user(call.caller_id, {**end, "peer": await asyncio.to_thread(_person, call.callee_id)})
        await hub.send_user(call.callee_id, {**end, "peer": await asyncio.to_thread(_person, call.caller_id)})
        if message:
            other_id = (message.pop("other_ids", None) or [call.callee_id])[0]
            name = caller_name or (await asyncio.to_thread(_person, call.caller_id)).get("display_name") or "Someone"
            event = {"type": "message", "message": message, "sender": {"id": call.caller_id, "display_name": name}}
            await hub.send_user(call.caller_id, event)
            muted = await asyncio.to_thread(chat.is_muted, call.chat_id, other_id)
            # A missed call is worth a pop-up to the person who missed it; anything else is only the line in the chat.
            await hub.send_user(other_id, {**event, "muted": muted or not unanswered})
            for who in (call.caller_id, other_id):
                await hub.send_user(who, {"type": "unread", "count": await asyncio.to_thread(chat.unread_count, who)})


desk = CallDesk()
