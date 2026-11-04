"""Google Drive in the Document Center: the connection, browsing it, copying and moving documents to and from it, and saving bills to it.

``gdrive_client`` is the only code that talks to a Drive (a fake one in development, Google's when its credentials are in the .env);
this module is the only writer of ``orion_ods.gdrive_connection`` and ``orion_ods.drive_link`` and the only place that decides what may
leave Orion for a Drive:

* A **Confidential** document leaves only when the person has confirmed it (``allow_confidential``), and a paper Orion filed by itself
  (a bill, an employee's or an EMD's paper) is copied, never moved: its place is decided by its source (``documents_filing``).
* A **bill** is saved to Drive as its PDF, by choice (a tick on the bill, or the company's setting), and the file follows the bill: an edit
  or a cancellation replaces its content. Saving to Drive never changes, delays or fails the bill (``sync_bill_quietly``).
* Nothing is deleted from either side for good: a move trashes the original only after the copy exists, Drive's own trash keeps it
  30 days, and Orion's keeps it until an admin purges it.
* The refresh token Google gives is kept encrypted (``seal``) with a key made from the server's session secret; the fake Drive has none.
  No token, code or Google response is ever logged or sent to the browser.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app import documents, documents_explorer, gdrive_client
from app.config import session_secret
from app.database import db_cursor
from app.gdrive_client import ROOT, DriveClient, DriveError, FakeDrive, GoogleDrive

logger = logging.getLogger(__name__)

STATE_MINUTES = 10
MAX_AT_ONCE = 50
BILL = "bill"
DOCUMENT = "document"
BILLS_MODES = ("off", "ask", "on")


# --------------------------------------------------------------------------------------------------------------------
# Keeping Google's token


def _key() -> str:
    """The passphrase the token is sealed with: made from the session secret, so a stolen database backup alone cannot open it."""
    return hmac.new(session_secret(), b"orion/gdrive-refresh-token", hashlib.sha256).hexdigest()


def seal(token: str) -> bytes:
    from pyrage import passphrase

    return bytes(passphrase.encrypt(token.encode(), _key()))


def unseal(blob: bytes) -> str:
    from pyrage import passphrase

    try:
        return bytes(passphrase.decrypt(bytes(blob), _key())).decode()
    except Exception as exc:  # noqa: BLE001 - a changed session secret makes the sealed token unreadable; say so, never show why in detail
        raise DriveError("The saved Google connection cannot be read (the server's secret changed). An admin needs to connect Google Drive again.", 401) from exc


_cache: dict[str, Any] = {"access": None, "expires": 0.0, "refresh": None}
_cache_lock = threading.Lock()


def _forget_tokens() -> None:
    with _cache_lock:
        _cache.update(access=None, expires=0.0, refresh=None)


def _access_token() -> str:
    """A current access token: the one in memory, or a new one from the refresh token. The (slow) unsealing happens once per start."""
    with _cache_lock:
        if _cache["access"] and time.monotonic() < _cache["expires"] - 60:
            return _cache["access"]
        refresh = _cache["refresh"]
    if not refresh:
        row = _load()
        if not row or not row["refresh_token_enc"]:
            raise DriveError("Google Drive is not connected. An admin can connect it in the Document Center.", 409)
        refresh = unseal(row["refresh_token_enc"])
    try:
        access, ttl = gdrive_client.refresh_access_token(refresh)
    except DriveError as exc:
        if exc.status == 401:  # Google has revoked it: stop pretending to be connected
            _disconnect_row()
            _forget_tokens()
        raise
    with _cache_lock:
        _cache.update(access=access, expires=time.monotonic() + ttl, refresh=refresh)
    return access


# --------------------------------------------------------------------------------------------------------------------
# The connection


def mode() -> str:
    return gdrive_client.configured_mode()


def _load() -> dict[str, Any] | None:
    with db_cursor() as cur:
        cur.execute(
            """SELECT connected, mode, account_email, refresh_token_enc, oauth_state, oauth_state_expires, bills_mode, bills_folder_id,
                      bills_folder_label, connected_by, connected_timestamp
                 FROM orion_ods.gdrive_connection WHERE id = 1"""
        )
        row = cur.fetchone()
        return dict(zip((c.name for c in cur.description), row)) if row else None


def _connected(row: dict[str, Any] | None) -> bool:
    """Connected, and in the way this server is set up now: a link made to the fake Drive is no use once Google's credentials are added."""
    return bool(row and row["connected"] and row["mode"] == mode())


def status(is_admin: bool) -> dict[str, Any]:
    row = _load()
    now = mode()
    connected = _connected(row)
    return {
        "mode": now,
        "connected": connected,
        "account": row["account_email"] if connected and row else None,
        "connected_at": row["connected_timestamp"].isoformat() if connected and row and row["connected_timestamp"] else None,
        # connected before, but the server was set up differently since: the person is told to connect again, not shown an error
        "reconnect": bool(row and row["connected"] and row["mode"] != now and now != "off"),
        "can_connect": is_admin and now != "off",
        "bills": {
            "mode": row["bills_mode"] if row else "ask",
            "folder_id": row["bills_folder_id"] if row else None,
            "folder_label": row["bills_folder_label"] if row else None,
        },
    }


def _upsert(cur, **values: Any) -> None:
    columns = list(values)
    cur.execute(
        f"""INSERT INTO orion_ods.gdrive_connection (id, {', '.join(columns)}) VALUES (1, {', '.join('%s' for _ in columns)})
            ON CONFLICT (id) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in columns)}""",
        list(values.values()),
    )


def _forget_links_if_other_mode(cur, new_mode: str) -> None:
    """File ids of one Drive mean nothing to the other, so connecting in a different mode forgets the links (the files stay where they are)."""
    cur.execute("SELECT mode FROM orion_ods.gdrive_connection WHERE id = 1")
    row = cur.fetchone()
    if row and row[0] and row[0] != new_mode:
        cur.execute("DELETE FROM orion_ods.drive_link")
        cur.execute("UPDATE orion_ods.gdrive_connection SET bills_folder_id = NULL, bills_folder_label = NULL, bills_mode = 'ask' WHERE id = 1")


def connect(user_id: int | None) -> dict[str, Any]:
    """Connect. The fake Drive is connected at once; with Google's credentials this returns the address to send the person to."""
    now = mode()
    if now == "off":
        raise DriveError("Google Drive is not set up on this server. Add the Google client ID and secret to the .env (see DEPLOYMENT.md).", 409)
    if now == "fake":
        with db_cursor(commit=True) as cur:
            _forget_links_if_other_mode(cur, "fake")
            _upsert(cur, connected=True, mode="fake", account_email=FakeDrive().account(), refresh_token_enc=None, oauth_state=None,
                    oauth_state_expires=None, connected_by=user_id, connected_timestamp=datetime.now(timezone.utc))
        return {"connected": True}
    state = secrets.token_urlsafe(32)
    with db_cursor(commit=True) as cur:
        _upsert(cur, oauth_state=state, oauth_state_expires=datetime.now(timezone.utc) + timedelta(minutes=STATE_MINUTES))
    return {"connected": False, "url": gdrive_client.authorize_url(state)}


def finish_google(code: str, state: str, user_id: int | None) -> None:
    """The person came back from Google with a code: check it was this server that sent them, and keep the long-lasting token."""
    row = _load()
    now = datetime.now(timezone.utc)
    if (mode() != "google" or not row or not row["oauth_state"] or not hmac.compare_digest(row["oauth_state"], state or "")
            or not row["oauth_state_expires"] or row["oauth_state_expires"] < now):
        raise DriveError("That sign-in did not start here, or it took too long. Start again from the Document Center.", 400)
    with db_cursor(commit=True) as cur:  # the state is used once
        cur.execute("UPDATE orion_ods.gdrive_connection SET oauth_state = NULL, oauth_state_expires = NULL WHERE id = 1")
    tokens = gdrive_client.exchange_code(code)
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise DriveError("Google did not give Orion lasting access. Remove Orion at myaccount.google.com/permissions and connect again.", 400)
    access = tokens["access_token"]
    email = GoogleDrive(lambda: access).account()
    with db_cursor(commit=True) as cur:
        _forget_links_if_other_mode(cur, "google")
        _upsert(cur, connected=True, mode="google", account_email=email, refresh_token_enc=seal(refresh), connected_by=user_id,
                connected_timestamp=now)
    with _cache_lock:
        _cache.update(access=access, expires=time.monotonic() + int(tokens.get("expires_in", 3600)), refresh=refresh)


def _disconnect_row() -> None:
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE orion_ods.gdrive_connection SET connected = FALSE, refresh_token_enc = NULL WHERE id = 1")


def disconnect() -> None:
    """Forget the connection and the token. Files in Drive and in Orion stay as they are; the links are kept for when it is connected again."""
    _disconnect_row()
    _forget_tokens()


def save_settings(bills_mode: str, folder_id: Optional[str]) -> dict[str, Any]:
    if bills_mode not in BILLS_MODES:
        raise DriveError("Choose never, ask or always for bills.")
    label = None
    if bills_mode == "on" and not folder_id:
        raise DriveError("Choose the Drive folder bills are saved in.")
    if folder_id:
        c = client()
        label = _label(c, folder_id)
    with db_cursor(commit=True) as cur:
        _upsert(cur, bills_mode=bills_mode, bills_folder_id=folder_id or None, bills_folder_label=label)
    return status(True)


# --------------------------------------------------------------------------------------------------------------------
# Drive itself


def client() -> DriveClient:
    """The Drive, if this server is connected to one; otherwise the reason it cannot be used."""
    now = mode()
    if now == "off":
        raise DriveError("Google Drive is not set up on this server.", 409)
    if not _connected(_load()):
        raise DriveError("Google Drive is not connected. An admin can connect it in the Document Center.", 409)
    return FakeDrive() if now == "fake" else GoogleDrive(_access_token)


def _label(c: DriveClient, folder_id: str) -> str:
    """"My Drive › Clients › Acme": where a folder is, as words."""
    if folder_id == ROOT:
        return "My Drive"
    folder = c.get(folder_id)
    if not folder.is_folder:
        raise DriveError("That is not a folder.")
    return " › ".join(["My Drive", *(item.name for item in c.path(folder_id))])


def browse(folder_id: Optional[str], query: Optional[str], page_token: Optional[str]) -> dict[str, Any]:
    c = client()
    folder = folder_id or ROOT
    items, more = c.list(folder, (query or "").strip() or None, page_token)
    trail = [{"id": ROOT, "name": "My Drive"}]
    if folder != ROOT:
        folder_item = c.get(folder)
        if not folder_item.is_folder:
            raise DriveError("That is not a folder.")
        trail += [{"id": item.id, "name": item.name} for item in c.path(folder)]
    return {
        "folder": folder, "trail": trail, "searching": bool((query or "").strip()), "next": more,
        "folders": [i.as_dict() for i in items if i.is_folder], "files": [i.as_dict() for i in items if not i.is_folder],
        "account": status(False)["account"], "mode": mode(),
    }


def new_folder(parent_id: str, name: str) -> dict[str, Any]:
    return client().create_folder(parent_id or ROOT, name).as_dict()


def rename(file_id: str, name: str) -> dict[str, Any]:
    c = client()
    item = c.rename(file_id, name)
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE orion_ods.drive_link SET name = %s, updated_timestamp = CURRENT_TIMESTAMP WHERE file_id = %s", (item.name, file_id))
    return item.as_dict()


def trash(file_id: str) -> None:
    client().trash(file_id)
    with db_cursor(commit=True) as cur:  # a link to a file that is in the trash is not a link any more
        cur.execute("DELETE FROM orion_ods.drive_link WHERE file_id = %s AND kind = 'document'", (file_id,))
        cur.execute("UPDATE orion_ods.drive_link SET state = 'stopped', last_error = 'The file was moved to the trash in Drive.' WHERE file_id = %s", (file_id,))


def move_item(file_id: str, folder_id: str) -> dict[str, Any]:
    c = client()
    item = c.move(file_id, folder_id or ROOT)
    label = _label(c, item.parent or ROOT)
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE orion_ods.drive_link SET folder_id = %s, folder_label = %s, updated_timestamp = CURRENT_TIMESTAMP WHERE file_id = %s",
                    (item.parent, label, file_id))
    return item.as_dict()


def upload(parent_id: str, name: str, data: bytes, mime: str) -> dict[str, Any]:
    return client().upload(parent_id or ROOT, name, data, mime or "application/octet-stream").as_dict()


def download(file_id: str) -> tuple[str, str, bytes]:
    return client().download(file_id)


# --------------------------------------------------------------------------------------------------------------------
# Links: what is in both places


def web_url(file_id: Optional[str], folder: bool = False) -> Optional[str]:
    """Where a file opens in Google's own page. The fake Drive has no such page."""
    if not file_id or mode() != "google":
        return None
    return f"https://drive.google.com/drive/folders/{file_id}" if folder else f"https://drive.google.com/file/d/{file_id}/view"


def _links(cur, where: str, params: tuple) -> list[dict[str, Any]]:
    cur.execute(
        f"""SELECT link_id, kind, ref, file_id, folder_id, folder_label, name, direction, state, last_error, updated_timestamp
              FROM orion_ods.drive_link WHERE {where} ORDER BY link_id""",
        params,
    )
    out = []
    for link_id, kind, ref, file_id, folder_id, folder_label, name, direction, state, error, updated in cur.fetchall():
        out.append({
            "id": link_id, "kind": kind, "ref": ref, "file_id": file_id, "folder_id": folder_id, "folder_label": folder_label, "name": name,
            "direction": direction, "state": state, "error": error, "updated": updated.isoformat() if updated else None,
            "url": web_url(file_id), "folder_url": web_url(folder_id, True),
        })
    return out


def links_for(kind: str, ref: str) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        return _links(cur, "kind = %s AND ref = %s", (kind, ref))


def _add_link(cur, kind: str, ref: str, item_id: str, folder_id: Optional[str], folder_label: str, name: str, direction: str, version: str, user_id: int | None) -> None:
    cur.execute(
        """INSERT INTO orion_ods.drive_link (kind, ref, file_id, folder_id, folder_label, name, direction, synced_version, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (kind, ref, file_id) WHERE file_id IS NOT NULL DO NOTHING""",
        (kind, ref, item_id, folder_id, folder_label, name, direction, version, user_id),
    )


# --------------------------------------------------------------------------------------------------------------------
# Documents, both ways


def _file_name(title: str, file_name: str) -> str:
    """The name a document gets in Drive: its title, with the file's own extension."""
    ext = file_name.rpartition(".")[2] if "." in file_name else ""
    base = " ".join((title or file_name).split())[:150]
    return base if not ext or base.lower().endswith("." + ext.lower()) else f"{base}.{ext}"


def copy_to_drive(user: dict, document_ids: list[int], folder_id: str, move: bool, allow_confidential: bool) -> dict[str, Any]:
    ids = sorted({int(i) for i in document_ids})
    if not ids:
        raise DriveError("Choose at least one document.")
    if len(ids) > MAX_AT_ONCE:
        raise DriveError(f"Choose at most {MAX_AT_ONCE} documents at a time.")
    c = client()
    folder = folder_id or ROOT
    label = _label(c, folder)
    see_conf = documents.can_see_confidential(user)
    done: list[str] = []
    failed: list[dict[str, str]] = []
    for document_id in ids:
        with db_cursor() as cur:
            cur.execute("SELECT title, confidentiality, source_type, is_deleted FROM orion_ods.document WHERE document_id = %s", (document_id,))
            row = cur.fetchone()
        if not row or (row[1] == "Confidential" and not see_conf):
            failed.append({"name": f"Document {document_id}", "message": "That document does not exist."})
            continue
        title, confidentiality, source_type, deleted = row
        if deleted:
            failed.append({"name": title, "message": "It is in the trash."})
        elif confidentiality == "Confidential" and not allow_confidential:
            failed.append({"name": title, "message": "It is Confidential. Confirm to send it to Google Drive."})
        elif move and source_type:
            failed.append({"name": title, "message": "Orion filed this paper by itself, so it stays in Orion. Copy it instead."})
        else:
            try:
                file = documents.get_file(document_id, None, "downloaded", user["id"], see_conf)
                if file is None:
                    raise DriveError("That document does not exist.")
                item = c.upload(folder, _file_name(title, file["file_name"]), file["data"], file["content_type"])
                with db_cursor(commit=True) as cur:
                    _add_link(cur, DOCUMENT, str(document_id), item.id, folder, label, item.name, "to_drive", str(file["version_no"]), user["id"])
                    documents._log(cur, document_id, "downloaded", f"Copied to Google Drive: {label}", user["id"])
                if move:
                    documents.set_deleted(user["id"], [document_id], True, see_conf)
                done.append(title)
            except DriveError as exc:
                failed.append({"name": title, "message": str(exc)})
    return {"done": len(done), "failed": failed, "to": label, "moved": bool(move)}


def copy_from_drive(user: dict, file_ids: list[str], to_node: str, move: bool) -> dict[str, Any]:
    ids = [str(i) for i in dict.fromkeys(file_ids)]
    if not ids:
        raise DriveError("Choose at least one file.")
    if len(ids) > MAX_AT_ONCE:
        raise DriveError(f"Choose at most {MAX_AT_ONCE} files at a time.")
    c = client()
    with db_cursor() as cur:
        try:
            (scope, case_code, client_code, folder), label = documents_explorer.destination_of(cur, to_node)
        except documents.DocumentCenterError as exc:
            raise DriveError(str(exc)) from exc
    done = 0
    failed: list[dict[str, str]] = []
    for file_id in ids:
        name = file_id
        try:
            item = c.get(file_id)
            name = item.name
            if item.is_folder:
                raise DriveError("A folder cannot be copied as one yet. Open it and choose its files.")
            file_name, _mime, data = c.download(file_id)
            raw = {"scope": scope, "case_code": case_code, "client_code": client_code, "folder_id": folder, "category": "Other",
                   "title": file_name.rpartition(".")[0] or file_name, "description": "Copied from Google Drive"}
            try:
                created = documents.create_document(user["id"], raw, file_name, data)
            except documents.DocumentCenterError as exc:
                raise DriveError(str(exc)) from exc
            with db_cursor(commit=True) as cur:
                _add_link(cur, DOCUMENT, str(created["id"]), item.id, item.parent, "", item.name, "from_drive", "1", user["id"])
            if move:
                c.trash(file_id)
            done += 1
        except DriveError as exc:
            failed.append({"name": name, "message": str(exc)})
    return {"done": done, "failed": failed, "to": label, "moved": bool(move)}


# --------------------------------------------------------------------------------------------------------------------
# Bills


def _bill_version(code: str) -> tuple[str, bool] | None:
    """(what the Drive copy must show, whether the bill is cancelled) or None when there is no such bill."""
    with db_cursor() as cur:
        cur.execute("SELECT version_no, status, font_family, font_size FROM orion_ods.bill WHERE bill_code = %s", (code,))
        row = cur.fetchone()
    if not row:
        return None
    return f"{row[0]}:{row[1]}:{row[2] or ''}:{row[3] or ''}", row[1] == "Cancelled"


def bill_link(code: str) -> dict[str, Any] | None:
    found = links_for(BILL, code)
    return found[0] if found else None


def save_bill(code: str, folder_id: str, user_id: int | None) -> dict[str, Any]:
    """Keep this bill's PDF in a Drive folder, and keep it up to date. Called with the person's choice (or the company's setting)."""
    c = client()
    folder = folder_id or ROOT
    label = _label(c, folder)
    if _bill_version(code) is None:
        raise DriveError("That bill does not exist.")
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT file_id, folder_id FROM orion_ods.drive_link WHERE kind = 'bill' AND ref = %s", (code,))
        existing = cur.fetchone()
        if existing is None:
            cur.execute(
                """INSERT INTO orion_ods.drive_link (kind, ref, folder_id, folder_label, direction, state, created_by)
                   VALUES ('bill', %s, %s, %s, 'to_drive', 'failed', %s)""",
                (code, folder, label, user_id),
            )
        else:
            cur.execute("UPDATE orion_ods.drive_link SET state = 'failed', folder_id = %s, folder_label = %s WHERE kind = 'bill' AND ref = %s", (folder, label, code))
    if existing and existing[0] and existing[1] != folder:
        try:
            c.move(existing[0], folder)  # the same file, in the new folder
        except DriveError as exc:
            logger.info("The bill's Drive file could not be moved (%s); it is saved again in the new folder", exc.status)
            with db_cursor(commit=True) as cur:
                cur.execute("UPDATE orion_ods.drive_link SET file_id = NULL, synced_version = NULL WHERE kind = 'bill' AND ref = %s", (code,))
    return sync_bill(code) or {}


def sync_bill(code: str) -> dict[str, Any] | None:
    """Make the Drive copy of a bill show what the bill shows now. Returns the link; None when the bill is not saved to Drive (or is stopped)."""
    from app import receivables

    with db_cursor() as cur:
        cur.execute("SELECT file_id, folder_id, synced_version, state, name FROM orion_ods.drive_link WHERE kind = 'bill' AND ref = %s", (code,))
        link = cur.fetchone()
    if link is None or link[3] == "stopped":
        return None
    file_id, folder_id, synced, state, _name = link
    wanted = _bill_version(code)
    if wanted is None:
        return None
    version, cancelled = wanted
    if file_id and synced == version and state == "synced":
        return bill_link(code)
    try:
        c = client()
        made = receivables.invoice_document(code, False)
        if made is None:
            raise DriveError("That bill does not exist.")
        name, data = made
        if cancelled:
            name = f"{name.removesuffix('.pdf')} (cancelled).pdf"
        try:
            item = c.replace(file_id, data, "application/pdf", name) if file_id else c.upload(folder_id or ROOT, name, data, "application/pdf")
        except DriveError as exc:
            if not file_id or exc.status != 404:
                raise
            item = c.upload(folder_id or ROOT, name, data, "application/pdf")  # somebody removed it from Drive: put it back
        outcome: tuple = ("synced", None, item.id, item.name, version)
    except DriveError as exc:
        outcome = ("failed", str(exc), file_id, None, synced)
    with db_cursor(commit=True) as cur:
        cur.execute(
            """UPDATE orion_ods.drive_link SET state = %s, last_error = %s, file_id = %s, name = COALESCE(%s, name), synced_version = %s,
                      updated_timestamp = CURRENT_TIMESTAMP WHERE kind = 'bill' AND ref = %s""",
            (*outcome, code),
        )
    return bill_link(code)


def sync_bill_quietly(code: str) -> None:
    """After a bill was saved: bring its Drive copy up to date. A problem is kept on the link, shown on the bill and retried by "Try again"; it never reaches the save."""
    try:
        sync_bill(code)
    except Exception:  # noqa: BLE001 - the bill is saved; Drive is a copy
        logger.exception("Saving bill %s to Google Drive failed", code)


def stop_bill(code: str) -> None:
    """Stop keeping a bill's Drive copy up to date. The file stays in Drive as it is."""
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE orion_ods.drive_link SET state = 'stopped', updated_timestamp = CURRENT_TIMESTAMP WHERE kind = 'bill' AND ref = %s", (code,))


def after_bill_created(code: str, save: Optional[bool], folder_id: Optional[str], user_id: int | None) -> None:
    """What a new bill does about Drive: the person's tick (save, or not), else the company's setting. Never raises."""
    try:
        row = _load()
        if not _connected(row):
            return
        if save is False:
            return
        folder = folder_id or (row["bills_folder_id"] if row and row["bills_mode"] == "on" else None)
        if save is True or (save is None and row and row["bills_mode"] == "on"):
            if folder:
                save_bill(code, folder, user_id)
    except Exception:  # noqa: BLE001 - a bill is never held up by Drive
        logger.exception("Saving the new bill %s to Google Drive failed", code)
