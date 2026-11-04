import re

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_ident(name: str) -> str:
    if not IDENT.match(name):
        raise ValueError("Invalid column name")
    return f'"{name}"'


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def normalize_search(raw: str | None) -> str:
    text = (raw or "").strip()
    if len(text) > 200:
        text = text[:200]
    return text


def normalize_sort(raw: str | None, columns: list[str]) -> str | None:
    if not raw:
        return None
    if raw not in columns:
        return None
    return raw


def normalize_dir(raw: str | None) -> str:
    return "ASC" if (raw or "").lower() == "asc" else "DESC"


def search_sql(columns: list[str], query: str) -> tuple[str, list]:
    if not query or not columns:
        return "", []
    pattern = f"%{escape_like(query)}%"
    parts = [f"COALESCE({quote_ident(col)}::text, '') ILIKE %s ESCAPE '\\'" for col in columns]
    return "(" + " OR ".join(parts) + ")", [pattern] * len(columns)
