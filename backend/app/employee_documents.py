"""Files kept against an employee: the Aadhaar and PAN scans, and any other document worth keeping.

Each file is a row of ``orion_ods.employee_document`` (created by ``.cursor/db/migrate_employee_documents.sql``), with
the file itself in the database so the encrypted daily backup covers it. The routes in
``routers/employee_documents_router.py`` need permission to change operational data, for reading as well as for
writing: a scan of an Aadhaar card is not something every viewer of the data should see.

What is accepted is decided here and not by the browser: the type comes from the file's extension, and the file's
first bytes have to agree with it. The only types a browser would draw inline (PDF and images) are the ones that
are checked this way, so an uploaded page of script can never be served back as a page.
"""

from __future__ import annotations

import re
from typing import Any

from app.database import db_cursor

MAX_BYTES = 8 * 1024 * 1024
MAX_PER_EMPLOYEE = 30

DOC_TYPES = (
    "Aadhaar card",
    "PAN card",
    "Photo",
    "Bank passbook or cancelled cheque",
    "Address proof",
    "Police verification",
    "Educational certificate",
    "Appointment letter",
    "PF or ESIC form",
    "Other",
)

# extension -> (content type, what the file must start with, whether a browser may show it inline)
FILE_TYPES: dict[str, tuple[str, tuple[bytes, ...], bool]] = {
    "pdf": ("application/pdf", (b"%PDF-",), True),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",), True),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",), True),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",), True),
    "webp": ("image/webp", (b"RIFF",), True),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", (b"PK\x03\x04",), False),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", (b"PK\x03\x04",), False),
    "doc": ("application/msword", (b"\xd0\xcf\x11\xe0",), False),
    "xls": ("application/vnd.ms-excel", (b"\xd0\xcf\x11\xe0",), False),
}
ACCEPTED = ", ".join(f".{ext}" for ext in FILE_TYPES)


class DocumentError(ValueError):
    """The upload cannot be kept. The message is safe to show to the user."""


def clean_file_name(raw: str | None) -> str:
    """The name to show: no folders, no control characters, and not too long."""
    name = re.sub(r"[\x00-\x1f\\/]", "_", (raw or "").replace("\\", "/").split("/")[-1]).strip()
    if len(name) > 150:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 150 - len(ext) - 1] + dot + ext) if dot else name[:150]
    return name


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
        raise DocumentError("Say what this document is, for example Experience letter.")
    return {
        "doc_type": doc_type, "title": title_text, "file_name": name, "content_type": content_type, "size_bytes": len(data),
    }


def is_inline(content_type: str) -> bool:
    return any(content_type == value[0] and value[2] for value in FILE_TYPES.values())


def _plain(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _employee_exists(cur, employee_code: str) -> bool:
    cur.execute("SELECT 1 FROM orion_ods.employee WHERE employee_code = %s", (employee_code,))
    return cur.fetchone() is not None


def list_documents(employee_code: str) -> list[dict[str, Any]] | None:
    """The employee's documents, oldest first, without the files. None when there is no such employee."""
    with db_cursor() as cur:
        if not _employee_exists(cur, employee_code):
            return None
        cur.execute(
            """
            SELECT d.document_id AS id, d.doc_type, d.title, d.file_name, d.content_type, d.size_bytes,
                   d.uploaded_timestamp, u.display_name AS uploaded_by_name
              FROM orion_ods.employee_document d
              LEFT JOIN orion_ods.app_user u ON u.id = d.uploaded_by
             WHERE d.employee_code = %s
             ORDER BY d.document_id
            """,
            (employee_code,),
        )
        return [{col.name: _plain(value) for col, value in zip(cur.description, row)} for row in cur.fetchall()]


def add_document(employee_code: str, file_name: str | None, data: bytes, doc_type: str | None, title: str | None,
                 user_id: int | None) -> dict[str, Any] | None:
    """Keep an upload. None when there is no such employee."""
    values = check_upload(file_name, data, doc_type, title)
    with db_cursor(commit=True) as cur:
        if not _employee_exists(cur, employee_code):
            return None
        cur.execute("SELECT COUNT(*) FROM orion_ods.employee_document WHERE employee_code = %s", (employee_code,))
        if cur.fetchone()[0] >= MAX_PER_EMPLOYEE:
            raise DocumentError(f"An employee can have at most {MAX_PER_EMPLOYEE} documents. Delete one you no longer need.")
        cur.execute(
            """
            INSERT INTO orion_ods.employee_document
                (employee_code, doc_type, title, file_name, content_type, size_bytes, file_data, uploaded_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING document_id
            """,
            (employee_code, values["doc_type"], values["title"], values["file_name"], values["content_type"],
             values["size_bytes"], data, user_id),
        )
        return {"id": cur.fetchone()[0], **values}


def get_document(employee_code: str, document_id: int) -> dict[str, Any] | None:
    """One document with its file, only if it belongs to that employee."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT file_name, content_type, file_data
              FROM orion_ods.employee_document
             WHERE employee_code = %s AND document_id = %s
            """,
            (employee_code, document_id),
        )
        row = cur.fetchone()
    return {"file_name": row[0], "content_type": row[1], "data": bytes(row[2])} if row else None


def delete_document(employee_code: str, document_id: int) -> bool:
    with db_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM orion_ods.employee_document WHERE employee_code = %s AND document_id = %s",
            (employee_code, document_id),
        )
        return cur.rowcount > 0
