from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status

from app import documents_filing, employee_documents as documents
from app.dependencies import require_ods_write

router = APIRouter(prefix="/employees", tags=["employee documents"])


def _no_employee() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That employee does not exist.")


def _no_document() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That document does not exist.")


def _options() -> dict:
    return {
        "types": list(documents.DOC_TYPES),
        "accepted": documents.ACCEPTED,
        "max_mb": documents.MAX_BYTES // (1024 * 1024),
    }


@router.get("/document-options")
def document_options(_user=Depends(require_ods_write)):
    """The kinds of document and file that can be uploaded, for the Add screen where there is no employee yet."""
    return _options()


@router.get("/{employee_code}/documents")
def list_documents(employee_code: str, _user=Depends(require_ods_write)):
    found = documents.list_documents(employee_code)
    if found is None:
        raise _no_employee()
    return {"documents": found, **_options()}


@router.post("/{employee_code}/documents", status_code=status.HTTP_201_CREATED)
def upload_document(
    employee_code: str,
    doc_type: str = Form(...),
    title: str = Form(""),
    file: UploadFile = File(...),
    user=Depends(require_ods_write),
):
    # One byte more than the limit is read, so a file that is too big is refused without reading the rest of it.
    data = file.file.read(documents.MAX_BYTES + 1)
    try:
        added = documents.add_document(employee_code, file.filename, data, doc_type, title, user["id"])
    except documents.DocumentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if added is None:
        raise _no_employee()
    documents_filing.reconcile_quietly(employee_code=employee_code)  # the file is filed in the Document Center too
    return added


@router.get("/{employee_code}/documents/{document_id}/file")
def document_file(
    employee_code: str,
    document_id: int,
    download: bool = Query(default=False),
    _user=Depends(require_ods_write),
):
    found = documents.get_document(employee_code, document_id)
    if found is None:
        raise _no_document()
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


@router.delete("/{employee_code}/documents/{document_id}")
def delete_document(employee_code: str, document_id: int, _user=Depends(require_ods_write)):
    if not documents.delete_document(employee_code, document_id):
        raise _no_document()
    documents_filing.reconcile_quietly(employee_code=employee_code)  # and its filed copy goes to the trash
    return {"ok": True}
