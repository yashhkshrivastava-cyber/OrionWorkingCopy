"""Drawing the letterhead onto a PDF page.

``Letterhead`` wraps a design from ``letterhead.load_design``. It knows where the two strips go on a page of
any size (the strips keep their proportions and always span the page between the side gaps), draws them, and
builds a ReportLab document whose text stays clear of them on every page.

It depends on nothing else in the application, so the bill PDFs and the stamping of uploaded PDFs can both use it.
"""

from __future__ import annotations

import io
from typing import Any, Callable

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import SimpleDocTemplate


class Letterhead:
    def __init__(self, design: dict[str, Any]):
        self.design = design
        self.settings: dict[str, float] = design["settings"]
        self._readers: dict[str, ImageReader] = {}

    def _reader(self, part: str) -> ImageReader:
        # One reader per document, so a strip is stored in the PDF once however many pages show it.
        if part not in self._readers:
            self._readers[part] = ImageReader(io.BytesIO(self.design[part]["bytes"]))
        return self._readers[part]

    def boxes(self, page_width: float, page_height: float) -> dict[str, tuple[float, float, float, float]]:
        """(x, y, width, height) of each strip in points, y measured from the bottom of the page."""
        s = self.settings
        width = max(page_width - 2 * s["side_mm"] * mm, 10 * mm)
        x = (page_width - width) / 2
        header, footer = self.design["header"], self.design["footer"]
        header_height = width * header["height"] / max(header["width"], 1)
        footer_height = width * footer["height"] / max(footer["width"], 1)
        return {
            "header": (x, page_height - s["header_top_mm"] * mm - header_height, width, header_height),
            "footer": (x, s["footer_bottom_mm"] * mm, width, footer_height),
        }

    def strips(self, page_width: float, page_height: float) -> tuple[float, float]:
        """How far the strips reach in from the top and from the bottom of the page, in points."""
        boxes = self.boxes(page_width, page_height)
        top = page_height - boxes["header"][1]
        bottom = boxes["footer"][1] + boxes["footer"][3]
        return top, bottom

    def text_space(self, page_width: float = A4[0], page_height: float = A4[1], gap_mm: float | None = None) -> tuple[float, float]:
        """The room text must leave at the top and at the bottom: the strips plus the gap kept beside each
        (the design's own gaps, or ``gap_mm`` for both)."""
        top, bottom = self.strips(page_width, page_height)
        gap_top = self.settings["body_gap_top_mm"] if gap_mm is None else gap_mm
        gap_bottom = self.settings["body_gap_bottom_mm"] if gap_mm is None else gap_mm
        return top + gap_top * mm, bottom + gap_bottom * mm

    def draw(self, canvas: Canvas, page_width: float, page_height: float, *, header: bool = True, footer: bool = True) -> None:
        boxes = self.boxes(page_width, page_height)
        for part, wanted in (("header", header), ("footer", footer)):
            if wanted:
                x, y, width, height = boxes[part]
                canvas.drawImage(self._reader(part), x, y, width=width, height=height, mask="auto")

    def build(self, story: list[Any], *, title: str = "", author: str = "", side_mm: float | None = None,
              gap_mm: float | None = None, decorate: Callable[[Canvas, Any], None] | None = None) -> bytes:
        """An A4 document of ``story`` on the letterhead. ``side_mm`` overrides the text margins and ``gap_mm`` the
        gap kept beside each strip (a bill sets both); ``decorate`` draws anything else on each page, over the
        letterhead."""
        top, bottom = self.text_space(gap_mm=gap_mm)
        left = (side_mm if side_mm is not None else self.settings["body_left_mm"]) * mm
        right = (side_mm if side_mm is not None else self.settings["body_right_mm"]) * mm

        def on_page(canvas: Canvas, doc: Any) -> None:
            canvas.saveState()
            self.draw(canvas, A4[0], A4[1])
            canvas.restoreState()
            if decorate:
                decorate(canvas, doc)

        out = io.BytesIO()
        SimpleDocTemplate(out, pagesize=A4, leftMargin=left, rightMargin=right, topMargin=top, bottomMargin=bottom,
                          title=title, author=author).build(story, onFirstPage=on_page, onLaterPages=on_page)
        return out.getvalue()

    def page_pdf(self, page_width: float = A4[0], page_height: float = A4[1], *, header: bool = True, footer: bool = True,
                 pages: int = 1) -> bytes:
        """Pages that carry only the letterhead: blank letterhead paper, and the layer laid over an uploaded PDF."""
        out = io.BytesIO()
        canvas = Canvas(out, pagesize=(page_width, page_height))
        canvas.setTitle("Letterhead")
        for _ in range(max(pages, 1)):
            self.draw(canvas, page_width, page_height, header=header, footer=footer)
            canvas.showPage()
        canvas.save()
        return out.getvalue()
