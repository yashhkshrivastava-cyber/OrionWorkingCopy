"""Filing what Orion produces or collects in the Document Center, by itself.

A tax invoice that is issued, an Aadhaar scan uploaded on an employee, a demand-draft copy kept against an EMD: each also
appears in the Document Center, in the folders where a person would look for it. The Document Center is therefore the one
place to find every paper, and the module that made it (billing, an employee's record, an EMD) stays the one place it is
changed.

* A filed document is a real ``orion_ods.document`` with a ``source_type`` and ``source_ref`` that name where it came from;
  the pair is unique, so a source is never filed twice. Its file is a version like any other (the bytes are stored once, by
  their SHA-256, so filing costs no room when the file is already there).
* It has one *home* (a case, a client or the company) and is also *placed* in other places (``document_placement``): a
  case's invoice has the case as its home and is placed in its client's Billing folder. It is one document, not a copy.
* The folders are made here and carry a ``system_key``, so they are found again, renamed when a case or client is, and taken
  over when a person had already made a folder of the same name.
* Nothing is filed by hand and nothing here can be changed in the Document Center (``documents.refuse_filed``): a bill is
  changed in Billing, an employee's file on the employee. When the source changes, the document follows: a new bill version is
  a new version of the document, a cancelled bill is Archived, an employee who moves to another case is placed under it, and
  a source that is deleted sends its document to the trash.
* ``reconcile`` brings everything in step, and is safe to run at any time and as often as wanted (it does nothing when
  nothing changed). It runs when the API starts, after the things that matter are saved, and from the Document Center's
  "Update filing" button. This module is the only writer of filed documents.

Where things are filed (a case's folders; a client's folders follow the same pattern)::

    Case     Billing and payments / Tax invoices / FY 2026-27
             Tender and bid / EMD and guarantees
             Compliance / Staff records / Asha Rao (EMP-0001)
    Client   Billing / Tax invoices / Site name (CS-0001) / FY 2026-27
             Tenders and EMD / Site name (CS-0001)
    Company  People and HR / Employees / Asha Rao (EMP-0001)
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from psycopg2 import errors as pg_errors

from app import documents
from app.database import db_cursor

logger = logging.getLogger(__name__)

BILL = "bill"
EMPLOYEE_DOCUMENT = "employee_document"
EMD_DOCUMENT = "emd_document"

# The category a filed document gets, in the space it is at home in.
CATEGORY = {BILL: "Invoice and payment", EMD_DOCUMENT: "Performance guarantee / EMD", EMPLOYEE_DOCUMENT: "Employee records"}


# --------------------------------------------------------------------------------------------------------------------
# Where a document goes


def fiscal_year(day: date) -> tuple[str, str]:
    """(key, folder name) of the financial year, April to March, that a day falls in: ("FY2026", "FY 2026-27")."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"FY{start}", f"FY {start}-{str(start + 1)[2:]}"


@dataclass(frozen=True)
class Place:
    """A space, and the folders inside it, from the outside in. Each step is (key, name); the key is the folder's identity."""

    scope: str
    case_code: str | None = None
    client_code: str | None = None
    steps: tuple[tuple[str, str], ...] = ()
    # A folder a person chose (``set_choice``): the place is this folder, not the one the steps lead to.
    folder_id: int | None = None

    @property
    def space(self) -> tuple[str, str | None, str | None]:
        return self.scope, self.case_code, self.client_code


def _named(name: str | None, code: str) -> str:
    """"Site name (CS-0001)": the code keeps two records with one name apart, and it is what the folder is found by."""
    label = re.sub(r"[\\/\x00-\x1f]", "-", " ".join((name or "").split()))
    if not label:
        return code
    suffix = f" ({code})"
    room = 80 - len(suffix)  # a folder name is at most 80 characters; the code is what must survive
    if len(label) > room:
        label = label[: room - 1].rstrip() + "…"
    return label + suffix


def bill_places(bill: dict[str, Any]) -> tuple[Place, tuple[Place, ...]]:
    """A bill is at home in its case and is also in its client's Billing folder. An old bill with no case is at home in the client."""
    year_key, year_name = fiscal_year(bill["bill_date"])
    case, client = bill["case_code"], bill["client_code"]
    invoices = (("billing", "Billing and payments"), ("billing/invoices", "Tax invoices"))
    if case:
        home = Place("case", case_code=case, steps=(*invoices, (f"billing/invoices/{year_key}", year_name)))
        if not client:
            return home, ()
        site = _named(bill["case_name"], case)
        return home, (
            Place(
                "client", client_code=client,
                steps=(
                    ("billing", "Billing"), ("billing/invoices", "Tax invoices"), (f"billing/invoices/{case}", site),
                    (f"billing/invoices/{case}/{year_key}", year_name),
                ),
            ),
        )
    return Place("client", client_code=client, steps=(("billing", "Billing"), ("billing/invoices", "Tax invoices"), (f"billing/invoices/{year_key}", year_name))), ()


def emd_places(emd: dict[str, Any]) -> tuple[Place, tuple[Place, ...]]:
    """An EMD's papers are at home in its case, under Tender and bid, and are also in its client's Tenders and EMD folder."""
    case, client = emd["case_code"], emd["client_code"]
    home = Place("case", case_code=case, steps=(("tender", "Tender and bid"), ("tender/emd", "EMD and guarantees")))
    if not client:
        return home, ()
    site = _named(emd["case_name"], case)
    return home, (Place("client", client_code=client, steps=(("tender", "Tenders and EMD"), (f"tender/{case}", site))),)


def employee_places(employee: dict[str, Any]) -> tuple[Place, tuple[Place, ...]]:
    """An employee's papers are in the company's People and HR, and under the case (the site) the employee works at."""
    person = _named(employee["employee_name"], employee["employee_code"])
    code = employee["employee_code"]
    home = Place("company", steps=(("people", "People and HR"), ("people/employees", "Employees"), (f"people/employees/{code}", person)))
    case = employee["case_code"]
    if not case:
        return home, ()
    return home, (
        Place("case", case_code=case, steps=(("compliance", "Compliance"), ("compliance/staff", "Staff records"), (f"compliance/staff/{code}", person))),
    )


# --------------------------------------------------------------------------------------------------------------------
# Where a person chose to keep a document

Choice = tuple[str, "str | None", "str | None", "int | None"]  # (scope, case_code, client_code, folder_id)


def _load_choices(source_type: str) -> dict[str, Choice]:
    """{source_ref: choice} for the documents of one kind that someone filed by hand."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT source_ref, scope, case_code, client_code, folder_id FROM orion_ods.document_filing_choice WHERE source_type = %s",
            (source_type,),
        )
        return {ref: (scope, case, client, folder) for ref, scope, case, client, folder in cur.fetchall()}


def _choose(home: Place, others: tuple[Place, ...], choice: Choice | None) -> tuple[Place, tuple[Place, ...]]:
    """Apply a person's choice: the chosen folder is the home, the places the filing would have used in other spaces stay as
    placements (a bill chosen into a client's folder is still in its case), and the one it would have used in the chosen space goes."""
    if not choice:
        return home, others
    scope, case, client, folder = choice
    chosen = Place(scope, case_code=case, client_code=client, folder_id=folder)
    return chosen, tuple(place for place in (home, *others) if place.space != chosen.space)


def _choice_key(choice: Choice | None) -> str:
    return "" if not choice else "->" + "/".join(str(part or "") for part in choice)


def set_choice(source_type: str, source_ref: str, destination: Choice | None, user_id: int | None) -> None:
    """Keep a filed document where a person chose, or, with None, go back to where the filing puts it by itself.
    The caller then calls ``refile``."""
    with db_cursor(commit=True) as cur:
        if destination is None:
            cur.execute("DELETE FROM orion_ods.document_filing_choice WHERE source_type = %s AND source_ref = %s", (source_type, source_ref))
            return
        cur.execute(
            """INSERT INTO orion_ods.document_filing_choice (source_type, source_ref, scope, case_code, client_code, folder_id, chosen_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (source_type, source_ref) DO UPDATE SET scope = EXCLUDED.scope, case_code = EXCLUDED.case_code,
                   client_code = EXCLUDED.client_code, folder_id = EXCLUDED.folder_id, chosen_by = EXCLUDED.chosen_by,
                   chosen_timestamp = CURRENT_TIMESTAMP""",
            (source_type, source_ref, *destination, user_id),
        )


def refile(source_type: str, source_ref: str) -> None:
    """Bring one filed source in step again, after its choice changed."""
    if source_type == BILL:
        reconcile_quietly(bill_code=source_ref)
    elif source_type == EMPLOYEE_DOCUMENT:
        reconcile_quietly(employee_code=source_ref.split(":")[0])
    elif source_type == EMD_DOCUMENT:
        reconcile_quietly(emd_code=source_ref.split(":")[0])


def describe_places(cur, home: Place, others: tuple[Place, ...]) -> list[dict[str, Any]]:
    """Where a document would be, as words for the person choosing: [{home, label}] with each place's name and folder path."""

    def label(place: Place) -> str:
        if place.scope == "company":
            first = "Company documents"
        elif place.scope == "case":
            cur.execute('SELECT case_name FROM orion_ods."case" WHERE case_code = %s', (place.case_code,))
            found = cur.fetchone()
            first = f"Case: {found[0] if found else place.case_code}"
        else:
            cur.execute("SELECT client_name FROM orion_ods.client WHERE client_code = %s", (place.client_code,))
            found = cur.fetchone()
            first = f"Client: {found[0] if found else place.client_code}"
        names = [name for _key, name in place.steps]
        if place.folder_id is not None:
            names = [step["name"] for step in documents._folder_path(cur, place.folder_id)]
        return " › ".join([first, *names])

    return [{"home": index == 0, "label": label(place)} for index, place in enumerate((home, *others))]


def preview_bill(case_code: str, bill_date: date, choice: Choice | None) -> list[dict[str, Any]]:
    """Where a bill for this case and date would be filed, for the person choosing before it exists."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT cs.case_name, cs.client_code FROM orion_ods."case" cs WHERE cs.case_code = %s""",
            (case_code,),
        )
        found = cur.fetchone()
        if not found:
            raise documents.DocumentCenterError("Choose the case first.")
        bill = {"case_code": case_code, "case_name": found[0], "client_code": found[1], "bill_date": bill_date}
        home, others = _choose(*bill_places(bill), choice)
        return describe_places(cur, home, others)


# --------------------------------------------------------------------------------------------------------------------
# Making the folders and the document


def _ensure_folders(cur, place: Place) -> int | None:
    """The id of the last folder of a place's path, made (or taken over, or renamed) as needed."""
    if place.folder_id is not None:
        return place.folder_id
    parent: int | None = None
    for key, name in place.steps:
        cur.execute(
            """SELECT folder_id, name, parent_id FROM orion_ods.doc_folder
                WHERE scope = %s AND case_code IS NOT DISTINCT FROM %s AND client_code IS NOT DISTINCT FROM %s AND system_key = %s""",
            (*place.space, key),
        )
        found = cur.fetchone()
        if found:
            folder_id, current, current_parent = found
            if current != name or current_parent != parent:
                # Renamed to follow its case or client, unless a folder beside it already has that name.
                cur.execute(
                    """SELECT 1 FROM orion_ods.doc_folder
                        WHERE scope = %s AND case_code IS NOT DISTINCT FROM %s AND client_code IS NOT DISTINCT FROM %s
                          AND parent_id IS NOT DISTINCT FROM %s AND lower(name) = lower(%s) AND folder_id <> %s""",
                    (*place.space, parent, name, folder_id),
                )
                if cur.fetchone() is None:
                    cur.execute("UPDATE orion_ods.doc_folder SET name = %s, parent_id = %s WHERE folder_id = %s", (name, parent, folder_id))
            parent = folder_id
            continue
        # A folder a person made with the same name in the same place is taken over, not doubled.
        cur.execute(
            """SELECT folder_id FROM orion_ods.doc_folder
                WHERE scope = %s AND case_code IS NOT DISTINCT FROM %s AND client_code IS NOT DISTINCT FROM %s
                  AND parent_id IS NOT DISTINCT FROM %s AND lower(name) = lower(%s) AND system_key IS NULL""",
            (*place.space, parent, name),
        )
        taken = cur.fetchone()
        if taken:
            cur.execute("UPDATE orion_ods.doc_folder SET system_key = %s WHERE folder_id = %s", (key, taken[0]))
            parent = taken[0]
            continue
        cur.execute(
            """INSERT INTO orion_ods.doc_folder (scope, case_code, client_code, parent_id, name, system_key)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING folder_id""",
            (*place.space, parent, name, key),
        )
        parent = cur.fetchone()[0]
    return parent


LOOK_MARK = "\x1f"  # between a stored source_version's layout and its look; neither can hold it


def stored_version(content: str, layout: str, look: str = "") -> str:
    """What is kept in ``document.source_version`` to tell whether a source has changed since it was filed."""
    return f"{content}|{layout}" + (f"{LOOK_MARK}{look}" if look else "")


@dataclass
class Filing:
    """Everything needed to file one source: what it is, its file, and where it goes."""

    source_type: str
    source_ref: str
    # content decides whether the file is new; layout decides the title, folders and placements. Either changing files it again.
    content: str
    layout: str
    title: str
    # None for a source whose file is already filed and has not changed (a case was renamed): only the place and the details are
    # brought up to date, and the file as it was filed stays as it is.
    file_name: str | None
    data: bytes | None
    home: Place
    others: tuple[Place, ...]
    status: str = "Active"
    confidentiality: str = "Standard"
    document_date: date | None = None
    tags: tuple[str, ...] = ()
    user_id: int | None = None
    note: str = "Filed automatically"
    extra: dict[str, Any] = field(default_factory=dict)
    # How the file is drawn (a bill's typeface and size). It is not what the source says, so a change in it makes no new version: the
    # current version's file is drawn again in its place (``redraw``), and the history keeps one version for one content.
    look: str = ""
    redraw: bool = False

    @property
    def version(self) -> str:
        return stored_version(self.content, self.layout, self.look)


def _place_documents(cur, document_id: int, places: tuple[Place, ...]) -> None:
    """Make the document's placements exactly these: add the missing, move the changed, drop the rest."""
    wanted = {}
    for place in places:
        wanted[place.space] = _ensure_folders(cur, place)
    cur.execute("SELECT placement_id, scope, case_code, client_code FROM orion_ods.document_placement WHERE document_id = %s", (document_id,))
    for placement_id, *space in cur.fetchall():
        if tuple(space) not in wanted:
            cur.execute("DELETE FROM orion_ods.document_placement WHERE placement_id = %s", (placement_id,))
    for space, folder_id in wanted.items():
        cur.execute(
            """INSERT INTO orion_ods.document_placement (document_id, scope, case_code, client_code, folder_id)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (document_id, scope, COALESCE(case_code, ''), COALESCE(client_code, ''))
               DO UPDATE SET folder_id = EXCLUDED.folder_id""",
            (document_id, *space, folder_id),
        )


def file_document(filing: Filing) -> str:
    """File one source. Returns "filed" (new), "updated" (a new version, or its details or place changed) or "unchanged"."""
    name = ext = content_type = sha = None
    if filing.data is not None:
        name, ext, content_type = documents.check_file(filing.file_name, filing.data)
        sha = documents.sha256_of(filing.data)
    with db_cursor(commit=True) as cur:
        cur.execute(
            """SELECT document_id, current_version, source_version, is_deleted FROM orion_ods.document
                WHERE source_type = %s AND source_ref = %s FOR UPDATE""",
            (filing.source_type, filing.source_ref),
        )
        existing = cur.fetchone()
        if existing and existing[2] == filing.version and not existing[3]:
            return "unchanged"
        if existing is None and filing.data is None:
            raise LookupError(f"{filing.source_ref} is not filed yet")
        home_folder = _ensure_folders(cur, filing.home)
        space = filing.home.space
        if existing is None:
            text = documents.extract_text(ext, filing.data)
            documents._store_blob(cur, sha, filing.data)
            cur.execute(
                """
                INSERT INTO orion_ods.document
                    (scope, case_code, client_code, folder_id, title, category, tags, status, confidentiality, document_date,
                     content_text, source_type, source_ref, source_version, created_by, last_updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING document_id
                """,
                (*space, home_folder, filing.title, CATEGORY[filing.source_type], list(filing.tags), filing.status,
                 filing.confidentiality, filing.document_date, text, filing.source_type, filing.source_ref, filing.version,
                 filing.user_id, filing.user_id),
            )
            document_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO orion_ods.document_version
                       (document_id, version_no, file_name, content_type, size_bytes, sha256, change_note, uploaded_by)
                   VALUES (%s, 1, %s, %s, %s, %s, %s, %s)""",
                (document_id, name, content_type, len(filing.data), sha, filing.note, filing.user_id),
            )
            documents._log(cur, document_id, "uploaded", f"{name} (filed automatically)", filing.user_id)
            _place_documents(cur, document_id, filing.others)
            return "filed"

        document_id, current_version, _stored, was_deleted = existing
        cur.execute("SELECT sha256 FROM orion_ods.document_version WHERE document_id = %s AND version_no = %s", (document_id, current_version))
        version_no = current_version
        drawn = cur.fetchone()[0]
        if filing.data is not None and drawn != sha and filing.redraw:
            # Same content, drawn another way: the current version's file is replaced, no version is added.
            documents._store_blob(cur, sha, filing.data)
            cur.execute(
                """UPDATE orion_ods.document_version SET file_name = %s, content_type = %s, size_bytes = %s, sha256 = %s
                    WHERE document_id = %s AND version_no = %s""",
                (name, content_type, len(filing.data), sha, document_id, current_version),
            )
            cur.execute(
                """DELETE FROM orion_ods.document_blob b WHERE b.sha256 = %s
                      AND NOT EXISTS (SELECT 1 FROM orion_ods.document_version v WHERE v.sha256 = b.sha256)""",
                (drawn,),
            )
            documents._log(cur, document_id, "edited", f"Version {current_version} drawn again in its new typeface or size (no new version)", filing.user_id)
        elif filing.data is not None and drawn != sha:
            version_no = current_version + 1
            documents._store_blob(cur, sha, filing.data)
            cur.execute(
                """INSERT INTO orion_ods.document_version
                       (document_id, version_no, file_name, content_type, size_bytes, sha256, change_note, uploaded_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (document_id, version_no, name, content_type, len(filing.data), sha, filing.note, filing.user_id),
            )
            documents._log(cur, document_id, "new_version", f"Version {version_no}: {name} (filed automatically)", filing.user_id)
        text = documents.extract_text(ext, filing.data) if version_no != current_version else None
        cur.execute(
            """
            UPDATE orion_ods.document SET
                scope = %s, case_code = %s, client_code = %s, folder_id = %s, title = %s, status = %s, document_date = %s,
                confidentiality = %s, current_version = %s, source_version = %s,
                content_text = COALESCE(%s, content_text),
                is_deleted = FALSE, deleted_by = NULL, deleted_timestamp = NULL,
                last_updated_by = %s, last_updated_timestamp = CURRENT_TIMESTAMP
             WHERE document_id = %s
            """,
            (*space, home_folder, filing.title, filing.status, filing.document_date, filing.confidentiality, version_no,
             filing.version, text, filing.user_id, document_id),
        )
        if was_deleted:
            documents._log(cur, document_id, "restored", "The source is back", None)
        _place_documents(cur, document_id, filing.others)
        return "updated"


# --------------------------------------------------------------------------------------------------------------------
# The sources


def _bill_filing(row: dict[str, Any], with_file: bool = True, redraw: bool = False) -> Filing:
    """A bill's PDF (without the letterhead: the invoice as issued) and where it goes. Renders the PDF, unless the file already
    filed is the one to keep (only a name changed): an invoice is not redrawn because its site was renamed."""
    file_name = data = None
    if with_file:
        from app import receivables

        made = receivables.invoice_document(row["bill_code"], False)
        if made is None:
            raise LookupError(f"bill {row['bill_code']} is gone")
        file_name, data = made
    cancelled = row["status"] == "Cancelled"
    home, others = _choose(*bill_places(row), row.get("choice"))
    return Filing(
        source_type=BILL, source_ref=row["bill_code"], content=_bill_content(row), layout=_bill_layout(row),
        look=row.get("look") or "", redraw=redraw,
        title=f"Tax invoice {row['bill_number']}" + (" (cancelled)" if cancelled else ""),
        file_name=file_name, data=data, home=home, others=others, status="Archived" if cancelled else "Active",
        document_date=row["bill_date"], tags=("invoice", "bill"), user_id=row["version_by"],
        note=("Cancelled" if cancelled else f"Bill version {row['version_no']}"),
    )


def _bill_content(row: dict[str, Any]) -> str:
    # Only what the bill says: its version and whether it is cancelled. Its typeface and text size are how it looks, not a change
    # (it makes no new version in Billing either), so choosing another one files nothing new.
    return f"{row['version_no']}:{row['status']}"


def _without_font(stored: str) -> str:
    """A version filed when the typeface was still part of ``_bill_content`` ends ``...:Family:size``. Read it as it is now written,
    so those bills are not filed a second time for a choice that was never a change."""
    content, bar, layout = stored.partition("|")
    return ":".join(content.split(":")[:2]) + bar + layout


def _bill_look(row: dict[str, Any], company: dict[str, Any]) -> str:
    """The typeface and size the bill is drawn in (its own choice, else the company's), or nothing when it is the usual Arial 9, so that a
    bill nobody has restyled has the same stored version as before the look was kept."""
    from app import bill_fonts

    font = bill_fonts.effective(row, company)
    if font["family"] == bill_fonts.DEFAULT_FAMILY and font["size"] == bill_fonts.DEFAULT_SIZE:
        return ""
    return f"{font['family']}:{font['size']}"


def _bill_layout(row: dict[str, Any]) -> str:
    return "/".join(str(row.get(k) or "") for k in ("case_code", "case_name", "client_code", "bill_number", "bill_date")) + _choice_key(row.get("choice"))


_BILLS = """
    SELECT b.bill_code, b.bill_number, b.bill_date, b.version_no, b.status, b.case_code, cs.case_name,
           COALESCE(b.client_code, cs.client_code) AS client_code, b.version_by, b.font_family, b.font_size
      FROM orion_ods.bill b
      LEFT JOIN orion_ods."case" cs ON cs.case_code = b.case_code
"""

_EMPLOYEE_DOCUMENTS = """
    SELECT d.document_id, d.employee_code, d.doc_type, d.title, d.file_name, d.uploaded_by, d.uploaded_timestamp,
           e.employee_name, e.employee_case_code AS case_code
      FROM orion_ods.employee_document d
      JOIN orion_ods.employee e ON e.employee_code = d.employee_code
"""

_EMD_DOCUMENTS = """
    SELECT d.document_id, d.emd_code, d.doc_type, d.title, d.file_name, d.uploaded_by, d.uploaded_timestamp,
           m.case_code, cs.case_name, cs.client_code
      FROM orion_ods.emd_document d
      JOIN orion_ods.emd m ON m.emd_code = d.emd_code
      JOIN orion_ods."case" cs ON cs.case_code = m.case_code
"""


def _rows(cur) -> list[dict[str, Any]]:
    return [dict(zip((c.name for c in cur.description), row)) for row in cur.fetchall()]


def _kept_title(row: dict[str, Any], lead: str) -> str:
    detail = row["title"] or row["doc_type"]
    return " ".join(f"{lead} — {detail}".split())[:150]


def _employee_filing(row: dict[str, Any], data: bytes | None) -> Filing:
    home, others = _choose(*employee_places(row), row.get("choice"))
    return Filing(
        source_type=EMPLOYEE_DOCUMENT, source_ref=f"{row['employee_code']}:{row['document_id']}", content="1",
        layout=f"{row['case_code'] or ''}/{row['employee_name']}/{row['title'] or ''}/{row['doc_type']}" + _choice_key(row.get("choice")),
        title=_kept_title(row, f"{row['employee_name']} ({row['employee_code']})"), file_name=row["file_name"], data=data,
        home=home, others=others, confidentiality="Confidential", document_date=row["uploaded_timestamp"].date(),
        tags=("employee", row["doc_type"].lower()[:30]), user_id=row["uploaded_by"], note="Uploaded on the employee",
    )


def _emd_filing(row: dict[str, Any], data: bytes | None) -> Filing:
    home, others = _choose(*emd_places(row), row.get("choice"))
    return Filing(
        source_type=EMD_DOCUMENT, source_ref=f"{row['emd_code']}:{row['document_id']}", content="1",
        layout=f"{row['case_code']}/{row['case_name']}/{row['client_code'] or ''}/{row['title'] or ''}/{row['doc_type']}" + _choice_key(row.get("choice")),
        title=_kept_title(row, row["emd_code"]), file_name=row["file_name"], data=data, home=home, others=others,
        document_date=row["uploaded_timestamp"].date(), tags=("emd", row["doc_type"].lower()[:30]), user_id=row["uploaded_by"],
        note="Uploaded on the EMD",
    )


def _file_bytes(table: str, document_id: int) -> bytes:
    with db_cursor() as cur:
        cur.execute(f"SELECT file_data FROM orion_ods.{table} WHERE document_id = %s", (document_id,))  # noqa: S608 - a fixed table name
        found = cur.fetchone()
    return bytes(found[0]) if found else b""


def _stored_versions(source_type: str) -> dict[str, tuple[str, bool]]:
    """What is already filed for a kind of source: {source_ref: (source_version, is_deleted)}."""
    with db_cursor() as cur:
        cur.execute("SELECT source_ref, source_version, is_deleted FROM orion_ods.document WHERE source_type = %s", (source_type,))
        return {ref: (version, deleted) for ref, version, deleted in cur.fetchall()}


def _needs(stored: dict[str, tuple[str, bool]], ref: str, version: str) -> bool:
    have = stored.get(ref)
    return have is None or have[1] or have[0] != version


def _file_is_current(stored: dict[str, tuple[str, bool]], ref: str, version: str) -> bool:
    """Whether the file already filed is the right one, so only the details and the place need bringing up to date."""
    have = stored.get(ref)
    return have is not None and not have[1] and have[0].split("|", 1)[0] == version.split("|", 1)[0]


def _attempt(counts: dict[str, int], label: str, action) -> None:
    try:
        counts[action()] += 1
    except (documents.DocumentCenterError, LookupError, pg_errors.UniqueViolation) as exc:
        # One source that cannot be filed (a file that is not what its name says, a bill that was deleted a moment ago, another
        # process that filed it first) does not stop the rest. It is tried again next time.
        counts["failed"] += 1
        logger.warning("Could not file %s in the Document Center: %s", label, exc)
    except Exception:  # noqa: BLE001 - a bill whose PDF cannot be drawn must not stop every other paper being filed
        counts["failed"] += 1
        logger.exception("Could not file %s in the Document Center", label)


def _file_bills(counts: dict[str, int], bill_code: str | None, case_code: str | None, client_code: str | None) -> None:
    where, params = [], []
    for column, value in (("b.bill_code", bill_code), ("b.case_code", case_code), ("COALESCE(b.client_code, cs.client_code)", client_code)):
        if value:
            where.append(f"{column} = %s")
            params.append(value)
    with db_cursor() as cur:
        cur.execute(_BILLS + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY b.bill_code", params)
        bills = _rows(cur)
    stored = {ref: (_without_font(version), deleted) for ref, (version, deleted) in _stored_versions(BILL).items()}
    choices = _load_choices(BILL)
    from app import billing

    company = billing.get_profile()
    for bill in bills:
        bill["choice"] = choices.get(bill["bill_code"])
        bill["look"] = _bill_look(bill, company)
        version = stored_version(_bill_content(bill), _bill_layout(bill), bill["look"])
        if _needs(stored, bill["bill_code"], version):
            keep = _file_is_current(stored, bill["bill_code"], version)
            # The same content in another typeface or size: the file is drawn again and replaces the current version's, with no new version.
            redraw = keep and stored[bill["bill_code"]][0].partition(LOOK_MARK)[2] != bill["look"]
            _attempt(
                counts, f"bill {bill['bill_code']}",
                lambda bill=bill, keep=keep, redraw=redraw: file_document(_bill_filing(bill, with_file=redraw or not keep, redraw=redraw)),
            )
        else:
            counts["unchanged"] += 1


def _file_kept(counts: dict[str, int], kind: str, sql: str, table: str, build, filters: dict[str, Any]) -> None:
    """Employee and EMD papers: the same loop, since each is a file already kept on its record."""
    where, params = [], []
    for column, value in filters.items():
        if value:
            where.append(f"{column} = %s")
            params.append(value)
    with db_cursor() as cur:
        cur.execute(sql + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY d.document_id", params)
        rows = _rows(cur)
    stored = _stored_versions(kind)
    choices = _load_choices(kind)
    for row in rows:
        code = row["employee_code"] if kind == EMPLOYEE_DOCUMENT else row["emd_code"]
        ref = f"{code}:{row['document_id']}"
        row["choice"] = choices.get(ref)

        probe = build(row, b"")
        keep = _file_is_current(stored, ref, probe.version)

        def one(row=row, keep=keep):
            return file_document(build(row, None if keep else _file_bytes(table, row["document_id"])))

        if _needs(stored, ref, probe.version):
            _attempt(counts, f"{kind} {ref}", one)
        else:
            counts["unchanged"] += 1


def _retire(counts: dict[str, int]) -> None:
    """Send to the trash the filed documents whose source no longer exists, and remove the folders nothing is in any more."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE orion_ods.document d SET is_deleted = TRUE, deleted_timestamp = CURRENT_TIMESTAMP, deleted_by = NULL,
                   folder_id = NULL, last_updated_timestamp = CURRENT_TIMESTAMP
             WHERE d.source_type IS NOT NULL AND NOT d.is_deleted AND NOT (
                   (d.source_type = 'bill' AND EXISTS (SELECT 1 FROM orion_ods.bill b WHERE b.bill_code = d.source_ref))
                OR (d.source_type = 'employee_document' AND EXISTS (
                        SELECT 1 FROM orion_ods.employee_document s
                         WHERE s.employee_code || ':' || s.document_id = d.source_ref))
                OR (d.source_type = 'emd_document' AND EXISTS (
                        SELECT 1 FROM orion_ods.emd_document s WHERE s.emd_code || ':' || s.document_id = d.source_ref)))
            RETURNING d.document_id
            """
        )
        retired = [document_id for (document_id,) in cur.fetchall()]
        for document_id in retired:
            documents._log(cur, document_id, "deleted", "The source was removed", None)
            counts["retired"] += 1
        # A choice whose source is gone (nothing will ever file it again) is forgotten.
        cur.execute(
            """DELETE FROM orion_ods.document_filing_choice c WHERE NOT (
                   (c.source_type = 'bill' AND EXISTS (SELECT 1 FROM orion_ods.bill b WHERE b.bill_code = c.source_ref))
                OR (c.source_type = 'employee_document' AND EXISTS (
                        SELECT 1 FROM orion_ods.employee_document s WHERE s.employee_code || ':' || s.document_id = c.source_ref))
                OR (c.source_type = 'emd_document' AND EXISTS (
                        SELECT 1 FROM orion_ods.emd_document s WHERE s.emd_code || ':' || s.document_id = c.source_ref)))"""
        )
        # In the trash a filed document is in no place, so the folders it was in can go; if its source comes back it is placed again.
        cur.execute(
            """DELETE FROM orion_ods.document_placement p USING orion_ods.document d
                WHERE d.document_id = p.document_id AND d.is_deleted AND d.source_type IS NOT NULL"""
        )
        cur.execute("UPDATE orion_ods.document SET folder_id = NULL WHERE is_deleted AND source_type IS NOT NULL AND folder_id IS NOT NULL")
        # An empty folder this module made, from the deepest up (a few passes: one per level).
        for _ in range(documents.MAX_FOLDER_DEPTH):
            cur.execute(
                """
                DELETE FROM orion_ods.doc_folder f
                 WHERE f.system_key IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM orion_ods.doc_folder c WHERE c.parent_id = f.folder_id)
                   AND NOT EXISTS (SELECT 1 FROM orion_ods.document d WHERE d.folder_id = f.folder_id)
                   AND NOT EXISTS (SELECT 1 FROM orion_ods.document_placement p WHERE p.folder_id = f.folder_id)
                """
            )
            if cur.rowcount == 0:
                break


def reconcile(*, bill_code: str | None = None, case_code: str | None = None, client_code: str | None = None,
              employee_code: str | None = None, emd_code: str | None = None) -> dict[str, int]:
    """Bring the Document Center in step with its sources. With no argument everything is looked at; each argument narrows it to
    one bill, case, client, employee or EMD. Returns how many were filed, updated, left as they were, retired or failed."""
    counts = {"filed": 0, "updated": 0, "unchanged": 0, "retired": 0, "failed": 0}
    narrowed = any((bill_code, case_code, client_code, employee_code, emd_code))
    if not narrowed or bill_code or case_code or client_code:
        _file_bills(counts, bill_code, case_code, client_code)
    if not narrowed or employee_code or case_code:
        _file_kept(counts, EMPLOYEE_DOCUMENT, _EMPLOYEE_DOCUMENTS, "employee_document", _employee_filing,
                   {"d.employee_code": employee_code, "e.employee_case_code": case_code})
    if not narrowed or emd_code or case_code or client_code:
        _file_kept(counts, EMD_DOCUMENT, _EMD_DOCUMENTS, "emd_document", _emd_filing,
                   {"d.emd_code": emd_code, "m.case_code": case_code, "cs.client_code": client_code})
    _retire(counts)
    return counts


def reconcile_quietly(**narrow: str | None) -> None:
    """``reconcile`` for after something else was saved: a problem is logged and never reaches the person who saved it."""
    try:
        reconcile(**narrow)
    except Exception:  # noqa: BLE001 - filing a copy must never undo or fail the save that caused it; the next run does it
        logger.exception("Filing in the Document Center failed")


def entity_saved(name: str, record_id: Any) -> None:
    """A case, client, employee or EMD was saved or deleted: refile what depends on its name, its client or its case."""
    key = {"Case": "case_code", "Client": "client_code", "Employee": "employee_code", "EMD": "emd_code"}.get(name)
    if key and record_id:
        reconcile_quietly(**{key: str(record_id)})


# A look at everything shortly after the API starts (the first run files what was there before this existed, and what was saved while
# the API was down), and again now and then, so a source changed in a way no hook saw is still filed.
FIRST_RUN_DELAY_SECONDS = 20
REPEAT_SECONDS = 6 * 60 * 60


def start(stop: threading.Event) -> threading.Thread:
    """Start the background filing. ``stop`` ends it; the thread never blocks shutdown."""

    def loop() -> None:
        if stop.wait(FIRST_RUN_DELAY_SECONDS):
            return
        while True:
            try:
                counts = reconcile()
                logger.info("Document Center filing: %s", counts)
            except Exception:  # noqa: BLE001 - the loop must survive a bad run; the next one tries again
                logger.exception("Filing in the Document Center failed")
            if stop.wait(REPEAT_SECONDS):
                return

    thread = threading.Thread(target=loop, name="orion-documents-filing", daemon=True)
    thread.start()
    return thread
