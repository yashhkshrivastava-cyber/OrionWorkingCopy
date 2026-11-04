"""The only code that talks to a Google Drive.

Everything else in Orion (``gdrive.py``, the router) asks a ``DriveClient`` for files and never knows which one it has:

* ``FakeDrive``    a Drive kept in ``data/fake-drive`` on this computer, with folders, files, renames and a trash, so the whole feature can be
                   built, shown and tested with no Google account. It is for development; production refuses it (``startup_checks``).
* ``GoogleDrive``  the real thing, over Google's Drive REST API (v3) with an OAuth access token.

Which one is used is decided in one place, ``configured_mode()``: add ``ORION_GOOGLE_CLIENT_ID`` and ``ORION_GOOGLE_CLIENT_SECRET`` to the
``.env`` (see DEPLOYMENT.md, "Google Drive") and restart, and the fake Drive is replaced by Google's; nothing else changes.

Orion asks Google for the ``drive`` scope, because browsing the folders that are already there needs it, and uses it only for what a person
does on the Document Center or chooses for a bill. A file is only ever sent or fetched by the server, so nothing from Google reaches the
browser (the Content-Security-Policy needs no new host), and a person's request never carries a Google token.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import ssl
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlencode

import httpx

from app.config import env
from app.startup_checks import is_production

logger = logging.getLogger(__name__)

FOLDER = "application/vnd.google-apps.folder"
ROOT = "root"  # the top of My Drive, in both Drives
MAX_PAGE = 200
MAX_FILE_BYTES = 300 * 1024 * 1024  # the Document Center's own limit: nothing larger is moved either way

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive"

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# A Google Doc, Sheet or Slides has no file of its own; it is exported when it is copied out. (mime of the export, extension)
EXPORTS = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (XLSX, ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}


class DriveError(Exception):
    """Drive could not do it. The message is safe to show to the user (never a token, a URL with a secret, or a Google response body)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Item:
    """A file or folder in Drive."""

    id: str
    name: str
    mime: str
    size: Optional[int]
    modified: Optional[str]
    parent: Optional[str]
    url: Optional[str] = None

    @property
    def is_folder(self) -> bool:
        return self.mime == FOLDER

    @property
    def exportable(self) -> bool:
        return self.mime in EXPORTS

    @property
    def copyable(self) -> bool:
        """A real file or a Google document that can be exported; a shortcut, form or map cannot be copied out."""
        return not self.is_folder and (not self.mime.startswith("application/vnd.google-apps.") or self.exportable)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "mime": self.mime, "size": self.size, "modified": self.modified, "url": self.url,
            "is_folder": self.is_folder, "copyable": self.copyable,
        }


def clean_name(name: Any) -> str:
    text = " ".join(str(name or "").replace("/", "-").replace("\\", "-").split())
    if not text:
        raise DriveError("Give it a name.")
    return text[:200]


class DriveClient:
    """What Orion needs of a Drive. Both implementations answer these and nothing else."""

    mode = ""

    def account(self) -> str:
        raise NotImplementedError

    def list(self, folder_id: str, query: Optional[str] = None, page_token: Optional[str] = None) -> tuple[list[Item], Optional[str]]:
        """The folders and files in a folder (or, with ``query``, those anywhere whose name matches), folders first; and a token for more."""
        raise NotImplementedError

    def get(self, file_id: str) -> Item:
        raise NotImplementedError

    def path(self, file_id: str) -> list[Item]:
        """The folders from the top of My Drive down to ``file_id`` (a folder), not counting the top itself."""
        raise NotImplementedError

    def create_folder(self, parent_id: str, name: str) -> Item:
        raise NotImplementedError

    def upload(self, parent_id: str, name: str, data: bytes, mime: str) -> Item:
        raise NotImplementedError

    def replace(self, file_id: str, data: bytes, mime: str, name: Optional[str] = None) -> Item:
        """New content for a file that is already there (and, when ``name`` is given, a new name)."""
        raise NotImplementedError

    def rename(self, file_id: str, name: str) -> Item:
        raise NotImplementedError

    def move(self, file_id: str, new_parent_id: str) -> Item:
        """Put a file or folder in another folder."""
        raise NotImplementedError

    def trash(self, file_id: str) -> None:
        """Move to Drive's own trash (which Google empties after 30 days). Nothing is ever deleted for good from here."""
        raise NotImplementedError

    def download(self, file_id: str) -> tuple[str, str, bytes]:
        """(name, mime, bytes) of a file; a Google Doc, Sheet or Slides is exported (the name gets the export's extension)."""
        raise NotImplementedError


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def exported_name(item: Item) -> tuple[str, str]:
    """(file name, mime) a copied-out file will have."""
    if item.exportable:
        mime, ext = EXPORTS[item.mime]
        return (item.name if item.name.lower().endswith(ext) else item.name + ext), mime
    return item.name, item.mime


# --------------------------------------------------------------------------------------------------------------------
# The fake Drive


def fake_drive_dir() -> Path:
    return Path(env("ORION_FAKE_DRIVE_DIR", "") or Path(__file__).resolve().parents[2] / "data" / "fake-drive")


class FakeDrive(DriveClient):
    """A Drive on this computer: ``index.json`` (what is where) and ``blobs/<id>`` (the bytes). One lock; written whole each time."""

    mode = "fake"
    _lock = threading.Lock()

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.dir = Path(directory) if directory else fake_drive_dir()

    # -- storage
    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            return json.loads((self.dir / "index.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise DriveError("The fake Drive's index cannot be read. Delete the data/fake-drive folder to start it again.", 500) from exc

    def _save(self, index: dict[str, dict[str, Any]]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        temp = self.dir / "index.json.tmp"
        temp.write_text(json.dumps(index), encoding="utf-8")
        os.replace(temp, self.dir / "index.json")

    def _blob(self, file_id: str) -> Path:
        return self.dir / "blobs" / file_id

    @staticmethod
    def _item(file_id: str, raw: dict[str, Any]) -> Item:
        return Item(file_id, raw["name"], raw["mime"], raw.get("size"), raw["modified"], raw["parent"], f"https://drive.fake.orion.local/file/{file_id}")

    def _found(self, index: dict[str, dict[str, Any]], file_id: str) -> dict[str, Any]:
        raw = index.get(file_id)
        if raw is None or raw.get("trashed"):
            raise DriveError("That file or folder is no longer in Drive.", 404)
        return raw

    def _parent_ok(self, index: dict[str, dict[str, Any]], parent_id: str) -> None:
        if parent_id != ROOT and not (self._found(index, parent_id)["mime"] == FOLDER):
            raise DriveError("That is not a folder.", 400)

    # -- the interface
    def account(self) -> str:
        return "fake-drive@orion.local"

    def list(self, folder_id: str, query: Optional[str] = None, page_token: Optional[str] = None) -> tuple[list[Item], Optional[str]]:
        with self._lock:
            index = self._load()
            if folder_id != ROOT and not query:
                self._found(index, folder_id)
            words = [w for w in (query or "").lower().split() if w]
            found = [
                self._item(i, raw) for i, raw in index.items()
                if not raw.get("trashed") and (all(w in raw["name"].lower() for w in words) if words else raw["parent"] == folder_id)
            ]
        found.sort(key=lambda it: (not it.is_folder, it.name.lower()))
        start = int(page_token or 0)
        page = found[start:start + MAX_PAGE]
        return page, (str(start + MAX_PAGE) if start + MAX_PAGE < len(found) else None)

    def get(self, file_id: str) -> Item:
        if file_id == ROOT:
            return Item(ROOT, "My Drive", FOLDER, None, None, None)
        with self._lock:
            index = self._load()
            return self._item(file_id, self._found(index, file_id))

    def path(self, file_id: str) -> list[Item]:
        out: list[Item] = []
        with self._lock:
            index = self._load()
            current: Optional[str] = file_id
            while current and current != ROOT and len(out) < 30:
                out.insert(0, self._item(current, self._found(index, current)))
                current = index[current]["parent"]
        return out

    def create_folder(self, parent_id: str, name: str) -> Item:
        name = clean_name(name)
        with self._lock:
            index = self._load()
            self._parent_ok(index, parent_id)
            file_id = "f" + uuid.uuid4().hex[:20]
            index[file_id] = {"name": name, "mime": FOLDER, "parent": parent_id, "modified": _now(), "size": None}
            self._save(index)
            return self._item(file_id, index[file_id])

    def upload(self, parent_id: str, name: str, data: bytes, mime: str) -> Item:
        name = clean_name(name)
        if len(data) > MAX_FILE_BYTES:
            raise DriveError(f"That file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
        with self._lock:
            index = self._load()
            self._parent_ok(index, parent_id)
            file_id = "f" + uuid.uuid4().hex[:20]
            self._blob(file_id).parent.mkdir(parents=True, exist_ok=True)
            self._blob(file_id).write_bytes(data)
            index[file_id] = {"name": name, "mime": mime or "application/octet-stream", "parent": parent_id, "modified": _now(), "size": len(data)}
            self._save(index)
            return self._item(file_id, index[file_id])

    def replace(self, file_id: str, data: bytes, mime: str, name: Optional[str] = None) -> Item:
        with self._lock:
            index = self._load()
            raw = self._found(index, file_id)
            if raw["mime"] == FOLDER:
                raise DriveError("That is a folder.")
            self._blob(file_id).write_bytes(data)
            raw.update(size=len(data), modified=_now(), mime=mime or raw["mime"])
            if name:
                raw["name"] = clean_name(name)
            self._save(index)
            return self._item(file_id, raw)

    def rename(self, file_id: str, name: str) -> Item:
        name = clean_name(name)
        with self._lock:
            index = self._load()
            raw = self._found(index, file_id)
            raw.update(name=name, modified=_now())
            self._save(index)
            return self._item(file_id, raw)

    def move(self, file_id: str, new_parent_id: str) -> Item:
        with self._lock:
            index = self._load()
            raw = self._found(index, file_id)
            self._parent_ok(index, new_parent_id)
            parent: Optional[str] = new_parent_id
            while parent and parent != ROOT:  # not into itself
                if parent == file_id:
                    raise DriveError("A folder cannot be moved into itself.")
                parent = index.get(parent, {}).get("parent")
            raw.update(parent=new_parent_id, modified=_now())
            self._save(index)
            return self._item(file_id, raw)

    def trash(self, file_id: str) -> None:
        with self._lock:
            index = self._load()
            self._found(index, file_id)
            index[file_id]["trashed"] = True
            self._save(index)

    def download(self, file_id: str) -> tuple[str, str, bytes]:
        with self._lock:
            index = self._load()
            raw = self._found(index, file_id)
            if raw["mime"] == FOLDER:
                raise DriveError("A folder cannot be downloaded.")
            try:
                return raw["name"], raw["mime"], self._blob(file_id).read_bytes()
            except FileNotFoundError as exc:
                raise DriveError("That file's content is missing from the fake Drive.", 404) from exc


# --------------------------------------------------------------------------------------------------------------------
# Google's Drive


def _escape(value: str) -> str:
    """A string inside a Drive search query."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDrive(DriveClient):
    """Google's Drive v3 over REST. ``token`` gives a fresh access token each time it is called."""

    mode = "google"

    def __init__(self, token: Callable[[], str], http: Optional[httpx.Client] = None) -> None:
        self.token = token
        # The computer's own certificate store, as the browser here uses; certificates are still checked.
        self.http = http or httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0), verify=ssl.create_default_context())
        self._root: Optional[str] = None

    # -- the one place a request is made
    def _call(self, method: str, url: str, *, expect: tuple[int, ...] = (200,), **kwargs: Any) -> httpx.Response:
        extra = kwargs.pop("headers", {})
        for attempt in range(3):
            try:
                response = self.http.request(method, url, headers={"Authorization": f"Bearer {self.token()}", **extra}, **kwargs)
            except httpx.HTTPError as exc:
                logger.warning("Google Drive could not be reached: %s", type(exc).__name__)
                raise DriveError("Google Drive could not be reached. Check the internet connection and try again.", 502) from exc
            if response.status_code in expect:
                return response
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
            break
        raise _error(response)

    @staticmethod
    def _item(raw: dict[str, Any]) -> Item:
        parents = raw.get("parents") or []
        return Item(raw["id"], raw.get("name") or "", raw.get("mimeType") or "", int(raw["size"]) if raw.get("size") else None,
                    raw.get("modifiedTime"), parents[0] if parents else None, raw.get("webViewLink"))

    FIELDS = "id,name,mimeType,size,modifiedTime,parents,webViewLink"

    def account(self) -> str:
        body = self._call("GET", f"{API}/about", params={"fields": "user(emailAddress)"}).json()
        return str((body.get("user") or {}).get("emailAddress") or "")

    def root_id(self) -> str:
        if self._root is None:
            self._root = self._call("GET", f"{API}/files/root", params={"fields": "id"}).json()["id"]
        return self._root

    def list(self, folder_id: str, query: Optional[str] = None, page_token: Optional[str] = None) -> tuple[list[Item], Optional[str]]:
        words = [w for w in (query or "").split() if w][:6]
        if words:
            terms = " and ".join(f"(name contains '{_escape(w)}' or fullText contains '{_escape(w)}')" for w in words)
            q = f"{terms} and trashed = false"
        else:
            q = f"'{_escape(folder_id)}' in parents and trashed = false"
        params = {
            "q": q, "pageSize": MAX_PAGE, "orderBy": "folder,name", "fields": f"nextPageToken,files({self.FIELDS})",
            "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        body = self._call("GET", f"{API}/files", params=params).json()
        return [self._item(raw) for raw in body.get("files", [])], body.get("nextPageToken")

    def get(self, file_id: str) -> Item:
        return self._item(self._call("GET", f"{API}/files/{file_id}", params={"fields": self.FIELDS, "supportsAllDrives": "true"}).json())

    def path(self, file_id: str) -> list[Item]:
        top = self.root_id()
        out: list[Item] = []
        current: Optional[str] = file_id
        while current and current not in (ROOT, top) and len(out) < 30:
            item = self.get(current)
            out.insert(0, item)
            current = item.parent
        return out

    def create_folder(self, parent_id: str, name: str) -> Item:
        body = {"name": clean_name(name), "mimeType": FOLDER, "parents": [parent_id]}
        return self._item(self._call("POST", f"{API}/files", params={"fields": self.FIELDS, "supportsAllDrives": "true"}, json=body, expect=(200, 201)).json())

    @staticmethod
    def _multipart(metadata: dict[str, Any], data: bytes, mime: str) -> tuple[bytes, str]:
        boundary = "orion" + secrets.token_hex(12)
        head = f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(metadata)}\r\n"
        part = f"--{boundary}\r\nContent-Type: {mime or 'application/octet-stream'}\r\n\r\n"
        return head.encode() + part.encode() + data + f"\r\n--{boundary}--".encode(), f"multipart/related; boundary={boundary}"

    def upload(self, parent_id: str, name: str, data: bytes, mime: str) -> Item:
        if len(data) > MAX_FILE_BYTES:
            raise DriveError(f"That file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
        content, content_type = self._multipart({"name": clean_name(name), "parents": [parent_id]}, data, mime)
        response = self._call(
            "POST", f"{UPLOAD}/files", params={"uploadType": "multipart", "fields": self.FIELDS, "supportsAllDrives": "true"},
            content=content, headers={"Content-Type": content_type}, expect=(200, 201),
        )
        return self._item(response.json())

    def replace(self, file_id: str, data: bytes, mime: str, name: Optional[str] = None) -> Item:
        content, content_type = self._multipart({"name": clean_name(name)} if name else {}, data, mime)
        response = self._call(
            "PATCH", f"{UPLOAD}/files/{file_id}", params={"uploadType": "multipart", "fields": self.FIELDS, "supportsAllDrives": "true"},
            content=content, headers={"Content-Type": content_type},
        )
        return self._item(response.json())

    def rename(self, file_id: str, name: str) -> Item:
        response = self._call("PATCH", f"{API}/files/{file_id}", params={"fields": self.FIELDS, "supportsAllDrives": "true"}, json={"name": clean_name(name)})
        return self._item(response.json())

    def move(self, file_id: str, new_parent_id: str) -> Item:
        current = self.get(file_id)
        params = {"addParents": new_parent_id, "fields": self.FIELDS, "supportsAllDrives": "true"}
        if current.parent:
            params["removeParents"] = current.parent
        return self._item(self._call("PATCH", f"{API}/files/{file_id}", params=params, json={}).json())

    def trash(self, file_id: str) -> None:
        self._call("PATCH", f"{API}/files/{file_id}", params={"supportsAllDrives": "true"}, json={"trashed": True})

    def download(self, file_id: str) -> tuple[str, str, bytes]:
        item = self.get(file_id)
        if item.is_folder:
            raise DriveError("A folder cannot be downloaded.")
        if item.exportable:
            name, mime = exported_name(item)
            data = self._call("GET", f"{API}/files/{file_id}/export", params={"mimeType": mime}).content
        elif item.copyable:
            name, mime = item.name, item.mime
            data = self._call("GET", f"{API}/files/{file_id}", params={"alt": "media", "supportsAllDrives": "true"}).content
        else:
            raise DriveError("That kind of Google file (a shortcut, form or map) cannot be copied out of Drive.")
        if len(data) > MAX_FILE_BYTES:
            raise DriveError(f"That file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
        return name, mime, data


def _error(response: httpx.Response) -> DriveError:
    """What went wrong, from Google's answer, in words that are safe to show. The body is only read for its message, and is never logged."""
    status = response.status_code
    reason = ""
    try:
        error = response.json().get("error")
        reason = str(error.get("message") if isinstance(error, dict) else error or "")[:200]
    except (ValueError, AttributeError):
        pass
    logger.warning("Google Drive answered %s", status)
    if status == 401:
        return DriveError("Google no longer accepts the connection. An admin needs to connect Google Drive again.", 401)
    if status == 403:
        return DriveError(f"Google would not allow that{': ' + reason if reason else '.'}", 403)
    if status == 404:
        return DriveError("That file or folder is no longer in Drive.", 404)
    if status == 429:
        return DriveError("Google Drive is busy. Try again in a minute.", 429)
    return DriveError(f"Google Drive could not do that{': ' + reason if reason else '.'}", 502 if status >= 500 else 400)


# --------------------------------------------------------------------------------------------------------------------
# Which Drive, and signing in to Google


def google_credentials() -> tuple[str, str]:
    return env("ORION_GOOGLE_CLIENT_ID").strip(), env("ORION_GOOGLE_CLIENT_SECRET").strip()


def configured_mode(environ: Optional[dict[str, str]] = None) -> str:
    """"google", "fake" or "off". ORION_GDRIVE can force one; otherwise Google's when its credentials are in the .env, the fake Drive
    on a development computer, and nothing in production (a fake Drive there would look real and keep people's files on one PC)."""
    source = os.environ if environ is None else environ
    wanted = (source.get("ORION_GDRIVE") or "auto").strip().lower()
    if wanted in ("off", "fake", "google"):
        return wanted
    if (source.get("ORION_GOOGLE_CLIENT_ID") or "").strip() and (source.get("ORION_GOOGLE_CLIENT_SECRET") or "").strip():
        return "google"
    return "off" if is_production(source) else "fake"


def redirect_uri() -> str:
    """Where Google sends the person back to: this server's own address (ORION_APP_URL, as the password-reset mail uses)."""
    return env("ORION_APP_URL", "http://localhost:5173").rstrip("/") + "/api/gdrive/callback"


def authorize_url(state: str) -> str:
    client_id, _ = google_credentials()
    query = {
        "client_id": client_id, "redirect_uri": redirect_uri(), "response_type": "code", "scope": SCOPE, "state": state,
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
    }
    return f"{AUTH_URL}?{urlencode(query)}"


def _token_request(form: dict[str, str], http: Optional[httpx.Client] = None) -> dict[str, Any]:
    client = http or httpx.Client(timeout=httpx.Timeout(30.0, connect=15.0), verify=ssl.create_default_context())
    try:
        response = client.post(TOKEN_URL, data=form)
    except httpx.HTTPError as exc:
        raise DriveError("Google could not be reached. Check the internet connection and try again.", 502) from exc
    finally:
        if http is None:
            client.close()
    if response.status_code != 200:
        try:
            code = str(response.json().get("error") or "")
        except ValueError:
            code = ""
        logger.warning("Google's token service answered %s %s", response.status_code, code)
        if code == "invalid_grant":
            raise DriveError("Google no longer accepts the connection. An admin needs to connect Google Drive again.", 401)
        raise DriveError("Google would not sign Orion in. Check the client ID and secret in the .env.", 400)
    return response.json()


def exchange_code(code: str, http: Optional[httpx.Client] = None) -> dict[str, Any]:
    """The tokens Google gives for the code it sent back: {"refresh_token", "access_token", "expires_in"}."""
    client_id, client_secret = google_credentials()
    return _token_request(
        {"code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri(), "grant_type": "authorization_code"}, http
    )


def refresh_access_token(refresh_token: str, http: Optional[httpx.Client] = None) -> tuple[str, int]:
    client_id, client_secret = google_credentials()
    body = _token_request({"refresh_token": refresh_token, "client_id": client_id, "client_secret": client_secret, "grant_type": "refresh_token"}, http)
    return body["access_token"], int(body.get("expires_in", 3600))
