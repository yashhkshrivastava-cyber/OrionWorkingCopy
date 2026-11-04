"""PDF tools: the everyday things people do to PDFs before they send or file them.

Merge, split, take pages out or put them in another order, rotate, resize, turn pictures into a PDF and pictures out of one,
make a file smaller, put a watermark or page numbers on it, lock it with a password or unlock it, edit its details, read its
text, and mend one that will not open properly.

Every tool is a function of the files it is given and a few options: bytes in, bytes out. **Nothing is stored**, neither the
files nor the result, and no password is written to a log. The router (``routers/pdf_tools_router.py``) reads the uploads and
checks who may use the tools; this module checks the files (``open_pdf``) and the limits below.

Pages are chosen with one small language (``parse_pages``): ``1-3, 5, 8-`` (a range, one page, from page 8 to the end),
``last``, ``odd`` / ``even``, and a range written backwards (``5-1``) reverses it. Page numbers start at 1, as people count them.

Not done on purpose: turning a page into a picture (that needs a rendering engine, which would run untrusted files in native
code inside the server), reading text from scans (no OCR) and Word / Excel conversions.
"""

from __future__ import annotations

import io
import logging
import math
import re
import struct
import threading
import zipfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator

# pypdf reports every oddity of a file it can still read; the ones that matter are raised as errors here.
logging.getLogger("pypdf").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_TOTAL_BYTES = 120 * 1024 * 1024
MAX_FILES = 40
MAX_PAGES = 1500  # in one file, and in what comes out
MAX_PARTS = 500  # files in one ZIP
MAX_IMAGE_PIXELS = 60_000_000
MAX_EXTRACTED_IMAGES = 600
MIN_PASSWORD = 4
MAX_PASSWORD = 128

PAGE_SIZES_PT = {  # width x height in points (1/72 inch), portrait
    "a3": (841.89, 1190.55),
    "a4": (595.28, 841.89),
    "a5": (419.53, 595.28),
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
}

Upload = tuple[str, bytes]


class PdfToolError(ValueError):
    """Something the person can put right: a wrong page number, a locked file, a file that is not a PDF. Its text is shown to them."""


@dataclass
class Result:
    data: bytes
    filename: str
    media_type: str = "application/pdf"
    pages: int | None = None  # of the PDF that came out
    files: int | None = None  # inside a ZIP
    note: str = ""


# --------------------------------------------------------------------------- pages


_RANGE_SPACES = re.compile(r"\s*-\s*")
_SEPARATORS = re.compile(r"[,;\s]+")


def _page_number(word: str, total: int, label: str) -> int:
    """One page of ``word`` (a number, or ``last``), as a 0-based index."""
    if word in ("last", "end"):
        return total - 1
    if not word.isdigit() or len(word) > 6:
        raise PdfToolError(f"'{word}' is not a page number. Write pages like 1-3, 5, 8- (numbers, ranges and commas).")
    number = int(word)
    if number < 1:
        raise PdfToolError("Pages are numbered from 1.")
    if number > total:
        raise PdfToolError(f"Page {number} does not exist: {label} has {total} page{'s' if total != 1 else ''}.")
    return number - 1


def _token_pages(token: str, total: int, label: str) -> list[int]:
    """The pages one token stands for, in the order written: ``4``, ``2-6``, ``5-`` (to the end), ``-3`` (the first three),
    ``9-2`` (backwards), ``odd``, ``even``, ``all``."""
    if token == "all":
        return list(range(total))
    if token == "odd":
        return list(range(0, total, 2))
    if token == "even":
        return list(range(1, total, 2))
    if "-" not in token:
        return [_page_number(token, total, label)]
    first, _, second = token.partition("-")
    if "-" in second:
        raise PdfToolError(f"'{token}' is not a range. Write a range as 3-7.")
    if not first and not second:
        raise PdfToolError("A range needs a page on at least one side of the dash.")
    start = 0 if not first else _page_number(first, total, label)
    stop = total - 1 if not second else _page_number(second, total, label)
    if not first:  # "-3" means the first three pages
        return list(range(0, stop + 1))
    step = 1 if start <= stop else -1
    return list(range(start, stop + step, step))


def _normalise(spec: str | None) -> str:
    return _RANGE_SPACES.sub("-", (spec or "").strip().lower())


def parse_pages(spec: str | None, total: int, *, label: str = "This PDF", empty_is_all: bool = True) -> list[int]:
    """The 0-based pages ``spec`` names, in the order written (a page named twice comes twice). Empty means every page, unless
    ``empty_is_all`` is off."""
    text = _normalise(spec)
    if not text:
        if empty_is_all:
            return list(range(total))
        raise PdfToolError("Say which pages, for example 1-3, 5, 8-.")
    pages: list[int] = []
    for token in _SEPARATORS.split(text):
        if token:
            pages.extend(_token_pages(token, total, label))
        if len(pages) > MAX_PAGES:
            raise PdfToolError(f"That is more than {MAX_PAGES} pages.")
    if not pages:
        raise PdfToolError("Say which pages, for example 1-3, 5, 8-.")
    return pages


def parse_groups(spec: str | None, total: int, *, label: str = "This PDF") -> list[list[int]]:
    """One group of pages for each comma-separated part of ``spec``: ``1-3, 4, 7-`` is three groups."""
    text = _normalise(spec)
    parts = [part.strip() for part in re.split(r"[,;]", text) if part.strip()]
    if not parts:
        raise PdfToolError("Say where to split, for example 1-3, 4-6, 7-.")
    groups = []
    for part in parts:
        if re.search(r"\s", part):
            raise PdfToolError(f"'{part}' has a space in it. Put a comma between the parts.")
        groups.append(_token_pages(part, total, label))
    return groups


def _describe(pages: list[int]) -> str:
    """``3-6`` for a run of pages, otherwise ``2, 5, 9`` (page numbers as people count them)."""
    numbers = [p + 1 for p in pages]
    if len(numbers) == 1:
        return str(numbers[0])
    if numbers == list(range(numbers[0], numbers[-1] + 1)):
        return f"{numbers[0]}-{numbers[-1]}"
    if len(numbers) <= 6:
        return ", ".join(str(n) for n in numbers)
    return f"{len(numbers)} pages"


# --------------------------------------------------------------------------- options


def _options(raw: dict[str, Any] | None) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _bool(opts: dict[str, Any], key: str, default: bool) -> bool:
    value = opts.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _int(opts: dict[str, Any], key: str, default: int, low: int, high: int, label: str) -> int:
    value = opts.get(key, default)
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise PdfToolError(f"{label} must be a whole number.") from None
    if not low <= number <= high:
        raise PdfToolError(f"{label} must be between {low} and {high}.")
    return number


def _choice(opts: dict[str, Any], key: str, choices: tuple[str, ...], default: str, label: str) -> str:
    value = str(opts.get(key, default) or default).strip().lower()
    if value not in choices:
        raise PdfToolError(f"{label}: choose one of {', '.join(choices)}.")
    return value


def _text(opts: dict[str, Any], key: str, limit: int, label: str, *, required: bool = False) -> str:
    value = " ".join(str(opts.get(key) or "").split())
    if "\x00" in value:
        raise PdfToolError(f"{label} has a character that cannot be used.")
    if required and not value:
        raise PdfToolError(f"{label} is needed.")
    if len(value) > limit:
        raise PdfToolError(f"{label} can be at most {limit} characters.")
    return value


def _password(opts: dict[str, Any], key: str) -> str:
    value = str(opts.get(key) or "")
    if "\x00" in value or len(value) > MAX_PASSWORD:
        raise PdfToolError(f"The password can be at most {MAX_PASSWORD} characters.")
    return value


def _per_file(opts: dict[str, Any], key: str, count: int) -> list[str]:
    """A list of strings, one per file (missing ones are empty)."""
    raw = opts.get(key)
    values = [str(item or "") for item in raw] if isinstance(raw, list) else []
    return (values + [""] * count)[:count]


# --------------------------------------------------------------------------- reading files


def _parse_errors() -> tuple[type[BaseException], ...]:
    from pypdf.errors import PyPdfError

    return (PyPdfError, ValueError, KeyError, IndexError, TypeError, AttributeError, OSError, RecursionError, OverflowError,
            AssertionError, struct.error, zlib.error)


def stem(name: str | None, fallback: str = "Document") -> str:
    """A file name without its folder or extension, safe to put in a new name."""
    base = (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    base = "".join(ch for ch in base if ch.isalnum() or ch in " -_().").strip()[:70]
    return base or fallback


def check_size(name: str, data: bytes) -> None:
    if not data:
        raise PdfToolError(f"{name} is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise PdfToolError(f"{name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")


def open_pdf(name: str, data: bytes, password: str = "") -> tuple[Any, int]:
    """The PDF as a pypdf reader, and its number of pages; decrypted when it is locked and the password is right."""
    from pypdf import PdfReader

    check_size(name, data)
    if b"%PDF-" not in data[:1024]:
        raise PdfToolError(f"{name} is not a PDF file.")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(password or ""):
            hint = "That password does not open it." if password else "It is locked with a password: enter the password, or unlock it first."
            raise PdfToolError(f"{name} cannot be opened. {hint}")
        total = len(reader.pages)
    except PdfToolError:
        raise
    except _parse_errors():
        raise PdfToolError(f"{name} could not be read as a PDF. It may be damaged: the Repair tool can often mend it.") from None
    if total == 0:
        raise PdfToolError(f"{name} has no pages.")
    if total > MAX_PAGES:
        raise PdfToolError(f"{name} has {total} pages. The most that can be done at once is {MAX_PAGES}.")
    return reader, total


def _save(writer: Any) -> bytes:
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _finish(writer: Any) -> bytes:
    return _guard_write(_save, writer)


def _guard_write(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Writing a damaged page can fail late, in the middle of the work; say so in words."""
    try:
        return action(*args, **kwargs)
    except PdfToolError:
        raise
    except _parse_errors():
        raise PdfToolError("A page in that PDF could not be processed. The Repair tool can often mend such a file.") from None


def _one(files: list[Upload], options: dict[str, Any]) -> tuple[str, bytes, Any, int]:
    if len(files) != 1:
        raise PdfToolError("Choose one PDF.")
    name, data = files[0]
    reader, total = open_pdf(name, data, _password(options, "password"))
    return name, data, reader, total


def _clone(reader: Any) -> Any:
    from pypdf import PdfWriter

    return PdfWriter(clone_from=reader)


def _zip(parts: list[tuple[str, bytes]]) -> bytes:
    out = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:  # PDFs and photos do not compress further
        for name, data in parts:
            unique, n = name, 1
            while unique.lower() in used:
                n += 1
                unique = re.sub(r"(\.[^.]+)$", rf" ({n})\1", name)
            used.add(unique.lower())
            archive.writestr(unique, data)
    return out.getvalue()


# --------------------------------------------------------------------------- the tools


def merge(files: list[Upload], options: dict[str, Any]) -> Result:
    """Several PDFs as one, in the order given. Each may contribute only some of its pages, and each can be a bookmark."""
    from pypdf import PdfWriter

    if len(files) < 2:
        raise PdfToolError("Choose at least two PDFs to merge.")
    ranges = _per_file(options, "ranges", len(files))
    passwords = _per_file(options, "passwords", len(files))
    bookmarks = _bool(options, "bookmarks", True)
    writer = PdfWriter()
    total = 0
    for index, (name, data) in enumerate(files):
        reader, count = open_pdf(name, data, passwords[index])
        pages = parse_pages(ranges[index], count, label=name)
        total += len(pages)
        if total > MAX_PAGES:
            raise PdfToolError(f"The merged PDF would have more than {MAX_PAGES} pages.")
        every = pages == list(range(count))
        _guard_write(writer.append, reader, outline_item=stem(name, f"File {index + 1}") if bookmarks else None,
                     pages=None if every else pages)
    return Result(_finish(writer), "Merged.pdf", pages=total, note=f"{len(files)} files, {total} pages.")


def split(files: list[Upload], options: dict[str, Any]) -> Result:
    """One PDF cut into several, delivered as a ZIP: by the ranges written, every N pages, or a file for each page."""
    from pypdf import PdfWriter

    name, _data, reader, total = _one(files, options)
    mode = _choice(options, "mode", ("ranges", "every", "single"), "ranges", "How to split")
    if mode == "ranges":
        groups = parse_groups(options.get("ranges"), total, label=name)
    elif mode == "every":
        step = _int(options, "every", 1, 1, MAX_PAGES, "Pages in each file")
        groups = [list(range(start, min(start + step, total))) for start in range(0, total, step)]
    else:
        groups = [[i] for i in range(total)]
    if mode != "ranges" and len(groups) < 2:
        raise PdfToolError(f"{name} has {total} page{'s' if total != 1 else ''}, so there is nothing to split.")
    if len(groups) > MAX_PARTS:
        raise PdfToolError(f"That would make {len(groups)} files. The most is {MAX_PARTS}.")
    base = stem(name)
    parts = []
    for number, group in enumerate(groups, start=1):
        writer = PdfWriter()
        for page in group:
            writer.add_page(reader.pages[page])
        parts.append((f"{base} - part {number} (pages {_describe(group)}).pdf", _finish(writer)))
    return Result(_zip(parts), f"{base} - split.zip", "application/zip", files=len(parts), note=f"{len(parts)} files.")


def extract_pages(files: list[Upload], options: dict[str, Any]) -> Result:
    """A new PDF made of the pages asked for, in the order asked."""
    from pypdf import PdfWriter

    name, _data, reader, total = _one(files, options)
    pages = parse_pages(options.get("pages"), total, label=name, empty_is_all=False)
    writer = PdfWriter()
    for page in pages:
        writer.add_page(reader.pages[page])
    return Result(_finish(writer), f"{stem(name)} - extracted pages.pdf", pages=len(pages))


def remove_pages(files: list[Upload], options: dict[str, Any]) -> Result:
    """The PDF without the pages named."""
    from pypdf import PdfWriter

    name, _data, reader, total = _one(files, options)
    drop = set(parse_pages(options.get("pages"), total, label=name, empty_is_all=False))
    keep = [page for page in range(total) if page not in drop]
    if not keep:
        raise PdfToolError("That would remove every page. Leave at least one.")
    writer = PdfWriter()
    for page in keep:
        writer.add_page(reader.pages[page])
    return Result(_finish(writer), f"{stem(name)} - pages removed.pdf", pages=len(keep),
                  note=f"{len(drop)} page{'s' if len(drop) != 1 else ''} removed.")


def organize(files: list[Upload], options: dict[str, Any]) -> Result:
    """The pages in a new order. ``order`` lists the pages as they should come, and may name a page twice or write ``blank`` for a
    blank page; or, with ``reverse``, the whole PDF backwards."""
    from pypdf import PdfWriter

    name, _data, reader, total = _one(files, options)
    spec = _normalise(options.get("order"))
    if _bool(options, "reverse", False) and not spec:
        sequence: list[int | None] = list(range(total - 1, -1, -1))
    else:
        if not spec:
            raise PdfToolError("Write the new order of the pages, for example 3, 1, 2, blank, 4-9, or choose Reverse.")
        sequence = []
        for token in _SEPARATORS.split(spec):
            if token == "blank":
                sequence.append(None)
            elif token:
                sequence.extend(_token_pages(token, total, name))
            if len(sequence) > MAX_PAGES:
                raise PdfToolError(f"That is more than {MAX_PAGES} pages.")
    if all(item is None for item in sequence):
        raise PdfToolError("A PDF needs at least one page that is not blank.")
    writer = PdfWriter()
    last = reader.pages[0]
    for item in sequence:
        if item is None:
            box = last.mediabox
            writer.add_blank_page(float(box.width), float(box.height))
        else:
            last = reader.pages[item]
            writer.add_page(last)
    return Result(_finish(writer), f"{stem(name)} - reordered.pdf", pages=len(sequence))


def rotate(files: list[Upload], options: dict[str, Any]) -> Result:
    """Some pages, or all of them, turned a quarter, a half or three quarters of the way round (clockwise)."""
    name, _data, reader, total = _one(files, options)
    angle = int(_choice(options, "angle", ("90", "180", "270"), "90", "Angle"))
    pages = parse_pages(options.get("pages"), total, label=name)
    writer = _clone(reader)
    for page in set(pages):
        sheet = writer.pages[page]
        sheet.rotation = (sheet.rotation + angle) % 360  # a page turned back to upright is 0, not 360
    return Result(_finish(writer), f"{stem(name)} - rotated.pdf", pages=total,
                  note=f"{len(set(pages))} page{'s' if len(set(pages)) != 1 else ''} turned {angle} degrees.")


def resize(files: list[Upload], options: dict[str, Any]) -> Result:
    """Every page fitted onto a standard sheet (A3, A4, A5, Letter or Legal), kept in proportion and centred. A landscape page
    goes on a landscape sheet."""
    from pypdf import PageObject, PdfWriter, Transformation

    name, _data, reader, total = _one(files, options)
    size = _choice(options, "size", tuple(PAGE_SIZES_PT), "a4", "Paper size")
    base_w, base_h = PAGE_SIZES_PT[size]
    writer = PdfWriter()
    for source in reader.pages:
        if source.rotation:
            source.transfer_rotation_to_content()
        box = source.cropbox
        width, height = float(box.width), float(box.height)
        if width <= 0 or height <= 0:
            raise PdfToolError("A page in that PDF has no size.")
        sheet_w, sheet_h = (base_h, base_w) if width > height else (base_w, base_h)
        scale = min(sheet_w / width, sheet_h / height)
        page = PageObject.create_blank_page(width=sheet_w, height=sheet_h)
        move = Transformation().translate(-float(box.left), -float(box.bottom)).scale(scale, scale).translate(
            (sheet_w - width * scale) / 2, (sheet_h - height * scale) / 2)
        page.merge_transformed_page(source, move)
        writer.add_page(page)
    return Result(_finish(writer), f"{stem(name)} - {size.upper()}.pdf", pages=total,
                  note="Links and form fields on the pages are not kept.")


def _load_image(name: str, data: bytes) -> Any:
    from PIL import Image, UnidentifiedImageError

    check_size(name, data)
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:  # HEIC photos (from a phone) are read only when this is installed
        logger.debug("pillow_heif is not installed")
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise PdfToolError(f"{name} is too large a picture ({image.width} x {image.height}).")
        image.load()
    except PdfToolError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise PdfToolError(f"{name} is not a picture that can be read. Use a JPG, PNG, WebP, GIF, BMP, TIFF or HEIC file.") from None
    return image


_ASCII85 = threading.Lock()


@contextmanager
def _binary_images() -> Iterator[None]:
    """Reportlab writes pictures as ASCII85 text unless told not to, which makes every photo a quarter bigger. The switch is global,
    so it is turned off only while this job draws, and one picture job at a time does it."""
    from reportlab import rl_config

    with _ASCII85:
        before = rl_config.useA85
        rl_config.useA85 = 0
        try:
            yield
        finally:
            rl_config.useA85 = before


def images_to_pdf(files: list[Upload], options: dict[str, Any]) -> Result:
    """Pictures (a photo of a document, a scan) as a PDF, one to a page, in the order given."""
    from PIL import Image, ImageOps
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    if not files:
        raise PdfToolError("Choose at least one picture.")
    size = _choice(options, "size", ("a4", "letter", "fit"), "a4", "Paper size")
    orientation = _choice(options, "orientation", ("auto", "portrait", "landscape"), "auto", "Direction")
    margin = _int(options, "margin_mm", 10, 0, 40, "The margin") * mm
    out = io.BytesIO()
    with _binary_images():  # a photo goes in as it is, not wrapped in text that makes it a quarter bigger
        page = canvas.Canvas(out, pageCompression=1)
        for name, data in files:
            image = _load_image(name, data)
            original = image.format
            untouched = original == "JPEG" and image.getexif().get(0x0112, 1) in (0, 1) and image.mode in ("RGB", "L")
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA", "P"):  # transparency becomes white paper
                flat = image.convert("RGBA")
                background = Image.new("RGB", flat.size, "white")
                background.paste(flat, mask=flat.split()[3])
                image = background
            elif image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            if untouched:
                source = ImageReader(io.BytesIO(data))  # the photo as it was, not drawn again
            elif original in ("JPEG", "MPO", "HEIF", "WEBP"):  # a photo that had to be turned or converted stays light
                encoded = io.BytesIO()
                image.save(encoded, "JPEG", quality=90)
                source = ImageReader(io.BytesIO(encoded.getvalue()))
            else:  # a screenshot, a scan saved as PNG: kept exact
                source = ImageReader(image)
            px_w, px_h = image.size
            if size == "fit":
                dpi = 150.0
                sheet_w, sheet_h = min(px_w / dpi * 72, 14400.0), min(px_h / dpi * 72, 14400.0)
                inner = 0.0
            else:
                base_w, base_h = PAGE_SIZES_PT[size]
                landscape = px_w > px_h if orientation == "auto" else orientation == "landscape"
                sheet_w, sheet_h = (base_h, base_w) if landscape else (base_w, base_h)
                inner = margin
            room_w, room_h = max(sheet_w - 2 * inner, 1.0), max(sheet_h - 2 * inner, 1.0)
            scale = min(room_w / px_w, room_h / px_h)
            width, height = px_w * scale, px_h * scale
            page.setPageSize((sheet_w, sheet_h))
            page.drawImage(source, (sheet_w - width) / 2, (sheet_h - height) / 2, width=width, height=height)
            page.showPage()
        page.save()
    data = out.getvalue()
    label = stem(files[0][0], "Pictures") if len(files) == 1 else "Pictures"
    return Result(data, f"{label}.pdf", pages=len(files), note=f"{len(files)} picture{'s' if len(files) != 1 else ''}.")


def extract_images(files: list[Upload], options: dict[str, Any]) -> Result:
    """The pictures inside a PDF (photos, scans, logos), as a ZIP. Pages drawn as text and lines are not pictures and are not included."""
    name, _data, reader, total = _one(files, options)
    smallest = _int(options, "min_px", 100, 1, 5000, "The smallest side")
    found: list[tuple[str, bytes]] = []
    base = stem(name)
    for number, page in enumerate(reader.pages, start=1):
        try:
            images = list(page.images)
        except _parse_errors():
            continue
        for position, image in enumerate(images, start=1):
            try:
                picture = image.image
                if min(picture.size) < smallest:
                    continue
                extension = (image.name.rsplit(".", 1)[-1] if "." in image.name else "png").lower()
                found.append((f"{base} - page {number} picture {position}.{extension if extension in ('jpg', 'jpeg', 'png') else 'png'}",
                              image.data))
            except Exception:  # noqa: BLE001 - one picture that cannot be read must not stop the others
                logger.debug("a picture on page %s could not be read", number)
                continue
            if len(found) >= MAX_EXTRACTED_IMAGES:
                break
        if len(found) >= MAX_EXTRACTED_IMAGES:
            break
    if not found:
        raise PdfToolError("No pictures were found in that PDF. (A page that looks like a photo may be drawn another way.)")
    return Result(_zip(found), f"{base} - pictures.zip", "application/zip", files=len(found), note=f"{len(found)} pictures.")


COMPRESSION = {"light": (None, 85), "recommended": (2400, 70), "strong": (1500, 50)}  # (longest side in pixels, JPEG quality)


def compress(files: list[Upload], options: dict[str, Any]) -> Result:
    """A smaller file. Always tidied without loss; the pictures inside are also made lighter for the stronger choices."""
    name, data, reader, total = _one(files, options)
    level = _choice(options, "level", tuple(COMPRESSION), "recommended", "How much")
    longest, quality = COMPRESSION[level]
    writer = _clone(reader)
    replaced = 0
    for page in writer.pages:
        try:
            page.compress_content_streams()
            if level == "light":
                continue
            for image in list(page.images):
                try:
                    picture = image.image
                    if longest and max(picture.size) > longest:
                        factor = longest / max(picture.size)
                        picture = picture.resize((max(1, round(picture.width * factor)), max(1, round(picture.height * factor))))
                    if picture.mode not in ("RGB", "L"):
                        picture = picture.convert("RGB")
                    image.replace(picture, quality=quality)
                    replaced += 1
                except Exception:  # noqa: BLE001 - a picture that cannot be redone stays as it was; the rest still shrink
                    logger.debug("a picture could not be made lighter")
        except _parse_errors():
            continue
    _guard_write(writer.compress_identical_objects)
    done = _finish(writer)
    if len(done) >= len(data):
        return Result(data, f"{stem(name)} - compressed.pdf", pages=total,
                      note="That PDF is already as small as it can be made here, so it is returned as it was.")
    saved = round(100 * (1 - len(done) / len(data)))
    return Result(done, f"{stem(name)} - compressed.pdf", pages=total,
                  note=f"{_size(len(data))} became {_size(len(done))}, {saved}% smaller" + (f" ({replaced} pictures made lighter)." if replaced else "."))


def _size(count: int) -> str:
    return f"{count / (1024 * 1024):.1f} MB" if count >= 1024 * 1024 else f"{max(1, round(count / 1024))} KB"


_COLOURS = {"grey": (0.45, 0.45, 0.45), "red": (0.8, 0.1, 0.1), "blue": (0.1, 0.25, 0.75), "black": (0.0, 0.0, 0.0), "green": (0.05, 0.5, 0.25)}


def _font_for(text: str, bold: bool = False) -> str:
    """A registered face that can draw ``text``: the Hindi face for Devanagari, otherwise the face the bills use."""
    from app import billing_pdf

    if re.search(r"[ऀ-ॿ]", text):
        return billing_pdf._devanagari() or "Helvetica"
    regular, heavy, _rupee = billing_pdf.fonts()
    return heavy if bold else regular


def _overlay_pages(reader: Any, draw: Callable[[Any, float, float, int], None], pages: list[int] | None = None) -> Any:
    """The PDF with something drawn on top of the pages. ``draw(canvas, width, height, page_index)`` paints one page's layer."""
    from pypdf import PdfReader, Transformation
    from reportlab.pdfgen import canvas

    writer = _clone(reader)
    wanted = None if pages is None else set(pages)
    for index, page in enumerate(writer.pages):
        if wanted is not None and index not in wanted:
            continue
        if page.rotation:
            page.transfer_rotation_to_content()
        box = page.cropbox
        width, height = float(box.width), float(box.height)
        if width <= 0 or height <= 0:
            continue
        buffer = io.BytesIO()
        layer = canvas.Canvas(buffer, pagesize=(width, height))
        draw(layer, width, height, index)
        layer.showPage()
        layer.save()
        buffer.seek(0)
        page.merge_transformed_page(PdfReader(buffer).pages[0], Transformation().translate(float(box.left), float(box.bottom)))
    return writer


def watermark(files: list[Upload], options: dict[str, Any]) -> Result:
    """Words across the pages (CONFIDENTIAL, COPY, DRAFT): one big diagonal line in the middle, or repeated over the page."""
    name, _data, reader, total = _one(files, options)
    text = _text(options, "text", 60, "The watermark text", required=True)
    layout = _choice(options, "layout", ("center", "tiled"), "center", "Layout")
    colour = _COLOURS[_choice(options, "colour", tuple(_COLOURS), "grey", "Colour")]
    opacity = _int(options, "opacity", 25, 5, 100, "Opacity") / 100
    size = _int(options, "size", 64, 10, 200, "Size")
    angle = _int(options, "angle", 45, 0, 90, "Angle")
    pages = parse_pages(options.get("pages"), total, label=name)
    font = _font_for(text, bold=True)

    def draw(layer: Any, width: float, height: float, _index: int) -> None:
        from reportlab.pdfbase.pdfmetrics import stringWidth

        layer.setFillColorRGB(*colour)
        layer.setFillAlpha(opacity)
        fit = size
        if layout == "center":  # a line never runs off the sheet: it is shrunk to the room there is along its angle
            run = stringWidth(text, font, size)
            radians = math.radians(angle)
            room = 0.9 * min(width / max(math.cos(radians), 1e-6), height / max(math.sin(radians), 1e-6))
            fit = size if run <= room else size * room / run
        layer.setFont(font, fit)
        if layout == "center":
            layer.saveState()
            layer.translate(width / 2, height / 2)
            layer.rotate(angle)
            layer.drawCentredString(0, -fit * 0.3, text)
            layer.restoreState()
            return
        step_x, step_y = max(stringWidth(text, font, fit) + fit, fit * 3), fit * 4
        for row in range(-2, int(height / step_y) + 3):
            for column in range(-2, int(width / step_x) + 3):
                layer.saveState()
                layer.translate(column * step_x + (row % 2) * step_x / 2, row * step_y)
                layer.rotate(angle)
                layer.drawString(0, 0, text)
                layer.restoreState()

    writer = _overlay_pages(reader, draw, pages)
    return Result(_finish(writer), f"{stem(name)} - watermarked.pdf", pages=total)


_NUMBER_FORMATS = {"n": "{n}", "page_n": "Page {n}", "n_of_total": "{n} / {total}", "page_n_of_total": "Page {n} of {total}"}
_POSITIONS = ("bottom-center", "bottom-right", "bottom-left", "top-center", "top-right", "top-left")


def page_numbers(files: list[Upload], options: dict[str, Any]) -> Result:
    """A number on each page (or on the pages chosen), at a corner or the middle of the top or bottom."""
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth

    name, _data, reader, total = _one(files, options)
    position = _choice(options, "position", _POSITIONS, "bottom-center", "Position")
    pattern = _NUMBER_FORMATS[_choice(options, "format", tuple(_NUMBER_FORMATS), "page_n_of_total", "Format")]
    first = _int(options, "start", 1, 0, 9999, "The first number")
    size = _int(options, "size", 10, 6, 36, "Size")
    margin = _int(options, "margin_mm", 10, 3, 40, "The distance from the edge") * mm
    skip_first = _bool(options, "skip_first", False)
    pages = parse_pages(options.get("pages"), total, label=name)
    if skip_first:
        pages = [page for page in pages if page != 0]
    font = _font_for("0")

    def draw(layer: Any, width: float, height: float, index: int) -> None:
        label = pattern.format(n=first + index, total=first + total - 1)
        layer.setFont(font, size)
        layer.setFillColorRGB(0.1, 0.1, 0.1)
        run = stringWidth(label, font, size)
        side = position.rsplit("-", 1)[1]
        x = {"left": margin, "center": (width - run) / 2, "right": width - margin - run}[side]
        y = margin if position.startswith("bottom") else height - margin - size
        layer.drawString(x, y, label)

    writer = _overlay_pages(reader, draw, pages)
    return Result(_finish(writer), f"{stem(name)} - numbered.pdf", pages=total)


def protect(files: list[Upload], options: dict[str, Any]) -> Result:
    """The PDF locked with a password (AES-256), which anyone must give to open it. Printing and copying text can be switched off."""
    from pypdf import PdfWriter
    from pypdf.constants import UserAccessPermissions as Allow

    name, _data, reader, total = _one(files, options)
    secret = _password(options, "new_password")
    if len(secret) < MIN_PASSWORD:
        raise PdfToolError(f"The password needs at least {MIN_PASSWORD} characters.")
    owner = _password(options, "owner_password") or None
    allowed = 0xFFFFFFFC  # every permission; bits the PDF standard reserves stay set
    if not _bool(options, "allow_print", True):
        allowed &= ~int(Allow.PRINT | Allow.PRINT_TO_REPRESENTATION)
    if not _bool(options, "allow_copy", True):
        allowed &= ~int(Allow.EXTRACT | Allow.EXTRACT_TEXT_AND_GRAPHICS)
    if not _bool(options, "allow_edit", False):
        allowed &= ~int(Allow.MODIFY | Allow.ADD_OR_MODIFY | Allow.FILL_FORM_FIELDS | Allow.ASSEMBLE_DOC)
    writer = PdfWriter(clone_from=reader)
    try:
        writer.encrypt(secret, owner, algorithm="AES-256", permissions_flag=Allow(allowed & 0xFFFFFFFF))
    except ImportError:
        raise PdfToolError("Locking a PDF is not available on this server (the 'cryptography' package is missing).") from None
    return Result(_finish(writer), f"{stem(name)} - protected.pdf", pages=total,
                  note="Keep the password safe: Orion does not store it and cannot recover it.")


def unlock(files: list[Upload], options: dict[str, Any]) -> Result:
    """A copy of a locked PDF that opens without a password, for someone who knows the password. Orion does not guess or break passwords."""
    if len(files) != 1:
        raise PdfToolError("Choose one PDF.")
    name, data = files[0]
    from pypdf import PdfReader

    check_size(name, data)
    if b"%PDF-" not in data[:1024]:
        raise PdfToolError(f"{name} is not a PDF file.")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        locked = reader.is_encrypted
        if locked and not reader.decrypt(_password(options, "password")):
            raise PdfToolError("That password does not open the PDF." if options.get("password") else "Enter the password of the PDF.")
        total = len(reader.pages)
    except PdfToolError:
        raise
    except _parse_errors():
        raise PdfToolError(f"{name} could not be read as a PDF.") from None
    writer = _clone(reader)
    note = "The password and the restrictions are gone from this copy." if locked else "That PDF was not locked, so this is an ordinary copy."
    return Result(_finish(writer), f"{stem(name)} - unlocked.pdf", pages=total, note=note)


_INFO_FIELDS = (("title", "/Title"), ("author", "/Author"), ("subject", "/Subject"), ("keywords", "/Keywords"))


def metadata(files: list[Upload], options: dict[str, Any]) -> Result:
    """The PDF's details (title, author, subject, keywords) changed, or all cleared. The pages are not touched."""
    name, _data, reader, total = _one(files, options)
    writer = _clone(reader)
    details = {key: _text(options, field, 500, field.capitalize()) for field, key in _INFO_FIELDS}
    writer.metadata = None  # what the file said before is replaced, not added to
    if not _bool(options, "clear", False):
        writer.add_metadata({key: value for key, value in details.items() if value})
    return Result(_finish(writer), f"{stem(name)} - details.pdf", pages=total,
                  note="Every detail was cleared." if _bool(options, "clear", False) else "The details were saved.")


def extract_text(files: list[Upload], options: dict[str, Any]) -> Result:
    """The words in the PDF as a plain text file. Works for PDFs made on a computer; a scan has no text to read (there is no OCR)."""
    name, _data, reader, total = _one(files, options)
    pages = parse_pages(options.get("pages"), total, label=name)
    chunks, empty = [], 0
    for page in pages:
        try:
            words = (reader.pages[page].extract_text() or "").strip()
        except _parse_errors():
            words = ""
        empty += 0 if words else 1
        chunks.append(f"--- Page {page + 1} ---\n{words}")
    if empty == len(pages):
        raise PdfToolError("There is no text to read in those pages. If it is a scan or a photo, the words are a picture, and Orion cannot read pictures.")
    note = f"{empty} of the {len(pages)} pages had no text." if empty else ""
    return Result(("\n\n".join(chunks) + "\n").encode("utf-8-sig"), f"{stem(name)} - text.txt", "text/plain; charset=utf-8", pages=len(pages), note=note)


def repair(files: list[Upload], options: dict[str, Any]) -> Result:
    """A damaged PDF read as far as it can be, and its pages written out again as a clean file."""
    from pypdf import PdfWriter

    name, _data, reader, total = _one(files, options)
    writer = PdfWriter()
    lost = 0
    for index in range(total):
        try:
            writer.add_page(reader.pages[index])
        except _parse_errors():
            lost += 1
    if len(writer.pages) == 0:
        raise PdfToolError("None of the pages in that PDF could be recovered.")
    note = f"{lost} page{'s' if lost != 1 else ''} could not be recovered." if lost else "Every page was recovered."
    return Result(_finish(writer), f"{stem(name)} - repaired.pdf", pages=len(writer.pages), note=note)


# --------------------------------------------------------------------------- the list, and looking at files


@dataclass(frozen=True)
class Tool:
    run: Callable[[list[Upload], dict[str, Any]], Result]
    kind: str  # pdfs (two or more), pdf (one), images
    label: str


TOOLS: dict[str, Tool] = {
    "merge": Tool(merge, "pdfs", "Merge PDFs"),
    "split": Tool(split, "pdf", "Split a PDF"),
    "extract": Tool(extract_pages, "pdf", "Extract pages"),
    "remove": Tool(remove_pages, "pdf", "Remove pages"),
    "organize": Tool(organize, "pdf", "Reorder pages"),
    "rotate": Tool(rotate, "pdf", "Rotate pages"),
    "resize": Tool(resize, "pdf", "Resize pages"),
    "images-to-pdf": Tool(images_to_pdf, "images", "Pictures to PDF"),
    "extract-images": Tool(extract_images, "pdf", "Pictures from a PDF"),
    "compress": Tool(compress, "pdf", "Compress"),
    "watermark": Tool(watermark, "pdf", "Watermark"),
    "page-numbers": Tool(page_numbers, "pdf", "Page numbers"),
    "protect": Tool(protect, "pdf", "Lock with a password"),
    "unlock": Tool(unlock, "pdf", "Unlock"),
    "metadata": Tool(metadata, "pdf", "Edit details"),
    "text": Tool(extract_text, "pdf", "Read the text"),
    "repair": Tool(repair, "pdf", "Repair"),
}


def check_upload_set(kind: str, files: list[Upload]) -> None:
    """The number and total size of the files, before any of them is opened."""
    if not files:
        raise PdfToolError("Choose a file.")
    if len(files) > MAX_FILES:
        raise PdfToolError(f"At most {MAX_FILES} files at once.")
    if sum(len(data) for _name, data in files) > MAX_TOTAL_BYTES:
        raise PdfToolError(f"The files together are larger than {MAX_TOTAL_BYTES // (1024 * 1024)} MB.")
    if kind == "pdf" and len(files) != 1:
        raise PdfToolError("This tool works on one PDF at a time.")


def run(tool_id: str, files: list[Upload], options: dict[str, Any] | None) -> Result:
    tool = TOOLS.get(tool_id)
    if tool is None:
        raise PdfToolError("There is no such tool.")
    check_upload_set(tool.kind, files)
    result = tool.run(files, _options(options))
    if not result.data:
        raise PdfToolError("Nothing came out of that.")
    return result


def inspect(files: list[Upload], options: dict[str, Any] | None) -> list[dict[str, Any]]:
    """What each file is: pages, size, whether it is locked, its details. A file that cannot be read is reported, not refused, so one
    bad file does not hide the others."""
    check_upload_set("pdfs", files)
    passwords = _per_file(_options(options), "passwords", len(files))
    out = []
    for index, (name, data) in enumerate(files):
        row: dict[str, Any] = {"name": name, "bytes": len(data), "pages": None, "locked": False, "error": "", "width": None, "height": None}
        try:
            reader, total = open_pdf(name, data, passwords[index])
            row["pages"] = total
            box = reader.pages[0].mediabox
            row["width"], row["height"] = round(float(box.width)), round(float(box.height))
            info = reader.metadata or {}
            row["details"] = {field: str(info.get(key) or "") for field, key in _INFO_FIELDS}
            row["was_locked"] = bool(reader.is_encrypted)
        except PdfToolError as exc:
            row["error"] = str(exc)
            row["locked"] = "locked with a password" in str(exc) or "does not open it" in str(exc)
        except _parse_errors():
            row["error"] = f"{name} could not be read as a PDF."
        out.append(row)
    return out
