import asyncio
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.websockets import WebSocketDisconnected

from app import calls, chat, chat_ai, chat_groups
from app import sessions
from app.chat import ChatError, Forbidden, NotFound, RateLimited, hub
from app.chat_media import media_response, prepare_upload
from app.config import SESSION_COOKIE_NAME
from app.dependencies import get_current_user

router = APIRouter(prefix="/messages", tags=["messages"])


def _problem(exc: ChatError) -> HTTPException:
    """The status a refusal is answered with, from what kind of refusal it is, never from its wording."""
    if isinstance(exc, NotFound):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, Forbidden):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, RateLimited):
        code = status.HTTP_429_TOO_MANY_REQUESTS
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(code, str(exc))


class StartChatRequest(BaseModel):
    user_id: int


class EditRequest(BaseModel):
    body: str = Field(max_length=chat.MAX_BODY + 100)


class ReactionRequest(BaseModel):
    emoji: str = Field(max_length=40)


class ForwardRequest(BaseModel):
    chat_id: Optional[int] = None
    user_id: Optional[int] = None


class SettingsRequest(BaseModel):
    pinned: Optional[bool] = None
    muted: Optional[bool] = None
    archived: Optional[bool] = None


class CreateGroupRequest(BaseModel):
    title: str = Field(max_length=200)
    user_ids: list[int] = Field(max_length=chat.MAX_GROUP + 10)


class MembersRequest(BaseModel):
    user_ids: list[int] = Field(max_length=chat.MAX_GROUP + 10)


class RoleRequest(BaseModel):
    role: str = Field(max_length=10)


class RenameRequest(BaseModel):
    title: str = Field(max_length=200)


class AssistRequest(BaseModel):
    action: str = Field(max_length=20)
    text: str = Field(default="", max_length=chat.MAX_BODY)
    tone: str = Field(default="", max_length=20)
    language: str = Field(default="", max_length=40)
    allow_cloud_once: bool = False


# ------------------------------------------------------------------------------------------------ people and lists


@router.get("/directory")
def directory(user=Depends(get_current_user)):
    return chat.list_directory(user["id"], hub.online_ids())


@router.get("/chats")
def chats(user=Depends(get_current_user)):
    return chat.list_chats(user["id"], hub.online_ids())


@router.get("/unread")
def unread(user=Depends(get_current_user)):
    return {"count": chat.unread_count(user["id"])}


@router.post("/chats")
def start_chat(body: StartChatRequest, user=Depends(get_current_user)):
    try:
        return chat.get_or_create_chat(user["id"], body.user_id)
    except ChatError as exc:
        raise _problem(exc) from exc


@router.get("/search")
def search(q: str, chat_id: Optional[int] = None, user=Depends(get_current_user)):
    """Messages containing the text, in this person's own conversations only."""
    try:
        return {"results": chat.search_messages(user["id"], q, chat_id)}
    except ChatError as exc:
        raise _problem(exc) from exc


# ------------------------------------------------------------------------------------------------------------- calls


@router.get("/calls/config")
def call_config(user=Depends(get_current_user)):
    """The servers the browser uses to reach the other person (none on one network or over Tailscale)."""
    return {"ice_servers": calls.ice_servers()}


@router.get("/calls/ringing")
async def call_ringing(user=Depends(get_current_user)):
    """The call ringing for this person right now, for a page that has just loaded and may have missed the ring."""
    call = calls.desk.ringing_for(user["id"])
    return {"call": await calls.desk.ring_payload(call) if call else None}


# -------------------------------------------------------------------------------------------------- one conversation


@router.get("/chats/{chat_id}")
def get_chat(chat_id: int, user=Depends(get_current_user)):
    try:
        return chat.get_thread(chat_id, user["id"], hub.online_ids())
    except ChatError as exc:
        raise _problem(exc) from exc


@router.get("/chats/{chat_id}/messages")
def page_messages(chat_id: int, before: int = 0, after: int = 0, around: int = 0, limit: int = chat.PAGE, user=Depends(get_current_user)):
    """Older messages (``before``), messages missed while disconnected (``after``), or the stretch around one (``around``)."""
    try:
        if around:
            return chat.messages_around(chat_id, user["id"], around)
        return chat.list_messages(chat_id, user["id"], after_id=after, before_id=before, limit=limit)
    except ChatError as exc:
        raise _problem(exc) from exc


@router.get("/chats/{chat_id}/media")
def chat_media_list(chat_id: int, kind: Optional[str] = None, user=Depends(get_current_user)):
    if kind not in (None, "image", "video", "file", "audio"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown kind.")
    try:
        return {"items": chat.shared_media(chat_id, user["id"], kind)}
    except ChatError as exc:
        raise _problem(exc) from exc


@router.post("/chats/{chat_id}/messages")
async def post_message(chat_id: int, request: Request, user=Depends(get_current_user)):
    content_type = request.headers.get("content-type", "")
    text, reply_to, client_id, media = "", None, None, None
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        text = str(form.get("body") or "")
        reply_to = _int(form.get("reply_to"))
        client_id = str(form.get("client_id") or "") or None
        upload = form.get("file")
        # request.form() hands back Starlette's UploadFile; FastAPI's own class is a subclass of it, so checking against
        # that one would never match and every attachment would be dropped.
        if isinstance(upload, UploadFile) and upload.filename:
            media = prepare_upload(upload)
            if media["kind"] == "audio":
                duration = _int(form.get("duration_ms"))
                media["duration_ms"] = min(duration, chat.MAX_AUDIO_MS) if duration else None
                media["waveform"] = chat.clean_waveform(form.get("waveform"))
    else:
        data = await request.json()
        data = data if isinstance(data, dict) else {}
        text = str(data.get("body") or "")
        reply_to = _int(data.get("reply_to"))
        client_id = str(data.get("client_id") or "") or None
    try:
        message = chat.send_message(chat_id, user["id"], text, media, reply_to=reply_to, client_id=client_id)
    except ChatError as exc:
        raise _problem(exc) from exc
    if not message.pop("duplicate", False):
        await _fanout(user, message)
    else:
        message.pop("other_ids", None)
    return message


def _int(value) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


@router.post("/chats/{chat_id}/read")
async def read_chat(chat_id: int, user=Depends(get_current_user)):
    try:
        result = chat.mark_read(chat_id, user["id"])
    except ChatError as exc:
        raise _problem(exc) from exc
    await _read_events(user["id"], chat_id, result)
    return {"count": result["count"]}


@router.patch("/chats/{chat_id}/settings")
def chat_settings(chat_id: int, body: SettingsRequest, user=Depends(get_current_user)):
    try:
        return chat.set_settings(chat_id, user["id"], body.model_dump(exclude_none=True))
    except ChatError as exc:
        raise _problem(exc) from exc


@router.put("/chats/{chat_id}/pins/{message_id}")
async def pin_message(chat_id: int, message_id: int, user=Depends(get_current_user)):
    return await _pins(chat_id, message_id, user, True)


@router.delete("/chats/{chat_id}/pins/{message_id}")
async def unpin_message(chat_id: int, message_id: int, user=Depends(get_current_user)):
    return await _pins(chat_id, message_id, user, False)


async def _pins(chat_id: int, message_id: int, user: dict, pinned: bool):
    try:
        pins, others = chat.set_pin(chat_id, message_id, user["id"], pinned)
    except ChatError as exc:
        raise _problem(exc) from exc
    event = {"type": "pins", "chat_id": chat_id, "pins": pins}
    await hub.send_user(user["id"], event)
    for other_id in others:
        await hub.send_user(other_id, event)
    return {"pins": pins}


@router.delete("/chats/{chat_id}")
async def remove_chat(chat_id: int, user=Depends(get_current_user)):
    try:
        others = chat.delete_chat(chat_id, user["id"])
    except ChatError as exc:
        raise _problem(exc) from exc
    event = {"type": "chat_deleted", "chat_id": chat_id}
    for who in [user["id"], *others]:
        await hub.send_user(who, event)
        await hub.send_user(who, {"type": "unread", "count": chat.unread_count(who)})
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------- one message


@router.patch("/{message_id}")
async def edit_message(message_id: int, body: EditRequest, user=Depends(get_current_user)):
    try:
        message = chat.edit_message(message_id, user["id"], body.body)
    except ChatError as exc:
        raise _problem(exc) from exc
    others = message.pop("other_ids", None) or []
    event = {"type": "message_updated", "message": message}
    await hub.send_user(user["id"], event)
    for other_id in others:
        await hub.send_user(other_id, event)
    return message


@router.delete("/{message_id}")
async def delete_message(message_id: int, user=Depends(get_current_user)):
    try:
        message = chat.delete_message(message_id, user["id"])
    except ChatError as exc:
        raise _problem(exc) from exc
    others = message.pop("other_ids", None) or []
    event = {"type": "message_updated", "message": message}
    await hub.send_user(user["id"], event)
    for other_id in others:
        await hub.send_user(other_id, event)
        await hub.send_user(other_id, {"type": "unread", "count": chat.unread_count(other_id)})
    return message


@router.put("/{message_id}/reactions")
async def react(message_id: int, body: ReactionRequest, user=Depends(get_current_user)):
    try:
        result = chat.toggle_reaction(message_id, user["id"], body.emoji)
    except ChatError as exc:
        raise _problem(exc) from exc
    others = result.pop("other_ids")
    event = {"type": "reactions", **result}
    await hub.send_user(user["id"], event)
    for other_id in others:
        await hub.send_user(other_id, event)
    return result


@router.post("/{message_id}/forward")
async def forward(message_id: int, body: ForwardRequest, user=Depends(get_current_user)):
    try:
        target = body.chat_id
        if not target:
            if not body.user_id:
                raise ChatError("Choose who to send it to.")
            target = chat.get_or_create_chat(user["id"], body.user_id)["id"]
        message = chat.forward_message(message_id, user["id"], target)
    except ChatError as exc:
        raise _problem(exc) from exc
    await _fanout(user, message)
    return message


@router.get("/media/{message_id}")
def get_media(message_id: int, user=Depends(get_current_user)):
    try:
        info = chat.message_media(message_id, user["id"])
    except ChatError as exc:
        raise _problem(exc) from exc
    return media_response(info["path"], info["content_type"], info["filename"], info["kind"] in {"image", "video", "audio"})


# ------------------------------------------------------------------------------------------------------------- AI help


@router.post("/chats/{chat_id}/assist")
def assist(chat_id: int, body: AssistRequest, user=Depends(get_current_user)):
    """A draft from the AI (rewrite, reply suggestions, summary, translation). It is text to edit; nothing is sent."""
    try:
        return chat_ai.assist(
            user, chat_id, body.action, text=body.text, tone=body.tone, language=body.language, allow_cloud_once=body.allow_cloud_once
        )
    except ChatError as exc:
        raise _problem(exc) from exc


# ------------------------------------------------------------------------------------------------------- live updates


@router.websocket("/ws")
async def messages_ws(
    websocket: WebSocket,
    orion_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    user = _socket_user(orion_session)
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    await hub.connect(user["id"], websocket)
    # A socket stays open after it is accepted, so the session behind it is looked at again now and then: signing out, a
    # password change or a disabled account must end the live connection too, not only the next page load.
    watchdog = asyncio.create_task(_end_when_signed_out(websocket, orion_session))
    await hub.send_user(user["id"], {"type": "unread", "count": chat.unread_count(user["id"])})
    await hub.broadcast_presence()
    try:
        while True:
            data = await websocket.receive_json()
            if not isinstance(data, dict):
                continue
            kind = data.get("type")
            try:
                if kind == "send":
                    message = chat.send_message(
                        int(data["chat_id"]), user["id"], str(data.get("body") or ""),
                        reply_to=_int(data.get("reply_to")), client_id=str(data.get("client_id") or "") or None,
                    )
                    if message.pop("duplicate", False):
                        message.pop("other_ids", None)
                        await hub.send_user(user["id"], {"type": "message", "message": message, "sender": {"id": user["id"], "display_name": user["display_name"]}})
                    else:
                        await _fanout(user, message)
                elif kind == "read":
                    result = chat.mark_read(int(data["chat_id"]), user["id"])
                    await _read_events(user["id"], int(data["chat_id"]), result)
                elif kind == "typing":
                    chat.limits.take(user["id"], "typing", 6, 10)
                    for other_id in chat._assert_member(int(data["chat_id"]), user["id"]):
                        await hub.send_user(other_id, {"type": "typing", "chat_id": int(data["chat_id"]), "user_id": user["id"]})
                elif kind == "ping":
                    await websocket.send_json({"type": "pong"})
                elif isinstance(kind, str) and kind.startswith("call_"):
                    await _call_event(websocket, user, kind, data)
            except RateLimited:
                continue  # a client typing or sending faster than allowed is quietly slowed down, not disconnected
            except ChatError as exc:
                await websocket.send_json({"type": "error", "message": str(exc), "chat_id": data.get("chat_id"), "client_id": data.get("client_id")})
            except (KeyError, TypeError, ValueError):
                continue
    except (WebSocketDisconnect, WebSocketDisconnected):
        pass  # the person left, or the session watchdog just closed it while a message was arriving
    finally:
        watchdog.cancel()
        hub.disconnect(user["id"], websocket)
        if not hub.is_online(user["id"]):
            await calls.desk.on_disconnect(user["id"])
        await hub.broadcast_presence()


async def _call_event(websocket: WebSocket, user: dict, kind: str, data: dict) -> None:
    """What the browser says about a call. A refusal goes back to this browser only, as ``call_error``."""
    try:
        if kind == "call_invite":
            await calls.desk.invite(user, data.get("chat_id"), data.get("kind"))
        elif kind == "call_accept":
            await calls.desk.accept(user, data.get("call_id"))
        elif kind in {"call_end", "call_decline", "call_cancel"}:
            await calls.desk.end(user, data.get("call_id"))
        elif kind == "call_signal":
            await calls.desk.signal(user, data.get("call_id"), data.get("data"))
    except (ChatError, KeyError, TypeError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ChatError) else "That call could not be set up."
        await websocket.send_json({"type": "call_error", "message": message, "chat_id": data.get("chat_id"), "call_id": data.get("call_id")})


SOCKET_RECHECK_SECONDS = 30


async def _end_when_signed_out(websocket: WebSocket, token: Optional[str]) -> None:
    while True:
        await asyncio.sleep(SOCKET_RECHECK_SECONDS)
        if await run_in_threadpool(_socket_user, token) is None:
            try:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            except RuntimeError:
                pass  # it had already gone
            return


def _socket_user(token: Optional[str]):
    return sessions.user_for_token(token)


async def _read_events(user_id: int, chat_id: int, result: dict) -> None:
    await hub.send_user(user_id, {"type": "unread", "count": result["count"]})
    for other_id in result["other_ids"]:
        await hub.send_user(other_id, {"type": "read", "chat_id": chat_id, "user_id": user_id, "last_read_id": result["last_read_id"]})


async def _fanout(sender: dict, message: dict, *, to_sender: bool = True):
    others = message.pop("other_ids", None) or []
    event = {
        "type": "message",
        "message": message,
        "sender": {"id": sender["id"], "display_name": sender["display_name"]},
    }
    if to_sender:
        await hub.send_user(sender["id"], event)
    for other_id in others:
        muted = chat.is_muted(message["chat_id"], other_id)
        await hub.send_user(other_id, {**event, "muted": muted})
        await hub.send_user(other_id, {"type": "unread", "count": chat.unread_count(other_id)})
    if to_sender:
        await hub.send_user(sender["id"], {"type": "unread", "count": chat.unread_count(sender["id"])})


# ------------------------------------------------------------------------------------------------------------ groups


async def _group_changed(actor: dict, chat_id: int, result: dict, *, removed: Optional[int] = None) -> None:
    """Says what happened in a group: the line in the conversation to everybody still in it, and "something changed" so their lists
    and member lists are fetched again. A person who left or was removed is told the conversation is gone for them."""
    line = result.get("line")
    if line:
        await _fanout(actor, line, to_sender=removed != actor["id"])
    for who in result["everyone"]:
        await hub.send_user(who, {"type": "chat_changed", "chat_id": chat_id})
    if removed is not None:
        await hub.send_user(removed, {"type": "chat_deleted", "chat_id": chat_id})
        await hub.send_user(removed, {"type": "unread", "count": chat.unread_count(removed)})


@router.post("/groups")
async def create_group(body: CreateGroupRequest, user=Depends(get_current_user)):
    try:
        made = chat_groups.create_group(user["id"], body.title, body.user_ids)
        summary = chat.chat_summary(made["chat_id"], user["id"], hub.online_ids())
    except ChatError as exc:
        raise _problem(exc) from exc
    await _fanout(user, made["line"])
    for who in made["everyone"]:
        await hub.send_user(who, {"type": "chat_changed", "chat_id": made["chat_id"]})
    return summary


@router.patch("/groups/{chat_id}")
async def rename_group(chat_id: int, body: RenameRequest, user=Depends(get_current_user)):
    try:
        result = chat_groups.rename(chat_id, user["id"], body.title)
        summary = chat.chat_summary(chat_id, user["id"], hub.online_ids())
    except ChatError as exc:
        raise _problem(exc) from exc
    await _group_changed(user, chat_id, result)
    return summary


@router.post("/groups/{chat_id}/members")
async def add_group_members(chat_id: int, body: MembersRequest, user=Depends(get_current_user)):
    try:
        result = chat_groups.add_members(chat_id, user["id"], body.user_ids)
        summary = chat.chat_summary(chat_id, user["id"], hub.online_ids())
    except ChatError as exc:
        raise _problem(exc) from exc
    await _group_changed(user, chat_id, result)
    return summary


@router.delete("/groups/{chat_id}/members/{member_id}")
async def remove_group_member(chat_id: int, member_id: int, user=Depends(get_current_user)):
    """An admin removes someone, or a person leaves (their own id)."""
    try:
        result = chat_groups.remove_member(chat_id, user["id"], member_id)
    except ChatError as exc:
        raise _problem(exc) from exc
    await _group_changed(user, chat_id, result, removed=result["removed"])
    return {"ok": True, "deleted": result["deleted"]}


@router.put("/groups/{chat_id}/members/{member_id}/role")
async def set_group_role(chat_id: int, member_id: int, body: RoleRequest, user=Depends(get_current_user)):
    try:
        result = chat_groups.set_role(chat_id, user["id"], member_id, body.role)
        summary = chat.chat_summary(chat_id, user["id"], hub.online_ids())
    except ChatError as exc:
        raise _problem(exc) from exc
    await _group_changed(user, chat_id, result)
    return summary
