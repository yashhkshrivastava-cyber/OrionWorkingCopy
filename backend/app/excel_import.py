"""Insert-only Excel import for ODS entities."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

from fastapi.responses import Response

from app.db_utils import fetch_dropdown
from app.entities import merge_columns
from app.payload import PayloadError, clean_payload
from app.xlsx_io import excel_serial_to_date, read_first_sheet, write_xlsx

MAX_ROWS = 2000
SKIP_COLUMNS = {"created_timestamp", "last_updated_timestamp"}
INLINE_PREVIEW_LIMITS = {3, 10, 50}
EXPORT_LIMITS = {100, None}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).strip().lower())


def _camel(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def excel_columns(entity: dict) -> list[str]:
    pk = entity["primary_key"]
    return [
        key
        for key, config in entity["form_fields"].items()
        if key != pk and key not in SKIP_COLUMNS and not config.get("readonly")
    ]


def _header_aliases(entity: dict) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for key in excel_columns(entity):
        config = entity["form_fields"][key]
        for alias in (key, config["label"], _camel(key), key.replace("_", " ")):
            aliases.setdefault(_norm(alias), key)
    # The record's own code is not a form field, but a file may carry it to say which record a row is about
    pk = entity["primary_key"]
    for alias in (pk, _camel(pk), pk.replace("_", " ")):
        aliases.setdefault(_norm(alias), pk)
    return aliases


def _field_note(config: dict) -> str:
    if config.get("source_table"):
        return "Enter the name shown in Orion, or the code."
    if config.get("type") == "select_or_custom":
        presets = config.get("options") or []
        return "One of: " + ", ".join(presets) + ". Any other text is stored as a custom type."
    if config.get("compute_op") == "difference":
        return "Leave blank to auto-calculate."
    if config.get("compute_op") == "month_year":
        return "Leave blank to auto-calculate from the transaction date (YYYY-MM)."
    if config.get("compute_from"):
        return "Leave blank to auto-calculate from amount, tax, and GST."
    if config.get("option_aliases"):
        return "One of: " + ", ".join(config["options"]) + " (or " + ", ".join(a.capitalize() for a in config["option_aliases"]) + ")"
    if config.get("options"):
        return "One of: " + ", ".join(config["options"])
    if config["type"] == "boolean":
        return "Yes / No"
    if config["type"] == "date":
        return "Date, for example 2026-08-22"
    if config["type"] in ("number", "integer"):
        return "Number"
    return "Text"


def build_template(entity_name: str, entity: dict) -> bytes:
    columns = excel_columns(entity)
    fields = entity["form_fields"]
    records = [columns]
    keys = merge_columns(entity_name, entity)
    key_note = ", ".join(keys) if keys else entity["primary_key"]
    guide = [
        [f"Orion upload template — {entity_name}"],
        [
            "Fill the Records sheet and upload it. Codes and timestamps are generated on insert. "
            f"Rows merge on {key_note}: matching keys update, new keys insert. "
            "A row that matches more than one existing record is refused, never guessed. "
            f"To change one particular record, add a column named {entity['primary_key']} and put its code in that column "
            "(a download of the records has it). "
            "Do not add extra header rows. Lookup columns accept the display name or the code."
        ],
        [],
        ["Column", "Label", "Type", "Notes"],
    ]
    for key in columns:
        config = fields[key]
        guide.append([key, config["label"], config["type"], _field_note(config)])
    return write_xlsx({"Records": records, "Instructions": guide})


def _export_cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None  # a NaN already stored must not corrupt the workbook
    return value


def build_export(title: str, columns: list[str], rows: list[tuple]) -> bytes:
    """A download of existing records. Headers stay as stored column names."""
    sheet = [list(columns)]
    sheet.extend([_export_cell(value) for value in row] for row in rows)
    return write_xlsx({title[:31] or "Records": sheet})


def parse_preview_limit(raw: str, allowed: set[int | None]) -> int | None:
    if raw in ("all", ""):
        value: int | None = None
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("Limit must be a number or 'all'") from exc
    if value not in allowed:
        raise ValueError("That limit is not available here")
    return value


def excel_file_response(name: str, limit: int | None, columns: list[str], rows: list[tuple]) -> Response:
    slug = name.lower().replace(" ", "_")
    suffix = "all" if limit is None else f"latest_{limit}"
    filename = f"orion_{slug}_{suffix}.xlsx"
    return Response(
        content=build_export("Records", columns, rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _is_empty_row(values: dict) -> bool:
    return not any(value is not None and value != "" for value in values.values())


def _cell_value(value: Any, field_type: str) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    if field_type == "date" and isinstance(value, (int, float)):
        return excel_serial_to_date(value)
    if field_type in ("number", "integer", "date", "boolean"):
        return value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return value


def _lookup_index(config: dict) -> dict[str, str]:
    records = fetch_dropdown(
        config["source_table"],
        config["source_display_column"],
        config.get("source_pk_column", "id"),
        from_sql=config.get("source_from"),
    )
    index: dict[str, str] = {}
    for pk, label in records:
        pk_text = str(pk)
        index[_norm(pk_text)] = pk_text
        index[_norm(str(label))] = pk_text
        if " — " in str(label):
            index[_norm(str(label).split(" — ", 1)[0])] = pk_text
    return index


def _match_option(value: Any, options: list[str]) -> str | None:
    text = str(value).strip()
    for option in options:
        if text.lower() == option.lower():
            return option
    if len(text) == 1:
        matches = [option for option in options if option.lower().startswith(text.lower())]
        if len(matches) == 1:
            return matches[0]
    return None


def _resolve_value(key: str, config: dict, value: Any, lookups: dict[str, dict[str, str]]) -> Any:
    if value is None or value == "":
        return None
    if config.get("source_table"):
        mapped = lookups[key].get(_norm(str(value)))
        if not mapped:
            raise PayloadError(f"{config['label']} '{value}' was not found")
        return mapped
    if config.get("type") == "select_or_custom":
        presets = config.get("options") or []
        matched = _match_option(value, presets)
        return matched if matched else str(value).strip()
    if config.get("options"):
        if isinstance(value, bool):
            value = "Yes" if value else "No"
        value = (config.get("option_aliases") or {}).get(str(value).strip().lower(), value)
        matched = _match_option(value, config["options"])
        if not matched:
            raise PayloadError(f"{config['label']} must be one of: {', '.join(config['options'])}")
        return matched
    return value


def parse_workbook(entity: dict, content: bytes, entity_name: str = "") -> tuple[list[dict], list[dict]]:
    try:
        grid = read_first_sheet(content)
    except ValueError as exc:
        raise PayloadError("Could not read this Excel file. Please use the .xlsx template.") from exc

    if not grid:
        raise PayloadError("The Excel file is empty.")

    header_row = grid[0]
    aliases = _header_aliases(entity)
    pk = entity["primary_key"]
    columns: list[str | None] = []
    seen = set()
    for header in header_row:
        if header is None or str(header).strip() == "":
            columns.append(None)
            continue
        key = aliases.get(_norm(str(header)))
        if key and key not in seen:
            columns.append(key)
            seen.add(key)
        else:
            columns.append(None)

    if not seen:
        raise PayloadError("Could not recognise any columns. Download the template and keep the header row.")

    fields = entity["form_fields"]
    lookups = {
        key: _lookup_index(fields[key])
        for key in seen
        if key in fields and fields[key].get("source_table")
    }

    cleaned_rows: list[dict] = []
    errors: list[dict] = []
    data_rows = 0

    for excel_row, raw in enumerate(grid[1:], start=2):
        mapped: dict[str, Any] = {}
        code = None
        for index, key in enumerate(columns):
            if not key:
                continue
            cell = raw[index] if index < len(raw) else None
            if key == pk:
                code = _cell_value(cell, "text")
                code = str(code).strip() if code not in (None, "") else None
                continue
            mapped[key] = _cell_value(cell, fields[key]["type"])
        if _is_empty_row(mapped) and not code:
            continue
        data_rows += 1
        if data_rows > MAX_ROWS:
            errors.append({"row": excel_row, "message": f"Upload is limited to {MAX_ROWS} rows."})
            break
        try:
            resolved = {
                key: _resolve_value(key, fields[key], value, lookups)
                for key, value in mapped.items()
            }
            # A row that names its record changes that record, so it need not repeat the required fields the way a new one must
            cleaned = clean_payload(entity, resolved, for_update=bool(code))
            if not cleaned or all(value is None for value in cleaned.values()):
                raise PayloadError("Row has no usable values")
            # Which row of the sheet this was, and which record it is about, travel with the row to the merge
            cleaned["__row"] = excel_row
            if code:
                cleaned["__code"] = code
            cleaned_rows.append(cleaned)
        except PayloadError as exc:
            errors.append({"row": excel_row, "message": str(exc)})

    if data_rows == 0 and not errors:
        raise PayloadError("No data rows found. Add records under the header row.")
    keys = merge_columns(entity_name, entity)
    if not errors:
        by_code: dict[str, int] = {}
        by_key: dict[tuple, int] = {}
        for row in cleaned_rows:
            line = row["__row"]
            if row.get("__code"):
                code = row["__code"].lower()
                if code in by_code:
                    errors.append({"row": line, "message": f"{pk} {row['__code']} is already on row {by_code[code]} of this file"})
                by_code.setdefault(code, line)
                continue  # a row that names its record is not matched on the key
            if not keys or any(row.get(col) is None or row.get(col) == "" for col in keys):
                continue
            sig = tuple(str(row.get(col)).strip().lower() for col in keys)
            if sig in by_key:
                errors.append({
                    "row": line,
                    "message": f"Rows {by_key[sig]} and {line} are for the same record ({', '.join(keys)}: {', '.join(sig)}). Keep one, or give each its {pk}.",
                })
            else:
                by_key[sig] = line
    return cleaned_rows, errors
