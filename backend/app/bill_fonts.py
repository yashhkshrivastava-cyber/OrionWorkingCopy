"""The typefaces and sizes a printed bill can use.

A bill's text is drawn twice: on screen and in the browser's print (``BillDocument.tsx``) and in the PDF that is
emailed, sent on WhatsApp and kept in the Document Center (``billing_pdf.py``). Both read the choice from here, so
the two agree. The same keys and sizes are in ``frontend/src/billing/billFonts.ts`` (a test compares them).

The size is the base size in points. 9 is how a bill has always been printed; the other sizes scale the whole bill
(headings, columns and spacing) in proportion, so a larger size never crowds a column.

A bill may carry its own choice (``orion_ods.bill.font_family`` / ``font_size``); a bill that does not follows the
company's setting in the billing profile, and a company that has not set one gets Arial 9.
"""

from __future__ import annotations

from typing import Any

BASE_SIZE = 9.0  # points: the size every bill was printed at before the size could be chosen
SIZES: tuple[float, ...] = (8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0)
DEFAULT_FAMILY = "arial"
DEFAULT_SIZE = BASE_SIZE

# key -> (label, CSS font stack for the screen, the (regular, bold) files the PDF looks for). The files are searched
# in the system font folders in this order; a family none of whose files is found (or that has no rupee sign) is not
# offered for the PDF and a bill that asks for it is drawn in Arial.
FAMILIES: dict[str, dict[str, Any]] = {
    "arial": {
        "label": "Arial",
        "css": 'Arial, "Helvetica Neue", Helvetica, "Liberation Sans", sans-serif',
        "files": (("arial.ttf", "arialbd.ttf"), ("Arial.ttf", "Arial Bold.ttf"), ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
                  ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")),
    },
    "calibri": {
        "label": "Calibri",
        "css": 'Calibri, Carlito, "Segoe UI", Arial, sans-serif',
        "files": (("calibri.ttf", "calibrib.ttf"), ("Carlito-Regular.ttf", "Carlito-Bold.ttf")),
    },
    "segoe": {
        "label": "Segoe UI",
        "css": '"Segoe UI", "Nirmala UI", system-ui, Arial, sans-serif',
        "files": (("segoeui.ttf", "segoeuib.ttf"),),
    },
    "tahoma": {
        "label": "Tahoma",
        "css": 'Tahoma, "Segoe UI", Arial, sans-serif',
        "files": (("tahoma.ttf", "tahomabd.ttf"), ("Tahoma.ttf", "Tahoma Bold.ttf")),
    },
    "verdana": {
        "label": "Verdana",
        "css": 'Verdana, "DejaVu Sans", Geneva, sans-serif',
        "files": (("verdana.ttf", "verdanab.ttf"), ("Verdana.ttf", "Verdana Bold.ttf")),
    },
    "trebuchet": {
        "label": "Trebuchet MS",
        "css": '"Trebuchet MS", "Segoe UI", Arial, sans-serif',
        "files": (("trebuc.ttf", "trebucbd.ttf"), ("Trebuchet MS.ttf", "Trebuchet MS Bold.ttf")),
    },
    "times": {
        "label": "Times New Roman",
        "css": '"Times New Roman", Times, "Liberation Serif", serif',
        "files": (("times.ttf", "timesbd.ttf"), ("Times New Roman.ttf", "Times New Roman Bold.ttf"),
                  ("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf")),
    },
    "georgia": {
        "label": "Georgia",
        "css": 'Georgia, "Times New Roman", serif',
        "files": (("georgia.ttf", "georgiab.ttf"), ("Georgia.ttf", "Georgia Bold.ttf")),
    },
    "courier": {
        "label": "Courier New",
        "css": '"Courier New", Courier, "Liberation Mono", monospace',
        "files": (("cour.ttf", "courbd.ttf"), ("Courier New.ttf", "Courier New Bold.ttf"), ("LiberationMono-Regular.ttf", "LiberationMono-Bold.ttf")),
    },
}


class FontError(ValueError):
    """The choice is not one the bill offers. The message is safe to show to the user."""


def clean_family(value: Any, *, allow_empty: bool = False) -> str | None:
    """A family key from the catalogue. Empty means "follow the company's setting" when ``allow_empty``."""
    text = str(value or "").strip().lower()
    if not text:
        if allow_empty:
            return None
        return DEFAULT_FAMILY
    if text not in FAMILIES:
        raise FontError("Choose one of the typefaces offered for the bill.")
    return text


def clean_size(value: Any, *, allow_empty: bool = False) -> float | None:
    """A size in points from ``SIZES``. Empty means "follow the company's setting" when ``allow_empty``."""
    if value is None or str(value).strip() == "":
        return None if allow_empty else DEFAULT_SIZE
    try:
        size = float(value)
    except (TypeError, ValueError):
        raise FontError("Choose one of the text sizes offered for the bill.") from None
    if size not in SIZES:
        raise FontError("Choose one of the text sizes offered for the bill.")
    return size


def company_font(profile: dict[str, Any] | None) -> tuple[str, float]:
    """The company's own setting from the billing profile; a value that no longer means anything is ignored."""
    profile = profile or {}
    try:
        family = clean_family(profile.get("font_family"))
    except FontError:
        family = DEFAULT_FAMILY
    try:
        size = clean_size(profile.get("font_size"))
    except FontError:
        size = DEFAULT_SIZE
    return family or DEFAULT_FAMILY, size or DEFAULT_SIZE


def effective(bill: dict[str, Any], company: dict[str, Any] | None = None) -> dict[str, Any]:
    """The face and size a bill is drawn in: its own choice, else the company's, else Arial 9. ``own`` says whether
    the bill carries a choice of its own (so a screen can offer "use the company setting")."""
    default_family, default_size = company_font(company)
    try:
        family = clean_family(bill.get("font_family"), allow_empty=True)
    except FontError:
        family = None
    try:
        size = clean_size(bill.get("font_size"), allow_empty=True)
    except FontError:
        size = None
    return {"family": family or default_family, "size": size or default_size, "own": family is not None or size is not None}


def options() -> dict[str, Any]:
    """What the screens offer: the sizes, and the families (key, label, CSS stack)."""
    return {
        "sizes": list(SIZES), "default_family": DEFAULT_FAMILY, "default_size": DEFAULT_SIZE,
        "families": [{"key": key, "label": item["label"], "css": item["css"]} for key, item in FAMILIES.items()],
    }
