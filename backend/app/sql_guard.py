"""What the SQL editor will run, and what it will not: reading a script apart into statements and deciding, before anything reaches the database,
whether each may run in the mode the person chose.

The SQL editor (``sql_lab.py``) is for administrators and is audited; this module is the other half of keeping it safe. It is **not** a security
boundary against a determined administrator (SQL can always be written to say a thing another way); it stops the mistakes and the things nobody
should do from a browser, and it keeps Orion's own rules from being bypassed by accident:

* **Reading** is a read-only transaction (the database itself refuses a write), on any table except the *private* ones (passwords, sessions, sign-in
  tokens, Google's token, people's messages), which are never readable here. ``reports.users`` is the safe view of the users.
* **Changing data** (INSERT, UPDATE, DELETE) needs "Allow changes", and is refused on the tables whose rules live in Orion's code (bills and their
  money, the bank, documents, attendance and the rest of ``OWNED_TABLES``): those change only through the app, as AGENTS.md says. An UPDATE or DELETE with
  no WHERE, TRUNCATE and DROP must be confirmed.
* **Changing structure** (CREATE, ALTER, DROP, TRUNCATE) is limited to the ``reports`` schema, where saved views and scratch tables live. Orion's own
  schemas change only through the schema files and ``app.migrate``.
* Never: roles and grants, ``SET``, ``COPY``, ``DO``, transaction control (Orion owns the transaction), the functions that reach outside the database
  or other people's sessions, ``nextval`` (it would use up a bill number).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_STATEMENTS = 20
MAX_SQL = 100_000

REPORTS = "reports"
APP_SCHEMAS = ("orion_ods", "orion_dw", "tally_ods", "tally_dw")
SEARCH_PATH_READ = f"{REPORTS}, {', '.join(APP_SCHEMAS)}, public"

# Tables whose contents are secret or private. Never readable or writable here (reports.users is the safe view of the users).
PRIVATE_TABLES = re.compile(
    r"^(app_user|app_session|signup_request|gdrive_connection|idempotency_key|direct_chat|chat_[a-z_]+|ai_conversation[a-z_]*|ai_message[a-z_]*)$"
)
# Tables that Orion's code owns (AGENTS.md "Data ownership"): readable here, changed only through the app.
OWNED_TABLES = re.compile(
    r"^(bill|bill_[a-z_]+|credit_note[a-z_]*|task|task_[a-z_]+|case_transaction|expense_payment|salary_run|bank_[a-z_]+|document|document_[a-z_]+|doc_folder|drive_link|attendance_[a-z_]+|"
    r"opportunity_followup[a-z_]*|schema_migrations|sql_[a-z_]+|tender_[a-z_]+|letter[a-z_]*|employee_document|emd_document|backup_[a-z_]+|etl_[a-z_]+|"
    r"audit[a-z_]*|ai_[a-z_]+|app_[a-z_]+)$"
)

# Functions that reach outside the database, other people's sessions, the server's files, or a sequence Orion hands out numbers from.
BLOCKED_FUNCTIONS = re.compile(
    r"\b(pg_terminate_backend|pg_cancel_backend|pg_reload_conf|pg_rotate_logfile|pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|pg_ls_[a-z_]+|"
    r"lo_import|lo_export|lo_[a-z_]+|dblink[a-z_]*|nextval|setval|currval|lastval|set_config|query_to_xml[a-z_]*|table_to_xml[a-z_]*|schema_to_xml[a-z_]*|"
    r"database_to_xml[a-z_]*|cursor_to_xml[a-z_]*|pg_switch_wal|pg_create_[a-z_]+|pg_drop_[a-z_]+|pg_promote|pg_backup_[a-z_]+)\s*\("
)
BLOCKED_CATALOGS = re.compile(r"\b(pg_authid|pg_shadow|pg_user_mappings|pg_auth_members|pg_hba_file_rules|pg_file_settings|pg_stat_ssl|pg_largeobject)\b")

# What can be the first word. Everything else is refused with a sentence.
READ_WORDS = {"select", "with", "values", "table", "show", "explain"}
WRITE_WORDS = {"insert", "update", "delete", "merge"}
STRUCTURE_WORDS = {"create", "alter", "drop", "truncate", "comment", "refresh"}
NEVER_WORDS = {
    "begin", "start", "commit", "end", "rollback", "abort", "savepoint", "release", "set", "reset", "grant", "revoke", "copy", "do", "execute", "prepare",
    "deallocate", "listen", "unlisten", "notify", "load", "vacuum", "cluster", "lock", "discard", "security", "import", "call", "checkpoint", "declare",
    "fetch", "move", "close", "reindex", "analyze", "analyse",
}
CREATABLE = ("table", "view", "materialized view", "index", "unique index", "sequence")
ALTERABLE = ("table", "view", "materialized view", "index", "sequence")
DROPPABLE = ("table", "view", "materialized view", "index", "sequence")


class Blocked(ValueError):
    """The statement will not be run. The message says why, in words for the person."""


@dataclass
class Statement:
    text: str  # as written
    clean: str  # comments gone, string contents blanked, quoted names unquoted and lowercased: for reading it, never for running it
    first: str = ""  # its first word, lowercased
    line: int = 1  # where it starts in the script (for an error's position)


@dataclass
class Verdict:
    kind: str  # "read", "write" (data), "structure"
    search_path: str
    confirm: list[str] = field(default_factory=list)  # things the person must confirm before this runs


def scan(sql: str) -> list[Statement]:
    """Split a script at its top-level semicolons, honouring '…', "…", $tag$…$tag$, -- and /* */ (which nests), and make each statement's ``clean`` form."""
    statements: list[Statement] = []
    raw: list[str] = []
    clean: list[str] = []
    i, n = 0, len(sql)
    start_line, line = 1, 1

    def flush() -> None:
        nonlocal raw, clean, start_line
        written = "".join(raw)
        text = written.strip()
        cleaned = " ".join("".join(clean).split())
        if text and cleaned:
            lead = written[: len(written) - len(written.lstrip())].count("\n")
            statements.append(Statement(text=text, clean=cleaned.lower(), first=cleaned.split(" ", 1)[0].lower(), line=start_line + lead))
        raw, clean = [], []
        start_line = line

    while i < n:
        ch = sql[i]
        two = sql[i:i + 2]
        if ch == "\n":
            line += 1
        if two == "--":
            j = sql.find("\n", i)
            j = n if j < 0 else j
            raw.append(sql[i:j])
            clean.append(" ")
            i = j
        elif two == "/*":
            depth, j = 1, i + 2
            while j < n and depth:
                if sql[j:j + 2] == "/*":
                    depth, j = depth + 1, j + 2
                elif sql[j:j + 2] == "*/":
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            raw.append(sql[i:j])
            line += sql[i:j].count("\n")
            clean.append(" ")
            i = j
        elif ch == "'":
            j = i + 1
            escaped = i > 0 and sql[i - 1] in "eE" and (i < 2 or not (sql[i - 2].isalnum() or sql[i - 2] == "_"))
            while j < n:
                if escaped and sql[j] == "\\":
                    j += 2
                    continue
                if sql[j] == "'":
                    if sql[j + 1:j + 2] == "'":
                        j += 2
                        continue
                    break
                j += 1
            raw.append(sql[i:j + 1])
            line += sql[i:j + 1].count("\n")
            clean.append("''")
            i = j + 1
        elif ch == '"':
            j = i + 1
            while j < n:
                if sql[j] == '"':
                    if sql[j + 1:j + 2] == '"':
                        j += 2
                        continue
                    break
                j += 1
            raw.append(sql[i:j + 1])
            clean.append(" " + sql[i + 1:j].replace('""', '"').lower() + " ")
            i = j + 1
        elif ch == "$":
            m = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
            if m:
                tag = m.group(0)
                j = sql.find(tag, i + len(tag))
                j = n if j < 0 else j + len(tag)
                raw.append(sql[i:j])
                line += sql[i:j].count("\n")
                clean.append("''")
                i = j
            else:
                raw.append(ch)
                clean.append(ch)
                i += 1
        elif ch == ";":
            flush()
            i += 1
        else:
            raw.append(ch)
            clean.append(ch)
            i += 1
    flush()
    return statements


def _words(clean: str) -> list[str]:
    return re.findall(r"[a-z_][a-z0-9_$]*", clean)


def _tables(clean: str) -> list[str]:
    """The table names a statement mentions in a place a table goes (after FROM, JOIN, INTO, UPDATE, USING, TABLE, TRUNCATE, ONLY, a comma in a FROM list),
    without their schema. Read from the cleaned text, so it is a best effort, not a parser."""
    names: list[str] = []
    for match in re.finditer(r"\b(?:from|join|into|update|using|table|truncate|only|view|on)\s+(?:only\s+)?((?:[a-z_][a-z0-9_$]*\s*\.\s*)?[a-z_][a-z0-9_$]*(?:\s*,\s*(?:[a-z_][a-z0-9_$]*\s*\.\s*)?[a-z_][a-z0-9_$]*)*)", clean):
        for part in match.group(1).split(","):
            names.append(part.split(".")[-1].strip())
    return names


def _object_type(clean: str, after: str) -> str:
    """CREATE/ALTER/DROP [OR REPLACE] [TEMP|UNLOGGED|UNIQUE...] <type>: the type, as words ("view", "materialized view", "unique index")."""
    rest = re.sub(rf"^{after}\s+(or\s+replace\s+)?(temp(orary)?\s+|unlogged\s+|recursive\s+)?", "", clean)
    for kind in ("materialized view", "unique index", "table", "view", "index", "sequence"):
        if rest.startswith(kind + " ") or rest == kind:
            return kind
    return rest.split(" ", 1)[0] if rest else ""


def vet(statement: Statement, *, may_change: bool) -> Verdict:
    """Decide whether one statement may run. Raises ``Blocked`` with the reason; otherwise says what kind it is and what to confirm."""
    clean, first = statement.clean, statement.first
    if first in NEVER_WORDS:
        raise Blocked(f"{first.upper()} cannot be run in the SQL editor: every run is its own transaction, and roles, settings and the session are not changed from here.")
    if BLOCKED_CATALOGS.search(clean):
        raise Blocked("That part of the system catalog holds secrets and cannot be read here.")
    found = BLOCKED_FUNCTIONS.search(clean)
    if found:
        raise Blocked(f"The function {found.group(1)}() cannot be used in the SQL editor.")
    mentioned = [name for name in _tables(clean) + [w for w in _words(clean) if PRIVATE_TABLES.match(w)] if PRIVATE_TABLES.match(name)]
    if mentioned:
        raise Blocked(f"{mentioned[0]} holds passwords, sessions, tokens or private messages and is not readable here. reports.users is the safe view of the users.")

    if first == "explain":
        options = re.match(r"^explain\s*(\([^)]*\))?", clean)
        if options and options.group(1):
            analyses = bool(re.search(r"\banaly[sz]e\b", options.group(1)))
        else:
            analyses = bool(re.match(r"^explain\s+(verbose\s+)?analy[sz]e\b", clean))
        inner = re.sub(r"^explain\s*(\([^)]*\))?\s*((analy[sz]e|verbose)\s+)*", "", clean).strip()
        if not inner:
            raise Blocked("EXPLAIN needs a statement after it.")
        # A plan is only a plan unless it is run (ANALYZE): then the statement must be one that may run here.
        verdict = vet(Statement(text=statement.text, clean=inner, first=inner.split(" ", 1)[0], line=statement.line), may_change=may_change or not analyses)
        return verdict if analyses else Verdict("read", SEARCH_PATH_READ)

    if first in READ_WORDS:
        words = set(_words(clean))
        if first == "with" and words & WRITE_WORDS and re.search(r"\b(insert\s+into|update\s+[a-z_]|delete\s+from|merge\s+into)\b", clean):
            return _write(statement, may_change)
        if first == "select" and re.search(r"\binto\s+(temp|temporary|unlogged|table\s+)?[a-z_]", clean.split(" from ")[0]):
            raise Blocked("SELECT … INTO makes a table; use CREATE TABLE reports.name AS SELECT … instead.")
        return Verdict("read", SEARCH_PATH_READ)
    if first in WRITE_WORDS:
        return _write(statement, may_change)
    if first in STRUCTURE_WORDS:
        return _structure(statement, may_change)
    raise Blocked(f"{first.upper()} is not something the SQL editor runs.")


def _write(statement: Statement, may_change: bool) -> Verdict:
    clean = statement.clean
    if not may_change:
        raise Blocked("This changes data. Turn on “Allow changes” to run it (and consider “Roll back after running” to see its effect first).")
    for name in _tables(clean):
        if OWNED_TABLES.match(name):
            raise Blocked(f"{name} is changed only through Orion (its rules live in the application), not by SQL. You can read it here.")
    confirm: list[str] = []
    if statement.first in ("update", "delete") and not re.search(r"\bwhere\b", clean):
        confirm.append(f"This {statement.first.upper()} has no WHERE, so it changes every row of the table.")
    return Verdict("write", SEARCH_PATH_READ, confirm)


def _structure(statement: Statement, may_change: bool) -> Verdict:
    clean, first = statement.clean, statement.first
    if not may_change:
        raise Blocked("This changes structure. Turn on “Allow changes” to run it.")
    if first == "truncate":
        targets = _tables(clean) or [clean.split(" ")[-1]]
        if re.search(r"\b(orion_ods|orion_dw|tally_ods|tally_dw|public)\s*\.", clean) or any(OWNED_TABLES.match(t) for t in targets):
            raise Blocked("TRUNCATE is limited to tables in the reports schema.")
        return Verdict("structure", REPORTS, ["TRUNCATE removes every row of the table."])
    kind = _object_type(clean, first) if first in ("create", "alter", "drop") else first
    allowed = {"create": CREATABLE, "alter": ALTERABLE, "drop": DROPPABLE}.get(first)
    if allowed is not None and kind not in allowed:
        raise Blocked(f"{first.upper()} {kind.upper()} is not supported in the SQL editor: you can {first} {', '.join(allowed[:4])} and more, in the reports schema.")
    confirm = ["DROP removes the object (and, with CASCADE, whatever depends on it)."] if first == "drop" else []
    if first == "create" and kind in ("table", "view", "materialized view") and re.search(r"\bas\s+(\(|select|with|values|table)", clean):
        target = re.search(r"\b(?:view|table)\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_$]*(?:\s*\.\s*[a-z_][a-z0-9_$]*)?)", clean)
        if target and "." in target.group(1) and target.group(1).split(".")[0].strip() != REPORTS:
            raise Blocked(f"Views and tables made here belong in the {REPORTS} schema: name it {REPORTS}.{target.group(1).split('.')[-1].strip()}.")
        return Verdict("structure", SEARCH_PATH_READ, confirm)  # the body may name Orion's tables; the new object goes to reports (first in the path)
    if re.search(r"\b(orion_ods|orion_dw|tally_ods|tally_dw|public|pg_catalog|information_schema)\s*\.", clean):
        raise Blocked(f"Structure can be changed only in the {REPORTS} schema, and Orion's own schemas change through its schema files.")
    return Verdict("structure", REPORTS, confirm)


def vet_script(sql: str, *, may_change: bool) -> list[tuple[Statement, Verdict]]:
    """Every statement of a script, checked, or the first reason one cannot run. Nothing is run by this."""
    if len(sql) > MAX_SQL:
        raise Blocked("That script is too long to run in one go.")
    found = scan(sql)
    if not found:
        raise Blocked("There is nothing to run.")
    if len(found) > MAX_STATEMENTS:
        raise Blocked(f"Run at most {MAX_STATEMENTS} statements at a time.")
    out: list[tuple[Statement, Verdict]] = []
    for number, statement in enumerate(found, start=1):
        try:
            out.append((statement, vet(statement, may_change=may_change)))
        except Blocked as exc:
            where = f"Statement {number}" if len(found) > 1 else "This statement"
            raise Blocked(f"{where} was not run: {exc}") from exc
    return out
