"""The company letterhead, and the letters written onto it.

The letterhead is two image strips, a header and a footer, drawn across the top and bottom of an A4 page.
The ones shipped in ``backend/app/assets/letterhead`` are used until an admin uploads a replacement, which is
kept in ``orion_ods.letterhead_design`` (in the database, so it is part of every backup). Where the strips sit
and how much room the text keeps is a handful of millimetre settings, worked out once in ``layout`` and used
by both the browser (letters, printed bills) and the PDFs (``letterhead_page``).

A letter is whatever was typed onto the page. Its body arrives as HTML from the editor and is rebuilt here
from a short list of allowed tags before it is stored, because another signed-in user's browser will draw it.
"""

from __future__ import annotations

import html
import io
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from app.database import db_cursor

ASSETS = Path(__file__).resolve().parent / "assets" / "letterhead"
PARTS = ("header", "footer")
PAGE_WIDTH_MM = 210.0
PAGE_HEIGHT_MM = 297.0

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MIN_IMAGE_WIDTH = 600
MAX_IMAGE_WIDTH = 3000
MAX_BODY_CHARS = 400_000
FONTS = ("sans", "serif")

# Millimetres. (default, least, most)
SETTING_LIMITS: dict[str, tuple[float, float, float]] = {
    "header_top_mm": (2.5, 0, 30),       # gap above the header strip
    "footer_bottom_mm": (5.0, 0, 30),    # gap below the footer strip
    "side_mm": (1.5, 0, 20),             # gap to the left and right of both strips
    "body_left_mm": (20.0, 5, 45),       # text margin, left
    "body_right_mm": (18.0, 5, 45),      # text margin, right
    "body_gap_top_mm": (6.0, 0, 30),     # between the header and the first line of text
    "body_gap_bottom_mm": (5.0, 0, 30),  # between the last line of text and the footer
}
DEFAULT_SETTINGS = {key: limits[0] for key, limits in SETTING_LIMITS.items()}


class LetterheadError(ValueError):
    """The request cannot be carried out. The message is safe to show to the user."""


# --------------------------------------------------------------------------- the design


def _builtin(part: str) -> tuple[bytes, str]:
    return (ASSETS / f"{part}.jpg").read_bytes(), "image/jpeg"


def _image_size(data: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        return image.size


def clean_settings(raw: dict[str, Any] | None) -> dict[str, float]:
    """Every setting, each within its limits. Anything missing or unusable takes its default."""
    out: dict[str, float] = {}
    for key, (default, least, most) in SETTING_LIMITS.items():
        value = (raw or {}).get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        if number != number or number in (float("inf"), float("-inf")):  # NaN or infinite
            number = default
        out[key] = round(min(max(number, least), most), 1)
    return out


def layout(settings: dict[str, float], header_size: tuple[int, int], footer_size: tuple[int, int],
           page_width_mm: float = PAGE_WIDTH_MM) -> dict[str, float]:
    """Where everything sits, in millimetres. The one place this is worked out.

    Both strips span the page between the side gaps and keep their own proportions, so their heights follow
    from their images. ``top_space_mm`` and ``bottom_space_mm`` are what the text must stay clear of.
    """
    strip_width = max(page_width_mm - 2 * settings["side_mm"], 10.0)
    header_height = strip_width * header_size[1] / max(header_size[0], 1)
    footer_height = strip_width * footer_size[1] / max(footer_size[0], 1)
    return {
        "strip_width_mm": round(strip_width, 2),
        "header_height_mm": round(header_height, 2),
        "footer_height_mm": round(footer_height, 2),
        "top_space_mm": round(settings["header_top_mm"] + header_height + settings["body_gap_top_mm"], 2),
        "bottom_space_mm": round(settings["footer_bottom_mm"] + footer_height + settings["body_gap_bottom_mm"], 2),
    }


def _assemble(stored: dict[str, Any]) -> dict[str, Any]:
    design: dict[str, Any] = {
        "version": int(stored.get("version") or 0),
        "settings": clean_settings(stored.get("settings")),
        "updated_timestamp": stored["updated"].isoformat() if stored.get("updated") else None,
        "updated_by_name": stored.get("by"),
    }
    for part in PARTS:
        data = bytes(stored[part]) if stored.get(part) else None
        if data:
            design[part] = {"bytes": data, "type": stored.get(f"{part}_type") or "image/jpeg", "custom": True}
        else:
            builtin, mime = _builtin(part)
            design[part] = {"bytes": builtin, "type": mime, "custom": False}
        design[part]["width"], design[part]["height"] = _image_size(design[part]["bytes"])
    design["layout"] = layout(design["settings"], (design["header"]["width"], design["header"]["height"]),
                              (design["footer"]["width"], design["footer"]["height"]))
    return design


def builtin_design(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """The letterhead shipped with the application, as a new database prints it. Needs no database."""
    return _assemble({"settings": settings})


def load_design() -> dict[str, Any]:
    """The letterhead with its images: what ``letterhead_page`` draws from. Not for sending to a browser."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT d.header_image, d.header_type, d.footer_image, d.footer_type, d.settings, d.version,
                   d.updated_timestamp, u.display_name
              FROM orion_ods.letterhead_design d
              LEFT JOIN orion_ods.app_user u ON u.id = d.updated_by
             WHERE d.id = 1
            """
        )
        row = cur.fetchone()
    keys = ("header", "header_type", "footer", "footer_type", "settings", "version", "updated", "by")
    return _assemble(dict(zip(keys, row)) if row else {})


def public_design(design: dict[str, Any] | None = None) -> dict[str, Any]:
    """The same, as the browser gets it: sizes and where to fetch each image, not the images themselves."""
    design = design or load_design()
    out: dict[str, Any] = {
        "version": design["version"],
        "settings": design["settings"],
        "limits": {key: {"default": d, "min": lo, "max": hi} for key, (d, lo, hi) in SETTING_LIMITS.items()},
        "layout": design["layout"],
        "page": {"width_mm": PAGE_WIDTH_MM, "height_mm": PAGE_HEIGHT_MM},
        "updated_timestamp": design["updated_timestamp"],
        "updated_by_name": design["updated_by_name"],
    }
    for part in PARTS:
        info = design[part]
        out[part] = {"custom": info["custom"], "width": info["width"], "height": info["height"], "type": info["type"],
                     "size_bytes": len(info["bytes"]), "url": f"/api/letterhead/design/{part}?v={design['version']}"}
    return out


def design_image(part: str) -> tuple[bytes, str]:
    if part not in PARTS:
        raise LetterheadError("There is a header and a footer, nothing else.")
    info = load_design()[part]
    return info["bytes"], info["type"]


def prepare_image(data: bytes) -> tuple[bytes, str]:
    """Check an uploaded strip and return what is stored: a JPG or PNG, flattened onto white, not oversized."""
    from PIL import Image

    if not data:
        raise LetterheadError("That file is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise LetterheadError("The image is larger than 8 MB. Save it smaller and try again.")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        raise LetterheadError("That file is not an image Orion can read. Use a JPG or PNG.") from None
    kind = (image.format or "").upper()
    if kind not in ("JPEG", "PNG"):
        raise LetterheadError("Use a JPG or PNG image.")
    width, height = image.size
    if width < MIN_IMAGE_WIDTH:
        raise LetterheadError(f"The image is only {width} pixels wide. It needs at least {MIN_IMAGE_WIDTH} to print sharply.")
    if width < 2 * height:
        raise LetterheadError("A header or footer is a wide strip: the image must be at least twice as wide as it is tall.")

    changed = False
    if image.mode in ("RGBA", "LA", "P") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.split()[-1])
        image, changed = flat, True
    elif image.mode != "RGB":
        image, changed = image.convert("RGB"), True
    if width > MAX_IMAGE_WIDTH:
        image = image.resize((MAX_IMAGE_WIDTH, round(height * MAX_IMAGE_WIDTH / width)), Image.LANCZOS)
        changed = True
    if not changed:
        return data, "image/jpeg" if kind == "JPEG" else "image/png"
    out = io.BytesIO()
    if kind == "JPEG":
        image.save(out, format="JPEG", quality=92, optimize=True)
        return out.getvalue(), "image/jpeg"
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), "image/png"


def _upsert_design(assignments: str, params: list[Any], user_id: int | None) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO orion_ods.letterhead_design (id, version) VALUES (1, 0) ON CONFLICT (id) DO NOTHING"
        )
        cur.execute(
            f"""
            UPDATE orion_ods.letterhead_design
               SET {assignments}, version = version + 1, updated_by = %s, updated_timestamp = CURRENT_TIMESTAMP
             WHERE id = 1
            """,
            [*params, user_id],
        )


def save_settings(raw: dict[str, Any], user_id: int | None) -> dict[str, Any]:
    import psycopg2.extras

    _upsert_design("settings = %s", [psycopg2.extras.Json(clean_settings(raw))], user_id)
    return public_design()


def save_image(part: str, data: bytes, user_id: int | None) -> dict[str, Any]:
    import psycopg2

    if part not in PARTS:
        raise LetterheadError("There is a header and a footer, nothing else.")
    stored, mime = prepare_image(data)
    _upsert_design(f"{part}_image = %s, {part}_type = %s", [psycopg2.Binary(stored), mime], user_id)
    return public_design()


def reset_image(part: str, user_id: int | None) -> dict[str, Any]:
    """Back to the letterhead shipped with the application."""
    if part not in PARTS:
        raise LetterheadError("There is a header and a footer, nothing else.")
    _upsert_design(f"{part}_image = NULL, {part}_type = NULL", [], user_id)
    return public_design()


# --------------------------------------------------------------------------- the body of a letter

# What the editor can produce, and nothing else. Everything outside this list is dropped (its text is kept).
_RENAME = {"strong": "b", "em": "i", "div": "p", "h1": "h2", "h4": "h3", "h5": "h3", "h6": "h3", "strike": "s", "del": "s"}
_INLINE = {"b", "i", "u", "s", "sub", "sup"}
_BLOCK = {"p", "h2", "h3", "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th"}
_VOID = {"br", "hr"}
_TEXT_BLOCKS = {"p", "h2", "h3"}                      # cannot hold another block
_ALIGNABLE = {"p", "h2", "h3", "li", "td", "th"}
_CONTAINERS = {"li", "td", "th"}                      # a paragraph inside one of these is its own
_SKIP_WITH_CONTENT = {"script", "style", "head", "title", "iframe", "object", "embed", "svg", "math", "noscript",
                      "template", "textarea", "select", "button", "form"}
_ALIGN = re.compile(r"text-align\s*:\s*(left|center|right|justify)\b", re.I)
_ALIGN_WORDS = {"left", "center", "right", "justify"}


class _Cleaner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.skipping = 0

    # -- helpers
    def _close(self, count: int) -> None:
        for _ in range(count):
            self.out.append(f"</{self.stack.pop()}>")

    def _close_open_text_block(self) -> None:
        """A paragraph cannot hold a block: starting one ends the paragraph it would have been inside."""
        for depth in range(len(self.stack) - 1, -1, -1):
            tag = self.stack[depth]
            if tag in _CONTAINERS or tag in ("ul", "ol", "table", "thead", "tbody", "tr"):
                return
            if tag in _TEXT_BLOCKS:
                self._close(len(self.stack) - depth)
                return

    @staticmethod
    def _attributes(tag: str, attrs: list[tuple[str, str | None]]) -> str:
        given = {name.lower(): (value or "") for name, value in attrs}
        parts: list[str] = []
        if tag in _ALIGNABLE:
            found = _ALIGN.search(given.get("style", ""))
            align = found.group(1).lower() if found else given.get("align", "").strip().lower()
            if align in _ALIGN_WORDS and align != "left":
                parts.append(f' style="text-align:{align}"')
        if tag in ("td", "th"):
            for name in ("colspan", "rowspan"):
                value = given.get(name, "").strip()
                if value.isdigit() and 1 < int(value) <= 20:
                    parts.append(f' {name}="{int(value)}"')
        if tag == "p" and given.get("data-break", "").strip().lower() == "page":
            parts.append(' data-break="page"')
        return "".join(parts)

    # -- parser events
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP_WITH_CONTENT:
            self.skipping += 1
            return
        if self.skipping:
            return
        tag = _RENAME.get(tag, tag)
        if tag in _VOID:
            if tag == "hr":
                self._close_open_text_block()
            self.out.append(f"<{tag}>")
            return
        if tag in _BLOCK:
            self._close_open_text_block()
            if len(self.stack) > 40:  # absurd nesting: keep the text, drop the structure
                return
            self.stack.append(tag)
            self.out.append(f"<{tag}{self._attributes(tag, attrs)}>")
        elif tag in _INLINE:
            if len(self.stack) > 40:
                return
            self.stack.append(tag)
            self.out.append(f"<{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if _RENAME.get(tag.lower(), tag.lower()) not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_WITH_CONTENT:
            self.skipping = max(0, self.skipping - 1)
            return
        if self.skipping:
            return
        tag = _RENAME.get(tag, tag)
        if tag in self.stack:
            depth = len(self.stack) - 1 - self.stack[::-1].index(tag)
            self._close(len(self.stack) - depth)

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        self._close(len(self.stack))
        return "".join(self.out).strip()


def clean_html(raw: Any) -> str:
    """The body of a letter reduced to the tags the editor makes. Scripts, styles, links, images, classes,
    event handlers and anything else are removed; the words are kept."""
    text = str(raw or "")
    if len(text) > MAX_BODY_CHARS:
        raise LetterheadError("The letter is too long to save. Split it into two.")
    cleaner = _Cleaner()
    cleaner.feed(text)
    cleaner.close()
    return cleaner.result()


def plain_text(body_html: str, limit: int = 160) -> str:
    """The first words of a letter, for the list."""
    text = re.sub(r"<(br|/p|/li|/h2|/h3|/tr|hr)\b[^>]*>", " ", body_html or "", flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------- letters


def _text(value: Any, limit: int) -> str | None:
    text = " ".join(str(value or "").split())
    return text[:limit] or None


def clean_letter(data: dict[str, Any]) -> dict[str, Any]:
    title = _text(data.get("title"), 200)
    if not title:
        raise LetterheadError("Give the letter a name, so it can be found again.")
    when = data.get("letter_date")
    if isinstance(when, str):
        try:
            when = date.fromisoformat(when[:10])
        except ValueError:
            when = None
    if not isinstance(when, date):
        raise LetterheadError("Choose the date of the letter.")
    font = str(data.get("font") or "sans")
    if font not in FONTS:
        raise LetterheadError("Choose one of the two fonts.")
    try:
        size = int(data.get("font_size") or 11)
    except (TypeError, ValueError):
        raise LetterheadError("The text size must be a number.") from None
    if not 8 <= size <= 16:
        raise LetterheadError("The text size must be between 8 and 16.")
    return {
        "title": title,
        "ref_no": _text(data.get("ref_no"), 120),
        "letter_date": when,
        "body_html": clean_html(data.get("body_html")),
        "font": font,
        "font_size": size,
        "show_header": bool(data.get("show_header", True)),
        "show_footer": bool(data.get("show_footer", True)),
    }


_LETTER_COLUMNS = """
    l.letter_id, l.title, l.ref_no, l.letter_date, l.font, l.font_size, l.show_header, l.show_footer,
    l.created_timestamp, l.last_updated_timestamp, cu.display_name AS created_by_name,
    uu.display_name AS last_updated_by_name
"""
_LETTER_FROM = """
    orion_ods.letter l
    LEFT JOIN orion_ods.app_user cu ON cu.id = l.created_by
    LEFT JOIN orion_ods.app_user uu ON uu.id = l.last_updated_by
"""


def _plain(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _row(cur, row) -> dict[str, Any]:
    return {col.name: _plain(value) for col, value in zip(cur.description, row)}


def list_letters(search: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    where, params = ["TRUE"], []
    needle = (search or "").strip()[:100]
    if needle:
        where.append("(l.title ILIKE %s OR l.ref_no ILIKE %s OR regexp_replace(l.body_html, '<[^>]+>', ' ', 'g') ILIKE %s)")
        pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params.extend([pattern] * 3)
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT {_LETTER_COLUMNS}, l.body_html
              FROM {_LETTER_FROM}
             WHERE {' AND '.join(where)}
             ORDER BY l.letter_date DESC, l.letter_id DESC
             LIMIT %s
            """,
            [*params, max(1, min(limit, 2000))],
        )
        letters = [_row(cur, row) for row in cur.fetchall()]
    for letter in letters:
        letter["preview"] = plain_text(letter.pop("body_html"))
    return letters


def get_letter(letter_id: int) -> dict[str, Any] | None:
    with db_cursor() as cur:
        cur.execute(f"SELECT {_LETTER_COLUMNS}, l.body_html FROM {_LETTER_FROM} WHERE l.letter_id = %s", (letter_id,))
        row = cur.fetchone()
        return _row(cur, row) if row else None


def create_letter(data: dict[str, Any], user_id: int | None) -> dict[str, Any]:
    letter = clean_letter(data)
    columns = list(letter)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            INSERT INTO orion_ods.letter ({', '.join(columns)}, created_by, last_updated_by)
            VALUES ({', '.join(['%s'] * len(columns))}, %s, %s)
            RETURNING letter_id
            """,
            [*letter.values(), user_id, user_id],
        )
        new_id = cur.fetchone()[0]
    return get_letter(new_id)


def update_letter(letter_id: int, data: dict[str, Any], user_id: int | None) -> dict[str, Any] | None:
    letter = clean_letter(data)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE orion_ods.letter
               SET {', '.join(f'{column} = %s' for column in letter)},
                   last_updated_by = %s, last_updated_timestamp = CURRENT_TIMESTAMP
             WHERE letter_id = %s
            """,
            [*letter.values(), user_id, letter_id],
        )
        if cur.rowcount == 0:
            return None
    return get_letter(letter_id)


def delete_letter(letter_id: int) -> bool:
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM orion_ods.letter WHERE letter_id = %s", (letter_id,))
        return cur.rowcount > 0


__all__ = [
    "DEFAULT_SETTINGS", "LetterheadError", "PARTS", "SETTING_LIMITS", "builtin_design", "clean_html", "clean_letter", "clean_settings",
    "create_letter", "delete_letter", "design_image", "get_letter", "layout", "list_letters", "load_design",
    "plain_text", "prepare_image", "public_design", "reset_image", "save_image", "save_settings", "update_letter",
]
