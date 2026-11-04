"""The Document Center as a file explorer: where you are (a *node*), what is in it and how to get back out, and moving things.

A node is one of

    root              Documents (the company, the clients and the cases)
    company           the company's own documents
    clients, cases    every client / every case
    client:CL-0001    one client      case:CS-0001   one case
    folder:12         a folder (it belongs to the company, a case or a client)
    all, trash        every document in one list, and the trash

Reading is here; the writes are ``documents`` (moving, folders) and ``documents_filing`` (where a bill or another filed paper is kept).
The documents of a node are the node's own (what a folder holds directly, as on a computer); with a search or a filter they are
everything inside it. A folder's count is everything inside it, as the Document Center has always counted.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app import documents, documents_filing
from app.database import db_cursor

DocumentCenterError = documents.DocumentCenterError

_NODE = re.compile(r"^(root|company|clients|cases|all|trash|(client|case):[A-Za-z0-9._-]{1,40}|folder:[0-9]{1,9})$")
PLACES = ("root", "company", "clients", "cases")  # nodes that are only a way to get to the others
SPACE_NODES = ("company", "client", "case")


def _node_id(kind: str, value: str | None = None) -> str:
    return f"{kind}:{value}" if value else kind


def resolve(cur, node: str) -> dict[str, Any]:
    """What a node is: its kind, the space it is in, its name, and the way back (``trail``, each step with its own node)."""
    node = (node or "root").strip()
    if not _NODE.match(node):
        raise DocumentCenterError("That is not a place in the Document Center.")
    kind, _, value = node.partition(":")
    base: dict[str, Any] = {"id": node, "kind": kind, "scope": None, "case_code": None, "client_code": None, "folder_id": None}
    root = {"id": "root", "label": "Documents"}
    if kind == "root":
        return {**base, "label": "Documents", "trail": [root]}
    if kind == "all":
        return {**base, "label": "All documents", "trail": [root, {"id": "all", "label": "All documents"}]}
    if kind == "trash":
        return {**base, "label": "Trash", "trail": [root, {"id": "trash", "label": "Trash"}]}
    if kind == "company":
        return {**base, "scope": "company", "label": "Company documents", "trail": [root, {"id": "company", "label": "Company documents"}]}
    if kind == "clients":
        return {**base, "label": "Clients", "trail": [root, {"id": "clients", "label": "Clients"}]}
    if kind == "cases":
        return {**base, "label": "Cases", "trail": [root, {"id": "cases", "label": "Cases"}]}
    if kind == "client":
        cur.execute("SELECT client_name FROM orion_ods.client WHERE client_code = %s", (value,))
        found = cur.fetchone()
        if not found:
            raise DocumentCenterError("That client does not exist.")
        return {**base, "scope": "client", "client_code": value, "label": found[0],
                "trail": [root, {"id": "clients", "label": "Clients"}, {"id": node, "label": found[0]}]}
    if kind == "case":
        cur.execute('SELECT case_name FROM orion_ods."case" WHERE case_code = %s', (value,))
        found = cur.fetchone()
        if not found:
            raise DocumentCenterError("That case does not exist.")
        return {**base, "scope": "case", "case_code": value, "label": found[0],
                "trail": [root, {"id": "cases", "label": "Cases"}, {"id": node, "label": found[0]}]}
    folder_id = int(value)
    cur.execute("SELECT scope, case_code, client_code, name, system_key FROM orion_ods.doc_folder WHERE folder_id = %s", (folder_id,))
    row = cur.fetchone()
    if not row:
        raise DocumentCenterError("That folder does not exist (it may have been deleted).")
    scope, case_code, client_code, name, system_key = row
    space = resolve(cur, "company" if scope == "company" else _node_id(scope, case_code or client_code))
    trail = [*space["trail"], *({"id": _node_id("folder", step["id"]), "label": step["name"]} for step in documents._folder_path(cur, folder_id))]
    return {**base, "scope": scope, "case_code": case_code, "client_code": client_code, "folder_id": folder_id, "label": name,
            "system": bool(system_key), "trail": trail}


def _children_counts(see_confidential: bool) -> str:
    return "" if see_confidential else "AND d.confidentiality = 'Standard'"


def _space_entries(cur, kind: str, see_confidential: bool) -> list[dict[str, Any]]:
    """Every client or every case, whether or not it has documents, with how many it holds."""
    conf = _children_counts(see_confidential)
    today = date.today()
    counts = """COUNT(*) AS n, COUNT(*) FILTER (WHERE d.expiry_date IS NOT NULL AND d.status IN ('Draft', 'Active')
                                                 AND d.expiry_date <= %s + d.reminder_days) AS attention"""
    if kind == "clients":
        cur.execute(
            f"""WITH {documents._APPEARANCES}, held AS (
                    SELECT d.client_code, {counts} FROM appear d WHERE d.scope = 'client' {conf} GROUP BY d.client_code)
                SELECT cl.client_code, cl.client_name, COALESCE(h.n, 0), COALESCE(h.attention, 0)
                  FROM orion_ods.client cl LEFT JOIN held h ON h.client_code = cl.client_code
                 ORDER BY lower(cl.client_name) LIMIT 5000""",
            (today,),
        )
        return [{"node": f"client:{code}", "name": name, "kind": "client", "documents": n, "attention": att, "sub": None}
                for code, name, n, att in cur.fetchall()]
    cur.execute(
        f"""WITH {documents._APPEARANCES}, held AS (
                SELECT d.case_code, {counts} FROM appear d WHERE d.scope = 'case' {conf} GROUP BY d.case_code)
            SELECT c.case_code, c.case_name, c.case_status, cl.client_name, COALESCE(h.n, 0), COALESCE(h.attention, 0)
              FROM orion_ods."case" c
              LEFT JOIN orion_ods.client cl ON cl.client_code = c.client_code
              LEFT JOIN held h ON h.case_code = c.case_code
             ORDER BY (c.case_status = 'Active') DESC NULLS LAST, lower(c.case_name) LIMIT 5000""",
        (today,),
    )
    return [{"node": f"case:{code}", "name": name, "kind": "case", "documents": n, "attention": att,
             "sub": " · ".join(part for part in (client, status) if part) or None}
            for code, name, status, client, n, att in cur.fetchall()]


def _folder_entries(cur, ctx: dict[str, Any], see_confidential: bool) -> list[dict[str, Any]]:
    """The folders directly inside a company, case, client or folder."""
    listing = documents.list_folders(ctx["scope"], ctx["case_code"], ctx["client_code"], see_confidential)["folders"]
    parent = ctx["folder_id"]
    below: dict[int | None, int] = {}
    for folder in listing:
        below[folder["parent_id"]] = below.get(folder["parent_id"], 0) + 1
    return [
        {"node": f"folder:{f['id']}", "name": f["name"], "kind": "folder", "documents": f["documents"], "system": f["system"],
         "children": below.get(f["id"], 0)}
        for f in listing if f["parent_id"] == parent
    ]


def _root_entries(cur, see_confidential: bool) -> list[dict[str, Any]]:
    conf = _children_counts(see_confidential)
    cur.execute(f"WITH {documents._APPEARANCES} SELECT COUNT(*) FROM appear d WHERE d.scope = 'company' {conf}")
    company = cur.fetchone()[0]
    cur.execute(f"WITH {documents._APPEARANCES} SELECT COUNT(*) FROM appear d WHERE d.scope = 'client' {conf}")
    clients_docs = cur.fetchone()[0]
    cur.execute(f"WITH {documents._APPEARANCES} SELECT COUNT(*) FROM appear d WHERE d.scope = 'case' {conf}")
    cases_docs = cur.fetchone()[0]
    cur.execute("SELECT (SELECT COUNT(*) FROM orion_ods.client), (SELECT COUNT(*) FROM orion_ods.\"case\")")
    clients, cases = cur.fetchone()
    return [
        {"node": "company", "name": "Company documents", "kind": "company", "documents": company, "sub": "Registrations, policies, people"},
        {"node": "clients", "name": "Clients", "kind": "group", "documents": clients_docs, "sub": f"{clients} " + ("client" if clients == 1 else "clients")},
        {"node": "cases", "name": "Cases", "kind": "group", "documents": cases_docs, "sub": f"{cases} " + ("case" if cases == 1 else "cases")},
    ]


def _document_filters(ctx: dict[str, Any], searching: bool) -> dict[str, Any] | None:
    """What selects a node's documents: its own when browsing, everything inside it when searching. None: it holds none of its own."""
    kind = ctx["kind"]
    if kind == "trash":
        return {"trash": True}
    if kind == "all":
        return {}
    if kind in ("root", "clients", "cases"):
        if not searching:
            return None
        return {} if kind == "root" else {"scope": "client" if kind == "clients" else "case"}
    if kind == "folder":
        return {"scope": ctx["scope"], "case_code": ctx["case_code"], "client_code": ctx["client_code"], "folder_id": ctx["folder_id"],
                "exact": not searching}
    if kind == "company":
        return {"scope": "company", **({} if searching else {"folder_id": "none"})}
    if kind == "case":
        return {"case_code": ctx["case_code"], **({"scope": "case", "folder_id": "none"} if not searching else {})}
    return {"client_code": ctx["client_code"], **({"scope": "client", "folder_id": "none"} if not searching else {})}


def browse(node: str, filters: dict[str, Any], see_confidential: bool, limit: int = 100, offset: int = 0,
           folders_only: bool = False) -> dict[str, Any]:
    """Where ``node`` is, the way back, what folders are in it and its documents (one page of them)."""
    with db_cursor() as cur:
        ctx = resolve(cur, node)
        if ctx["kind"] == "root":
            entries = _root_entries(cur, see_confidential)
        elif ctx["kind"] in ("clients", "cases"):
            entries = _space_entries(cur, ctx["kind"], see_confidential)
        elif ctx["kind"] in (*SPACE_NODES, "folder"):
            entries = _folder_entries(cur, ctx, see_confidential)
        else:
            entries = []
    searching = any(filters.get(key) for key in ("q", "category", "status", "expiry", "tag"))
    node_filters = _document_filters(ctx, searching)
    page = None
    if node_filters is not None and not folders_only:
        page = documents.search_documents({**filters, **node_filters}, see_confidential, limit, offset)
    can_create = ctx["kind"] in (*SPACE_NODES, "folder")
    space = {"scope": ctx["scope"], "case_code": ctx["case_code"], "client_code": ctx["client_code"], "folder_id": ctx["folder_id"]} if can_create else None
    return {
        "node": {"id": ctx["id"], "kind": ctx["kind"], "label": ctx["label"], "system": ctx.get("system", False)},
        "trail": ctx["trail"], "space": space, "can_create_folder": can_create, "folders": entries, "documents": page,
        "searching": searching,
    }


def destination_of(cur, node: str) -> tuple[documents.Destination, str]:
    """A node as the place something can be moved or filed to: a folder, or the top of the company, a case or a client."""
    ctx = resolve(cur, node)
    if ctx["kind"] not in (*SPACE_NODES, "folder"):
        raise DocumentCenterError("Choose a folder, a case, a client or Company documents to move this to.")
    return (ctx["scope"], ctx["case_code"], ctx["client_code"], ctx["folder_id"]), " › ".join(step["label"] for step in ctx["trail"][1:])


def move(user_id: int | None, document_ids: list[int], folder_ids: list[int], to: str, see_confidential: bool) -> dict[str, Any]:
    """Move documents and folders to ``to``. Filed documents (bills, employee papers) go there by choice and the filing follows."""
    with db_cursor() as cur:
        destination, label = destination_of(cur, to)
    result = documents.move_items(user_id, document_ids, folder_ids, destination, label, see_confidential)
    for source_type, source_ref, document_id in result.pop("filed"):
        documents_filing.set_choice(source_type, source_ref, destination, user_id)
        documents_filing.refile(source_type, source_ref)
        with db_cursor(commit=True) as cur:
            documents._log(cur, document_id, "moved", f"Kept in {label}", user_id)
        result["moved"] += 1
    return {**result, "to": label}


def reset_home(user_id: int | None, document_id: int, see_confidential: bool) -> bool:
    """Put a filed document back where Orion files it by itself."""
    with db_cursor() as cur:
        cur.execute("SELECT source_type, source_ref, confidentiality FROM orion_ods.document WHERE document_id = %s", (document_id,))
        row = cur.fetchone()
    if not row or (row[2] == "Confidential" and not see_confidential):
        return False
    if not row[0]:
        raise DocumentCenterError("Only a document Orion filed by itself (a bill, an employee's or an EMD's paper) has a usual place to go back to.")
    documents_filing.set_choice(row[0], row[1], None, user_id)
    documents_filing.refile(row[0], row[1])
    with db_cursor(commit=True) as cur:
        documents._log(cur, document_id, "moved", "Back in its usual place", user_id)
    return True


def choice_destination(node: str | None) -> documents_filing.Choice | None:
    """A node chosen as where a document will be kept, as the filing stores it. None (nothing chosen) is the usual place."""
    if not node:
        return None
    with db_cursor() as cur:
        destination, _label = destination_of(cur, node)
    return destination


def bill_preview(case_code: str, bill_date: date, node: str | None) -> list[dict[str, Any]]:
    """Where a bill will be filed, as words, for the Billing page to show before the bill is saved."""
    return documents_filing.preview_bill(case_code, bill_date, choice_destination(node))


def locations(source_type: str, source_ref: str, see_confidential: bool) -> dict[str, Any] | None:
    """Where a filed paper is kept (its home and its other places, each with the node to open it at), and whether a person chose it."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT document_id, scope, case_code, client_code, folder_id, confidentiality, is_deleted
                 FROM orion_ods.document WHERE source_type = %s AND source_ref = %s""",
            (source_type, source_ref),
        )
        row = cur.fetchone()
        if not row or (row[5] == "Confidential" and not see_confidential):
            return None
        document_id, scope, case_code, client_code, folder_id, _conf, deleted = row
        cur.execute(
            "SELECT scope, case_code, client_code, folder_id FROM orion_ods.document_placement WHERE document_id = %s ORDER BY placement_id",
            (document_id,),
        )
        places = [(scope, case_code, client_code, folder_id), *cur.fetchall()]
        out = []
        for index, (p_scope, p_case, p_client, p_folder) in enumerate(places):
            node = _node_id("folder", p_folder) if p_folder else ("company" if p_scope == "company" else _node_id(p_scope, p_case or p_client))
            ctx = resolve(cur, node)
            out.append({"home": index == 0, "node": node, "label": " › ".join(step["label"] for step in ctx["trail"][1:])})
        cur.execute("SELECT 1 FROM orion_ods.document_filing_choice WHERE source_type = %s AND source_ref = %s", (source_type, source_ref))
        chosen = cur.fetchone() is not None
    return {"document_id": document_id, "deleted": deleted, "chosen": chosen, "locations": [] if deleted else out}


def choose_for_source(user_id: int | None, source_type: str, source_ref: str, node: str | None, see_confidential: bool) -> dict[str, Any]:
    """Keep a filed paper in the folder ``node`` (or, with None, where Orion files it by itself), then say where it is now."""
    found = locations(source_type, source_ref, see_confidential)
    if found is None:
        raise DocumentCenterError("That paper is not in the Document Center yet. Update the filing, then try again.")
    documents_filing.set_choice(source_type, source_ref, choice_destination(node), user_id)
    documents_filing.refile(source_type, source_ref)
    return locations(source_type, source_ref, see_confidential) or found
