"""Minimal .xlsx read/write using zipfile so we do not depend on openpyxl."""

from __future__ import annotations

import re
import zipfile
from datetime import date, datetime, timedelta
from io import BytesIO
from xml.sax.saxutils import escape, unescape

EXCEL_EPOCH = datetime(1899, 12, 30)


def col_letter(index: int) -> str:
    result = ""
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def excel_serial_to_date(value: float) -> date:
    return (EXCEL_EPOCH + timedelta(days=float(value))).date()


def _xml_text(value: str) -> str:
    return escape(value, {"'": "&apos;", '"': "&quot;"})


def write_xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    sheet_names = list(sheets.keys())
    content_types_overrides = []
    workbook_sheets = []
    rels = []
    worksheet_files = {}

    for index, name in enumerate(sheet_names, start=1):
        path = f"xl/worksheets/sheet{index}.xml"
        content_types_overrides.append(
            f'<Override PartName="/{path}" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        workbook_sheets.append(
            f'<sheet name="{_xml_text(name)}" sheetId="{index}" r:id="rId{index}"/>'
        )
        rels.append(
            f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        )
        worksheet_files[path] = _worksheet_xml(sheets[name])

    content_types = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
{"".join(content_types_overrides)}
</Types>'''

    root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''

    workbook = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>{"".join(workbook_sheets)}</sheets>
</workbook>'''

    workbook_rels = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{"".join(rels)}
</Relationships>'''

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        for path, xml in worksheet_files.items():
            zf.writestr(path, xml)
    return buffer.getvalue()


def _cell_xml(row: int, col: int, value: object) -> str:
    ref = f"{col_letter(col)}{row}"
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}" t="n"><v>{value}</v></c>'
    if isinstance(value, datetime):
        value = value.date().isoformat()
    if isinstance(value, date):
        value = value.isoformat()
    text = _xml_text(str(value))
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _worksheet_xml(rows: list[list[object]]) -> str:
    xml_rows = []
    for r_index, row in enumerate(rows, start=1):
        cells = "".join(_cell_xml(r_index, c_index, value) for c_index, value in enumerate(row, start=1))
        xml_rows.append(f'<row r="{r_index}">{cells}</row>')
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>{"".join(xml_rows)}</sheetData>
</worksheet>'''


def _shared_strings(xml: str) -> list[str]:
    strings = []
    for si in re.findall(r"<si\b[^>]*>(.*?)</si>", xml, flags=re.DOTALL | re.IGNORECASE):
        parts = re.findall(r"<t\b[^>]*>(.*?)</t>", si, flags=re.DOTALL | re.IGNORECASE)
        strings.append(unescape(re.sub(r"<[^>]+>", "", "".join(parts))))
    return strings


def _cell_ref(ref: str) -> tuple[int, int]:
    match = re.match(r"([A-Z]+)(\d+)", ref.upper())
    if not match:
        return 0, 0
    col = 0
    for char in match.group(1):
        col = col * 26 + (ord(char) - 64)
    return int(match.group(2)), col


def _cell_value(cell_xml: str, shared: list[str]) -> object:
    cell_type = re.search(r'\bt="([^"]+)"', cell_xml)
    kind = cell_type.group(1) if cell_type else "n"
    if kind == "inlineStr":
        parts = re.findall(r"<t\b[^>]*>(.*?)</t>", cell_xml, flags=re.DOTALL | re.IGNORECASE)
        return unescape(re.sub(r"<[^>]+>", "", "".join(parts))) or None
    value_match = re.search(r"<v\b[^>]*>(.*?)</v>", cell_xml, flags=re.DOTALL | re.IGNORECASE)
    raw = unescape(value_match.group(1)) if value_match else ""
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return raw
    if kind == "b":
        return raw in ("1", "true", "TRUE")
    if kind in ("n", "str") or not kind:
        if raw == "":
            return None
        try:
            number = float(raw)
            if number.is_integer():
                return int(number)
            return number
        except ValueError:
            return raw
    return raw or None


def read_first_sheet(content: bytes) -> list[list[object]]:
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            names = zf.namelist()
            shared: list[str] = []
            shared_name = next((n for n in names if n.lower().endswith("sharedstrings.xml")), None)
            if shared_name:
                shared = _shared_strings(zf.read(shared_name).decode("utf-8"))
            sheet_name = next((n for n in names if n.lower().startswith("xl/worksheets/sheet")), None)
            if not sheet_name:
                raise ValueError("No worksheet found")
            xml = zf.read(sheet_name).decode("utf-8")
    except zipfile.BadZipFile as exc:
        raise ValueError("Not a valid .xlsx file") from exc

    grid: dict[tuple[int, int], object] = {}
    max_row = 0
    max_col = 0
    for cell_xml in re.findall(r"<c\b[^>]*>.*?</c>|<c\b[^>]*/>", xml, flags=re.DOTALL | re.IGNORECASE):
        ref_match = re.search(r'\br="([A-Z]+\d+)"', cell_xml)
        if not ref_match:
            continue
        row, col = _cell_ref(ref_match.group(1))
        grid[(row, col)] = _cell_value(cell_xml, shared)
        max_row = max(max_row, row)
        max_col = max(max_col, col)

    rows: list[list[object]] = []
    for row in range(1, max_row + 1):
        rows.append([grid.get((row, col)) for col in range(1, max_col + 1)])
    return rows
