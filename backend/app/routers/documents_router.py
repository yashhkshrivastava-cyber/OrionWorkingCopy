"""The Document Center API. Reading needs Documents access, changing needs permission to change documents."""

from datetime import date
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel

from app import documents, documents_explorer, documents_filing
from app.ai import features as ai_features
from app.dependencies import require_documents, require_documents_write

router = APIRouter(prefix="/documents", tags=["documents"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That document does not exist.")


def _bad(exc: documents.DocumentCenterError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _read(file: UploadFile) -> bytes:
    # One byte more than the limit is read, so a file that is too big is refused without reading the rest of it.
    return file.file.read(documents.MAX_BYTES + 1)


class DocumentChanges(BaseModel):
    """Any of these may be sent; only what is sent is changed."""

    title: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = None
    confidentiality: Optional[str] = None
    document_date: Optional[str] = None
    expiry_date: Optional[str] = None
    reminder_days: Optional[int] = None
    folder_id: Optional[int] = None
    scope: Optional[str] = None
    case_code: Optional[str] = None
    client_code: Optional[str] = None


class BulkRequest(BaseModel):
    ids: list[int]
    action: str
    folder_id: Optional[int] = None
    status: Optional[str] = None


class FolderRequest(BaseModel):
    scope: str
    case_code: Optional[str] = None
    client_code: Optional[str] = None
    parent_id: Optional[int] = None
    name: Optional[str] = None


class FolderTreeRequest(BaseModel):
    scope: str
    case_code: Optional[str] = None
    client_code: Optional[str] = None
    parent_id: Optional[int] = None
    paths: list[str]


class FolderRename(BaseModel):
    name: str


@router.get("/options")
def options(_user=Depends(require_documents)):
    return documents.options()


@router.post("/ai/suggest")
def suggest_details(
    scope: str = Form(...),
    allow_cloud_once: bool = Form(False),
    file: UploadFile = File(...),
    user=Depends(require_documents_write),
):
    """Reads a file the person is about to keep and suggests its title, category, tags and dates. Nothing is saved."""
    if scope not in documents.CATEGORIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose where the document belongs first.")
    data = _read(file)
    if len(data) > documents.MAX_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"That file is larger than {documents.MAX_BYTES // (1024 * 1024)} MB.")
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The file is empty.")
    return ai_features.suggest_document(
        user, filename=file.filename or "document", data=data, categories=list(documents.CATEGORIES[scope]), allow_cloud_once=allow_cloud_once
    )


@router.get("/overview")
def overview(user=Depends(require_documents)):
    return documents.overview(documents.can_see_confidential(user))


@router.get("/spaces")
def spaces(user=Depends(require_documents)):
    return documents.spaces(documents.can_see_confidential(user))


@router.get("/targets")
def targets(q: str = Query(default="", max_length=100), _user=Depends(require_documents)):
    return documents.targets(q)


@router.get("/items")
def list_items(
    q: str = Query(default="", max_length=200),
    scope: Optional[str] = None,
    case_code: Optional[str] = None,
    client_code: Optional[str] = None,
    folder_id: Optional[str] = None,
    category: Optional[str] = None,
    doc_status: Optional[str] = Query(default=None, alias="status"),
    confidentiality: Optional[str] = None,
    tag: Optional[str] = None,
    expiry: Optional[str] = None,
    trash: bool = False,
    sort: str = "updated",
    direction: str = "desc",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_documents),
):
    if folder_id not in (None, "", "none") and not str(folder_id).isdigit():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That folder does not exist.")
    filters = {
        "q": q, "scope": scope, "case_code": case_code, "client_code": client_code, "folder_id": folder_id,
        "category": category, "status": doc_status, "confidentiality": confidentiality, "tag": tag, "expiry": expiry,
        "trash": trash, "sort": sort, "direction": direction,
    }
    try:
        return documents.search_documents(filters, documents.can_see_confidential(user), limit, offset)
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc


@router.post("/items", status_code=status.HTTP_201_CREATED)
def upload_item(
    scope: str = Form(...),
    case_code: str = Form(""),
    client_code: str = Form(""),
    folder_id: str = Form(""),
    title: str = Form(""),
    category: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    doc_status: str = Form("", alias="status"),
    confidentiality: str = Form(""),
    document_date: str = Form(""),
    expiry_date: str = Form(""),
    reminder_days: str = Form(""),
    file: UploadFile = File(...),
    user=Depends(require_documents_write),
):
    raw = {
        "scope": scope, "case_code": case_code, "client_code": client_code, "folder_id": folder_id, "title": title,
        "category": category, "description": description, "tags": tags, "document_date": document_date,
        "expiry_date": expiry_date,
    }
    # A blank status, confidentiality or reminder means "the usual", which create_document fills in.
    for key, value in (("status", doc_status), ("confidentiality", confidentiality), ("reminder_days", reminder_days)):
        if value.strip():
            raw[key] = value.strip()
    data = _read(file)
    try:
        return documents.create_document(user["id"], raw, file.filename, data)
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc


@router.get("/items/{document_id}")
def get_item(document_id: int, user=Depends(require_documents)):
    found = documents.get_document(document_id, documents.can_see_confidential(user))
    if found is None:
        raise _not_found()
    return found


@router.patch("/items/{document_id}")
def update_item(document_id: int, body: DocumentChanges, user=Depends(require_documents_write)):
    sent = body.model_dump(exclude_unset=True)
    try:
        if not documents.update_document(user["id"], document_id, sent, documents.can_see_confidential(user)):
            raise _not_found()
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc
    return {"ok": True}


@router.delete("/items/{document_id}")
def delete_item(document_id: int, user=Depends(require_documents_write)):
    try:
        if not documents.set_deleted(user["id"], [document_id], True, documents.can_see_confidential(user)):
            raise _not_found()
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc
    return {"ok": True}


@router.post("/items/{document_id}/restore")
def restore_item(document_id: int, user=Depends(require_documents_write)):
    if not documents.set_deleted(user["id"], [document_id], False, documents.can_see_confidential(user)):
        raise _not_found()
    return {"ok": True}


@router.delete("/items/{document_id}/purge")
def purge_item(document_id: int, user=Depends(require_documents_write)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only an admin can delete a document for good.")
    try:
        if not documents.purge_document(document_id, True):
            raise _not_found()
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc
    return {"ok": True}


@router.post("/items/{document_id}/versions", status_code=status.HTTP_201_CREATED)
def upload_version(
    document_id: int,
    note: str = Form(""),
    file: UploadFile = File(...),
    user=Depends(require_documents_write),
):
    data = _read(file)
    try:
        number = documents.add_version(user["id"], document_id, file.filename, data, note, documents.can_see_confidential(user))
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc
    if number is None:
        raise _not_found()
    return {"version_no": number}


@router.post("/items/{document_id}/versions/{version_no}/restore", status_code=status.HTTP_201_CREATED)
def restore_old_version(document_id: int, version_no: int, user=Depends(require_documents_write)):
    try:
        number = documents.restore_version(user["id"], document_id, version_no, documents.can_see_confidential(user))
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc
    if number is None:
        raise _not_found()
    return {"version_no": number}


@router.get("/items/{document_id}/file")
def item_file(
    document_id: int,
    version: Optional[int] = Query(default=None, ge=1),
    download: bool = Query(default=False),
    user=Depends(require_documents),
):
    found = documents.get_file(document_id, version, "downloaded" if download else "viewed", user["id"],
                               documents.can_see_confidential(user))
    if found is None:
        raise _not_found()
    inline = documents.is_inline(found["content_type"]) and not download
    disposition = "inline" if inline else "attachment"
    return Response(
        content=found["data"],
        media_type=found["content_type"],
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(found['file_name'])}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/bulk")
def bulk(body: BulkRequest, user=Depends(require_documents_write)):
    value = body.status if body.action == "status" else body.folder_id
    try:
        changed = documents.bulk_update(user["id"], body.ids, body.action, value, documents.can_see_confidential(user))
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc
    return {"changed": changed}


@router.get("/folders")
def list_folders(
    scope: str,
    case_code: Optional[str] = None,
    client_code: Optional[str] = None,
    user=Depends(require_documents),
):
    try:
        return documents.list_folders(scope, case_code, client_code, documents.can_see_confidential(user))
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc


@router.post("/folders", status_code=status.HTTP_201_CREATED)
def create_folder(body: FolderRequest, user=Depends(require_documents_write)):
    try:
        return documents.create_folder(user["id"], body.model_dump())
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc


@router.post("/folders/tree")
def create_folder_tree(body: FolderTreeRequest, user=Depends(require_documents_write)):
    """Get or create the folders of a folder being uploaded (``a/b/c`` paths), so the files can then be filed into them."""
    try:
        return documents.ensure_folder_paths(user["id"], body.model_dump())
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc


@router.post("/folders/standard")
def create_standard_folders(body: FolderRequest, user=Depends(require_documents_write)):
    try:
        return {"added": documents.create_standard_folders(user["id"], body.model_dump())}
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc


@router.patch("/folders/{folder_id}")
def rename_folder(folder_id: int, body: FolderRename, _user=Depends(require_documents_write)):
    try:
        found = documents.rename_folder(folder_id, body.name)
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That folder does not exist.")
    return {"ok": True}


class FolderDrop(BaseModel):
    """What the person was shown when they agreed: the folder is only emptied if it still holds exactly this."""

    seen_documents: int
    seen_subfolders: int


@router.get("/folders/{folder_id}/contents")
def folder_contents(folder_id: int, user=Depends(require_documents)):
    """What deleting a folder with everything in it would take away, and whether it may be done."""
    found = documents.folder_contents(folder_id, documents.can_see_confidential(user))
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That folder does not exist.")
    return found


@router.post("/folders/{folder_id}/drop")
def drop_folder(folder_id: int, body: FolderDrop, user=Depends(require_documents_write)):
    """Delete a folder with everything in it: its documents go to the trash, its folders are gone."""
    try:
        return documents.drop_folder(user["id"], folder_id, body.seen_documents, body.seen_subfolders, documents.can_see_confidential(user))
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int, _user=Depends(require_documents_write)):
    try:
        found = documents.delete_folder(folder_id)
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That folder does not exist.")
    return {"ok": True}


@router.post("/filing/update")
def update_filing(_user=Depends(require_documents_write)):
    """File anything that is not yet in the Document Center, bring the filed papers in step with their sources, and report how many."""
    return documents_filing.reconcile()


@router.get("/cases/{case_code}/checklist")
def case_checklist(case_code: str, user=Depends(require_documents)):
    found = documents.case_checklist(case_code, documents.can_see_confidential(user))
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That case does not exist.")
    return {"checklist": found}


# --- The file explorer -------------------------------------------------------------------------------------------------------


class MoveRequest(BaseModel):
    ids: list[int] = []
    folder_ids: list[int] = []
    to: str


class HomeRequest(BaseModel):
    to: Optional[str] = None  # a node; empty puts the paper back where Orion files it by itself


@router.get("/browse")
def browse(
    node: str = "root",
    q: str = Query(default="", max_length=200),
    category: Optional[str] = None,
    doc_status: Optional[str] = Query(default=None, alias="status"),
    tag: Optional[str] = None,
    expiry: Optional[str] = None,
    sort: str = "title",
    direction: str = "asc",
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    folders_only: bool = False,
    user=Depends(require_documents),
):
    """Where ``node`` is, the way back, its folders and its documents. See ``documents_explorer``."""
    filters = {"q": q, "category": category, "status": doc_status, "tag": tag, "expiry": expiry, "sort": sort, "direction": direction}
    try:
        return documents_explorer.browse(node, filters, documents.can_see_confidential(user), limit, offset, folders_only)
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc


@router.post("/move")
def move(body: MoveRequest, user=Depends(require_documents_write)):
    try:
        return documents_explorer.move(user["id"], body.ids, body.folder_ids, body.to, documents.can_see_confidential(user))
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc


@router.get("/source/{source_type}/{source_ref:path}")
def source_locations(source_type: str, source_ref: str, user=Depends(require_documents)):
    """Where a paper Orion filed by itself is kept, for the page it comes from (a bill's page shows it)."""
    found = documents_explorer.locations(source_type, source_ref, documents.can_see_confidential(user))
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That paper is not in the Document Center.")
    return found


@router.put("/source/{source_type}/{source_ref:path}")
def choose_source_home(source_type: str, source_ref: str, body: HomeRequest, user=Depends(require_documents_write)):
    """Keep a paper Orion filed by itself in the folder the person chose, or (no folder) back where Orion files it."""
    try:
        return documents_explorer.choose_for_source(user["id"], source_type, source_ref, body.to, documents.can_see_confidential(user))
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc


@router.get("/filing/preview")
def filing_preview(case_code: str, bill_date: date, to: Optional[str] = None, _user=Depends(require_documents)):
    """Where a bill for this case and day would be filed (with a folder chosen, or by itself), before it is saved."""
    try:
        return {"locations": documents_explorer.bill_preview(case_code, bill_date, to)}
    except documents.DocumentCenterError as exc:
        raise _bad(exc) from exc
