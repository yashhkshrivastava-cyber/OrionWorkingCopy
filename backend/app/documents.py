"""The Document Center: the company's documents, and every case's and client's.

A document belongs to one *space*: the company, one case or one client. It has a title, a category, tags, a status,
dates (including an expiry date that raises a reminder), and any number of versions. A new file is a new version and the
old ones are kept; the file's bytes are stored once per distinct content (``document_blob``, keyed by SHA-256), so a
file uploaded twice, or restored from an old version, takes no more room. The files are in the database so the
encrypted daily backup covers them. Tables are in ``.cursor/db/migrate_documents.sql``; this module is the only writer.

Rules kept here and not in the browser:

* What is accepted is decided by the file's extension and its first bytes (see ``employee_documents``): only PDF and
  images are ever shown inline, so an uploaded page of script can never be served back as a page.
* A Confidential document is seen only by people who may change documents, and by admins. It is left out of every list,
  search, count, checklist and file download for everyone else.
* Deleting is a move to the trash. The history of a document (who uploaded, changed, viewed and downloaded what) is kept
  in ``document_activity`` until the document is deleted for good.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import date, timedelta
from typing import Any
from xml.etree import ElementTree

import psycopg2
from psycopg2 import errors as pg_errors

from app.database import db_cursor
from app.employee_documents import FILE_TYPES as _BASE_FILE_TYPES
from app.employee_documents import clean_file_name, is_inline

MAX_BYTES = 300 * 1024 * 1024
#: Past this the words of a file are not read for search (a file is still kept and shown); reading one this large would hold up the save and fill the memory.
EXTRACT_MAX_BYTES = 50 * 1024 * 1024
MAX_VERSIONS = 100
MAX_TAGS = 15
MAX_FOLDER_DEPTH = 4
CONTENT_TEXT_LIMIT = 100_000

SCOPES = ("company", "case", "client")
STATUSES = ("Draft", "Active", "Superseded", "Archived")
CONFIDENTIALITY = ("Standard", "Confidential")

CATEGORIES: dict[str, tuple[str, ...]] = {
    "company": (
        "Registration and licences",
        "Statutory and tax",
        "Policies and SOPs",
        "Contracts and agreements",
        "Insurance",
        "Bank and finance",
        "HR templates and forms",
        "Employee records",
        "Certificates and awards",
        "Other",
    ),
    "case": (
        "Tender / RFP",
        "Bid submission",
        "Work order / LOI",
        "Contract / agreement",
        "Performance guarantee / EMD",
        "Insurance",
        "Invoice and payment",
        "Attendance and wages",
        "Compliance (PF / ESIC)",
        "Correspondence",
        "Site and photos",
        "Other",
    ),
    "client": ("KYC and registration", "Agreement", "GST and tax", "Invoice and payment", "Correspondence", "Other"),
}

# What a case is expected to have on file. The Document Center shows which of these are there and which are missing.
CASE_CHECKLIST = (
    "Tender / RFP",
    "Work order / LOI",
    "Contract / agreement",
    "Performance guarantee / EMD",
    "Insurance",
)

STANDARD_FOLDERS: dict[str, tuple[str, ...]] = {
    "company": ("Legal and registrations", "Tax and statutory", "Policies", "Insurance", "Finance"),
    "case": ("Tender and bid", "Contract and work orders", "Billing and payments", "Compliance", "Correspondence"),
    "client": ("Agreements", "KYC", "Correspondence"),
}

# The employee-document types, and the kinds of file an office keeps besides.
FILE_TYPES: dict[str, tuple[str, tuple[bytes, ...], bool]] = {
    **_BASE_FILE_TYPES,
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", (b"PK\x03\x04",), False),
    "ppt": ("application/vnd.ms-powerpoint", (b"\xd0\xcf\x11\xe0",), False),
    "txt": ("text/plain", (), False),
    "csv": ("text/csv", (), False),
}
ACCEPTED = ", ".join(f".{ext}" for ext in FILE_TYPES)

SORTS = {
    "updated": "d.last_updated_timestamp",
    "created": "d.created_timestamp",
    "title": "lower(d.title)",
    "expiry": "d.expiry_date",
    "size": "v.size_bytes",
}


class DocumentCenterError(ValueError):
    """The request cannot be carried out. The message is safe to show to the user."""


# Where an automatically filed document came from: (what to call it, the page of the record when there is one). The filing itself is
# ``documents_filing``; a document with a ``source_type`` is its alone to create, replace and retire.
SOURCES = {
    "bill": ("Bill {ref}", "/utility/billing/{ref}"),
    "employee_document": ("Employee {code}", None),
    "emd_document": ("EMD {code}", None),
}


def source_of(source_type: str | None, source_ref: str | None) -> dict[str, str | None] | None:
    """What a filed document was filed from, for the page: a label and the address of the record when it has one."""
    if not source_type or source_type not in SOURCES:
        return None
    label, path = SOURCES[source_type]
    ref = source_ref or ""
    values = {"ref": ref, "code": ref.split(":")[0]}
    return {"type": source_type, "label": label.format(**values), "path": path.format(**values) if path else None}


def refuse_filed(doc: dict[str, Any], what: str) -> None:
    """A filed document is kept in step with its source by ``documents_filing``; changing it here would only be undone."""
    if doc.get("source_type"):
        source = source_of(doc["source_type"], doc.get("source_ref"))
        where = source["label"] if source else "its source"
        raise DocumentCenterError(
            f"This document was filed automatically from {where}, so it cannot be {what} here. Change it there; "
            "only its tags and description can be changed in the Document Center."
        )

# --------------------------------------------------------------------------------------------------------------------
# Files


def check_file(file_name: str | None, data: bytes) -> tuple[str, str, str]:
    """(clean file name, extension, content type) of an upload that may be kept, or ``DocumentCenterError``."""
    name = clean_file_name(file_name)
    if not name:
        raise DocumentCenterError("Choose a file to upload.")
    ext = name.rpartition(".")[2].lower() if "." in name else ""
    if ext not in FILE_TYPES:
        raise DocumentCenterError(f"A file of that type cannot be kept. Upload one of: {ACCEPTED}.")
    if not data:
        raise DocumentCenterError(f"{name} is empty.")
    if len(data) > MAX_BYTES:
        raise DocumentCenterError(f"{name} is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    content_type, signatures, _inline = FILE_TYPES[ext]
    if signatures and not data.startswith(signatures):
        raise DocumentCenterError(f"{name} is not a real .{ext} file. Check that you chose the right one.")
    if ext == "webp" and data[8:12] != b"WEBP":
        raise DocumentCenterError(f"{name} is not a real .webp file. Check that you chose the right one.")
    if ext in ("txt", "csv") and b"\x00" in data[:8192]:
        raise DocumentCenterError(f"{name} is not a text file.")
    return name, ext, content_type


def _xml_text(xml: bytes, tag_suffix: str) -> str:
    """The text of every element whose tag ends with ``tag_suffix``. Documents that declare entities are skipped."""
    if b"<!ENTITY" in xml or b"<!DOCTYPE" in xml:
        return ""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return ""
    return " ".join(node.text for node in root.iter() if node.tag.endswith(tag_suffix) and node.text)


def extract_text(ext: str, data: bytes, *, lower: bool = True) -> str:
    """The words in a file, for search (lower-cased) or to be read as written (``lower=False``). Empty when the file has
    none, or cannot be read (a scan, a locked file)."""
    if len(data) > EXTRACT_MAX_BYTES:
        return ""
    try:
        if ext == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                return ""
            pages = []
            for page in list(reader.pages)[:60]:
                pages.append(page.extract_text() or "")
                if sum(len(p) for p in pages) > CONTENT_TEXT_LIMIT:
                    break
            text = " ".join(pages)
        elif ext in ("docx", "xlsx", "pptx"):
            wanted = {
                "docx": ("word/document.xml", "}t"),
                "xlsx": ("xl/sharedStrings.xml", "}t"),
                "pptx": ("ppt/slides/slide", "}t"),
            }[ext]
            parts = []
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for info in archive.infolist():
                    if not info.filename.startswith(wanted[0]) or not info.filename.endswith(".xml"):
                        continue
                    if info.file_size > 20 * 1024 * 1024:
                        continue
                    parts.append(_xml_text(archive.read(info), wanted[1]))
                    if sum(len(p) for p in parts) > CONTENT_TEXT_LIMIT:
                        break
            text = " ".join(parts)
        elif ext in ("txt", "csv"):
            text = data[: CONTENT_TEXT_LIMIT * 4].decode("utf-8", errors="replace")
        else:
            return ""
    except Exception:  # noqa: BLE001 - a file that cannot be read for search is still a file that can be kept
        return ""
    text = " ".join(text.split())[:CONTENT_TEXT_LIMIT]
    return text.lower() if lower else text


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------------------------------------------------
# Details of a document


def _parse_date(value: Any, label: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        parsed = value
    else:
        try:
            parsed = date.fromisoformat(str(value).strip()[:10])
        except ValueError as exc:
            raise DocumentCenterError(f"{label} is not a valid date.") from exc
    if not 1990 <= parsed.year <= 2100:
        raise DocumentCenterError(f"{label} must be between the years 1990 and 2100.")
    return parsed


def clean_tags(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    items = re.split(r"[,\n]", value) if isinstance(value, str) else list(value)
    tags: list[str] = []
    for item in items:
        tag = " ".join(str(item).split()).lower()
        if not tag:
            continue
        if len(tag) > 30:
            raise DocumentCenterError("A tag can be at most 30 characters.")
        if tag not in tags:
            tags.append(tag)
    if len(tags) > MAX_TAGS:
        raise DocumentCenterError(f"A document can have at most {MAX_TAGS} tags.")
    return tags


def clean_meta(raw: dict[str, Any], scope: str, partial: bool = False) -> dict[str, Any]:
    """The cleaned details of a document. With ``partial`` only the keys given are checked and returned."""
    out: dict[str, Any] = {}
    if not partial or "title" in raw:
        title = " ".join(str(raw.get("title") or "").split())
        if not title:
            raise DocumentCenterError("Give the document a title.")
        if len(title) > 150:
            raise DocumentCenterError("The title can be at most 150 characters.")
        out["title"] = title
    if not partial or "category" in raw:
        if raw.get("category") not in CATEGORIES[scope]:
            raise DocumentCenterError("Choose what kind of document this is.")
        out["category"] = raw["category"]
    if "description" in raw:
        description = str(raw.get("description") or "").strip()
        if len(description) > 2000:
            raise DocumentCenterError("The description can be at most 2000 characters.")
        out["description"] = description or None
    if "tags" in raw:
        out["tags"] = clean_tags(raw["tags"])
    if "status" in raw and raw["status"] is not None:
        if raw["status"] not in STATUSES:
            raise DocumentCenterError("That status is not one of: " + ", ".join(STATUSES) + ".")
        out["status"] = raw["status"]
    if "confidentiality" in raw and raw["confidentiality"] is not None:
        if raw["confidentiality"] not in CONFIDENTIALITY:
            raise DocumentCenterError("Confidentiality must be Standard or Confidential.")
        out["confidentiality"] = raw["confidentiality"]
    if "document_date" in raw:
        out["document_date"] = _parse_date(raw["document_date"], "The document date")
    if "expiry_date" in raw:
        out["expiry_date"] = _parse_date(raw["expiry_date"], "The expiry date")
    if "reminder_days" in raw and raw["reminder_days"] not in (None, ""):
        try:
            days = int(raw["reminder_days"])
        except (TypeError, ValueError) as exc:
            raise DocumentCenterError("Remind me before expiry must be a number of days.") from exc
        if isinstance(raw["reminder_days"], bool) or not 0 <= days <= 365:
            raise DocumentCenterError("Remind me before expiry must be between 0 and 365 days.")
        out["reminder_days"] = days
    return out


def check_dates(document_date: date | None, expiry_date: date | None) -> None:
    if document_date and expiry_date and expiry_date < document_date:
        raise DocumentCenterError("The expiry date cannot be before the document date.")


def expiry_state(expiry: date | None, reminder_days: int, status: str, today: date) -> str:
    """none (no expiry, or a document that no longer matters), valid, expiring (inside the reminder window) or expired."""
    if expiry is None or status in ("Superseded", "Archived"):
        return "none"
    if expiry < today:
        return "expired"
    if expiry <= today + timedelta(days=reminder_days):
        return "expiring"
    return "valid"


def can_see_confidential(user: dict) -> bool:
    from app.auth import can_write_documents

    return user.get("role") == "admin" or can_write_documents(user)


# --------------------------------------------------------------------------------------------------------------------
# Reading


def _plain(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _rows(cur) -> list[dict[str, Any]]:
    return [{col.name: _plain(value) for col, value in zip(cur.description, row)} for row in cur.fetchall()]


_SELECT = """
    SELECT d.document_id AS id, d.document_code AS code, d.scope, d.case_code, c.case_name,
           COALESCE(d.client_code, c.client_code) AS client_code, cl.client_name,
           d.folder_id, f.name AS folder_name, d.title, d.category, d.description, d.tags, d.status, d.confidentiality,
           d.document_date, d.expiry_date, d.reminder_days, d.current_version, d.is_deleted,
           d.created_timestamp, d.last_updated_timestamp, d.source_type, d.source_ref,
           v.file_name, v.content_type, v.size_bytes, v.uploaded_timestamp,
           cu.display_name AS created_by_name, uu.display_name AS updated_by_name
      FROM orion_ods.document d
      JOIN orion_ods.document_version v ON v.document_id = d.document_id AND v.version_no = d.current_version
      LEFT JOIN orion_ods."case" c ON c.case_code = d.case_code
      LEFT JOIN orion_ods.client cl ON cl.client_code = COALESCE(d.client_code, c.client_code)
      LEFT JOIN orion_ods.doc_folder f ON f.folder_id = d.folder_id
      LEFT JOIN orion_ods.app_user cu ON cu.id = d.created_by
      LEFT JOIN orion_ods.app_user uu ON uu.id = d.last_updated_by
"""


def _shape(row: dict[str, Any], today: date) -> dict[str, Any]:
    expiry = date.fromisoformat(row["expiry_date"]) if row["expiry_date"] else None
    row["expiry_state"] = expiry_state(expiry, row["reminder_days"], row["status"], today)
    row["inline"] = is_inline(row["content_type"])
    row["tags"] = list(row["tags"] or [])
    row["source"] = source_of(row.pop("source_type", None), row.pop("source_ref", None))
    return row


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# A folder and everything inside it, so opening "Billing and payments" shows the invoices filed two folders down.
_FOLDER_TREE = """(WITH RECURSIVE tree(id) AS (SELECT %(folder_id)s::int
                     UNION ALL SELECT f.folder_id FROM orion_ods.doc_folder f JOIN tree ON f.parent_id = tree.id)
                   SELECT id FROM tree)"""


def _in_space(filters: dict[str, Any], params: dict[str, Any]) -> str | None:
    """The condition for "in this company, case or client, and in this folder or below it".

    A document is in a place when that is its home, or when it has been filed there as well (``document_placement``): a
    case's tax invoice is found in the case and again in its client's Billing folder. The client alone also matches the
    documents of that client's cases, as it always has."""
    home: list[str] = []
    placed: list[str] = []
    scope = filters.get("scope")
    if scope:
        if scope not in SCOPES:
            raise DocumentCenterError("That is not a place documents are kept.")
        home.append("d.scope = %(scope)s")
        placed.append("p.scope = %(scope)s")
        params["scope"] = scope
    if filters.get("case_code"):
        home.append("d.case_code = %(case_code)s")
        placed.append("p.case_code = %(case_code)s")
        params["case_code"] = filters["case_code"]
    if filters.get("client_code"):
        home.append("COALESCE(d.client_code, c.client_code) = %(client_code)s")
        placed.append("p.client_code = %(client_code)s")
        params["client_code"] = filters["client_code"]
    folder = filters.get("folder_id")
    if folder == "none":
        home.append("d.folder_id IS NULL")
        placed.append("p.folder_id IS NULL")
    elif folder not in (None, ""):
        params["folder_id"] = int(folder)
        if filters.get("exact"):  # the folder's own contents, as a file explorer shows them, not those of the folders inside it
            home.append("d.folder_id = %(folder_id)s")
            placed.append("p.folder_id = %(folder_id)s")
        else:
            home.append(f"d.folder_id IN {_FOLDER_TREE}")
            placed.append(f"p.folder_id IN {_FOLDER_TREE}")
    if not home:
        return None
    return (
        f"(({' AND '.join(home)}) OR EXISTS (SELECT 1 FROM orion_ods.document_placement p "
        f"WHERE p.document_id = d.document_id AND {' AND '.join(placed)}))"
    )


def _where(filters: dict[str, Any], see_confidential: bool, today: date) -> tuple[str, dict[str, Any]]:
    clauses = ["d.is_deleted = %(trash)s"]
    params: dict[str, Any] = {"trash": bool(filters.get("trash"))}
    if not see_confidential:
        clauses.append("d.confidentiality = 'Standard'")
    space = _in_space(filters, params)
    if space:
        clauses.append(space)
    for key, column in (("category", "d.category"), ("status", "d.status"), ("confidentiality", "d.confidentiality")):
        if filters.get(key):
            clauses.append(f"{column} = %({key})s")
            params[key] = filters[key]
    if filters.get("tag"):
        clauses.append("%(tag)s = ANY (d.tags)")
        params["tag"] = str(filters["tag"]).strip().lower()
    expiry = filters.get("expiry")
    if expiry:
        live = "d.expiry_date IS NOT NULL AND d.status IN ('Draft', 'Active')"
        params["today"] = today
        if expiry == "expired":
            clauses.append(f"{live} AND d.expiry_date < %(today)s")
        elif expiry == "expiring":
            clauses.append(f"{live} AND d.expiry_date >= %(today)s AND d.expiry_date <= %(today)s + d.reminder_days")
        elif expiry == "valid":
            clauses.append(f"{live} AND d.expiry_date > %(today)s + d.reminder_days")
        elif expiry == "none":
            clauses.append("(d.expiry_date IS NULL OR d.status NOT IN ('Draft', 'Active'))")
        else:
            raise DocumentCenterError("Expiry must be expired, expiring, valid or none.")
    terms = [t for t in re.split(r"\s+", (filters.get("q") or "").strip().lower()) if t][:8]
    if terms:
        clauses.append(
            """lower(concat_ws(' ', d.document_code, d.title, d.category, d.description, array_to_string(d.tags, ' '),
                                  v.file_name, c.case_code, c.case_name, cl.client_name, d.content_text)) LIKE ALL (%(terms)s)"""
        )
        params["terms"] = [_like(t) for t in terms]
    return " AND ".join(clauses), params


def search_documents(filters: dict[str, Any], see_confidential: bool, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """One page of documents, newest change first unless ``sort`` says otherwise, and how many match in all."""
    today = date.today()
    where, params = _where(filters, see_confidential, today)
    sort = SORTS.get(filters.get("sort") or "updated")
    if sort is None:
        raise DocumentCenterError("Sort by updated, created, title, expiry or size.")
    direction = "ASC" if str(filters.get("direction")).lower() == "asc" else "DESC"
    nulls = " NULLS LAST" if sort == SORTS["expiry"] else ""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT COUNT(*) FROM orion_ods.document d
                  JOIN orion_ods.document_version v ON v.document_id = d.document_id AND v.version_no = d.current_version
                  LEFT JOIN orion_ods."case" c ON c.case_code = d.case_code
                  LEFT JOIN orion_ods.client cl ON cl.client_code = COALESCE(d.client_code, c.client_code)
                 WHERE {where}""",
            params,
        )
        total = cur.fetchone()[0]
        cur.execute(
            f"{_SELECT} WHERE {where} ORDER BY {sort} {direction}{nulls}, d.document_id DESC LIMIT %(limit)s OFFSET %(offset)s",
            {**params, "limit": limit, "offset": offset},
        )
        items = [_shape(row, today) for row in _rows(cur)]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def get_document(document_id: int, see_confidential: bool) -> dict[str, Any] | None:
    """One document with every version and its recent activity. None when it does not exist or may not be seen."""
    today = date.today()
    with db_cursor() as cur:
        cur.execute(f"{_SELECT} WHERE d.document_id = %s", (document_id,))
        found = _rows(cur)
        if not found or (found[0]["confidentiality"] == "Confidential" and not see_confidential):
            return None
        doc = _shape(found[0], today)
        cur.execute(
            """
            SELECT v.version_no, v.file_name, v.content_type, v.size_bytes, v.sha256, v.change_note,
                   v.uploaded_timestamp, u.display_name AS uploaded_by_name
              FROM orion_ods.document_version v
              LEFT JOIN orion_ods.app_user u ON u.id = v.uploaded_by
             WHERE v.document_id = %s
             ORDER BY v.version_no DESC
            """,
            (document_id,),
        )
        doc["versions"] = _rows(cur)
        cur.execute(
            """
            SELECT a.action, a.detail, a.at, u.display_name AS by_name
              FROM orion_ods.document_activity a
              LEFT JOIN orion_ods.app_user u ON u.id = a.by_user
             WHERE a.document_id = %s
             ORDER BY a.id DESC
             LIMIT 100
            """,
            (document_id,),
        )
        doc["activity"] = _rows(cur)
        doc["folder_path"] = _folder_path(cur, doc["folder_id"])
        cur.execute(
            """
            SELECT p.scope, p.case_code, c.case_name, p.client_code, cl.client_name, p.folder_id
              FROM orion_ods.document_placement p
              LEFT JOIN orion_ods."case" c ON c.case_code = p.case_code
              LEFT JOIN orion_ods.client cl ON cl.client_code = p.client_code
             WHERE p.document_id = %s
             ORDER BY p.placement_id
            """,
            (document_id,),
        )
        doc["placements"] = [{**place, "folder_path": _folder_path(cur, place["folder_id"])} for place in _rows(cur)]
    return doc


def _folder_path(cur, folder_id: int | None) -> list[dict[str, Any]]:
    path: list[dict[str, Any]] = []
    while folder_id is not None and len(path) <= MAX_FOLDER_DEPTH + 1:
        cur.execute("SELECT folder_id, parent_id, name FROM orion_ods.doc_folder WHERE folder_id = %s", (folder_id,))
        row = cur.fetchone()
        if not row:
            break
        path.insert(0, {"id": row[0], "name": row[2]})
        folder_id = row[1]
    return path


def get_file(document_id: int, version_no: int | None, action: str, user_id: int | None, see_confidential: bool) -> dict[str, Any] | None:
    """The file of a version (the current one by default), logging that it was viewed or downloaded."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT d.confidentiality, d.current_version, v.version_no, v.file_name, v.content_type, b.data
              FROM orion_ods.document d
              JOIN orion_ods.document_version v ON v.document_id = d.document_id AND v.version_no = COALESCE(%s, d.current_version)
              JOIN orion_ods.document_blob b ON b.sha256 = v.sha256
             WHERE d.document_id = %s
            """,
            (version_no, document_id),
        )
        row = cur.fetchone()
        if not row or (row[0] == "Confidential" and not see_confidential):
            return None
        _log(cur, document_id, action, f"Version {row[2]}", user_id)
    return {"file_name": row[3], "content_type": row[4], "data": bytes(row[5]), "version_no": row[2]}


# Every place a document appears in: its home and each place it was also filed in, one row each, so a count of a client's
# documents includes the case invoices filed in its Billing folder.
_APPEARANCES = """appear AS (
    SELECT d.document_id, d.scope, d.case_code, d.client_code, d.status, d.expiry_date, d.reminder_days, d.confidentiality
      FROM orion_ods.document d WHERE NOT d.is_deleted
    UNION ALL
    SELECT d.document_id, p.scope, p.case_code, p.client_code, d.status, d.expiry_date, d.reminder_days, d.confidentiality
      FROM orion_ods.document_placement p JOIN orion_ods.document d ON d.document_id = p.document_id WHERE NOT d.is_deleted
)"""


def spaces(see_confidential: bool) -> dict[str, Any]:
    """Where documents are kept: the company, and each case and client that has any, with counts."""
    today = date.today()
    conf = "" if see_confidential else "AND d.confidentiality = 'Standard'"
    with db_cursor() as cur:
        counts = """COUNT(*) AS documents,
                     COUNT(*) FILTER (WHERE d.expiry_date IS NOT NULL AND d.status IN ('Draft', 'Active')
                                        AND d.expiry_date <= %s + d.reminder_days) AS attention"""
        cur.execute(f"WITH {_APPEARANCES} SELECT {counts} FROM appear d WHERE d.scope = 'company' {conf}", (today,))
        company = _rows(cur)[0]
        cur.execute(
            f"""WITH {_APPEARANCES}
                SELECT d.case_code, c.case_name, c.case_status, cl.client_name, {counts}
                  FROM appear d
                  JOIN orion_ods."case" c ON c.case_code = d.case_code
                  LEFT JOIN orion_ods.client cl ON cl.client_code = c.client_code
                 WHERE d.scope = 'case' {conf}
                 GROUP BY d.case_code, c.case_name, c.case_status, cl.client_name
                 ORDER BY lower(c.case_name)""",
            (today,),
        )
        cases = _rows(cur)
        cur.execute(
            f"""WITH {_APPEARANCES}
                SELECT d.client_code, cl.client_name, {counts}
                  FROM appear d
                  JOIN orion_ods.client cl ON cl.client_code = d.client_code
                 WHERE d.scope = 'client' {conf}
                 GROUP BY d.client_code, cl.client_name
                 ORDER BY lower(cl.client_name)""",
            (today,),
        )
        clients = _rows(cur)
        cur.execute(f"SELECT COUNT(*) FROM orion_ods.document d WHERE d.is_deleted {conf}")
        trash = cur.fetchone()[0]
        # Each document once, however many places it is filed in (the counts above count it in every place it is).
        cur.execute(f"SELECT COUNT(*) FROM orion_ods.document d WHERE NOT d.is_deleted {conf}")
        total = cur.fetchone()[0]
    return {"company": company, "cases": cases, "clients": clients, "trash": trash, "total": total}


def targets(query: str) -> dict[str, list[dict[str, Any]]]:
    """Cases and clients to choose from when filing a document, whether or not they have documents yet."""
    pattern = _like(query.strip().lower()) if query.strip() else "%"
    with db_cursor() as cur:
        cur.execute(
            """SELECT c.case_code, c.case_name, c.case_status, cl.client_name
                 FROM orion_ods."case" c LEFT JOIN orion_ods.client cl ON cl.client_code = c.client_code
                WHERE lower(c.case_name || ' ' || c.case_code || ' ' || COALESCE(cl.client_name, '')) LIKE %s
                ORDER BY (c.case_status = 'Active') DESC NULLS LAST, lower(c.case_name) LIMIT 25""",
            (pattern,),
        )
        cases = _rows(cur)
        cur.execute(
            """SELECT client_code, client_name FROM orion_ods.client
                WHERE lower(client_name || ' ' || client_code) LIKE %s ORDER BY lower(client_name) LIMIT 25""",
            (pattern,),
        )
        clients = _rows(cur)
    return {"cases": cases, "clients": clients}


def overview(see_confidential: bool) -> dict[str, Any]:
    """Numbers and lists for the Document Center's home: what needs attention, what is new, and how much is stored."""
    today = date.today()
    base = {"trash": False}
    with db_cursor() as cur:
        out: dict[str, Any] = {}
        for key, expiry in (("expired", "expired"), ("expiring", "expiring")):
            where, params = _where({**base, "expiry": expiry}, see_confidential, today)
            cur.execute(
                f"""SELECT COUNT(*) FROM orion_ods.document d
                      JOIN orion_ods.document_version v ON v.document_id = d.document_id AND v.version_no = d.current_version
                      LEFT JOIN orion_ods."case" c ON c.case_code = d.case_code
                      LEFT JOIN orion_ods.client cl ON cl.client_code = COALESCE(d.client_code, c.client_code)
                     WHERE {where}""",
                params,
            )
            out[key] = cur.fetchone()[0]
        conf = "" if see_confidential else "AND d.confidentiality = 'Standard'"
        cur.execute(f"SELECT COUNT(*) FROM orion_ods.document d WHERE NOT d.is_deleted {conf}")
        out["total"] = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM orion_ods.document d WHERE NOT d.is_deleted AND d.status = 'Draft' {conf}")
        out["drafts"] = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM orion_ods.document_blob")
        out["stored_bytes"] = int(cur.fetchone()[0])
        cur.execute(
            f"""SELECT tag, COUNT(*) AS n FROM orion_ods.document d, unnest(d.tags) AS tag
                 WHERE NOT d.is_deleted {conf} GROUP BY tag ORDER BY n DESC, tag LIMIT 30"""
        )
        out["tags"] = _rows(cur)
    needs = search_documents({"expiry": "expired", "sort": "expiry", "direction": "asc"}, see_confidential, limit=8)["items"]
    soon = search_documents({"expiry": "expiring", "sort": "expiry", "direction": "asc"}, see_confidential, limit=8)["items"]
    recent = search_documents({"sort": "updated"}, see_confidential, limit=8)["items"]
    return {**out, "expired_documents": needs, "expiring_documents": soon, "recent": recent}


def case_checklist(case_code: str, see_confidential: bool) -> list[dict[str, Any]] | None:
    """Which of the papers every case should have are on file. None when there is no such case."""
    conf = "" if see_confidential else "AND confidentiality = 'Standard'"
    with db_cursor() as cur:
        cur.execute('SELECT 1 FROM orion_ods."case" WHERE case_code = %s', (case_code,))
        if cur.fetchone() is None:
            return None
        cur.execute(
            f"""SELECT category, COUNT(*) FROM orion_ods.document
                 WHERE case_code = %s AND NOT is_deleted AND status IN ('Draft', 'Active') {conf}
                 GROUP BY category""",
            (case_code,),
        )
        have = dict(cur.fetchall())
    return [{"category": name, "count": have.get(name, 0), "present": have.get(name, 0) > 0} for name in CASE_CHECKLIST]


# --------------------------------------------------------------------------------------------------------------------
# Writing


def _log(cur, document_id: int, action: str, detail: str | None, user_id: int | None) -> None:
    cur.execute(
        "INSERT INTO orion_ods.document_activity (document_id, action, detail, by_user) VALUES (%s, %s, %s, %s)",
        (document_id, action, detail, user_id),
    )


def _store_blob(cur, sha: str, data: bytes) -> None:
    cur.execute(
        "INSERT INTO orion_ods.document_blob (sha256, size_bytes, data) VALUES (%s, %s, %s) ON CONFLICT (sha256) DO NOTHING",
        (sha, len(data), psycopg2.Binary(data)),
    )


def _space_of(cur, raw: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """(scope, case_code, client_code) named by a request, checked to exist."""
    scope = raw.get("scope")
    if scope not in SCOPES:
        raise DocumentCenterError("Choose where this document belongs: the company, a case or a client.")
    case_code = raw.get("case_code") or None
    client_code = raw.get("client_code") or None
    if scope == "company":
        return scope, None, None
    if scope == "case":
        cur.execute('SELECT 1 FROM orion_ods."case" WHERE case_code = %s', (case_code,))
        if not case_code or cur.fetchone() is None:
            raise DocumentCenterError("Choose the case this document belongs to.")
        return scope, case_code, None
    cur.execute("SELECT 1 FROM orion_ods.client WHERE client_code = %s", (client_code,))
    if not client_code or cur.fetchone() is None:
        raise DocumentCenterError("Choose the client this document belongs to.")
    return scope, None, client_code


def _check_folder(cur, folder_id: Any, space: tuple[str, str | None, str | None]) -> int | None:
    if folder_id in (None, "", "none"):
        return None
    cur.execute("SELECT scope, case_code, client_code FROM orion_ods.doc_folder WHERE folder_id = %s", (int(folder_id),))
    row = cur.fetchone()
    if row is None:
        raise DocumentCenterError("That folder does not exist.")
    if tuple(row) != space:
        raise DocumentCenterError("That folder belongs to a different case, client or to the company.")
    return int(folder_id)


def create_document(user_id: int | None, raw: dict[str, Any], file_name: str | None, data: bytes) -> dict[str, Any]:
    """File a new document with its first version. Returns its id and code, and any live copies of the same file."""
    name, ext, content_type = check_file(file_name, data)
    if not " ".join(str(raw.get("title") or "").split()):
        raw = {**raw, "title": name.rpartition(".")[0] or name}
    raw = {"status": "Active", "confidentiality": "Standard", **{k: v for k, v in raw.items() if v is not None}}
    sha = sha256_of(data)
    text = extract_text(ext, data)
    with db_cursor(commit=True) as cur:
        scope, case_code, client_code = _space_of(cur, raw)
        meta = clean_meta(raw, scope)
        check_dates(meta.get("document_date"), meta.get("expiry_date"))
        folder_id = _check_folder(cur, raw.get("folder_id"), (scope, case_code, client_code))
        cur.execute(
            """SELECT DISTINCT d.document_code FROM orion_ods.document_version v
                 JOIN orion_ods.document d ON d.document_id = v.document_id
                WHERE v.sha256 = %s AND NOT d.is_deleted LIMIT 5""",
            (sha,),
        )
        duplicates = [r[0] for r in cur.fetchall()]
        _store_blob(cur, sha, data)
        cur.execute(
            """
            INSERT INTO orion_ods.document
                (scope, case_code, client_code, folder_id, title, category, description, tags, status, confidentiality,
                 document_date, expiry_date, reminder_days, content_text, created_by, last_updated_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING document_id, document_code
            """,
            (scope, case_code, client_code, folder_id, meta["title"], meta["category"], meta.get("description"),
             meta.get("tags", []), meta["status"], meta["confidentiality"], meta.get("document_date"),
             meta.get("expiry_date"), meta.get("reminder_days", 30), text, user_id, user_id),
        )
        document_id, code = cur.fetchone()
        cur.execute(
            """INSERT INTO orion_ods.document_version
                   (document_id, version_no, file_name, content_type, size_bytes, sha256, change_note, uploaded_by)
               VALUES (%s, 1, %s, %s, %s, %s, %s, %s)""",
            (document_id, name, content_type, len(data), sha, "First upload", user_id),
        )
        _log(cur, document_id, "uploaded", name, user_id)
    return {"id": document_id, "code": code, "title": meta["title"], "duplicates": duplicates}


def _lock(cur, document_id: int, see_confidential: bool) -> dict[str, Any] | None:
    cur.execute(
        """SELECT document_id, scope, case_code, client_code, folder_id, category, status, confidentiality, document_date,
                  expiry_date, current_version, is_deleted, source_type, source_ref
             FROM orion_ods.document WHERE document_id = %s FOR UPDATE""",
        (document_id,),
    )
    row = cur.fetchone()
    if row is None or (row[7] == "Confidential" and not see_confidential):
        return None
    keys = ("id", "scope", "case_code", "client_code", "folder_id", "category", "status", "confidentiality",
            "document_date", "expiry_date", "current_version", "is_deleted", "source_type", "source_ref")
    return dict(zip(keys, row))


def update_document(user_id: int | None, document_id: int, raw: dict[str, Any], see_confidential: bool) -> bool:
    """Change a document's details, or move it to another folder, case, client or the company. False if not found."""
    with db_cursor(commit=True) as cur:
        doc = _lock(cur, document_id, see_confidential)
        if doc is None:
            return False
        if doc["is_deleted"]:
            raise DocumentCenterError("This document is in the trash. Restore it before changing it.")
        if doc["source_type"] and set(raw) - {"tags", "description"}:
            refuse_filed(doc, "changed")
        space = (doc["scope"], doc["case_code"], doc["client_code"])
        moved = "scope" in raw
        if moved:
            space = _space_of(cur, raw)
        if moved and "category" not in raw and doc["category"] not in CATEGORIES[space[0]]:
            raise DocumentCenterError("Choose a category that fits where the document now belongs.")
        meta = clean_meta(raw, space[0], partial=True)
        if "folder_id" in raw or moved:
            meta["folder_id"] = _check_folder(cur, raw.get("folder_id"), space)
        check_dates(meta.get("document_date", doc["document_date"]), meta.get("expiry_date", doc["expiry_date"]))
        if moved:
            meta.update(scope=space[0], case_code=space[1], client_code=space[2])
        if not meta:
            return True
        columns = ", ".join(f"{key} = %({key})s" for key in meta)
        cur.execute(
            f"UPDATE orion_ods.document SET {columns}, last_updated_by = %(_user)s, last_updated_timestamp = CURRENT_TIMESTAMP "
            "WHERE document_id = %(_id)s",
            {**meta, "_user": user_id, "_id": document_id},
        )
        changed = ", ".join(sorted(k for k in meta if k not in ("case_code", "client_code")))
        _log(cur, document_id, "moved" if moved else "edited", changed, user_id)
    return True


def add_version(user_id: int | None, document_id: int, file_name: str | None, data: bytes, note: str | None,
                see_confidential: bool) -> int | None:
    """Keep a new file as the document's next version. Returns its number, or None if the document is not found."""
    name, ext, content_type = check_file(file_name, data)
    sha = sha256_of(data)
    text = extract_text(ext, data)
    note = " ".join((note or "").split())[:300] or None
    with db_cursor(commit=True) as cur:
        doc = _lock(cur, document_id, see_confidential)
        if doc is None:
            return None
        if doc["is_deleted"]:
            raise DocumentCenterError("This document is in the trash. Restore it before adding a version.")
        refuse_filed(doc, "given a new version")
        if doc["current_version"] >= MAX_VERSIONS:
            raise DocumentCenterError(f"A document can have at most {MAX_VERSIONS} versions.")
        cur.execute(
            "SELECT sha256 FROM orion_ods.document_version WHERE document_id = %s AND version_no = %s",
            (document_id, doc["current_version"]),
        )
        if cur.fetchone()[0] == sha:
            raise DocumentCenterError("That file is identical to the current version.")
        version_no = doc["current_version"] + 1
        _store_blob(cur, sha, data)
        cur.execute(
            """INSERT INTO orion_ods.document_version
                   (document_id, version_no, file_name, content_type, size_bytes, sha256, change_note, uploaded_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (document_id, version_no, name, content_type, len(data), sha, note, user_id),
        )
        cur.execute(
            """UPDATE orion_ods.document SET current_version = %s, content_text = %s, last_updated_by = %s,
                      last_updated_timestamp = CURRENT_TIMESTAMP WHERE document_id = %s""",
            (version_no, text, user_id, document_id),
        )
        _log(cur, document_id, "new_version", f"Version {version_no}: {name}", user_id)
    return version_no


def restore_version(user_id: int | None, document_id: int, version_no: int, see_confidential: bool) -> int | None:
    """Make an old version current again, as a new version that shares the old file. None if not found."""
    with db_cursor(commit=True) as cur:
        doc = _lock(cur, document_id, see_confidential)
        if doc is None:
            return None
        if doc["is_deleted"]:
            raise DocumentCenterError("This document is in the trash. Restore it before changing it.")
        refuse_filed(doc, "given a new version")
        if doc["current_version"] >= MAX_VERSIONS:
            raise DocumentCenterError(f"A document can have at most {MAX_VERSIONS} versions.")
        cur.execute(
            """SELECT v.file_name, v.content_type, v.size_bytes, v.sha256, b.data
                 FROM orion_ods.document_version v JOIN orion_ods.document_blob b ON b.sha256 = v.sha256
                WHERE v.document_id = %s AND v.version_no = %s""",
            (document_id, version_no),
        )
        row = cur.fetchone()
        if row is None:
            raise DocumentCenterError("That version does not exist.")
        if version_no == doc["current_version"]:
            raise DocumentCenterError("That is already the current version.")
        new_no = doc["current_version"] + 1
        cur.execute(
            """INSERT INTO orion_ods.document_version
                   (document_id, version_no, file_name, content_type, size_bytes, sha256, change_note, uploaded_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (document_id, new_no, row[0], row[1], row[2], row[3], f"Restored from version {version_no}", user_id),
        )
        ext = row[0].rpartition(".")[2].lower()
        cur.execute(
            """UPDATE orion_ods.document SET current_version = %s, content_text = %s, last_updated_by = %s,
                      last_updated_timestamp = CURRENT_TIMESTAMP WHERE document_id = %s""",
            (new_no, extract_text(ext, bytes(row[4])), user_id, document_id),
        )
        _log(cur, document_id, "new_version", f"Version {new_no}: restored from version {version_no}", user_id)
    return new_no


def set_deleted(user_id: int | None, document_ids: list[int], deleted: bool, see_confidential: bool) -> int:
    """Move documents to the trash, or back. Returns how many changed."""
    changed = 0
    with db_cursor(commit=True) as cur:
        for document_id in document_ids:
            doc = _lock(cur, document_id, see_confidential)
            if doc is None or doc["is_deleted"] == deleted:
                continue
            if deleted:
                refuse_filed(doc, "deleted")
            cur.execute(
                """UPDATE orion_ods.document SET is_deleted = %s, deleted_by = %s,
                          deleted_timestamp = CASE WHEN %s THEN CURRENT_TIMESTAMP END,
                          last_updated_by = %s, last_updated_timestamp = CURRENT_TIMESTAMP
                    WHERE document_id = %s""",
                (deleted, user_id if deleted else None, deleted, user_id, document_id),
            )
            _log(cur, document_id, "deleted" if deleted else "restored", None, user_id)
            changed += 1
    return changed


def purge_document(document_id: int, see_confidential: bool) -> bool:
    """Delete a trashed document for good, with its versions and history, and any file nothing else uses."""
    with db_cursor(commit=True) as cur:
        doc = _lock(cur, document_id, see_confidential)
        if doc is None:
            return False
        if not doc["is_deleted"]:
            raise DocumentCenterError("Only a document in the trash can be deleted for good.")
        cur.execute("SELECT DISTINCT sha256 FROM orion_ods.document_version WHERE document_id = %s", (document_id,))
        hashes = [r[0] for r in cur.fetchall()]
        cur.execute("DELETE FROM orion_ods.document WHERE document_id = %s", (document_id,))
        cur.execute(
            """DELETE FROM orion_ods.document_blob b WHERE b.sha256 = ANY (%s)
                  AND NOT EXISTS (SELECT 1 FROM orion_ods.document_version v WHERE v.sha256 = b.sha256)""",
            (hashes,),
        )
    return True


def bulk_update(user_id: int | None, document_ids: list[int], action: str, value: Any, see_confidential: bool) -> int:
    """Move, set the status of, delete or restore several documents at once. Returns how many changed."""
    ids = sorted({int(i) for i in document_ids})
    if not ids:
        raise DocumentCenterError("Choose at least one document.")
    if len(ids) > 200:
        raise DocumentCenterError("Choose at most 200 documents at a time.")
    if action in ("delete", "restore"):
        return set_deleted(user_id, ids, action == "delete", see_confidential)
    if action not in ("move", "status"):
        raise DocumentCenterError("That action is not one of: move, status, delete, restore.")
    if action == "status" and value not in STATUSES:
        raise DocumentCenterError("That status is not one of: " + ", ".join(STATUSES) + ".")
    changed = 0
    with db_cursor(commit=True) as cur:
        target = None
        if action == "move":
            target = _check_folder_any(cur, value)
        for document_id in ids:
            doc = _lock(cur, document_id, see_confidential)
            if doc is None or doc["is_deleted"]:
                continue
            refuse_filed(doc, "moved" if action == "move" else "given another status")
            if action == "status":
                cur.execute("UPDATE orion_ods.document SET status = %s WHERE document_id = %s", (value, document_id))
                detail = f"Status: {value}"
            else:
                if target is not None and (target[1], target[2], target[3]) != (doc["scope"], doc["case_code"], doc["client_code"]):
                    raise DocumentCenterError("A folder can only hold documents of its own case, client or the company.")
                cur.execute("UPDATE orion_ods.document SET folder_id = %s WHERE document_id = %s",
                            (target[0] if target else None, document_id))
                detail = "Moved to " + (target[4] if target else "the top level")
            cur.execute(
                "UPDATE orion_ods.document SET last_updated_by = %s, last_updated_timestamp = CURRENT_TIMESTAMP WHERE document_id = %s",
                (user_id, document_id),
            )
            _log(cur, document_id, "moved" if action == "move" else "edited", detail, user_id)
            changed += 1
    return changed


def _check_folder_any(cur, folder_id: Any) -> tuple[int, str, str | None, str | None, str] | None:
    if folder_id in (None, "", "none"):
        return None
    cur.execute("SELECT folder_id, scope, case_code, client_code, name FROM orion_ods.doc_folder WHERE folder_id = %s",
                (int(folder_id),))
    row = cur.fetchone()
    if row is None:
        raise DocumentCenterError("That folder does not exist.")
    return row


# --------------------------------------------------------------------------------------------------------------------
# Folders


def clean_folder_name(raw: Any) -> str:
    name = " ".join(str(raw or "").split())
    if not name:
        raise DocumentCenterError("Give the folder a name.")
    if len(name) > 80:
        raise DocumentCenterError("A folder name can be at most 80 characters.")
    if re.search(r"[\\/\x00-\x1f]", name):
        raise DocumentCenterError("A folder name cannot contain / or \\.")
    return name


def list_folders(scope: str, case_code: str | None, client_code: str | None, see_confidential: bool) -> dict[str, Any]:
    """Every folder of one space, with how many live documents each holds, counting those in the folders inside it and those
    filed here as well as at their home. ``system`` marks a folder the filing made and keeps in step."""
    if scope not in SCOPES:
        raise DocumentCenterError("That is not a place documents are kept.")
    conf = "" if see_confidential else "AND d.confidentiality = 'Standard'"
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT f.folder_id AS id, f.parent_id, f.name, (f.system_key IS NOT NULL) AS system,
                       (SELECT COUNT(*) FROM orion_ods.document d
                         WHERE d.folder_id = f.folder_id AND NOT d.is_deleted {conf})
                     + (SELECT COUNT(*) FROM orion_ods.document_placement p
                          JOIN orion_ods.document d ON d.document_id = p.document_id
                         WHERE p.folder_id = f.folder_id AND NOT d.is_deleted {conf}) AS documents
                  FROM orion_ods.doc_folder f
                 WHERE f.scope = %s AND f.case_code IS NOT DISTINCT FROM %s AND f.client_code IS NOT DISTINCT FROM %s
                 ORDER BY lower(f.name)""",
            (scope, case_code or None, client_code or None),
        )
        folders = _rows(cur)
        cur.execute(
            f"""SELECT COUNT(*) FROM orion_ods.document d
                 WHERE d.folder_id IS NULL AND NOT d.is_deleted AND d.scope = %s
                   AND d.case_code IS NOT DISTINCT FROM %s AND d.client_code IS NOT DISTINCT FROM %s {conf}""",
            (scope, case_code or None, client_code or None),
        )
        loose = cur.fetchone()[0]
    return {"folders": _rolled_up(folders), "loose": loose}


def _rolled_up(folders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each folder's count becomes its own documents plus those of every folder inside it, as opening it shows them."""
    by_id = {f["id"]: f for f in folders}
    total = {f["id"]: f["documents"] for f in folders}
    for folder in folders:
        parent = folder["parent_id"]
        seen = 0
        while parent in by_id and seen < MAX_FOLDER_DEPTH + 2:
            total[parent] += folder["documents"]
            parent = by_id[parent]["parent_id"]
            seen += 1
    return [{**f, "documents": total[f["id"]]} for f in folders]


def create_folder(user_id: int | None, raw: dict[str, Any]) -> dict[str, Any]:
    name = clean_folder_name(raw.get("name"))
    with db_cursor(commit=True) as cur:
        space = _space_of(cur, raw)
        parent = raw.get("parent_id") or None
        if parent is not None:
            parent = _check_folder(cur, parent, space)
            depth = len(_folder_path(cur, parent))
            if depth >= MAX_FOLDER_DEPTH:
                raise DocumentCenterError(f"Folders can be nested at most {MAX_FOLDER_DEPTH} deep.")
        try:
            cur.execute(
                """INSERT INTO orion_ods.doc_folder (scope, case_code, client_code, parent_id, name, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING folder_id""",
                (*space, parent, name, user_id),
            )
        except pg_errors.UniqueViolation as exc:
            raise DocumentCenterError(f"There is already a folder called {name} here.") from exc
        return {"id": cur.fetchone()[0], "name": name, "parent_id": parent}


MAX_FOLDER_PATHS = 500


def plan_folder_paths(paths: Any, room: int) -> dict[str, list[str]]:
    """The folders each path needs, as clean names from the top down. ``room`` is how many levels still fit under the place the
    folders go in: names deeper than that are left out, so what was in them is kept in the deepest folder that fits."""
    if not isinstance(paths, list) or not paths:
        raise DocumentCenterError("There are no folders to make.")
    if len(paths) > MAX_FOLDER_PATHS:
        raise DocumentCenterError(f"At most {MAX_FOLDER_PATHS} folders can be made at once.")
    plan: dict[str, list[str]] = {}
    for path in paths:
        names = [clean_folder_name(part) for part in str(path or "").split("/") if part.strip()]
        if not names:
            raise DocumentCenterError("Give every folder a name.")
        plan[str(path)] = names[: max(room, 0)]
    return plan


def ensure_folder_paths(user_id: int | None, raw: dict[str, Any]) -> dict[str, Any]:
    """Get or create the folders of an uploaded folder, inside one place (and one folder of it, if ``parent_id`` is given).
    A folder that is already there, whatever the case of its name, is used rather than doubled. Returns each path's folder id."""
    with db_cursor(commit=True) as cur:
        space = _space_of(cur, raw)
        base = _check_folder(cur, raw.get("parent_id") or None, space)
        room = MAX_FOLDER_DEPTH - (len(_folder_path(cur, base)) if base is not None else 0)
        plan = plan_folder_paths(raw.get("paths"), room)
        known: dict[tuple[int | None, str], int] = {}
        created = 0
        flattened = 0
        found: dict[str, int | None] = {}
        for path, names in plan.items():
            if len([p for p in path.split("/") if p.strip()]) > len(names):
                flattened += 1
            at = base
            for name in names:
                key = (at, name.lower())
                if key not in known:
                    where = (*space, at, name)
                    cur.execute(
                        """SELECT folder_id FROM orion_ods.doc_folder
                            WHERE scope = %s AND case_code IS NOT DISTINCT FROM %s AND client_code IS NOT DISTINCT FROM %s
                              AND parent_id IS NOT DISTINCT FROM %s AND lower(name) = lower(%s)""",
                        where,
                    )
                    row = cur.fetchone()
                    if row is None:
                        cur.execute(
                            """INSERT INTO orion_ods.doc_folder (scope, case_code, client_code, parent_id, name, created_by)
                               VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING folder_id""",
                            (*where, user_id),
                        )
                        row = cur.fetchone()
                        if row is None:  # made by someone else a moment ago
                            cur.execute(
                                """SELECT folder_id FROM orion_ods.doc_folder
                                    WHERE scope = %s AND case_code IS NOT DISTINCT FROM %s AND client_code IS NOT DISTINCT FROM %s
                                      AND parent_id IS NOT DISTINCT FROM %s AND lower(name) = lower(%s)""",
                                where,
                            )
                            row = cur.fetchone()
                        else:
                            created += 1
                    known[key] = row[0]
                at = known[key]
            found[path] = at
    return {"folders": found, "created": created, "flattened": flattened}


def create_standard_folders(user_id: int | None, raw: dict[str, Any]) -> int:
    """Add the usual folders for a space, skipping any that already exist. Returns how many were added."""
    with db_cursor(commit=True) as cur:
        space = _space_of(cur, raw)
        added = 0
        for name in STANDARD_FOLDERS[space[0]]:
            cur.execute(
                """INSERT INTO orion_ods.doc_folder (scope, case_code, client_code, parent_id, name, created_by)
                   VALUES (%s, %s, %s, NULL, %s, %s) ON CONFLICT DO NOTHING""",
                (*space, name, user_id),
            )
            added += cur.rowcount
    return added


def rename_folder(folder_id: int, name: Any) -> bool:
    clean = clean_folder_name(name)
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT system_key FROM orion_ods.doc_folder WHERE folder_id = %s", (folder_id,))
        found = cur.fetchone()
        if found and found[0]:
            raise DocumentCenterError("This folder is kept by Orion, which names it after what is filed in it, so it cannot be renamed.")
        try:
            cur.execute("UPDATE orion_ods.doc_folder SET name = %s WHERE folder_id = %s", (clean, folder_id))
        except pg_errors.UniqueViolation as exc:
            raise DocumentCenterError(f"There is already a folder called {clean} here.") from exc
        return cur.rowcount > 0


def delete_folder(folder_id: int) -> bool:
    """Delete an empty folder. Documents in the trash that were in it are left at the top level."""
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT 1 FROM orion_ods.doc_folder WHERE folder_id = %s", (folder_id,))
        if cur.fetchone() is None:
            return False
        cur.execute("SELECT 1 FROM orion_ods.doc_folder WHERE parent_id = %s LIMIT 1", (folder_id,))
        if cur.fetchone():
            raise DocumentCenterError("This folder has folders inside it. Choose to delete it with everything in it, or move those first.")
        cur.execute("SELECT 1 FROM orion_ods.document WHERE folder_id = %s AND NOT is_deleted LIMIT 1", (folder_id,))
        if cur.fetchone():
            raise DocumentCenterError("This folder still has documents in it. Choose to delete it with everything in it, or move them out first.")
        cur.execute(
            """SELECT 1 FROM orion_ods.document_placement p JOIN orion_ods.document d ON d.document_id = p.document_id
                WHERE p.folder_id = %s AND NOT d.is_deleted LIMIT 1""",
            (folder_id,),
        )
        if cur.fetchone():
            raise DocumentCenterError("This folder still has documents filed in it by Orion. They are removed when their source is.")
        cur.execute("UPDATE orion_ods.document SET folder_id = NULL WHERE folder_id = %s", (folder_id,))
        cur.execute("DELETE FROM orion_ods.doc_folder WHERE folder_id = %s", (folder_id,))
    return True


def folder_contents(folder_id: int, see_confidential: bool) -> dict[str, Any] | None:
    """What deleting a folder with everything in it would take away, for the person to read before they agree, and whether it may be done.
    None when there is no such folder. Documents go to the trash (they can be restored from there); folders are gone."""
    with db_cursor() as cur:
        cur.execute("SELECT name FROM orion_ods.doc_folder WHERE folder_id = %s", (folder_id,))
        found = cur.fetchone()
        if found is None:
            return None
        tree = _FOLDER_TREE.replace("%(folder_id)s", "%s")
        cur.execute(f"SELECT f.folder_id, f.name, f.system_key FROM orion_ods.doc_folder f WHERE f.folder_id IN {tree} ORDER BY f.folder_id", (folder_id,))
        folders = cur.fetchall()
        ids = [row[0] for row in folders]
        cur.execute(
            """SELECT d.document_id, d.title, d.source_type, d.is_deleted, d.confidentiality,
                      COALESCE((SELECT COUNT(*) FROM orion_ods.document_version v WHERE v.document_id = d.document_id), 0),
                      COALESCE((SELECT SUM(v.size_bytes) FROM orion_ods.document_version v WHERE v.document_id = d.document_id), 0)
                 FROM orion_ods.document d WHERE d.folder_id = ANY(%s) ORDER BY d.title""",
            (ids,),
        )
        documents = cur.fetchall()
        cur.execute(
            """SELECT COUNT(*) FROM orion_ods.document_placement p JOIN orion_ods.document d ON d.document_id = p.document_id
                WHERE p.folder_id = ANY(%s) AND NOT d.is_deleted""",
            (ids,),
        )
        placed = cur.fetchone()[0]
    everything_live = [d for d in documents if not d[3]]
    hidden = len([d for d in everything_live if d[4] == "Confidential" and not see_confidential])
    # What the person may not see is never named or counted, only said to be there.
    live = [d for d in everything_live if see_confidential or d[4] != "Confidential"]
    mine = [d for d in live if not d[2]]
    filed = len([d for d in live if d[2]]) + placed
    system = [row[1] for row in folders if row[2]]
    reason = None
    if system:
        reason = f"Orion keeps “{system[0]}” itself, for the papers it files automatically, so it cannot be deleted."
    elif filed:
        reason = (
            f"{filed} {'paper' if filed == 1 else 'papers'} Orion filed automatically (bills, employee or EMD papers) "
            f"{'is' if filed == 1 else 'are'} in it. They stay where Orion keeps them: choose another place for them first "
            "(open one and use Where it is kept), then delete the folder."
        )
    elif hidden:
        reason = f"It holds {hidden} confidential {'document' if hidden == 1 else 'documents'} you are not allowed to see, so it cannot be deleted by you."
    return {
        "folder_id": folder_id,
        "name": found[0],
        "subfolders": len(folders) - 1,
        "subfolder_names": [row[1] for row in folders[1:7]],
        "documents": len(mine),
        "document_titles": [d[1] for d in mine[:6]],
        "versions": sum(int(d[5]) for d in mine),
        "size_bytes": sum(int(d[6]) for d in mine),
        "trashed": len([d for d in documents if d[3]]),
        "filed": filed,
        "can_drop": reason is None,
        "reason": reason,
    }


def drop_folder(user_id: int | None, folder_id: int, seen_documents: int, seen_subfolders: int, see_confidential: bool) -> dict[str, int]:
    """Delete a folder and everything in it: its documents go to the trash (and can be restored from there), its folders are deleted. Only with
    the numbers the person was shown, so a folder that changed while they read the warning is looked at again, never emptied unseen."""
    seen = folder_contents(folder_id, see_confidential)
    if seen is None:
        raise DocumentCenterError("That folder does not exist.")
    if not seen["can_drop"]:
        raise DocumentCenterError(seen["reason"] or "That folder cannot be deleted.")
    if seen["documents"] != int(seen_documents) or seen["subfolders"] != int(seen_subfolders):
        raise DocumentCenterError("This folder changed while you were reading. Look at what is in it now, then confirm again.")
    tree = _FOLDER_TREE.replace("%(folder_id)s", "%s")
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT 1 FROM orion_ods.doc_folder WHERE folder_id = %s FOR UPDATE", (folder_id,))
        if cur.fetchone() is None:
            raise DocumentCenterError("That folder does not exist.")
        cur.execute(f"SELECT f.folder_id FROM orion_ods.doc_folder f WHERE f.folder_id IN {tree}", (folder_id,))
        ids = [row[0] for row in cur.fetchall()]
        cur.execute(
            """SELECT document_id FROM orion_ods.document
                WHERE folder_id = ANY(%s) AND NOT is_deleted AND source_type IS NULL FOR UPDATE""",
            (ids,),
        )
        trashed = [row[0] for row in cur.fetchall()]
        for document_id in trashed:
            cur.execute(
                """UPDATE orion_ods.document SET is_deleted = TRUE, deleted_by = %s, deleted_timestamp = CURRENT_TIMESTAMP,
                          last_updated_by = %s, last_updated_timestamp = CURRENT_TIMESTAMP WHERE document_id = %s""",
                (user_id, user_id, document_id),
            )
            _log(cur, document_id, "deleted", f"Its folder “{seen['name']}” was deleted", user_id)
        # What was already in the trash stays there, now at the top level of its place.
        cur.execute("UPDATE orion_ods.document SET folder_id = NULL WHERE folder_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM orion_ods.doc_folder WHERE folder_id = ANY(%s)", (ids,))
    return {"documents": len(trashed), "folders": len(ids)}


# --------------------------------------------------------------------------------------------------------------------
# Moving, as a file explorer does


Destination = tuple[str, "str | None", "str | None", "int | None"]  # (scope, case_code, client_code, folder_id)


def folder_destination(cur, folder_id: int) -> tuple[Destination, str]:
    """A folder as a place to move things to, and its name."""
    cur.execute("SELECT scope, case_code, client_code, name FROM orion_ods.doc_folder WHERE folder_id = %s", (folder_id,))
    row = cur.fetchone()
    if row is None:
        raise DocumentCenterError("That folder does not exist.")
    return (row[0], row[1], row[2], folder_id), row[3]


def _subtree_height(cur, folder_id: int) -> int:
    """How many levels a folder and everything inside it take (a folder with nothing in it is 1)."""
    cur.execute(
        """WITH RECURSIVE tree(id, depth) AS (SELECT %s::int, 1
                UNION ALL SELECT f.folder_id, tree.depth + 1 FROM orion_ods.doc_folder f JOIN tree ON f.parent_id = tree.id)
           SELECT MAX(depth) FROM tree""",
        (folder_id,),
    )
    return cur.fetchone()[0]


def move_folder(cur, folder_id: int, destination: Destination, label: str) -> None:
    """Put a folder (and what is in it) inside another folder, or at the top of its own case, client or the company."""
    cur.execute(
        "SELECT scope, case_code, client_code, parent_id, name, system_key FROM orion_ods.doc_folder WHERE folder_id = %s FOR UPDATE",
        (folder_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise DocumentCenterError("That folder does not exist.")
    scope, case_code, client_code, parent_id, name, system_key = row
    if system_key:
        raise DocumentCenterError(f"{name} is kept by Orion, which puts the papers it files there, so it cannot be moved.")
    if (scope, case_code, client_code) != destination[:3]:
        raise DocumentCenterError(
            f"{name} belongs to a different case, client or the company than {label}. Make a folder there and move the documents instead."
        )
    target = destination[3]
    if target == parent_id or (target is None and parent_id is None):
        return
    if target is not None:
        if target == folder_id or folder_id in {step["id"] for step in _folder_path(cur, target)}:
            raise DocumentCenterError(f"{name} cannot be moved into itself.")
        depth = len(_folder_path(cur, target))
    else:
        depth = 0
    if depth + _subtree_height(cur, folder_id) > MAX_FOLDER_DEPTH:
        raise DocumentCenterError(f"Folders can be nested at most {MAX_FOLDER_DEPTH} deep, so {name} cannot go inside {label}.")
    try:
        cur.execute("UPDATE orion_ods.doc_folder SET parent_id = %s WHERE folder_id = %s", (target, folder_id))
    except pg_errors.UniqueViolation as exc:
        raise DocumentCenterError(f"There is already a folder called {name} in {label}.") from exc


def move_items(user_id: int | None, document_ids: list[int], folder_ids: list[int], destination: Destination, label: str,
               see_confidential: bool) -> dict[str, Any]:
    """Move documents and folders to a folder, or to the top of a case, client or the company, which may be another one than they
    are in. A document that was filed automatically (a bill, an employee's paper) is not moved here: it is returned in ``filed`` so
    the filing can keep it where the person chose. Returns {"moved": n, "folders": m, "filed": [(source_type, source_ref, doc id)]}."""
    documents_ids = sorted({int(i) for i in document_ids})
    folders = sorted({int(i) for i in folder_ids})
    if not documents_ids and not folders:
        raise DocumentCenterError("Choose something to move.")
    if len(documents_ids) + len(folders) > 200:
        raise DocumentCenterError("Move at most 200 things at a time.")
    moved = 0
    filed: list[tuple[str, str, int]] = []
    with db_cursor(commit=True) as cur:
        for folder_id in folders:
            move_folder(cur, folder_id, destination, label)
        for document_id in documents_ids:
            doc = _lock(cur, document_id, see_confidential)
            if doc is None or doc["is_deleted"]:
                continue
            if doc["source_type"]:
                filed.append((doc["source_type"], doc["source_ref"], document_id))
                continue
            scope, case_code, client_code, folder_id = destination
            if (doc["scope"], doc["case_code"], doc["client_code"], doc["folder_id"]) == destination:
                continue
            category = doc["category"] if doc["category"] in CATEGORIES[scope] else "Other"
            cur.execute(
                """UPDATE orion_ods.document SET scope = %s, case_code = %s, client_code = %s, folder_id = %s, category = %s,
                          last_updated_by = %s, last_updated_timestamp = CURRENT_TIMESTAMP WHERE document_id = %s""",
                (scope, case_code, client_code, folder_id, category, user_id, document_id),
            )
            _log(cur, document_id, "moved", f"Moved to {label}" + (f" (kind changed to {category})" if category != doc["category"] else ""), user_id)
            moved += 1
    return {"moved": moved, "folders": len(folders), "filed": filed}


def options() -> dict[str, Any]:
    return {
        "scopes": list(SCOPES),
        "categories": {scope: list(values) for scope, values in CATEGORIES.items()},
        "statuses": list(STATUSES),
        "confidentiality": list(CONFIDENTIALITY),
        "checklist": list(CASE_CHECKLIST),
        "standard_folders": {scope: list(values) for scope, values in STANDARD_FOLDERS.items()},
        "accepted": ACCEPTED,
        "max_mb": MAX_BYTES // (1024 * 1024),
        "max_tags": MAX_TAGS,
    }
