"""Files kept against an EMD: the payment receipt, a copy of the demand draft or bank guarantee, the FDR receipt, the tender notice, the refund request and
the proof of the refund.

Each file is a row of ``orion_ods.emd_document`` (created by ``.cursor/db/migrate_contacts_emd.sql``), with the file itself in the database so the encrypted
daily backup covers it. It works exactly as an employee's documents do (``app.employee_documents``), whose rules about what a file may be it shares: the type
comes from the file's extension and the file's first bytes have to agree with it, so an uploaded page of script can never be served back as a page. The routes
in ``routers/emd_documents_router.py`` let people who can see operational data read them, and people who can change it add and delete.
"""

from __future__ import annotations

from typing import Any

from app.database import db_cursor
from app.employee_documents import ACCEPTED, FILE_TYPES, MAX_BYTES, DocumentError, clean_file_name, is_inline

MAX_PER_EMD = 30

DOC_TYPES = (
    "Payment receipt or acknowledgement",
    "Demand draft copy",
    "Bank guarantee",
    "FDR or deposit receipt",
    "Tender notice or document",
    "Refund request letter",
    "Proof of refund",
    "Other",
)

__all__ = ["ACCEPTED", "DOC_TYPES", "MAX_BYTES", "DocumentError", "add_document", "check_upload", "delete_document", "get_document", "is_inline", "list_documents"]


def check_upload(file_name: str | None, data: bytes, doc_type: str | None, title: str | None) -> dict[str, Any]:
    """The values to store for an upload, or ``DocumentError``."""
    name = clean_file_name(file_name)
    if not name:
        raise DocumentError("Choose a file to upload.")
    if doc_type not in DOC_TYPES:
        raise DocumentError("Choose what kind of document this is.")
    ext = name.rpartition(".")[2].lower() if "." in name else ""
    if ext not in FILE_TYPES:
        raise DocumentError(f"A file of that type cannot be kept. Upload one of: {ACCEPTED}.")
    if not data:
        raise DocumentError("That file is empty.")
    if len(data) > MAX_BYTES:
        raise DocumentError(f"That file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    content_type, signatures, _inline = FILE_TYPES[ext]
    if not data.startswith(signatures) or (ext == "webp" and data[8:12] != b"WEBP"):
        raise DocumentError(f"That file is not a real .{ext} file. Check that you chose the right one.")
    title_text = " ".join((title or "").split())[:100] or None
    if doc_type == "Other" and not title_text:
        raise DocumentError("Say what this document is, for example Bank's acknowledgement.")
    return {"doc_type": doc_type, "title": title_text, "file_name": name, "content_type": content_type, "size_bytes": len(data)}


def _plain(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _emd_exists(cur, emd_code: str) -> bool:
    cur.execute("SELECT 1 FROM orion_ods.emd WHERE emd_code = %s", (emd_code,))
    return cur.fetchone() is not None


def list_documents(emd_code: str) -> list[dict[str, Any]] | None:
    """The EMD's documents, oldest first, without the files. None when there is no such EMD."""
    with db_cursor() as cur:
        if not _emd_exists(cur, emd_code):
            return None
        cur.execute(
            """
            SELECT d.document_id AS id, d.doc_type, d.title, d.file_name, d.content_type, d.size_bytes,
                   d.uploaded_timestamp, u.display_name AS uploaded_by_name
              FROM orion_ods.emd_document d
              LEFT JOIN orion_ods.app_user u ON u.id = d.uploaded_by
             WHERE d.emd_code = %s
             ORDER BY d.document_id
            """,
            (emd_code,),
        )
        return [{col.name: _plain(value) for col, value in zip(cur.description, row)} for row in cur.fetchall()]


def add_document(emd_code: str, file_name: str | None, data: bytes, doc_type: str | None, title: str | None, user_id: int | None) -> dict[str, Any] | None:
    """Keep an upload. None when there is no such EMD."""
    values = check_upload(file_name, data, doc_type, title)
    with db_cursor(commit=True) as cur:
        if not _emd_exists(cur, emd_code):
            return None
        cur.execute("SELECT COUNT(*) FROM orion_ods.emd_document WHERE emd_code = %s", (emd_code,))
        if cur.fetchone()[0] >= MAX_PER_EMD:
            raise DocumentError(f"An EMD can have at most {MAX_PER_EMD} documents. Delete one you no longer need.")
        cur.execute(
            """
            INSERT INTO orion_ods.emd_document (emd_code, doc_type, title, file_name, content_type, size_bytes, file_data, uploaded_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING document_id
            """,
            (emd_code, values["doc_type"], values["title"], values["file_name"], values["content_type"], values["size_bytes"], data, user_id),
        )
        return {"id": cur.fetchone()[0], **values}


def get_document(emd_code: str, document_id: int) -> dict[str, Any] | None:
    """One document with its file, only if it belongs to that EMD."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT file_name, content_type, file_data FROM orion_ods.emd_document WHERE emd_code = %s AND document_id = %s",
            (emd_code, document_id),
        )
        row = cur.fetchone()
    return {"file_name": row[0], "content_type": row[1], "data": bytes(row[2])} if row else None


def delete_document(emd_code: str, document_id: int) -> bool:
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM orion_ods.emd_document WHERE emd_code = %s AND document_id = %s", (emd_code, document_id))
        return cur.rowcount > 0
