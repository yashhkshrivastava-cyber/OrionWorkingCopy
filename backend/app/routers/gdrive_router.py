"""Google Drive in the Document Center. Reading needs Documents access, changing needs permission to change documents, and connecting,
disconnecting and the company's settings need an admin. See ``app.gdrive``."""

import logging
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app import gdrive
from app.auth import can_write_documents
from app.dependencies import require_admin, require_billing, require_billing_write, require_documents, require_documents_write
from app.gdrive_client import MAX_FILE_BYTES, DriveError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/gdrive", tags=["gdrive"])


def _fail(exc: DriveError) -> HTTPException:
    # Google refusing the connection is not the person's own sign-in failing: a 401 here would sign them out of Orion.
    code = 409 if exc.status == 401 else exc.status if 400 <= exc.status < 600 else 400
    return HTTPException(status_code=code, detail=str(exc))


class SettingsRequest(BaseModel):
    bills_mode: str
    folder_id: Optional[str] = None


class FolderRequest(BaseModel):
    parent_id: Optional[str] = None
    name: str


class FileChange(BaseModel):
    name: Optional[str] = None
    folder_id: Optional[str] = None


class CopyToDrive(BaseModel):
    ids: list[int]
    folder_id: Optional[str] = None
    move: bool = False
    allow_confidential: bool = False


class CopyFromDrive(BaseModel):
    file_ids: list[str]
    to: str
    move: bool = False


class BillRequest(BaseModel):
    folder_id: str


@router.get("/status")
def get_status(user=Depends(require_documents)):
    return gdrive.status(user.get("role") == "admin")


@router.post("/connect")
def connect(user=Depends(require_admin)):
    try:
        return gdrive.connect(user["id"])
    except DriveError as exc:
        raise _fail(exc) from exc


@router.get("/callback")
def callback(code: str = "", state: str = "", error: str = "", user=Depends(require_admin)):
    """Where Google sends the admin back to. Whatever happens, they land on the Drive page, with a short note when it failed."""
    if error:
        return RedirectResponse(f"/documents?node=gdrive&drive_error={quote('Google did not allow the connection.')}", status_code=303)
    try:
        gdrive.finish_google(code, state, user["id"])
    except DriveError as exc:
        return RedirectResponse(f"/documents?node=gdrive&drive_error={quote(str(exc))}", status_code=303)
    return RedirectResponse("/documents?node=gdrive&drive_connected=1", status_code=303)


@router.post("/disconnect")
def disconnect(_user=Depends(require_admin)):
    gdrive.disconnect()
    return {"ok": True}


@router.put("/settings")
def save_settings(body: SettingsRequest, _user=Depends(require_admin)):
    try:
        return gdrive.save_settings(body.bills_mode, body.folder_id)
    except DriveError as exc:
        raise _fail(exc) from exc


@router.get("/browse")
def browse(folder: Optional[str] = None, q: str = Query(default="", max_length=200), page_token: Optional[str] = None, _user=Depends(require_documents)):
    try:
        return gdrive.browse(folder, q, page_token)
    except DriveError as exc:
        raise _fail(exc) from exc


@router.post("/folders", status_code=status.HTTP_201_CREATED)
def new_folder(body: FolderRequest, _user=Depends(require_documents_write)):
    try:
        return gdrive.new_folder(body.parent_id or "root", body.name)
    except DriveError as exc:
        raise _fail(exc) from exc


@router.patch("/files/{file_id}")
def change_file(file_id: str, body: FileChange, _user=Depends(require_documents_write)):
    try:
        if body.folder_id:
            return gdrive.move_item(file_id, body.folder_id)
        if body.name:
            return gdrive.rename(file_id, body.name)
    except DriveError as exc:
        raise _fail(exc) from exc
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Say a new name or a folder to move it to.")


@router.delete("/files/{file_id}")
def trash_file(file_id: str, _user=Depends(require_documents_write)):
    """Moves to Drive's own trash; nothing is deleted for good from Orion."""
    try:
        gdrive.trash(file_id)
    except DriveError as exc:
        raise _fail(exc) from exc
    return {"ok": True}


@router.post("/upload", status_code=status.HTTP_201_CREATED)
def upload(parent_id: str = Form("root"), file: UploadFile = File(...), _user=Depends(require_documents_write)):
    data = file.file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"That file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The file is empty.")
    try:
        return gdrive.upload(parent_id, file.filename or "file", data, file.content_type or "")
    except DriveError as exc:
        raise _fail(exc) from exc


@router.get("/files/{file_id}/download")
def download(file_id: str, _user=Depends(require_documents)):
    try:
        name, mime, data = gdrive.download(file_id)
    except DriveError as exc:
        raise _fail(exc) from exc
    # Always a download, never drawn by the browser: a file from Drive is not trusted to be what its name says.
    return Response(
        content=data, media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}", "X-Content-Type-Options": "nosniff", "X-Drive-Type": quote(mime)},
    )


@router.post("/copy-to-drive")
def copy_to_drive(body: CopyToDrive, user=Depends(require_documents_write)):
    try:
        return gdrive.copy_to_drive(user, body.ids, body.folder_id or "root", body.move, body.allow_confidential)
    except DriveError as exc:
        raise _fail(exc) from exc


@router.post("/copy-from-drive")
def copy_from_drive(body: CopyFromDrive, user=Depends(require_documents_write)):
    try:
        return gdrive.copy_from_drive(user, body.file_ids, body.to, body.move)
    except DriveError as exc:
        raise _fail(exc) from exc


@router.get("/links")
def links(kind: str = Query(pattern="^(bill|document)$"), ref: str = Query(max_length=60), _user=Depends(require_documents)):
    return {"links": gdrive.links_for(kind, ref)}


# --- Bills ---------------------------------------------------------------------------------------------------------------


def _bill_writer(user) -> None:
    if not can_write_documents(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You may change bills but not choose where documents are kept.")


@router.get("/bills/{bill_code}")
def bill_link(bill_code: str, _user=Depends(require_billing)):
    return {"link": gdrive.bill_link(bill_code)}


@router.put("/bills/{bill_code}")
def save_bill(bill_code: str, body: BillRequest, user=Depends(require_billing_write)):
    """Keep this bill in a Drive folder (a new folder moves the file there), and make the file show the bill as it is now."""
    _bill_writer(user)
    try:
        return {"link": gdrive.save_bill(bill_code, body.folder_id, user["id"])}
    except DriveError as exc:
        raise _fail(exc) from exc


@router.post("/bills/{bill_code}/sync")
def sync_bill(bill_code: str, user=Depends(require_billing_write)):
    _bill_writer(user)
    return {"link": gdrive.sync_bill(bill_code)}


@router.delete("/bills/{bill_code}")
def stop_bill(bill_code: str, user=Depends(require_billing_write)):
    """Stop keeping the bill's Drive copy up to date. The file stays in Drive."""
    _bill_writer(user)
    gdrive.stop_bill(bill_code)
    return {"link": gdrive.bill_link(bill_code)}

