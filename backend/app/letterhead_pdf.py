"""Putting a PDF that was made somewhere else onto the letterhead.

Each page of the uploaded file gets the header and footer laid over it. With ``fit`` on (the default) the page
is first shrunk to sit between the two strips, so nothing of it is covered; with it off the page stays full
size, for a document that already leaves room at the top and bottom. Pages keep their own size and direction,
so a landscape sheet stays landscape.

Nothing is stored: the file comes in, the stamped file goes out.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from reportlab.lib.units import mm

from app.letterhead import LetterheadError
from app.letterhead_page import Letterhead

# pypdf reports every oddity of a file it can still read; the ones that matter are raised as errors here.
logging.getLogger("pypdf").setLevel(logging.ERROR)

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PAGES = 300
FIT_GAP_MM = 2.0  # kept between a shrunk page and each strip


def blank_pdf(design: dict[str, Any], pages: int = 1) -> bytes:
    """Blank letterhead paper as an A4 PDF, to print a stack of or to type on elsewhere."""
    return Letterhead(design).page_pdf(pages=min(max(int(pages), 1), 50))


def stamp_pdf(data: bytes, design: dict[str, Any], *, fit: bool = True, first_page_only: bool = False,
              header: bool = True, footer: bool = True) -> tuple[bytes, int]:
    """The uploaded PDF with the letterhead on it, and how many pages it has."""
    from pypdf import PdfReader, PdfWriter, Transformation
    from pypdf.errors import PyPdfError

    if not data:
        raise LetterheadError("That file is empty.")
    if len(data) > MAX_PDF_BYTES:
        raise LetterheadError("The PDF is larger than 25 MB.")
    if not (header or footer):
        raise LetterheadError("Choose the header, the footer or both.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise LetterheadError("That PDF is locked with a password. Remove the password and try again.")
        total = len(reader.pages)
    except LetterheadError:
        raise
    except (PyPdfError, ValueError, KeyError, OSError, RecursionError):
        raise LetterheadError("That file could not be read as a PDF.") from None
    if total == 0:
        raise LetterheadError("That PDF has no pages.")
    if total > MAX_PAGES:
        raise LetterheadError(f"That PDF has {total} pages. The most that can be done at once is {MAX_PAGES}.")

    letterhead = Letterhead(design)
    writer = PdfWriter()
    layers: dict[tuple[float, float], Any] = {}  # one letterhead layer per page size, reused
    try:
        for index, source in enumerate(reader.pages):
            if source.rotation:
                source.transfer_rotation_to_content()
            box = source.cropbox
            width, height = float(box.width), float(box.height)
            if width <= 0 or height <= 0:
                raise LetterheadError("That PDF has a page with no size.")
            page = writer.add_blank_page(width=width, height=height)
            stamped = not first_page_only or index == 0
            move = Transformation().translate(-float(box.left), -float(box.bottom))
            if stamped and fit:
                top, bottom = letterhead.strips(width, height)
                top = top + FIT_GAP_MM * mm if header else 0.0
                bottom = bottom + FIT_GAP_MM * mm if footer else 0.0
                room = height - top - bottom
                if room <= height * 0.2:
                    raise LetterheadError("The header and footer leave no room on a page of this size.")
                scale = min(room / height, 1.0)
                move = move.scale(scale).translate((width - width * scale) / 2, bottom + (room - height * scale) / 2)
            page.merge_transformed_page(source, move)
            if stamped:
                key = (round(width, 1), round(height, 1))
                if key not in layers:
                    layers[key] = PdfReader(io.BytesIO(letterhead.page_pdf(width, height, header=header, footer=footer))).pages[0]
                page.merge_page(layers[key])
    except LetterheadError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        raise LetterheadError("That PDF could not be put on the letterhead. Try printing it to a new PDF first.") from None

    out = io.BytesIO()
    writer.add_metadata({"/Producer": "Orion"})
    writer.write(out)
    return out.getvalue(), total
