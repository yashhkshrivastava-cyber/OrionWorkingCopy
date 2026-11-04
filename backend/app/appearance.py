"""A person's appearance settings: which theme, light or dark, accent colour, style, corner radius, density and so on.

The browser applies them (``frontend/src/theme``); the server only keeps them, per user, so they follow the person to
another device. They are stored as one small JSON text in ``orion_ods.app_user.appearance``.

Nothing here is trusted: every key and value is checked against a short list before it is stored, so a stored value
can never be anything but a few short strings, numbers and booleans. A theme or style name the browser does not know
is not an error here (a newer or older browser may know different ones); the browser falls back to its default.
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_BYTES = 1024

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_HEX = re.compile(r"^#[0-9a-f]{6}$")

MODES = ("light", "dark", "system")
DENSITIES = ("compact", "comfortable", "spacious")
CONTRASTS = ("standard", "high")
MOTIONS = ("full", "reduced")
EXPERIENCES = ("classic", "lumen")


class AppearanceError(ValueError):
    """The settings cannot be kept. The message is safe to show."""


def _choice(value: Any, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise AppearanceError(f"{label} must be one of: {', '.join(allowed)}.")
    return value


def _name_or_none(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _NAME.match(value):
        raise AppearanceError(f"{label} is not a valid name.")
    return value


def _flag_or_none(value: Any, label: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise AppearanceError(f"{label} must be true, false or unset.")


def clean_appearance(raw: Any) -> dict[str, Any]:
    """The settings to keep, checked and in a fixed shape. Raises ``AppearanceError``."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise AppearanceError("The appearance settings are not valid.") from exc
    if not isinstance(raw, dict):
        raise AppearanceError("The appearance settings are not valid.")

    out: dict[str, Any] = {"v": 1}
    out["theme"] = _name_or_none(raw.get("theme", "default"), "The theme") or "default"
    out["mode"] = _choice(raw.get("mode", "system"), MODES, "Mode")

    accent = raw.get("accent")
    if accent is not None:
        if not isinstance(accent, str) or not _HEX.match(accent.lower()):
            raise AppearanceError("The accent colour must look like #1fa39b.")
        accent = accent.lower()
    out["accent"] = accent

    out["style"] = _name_or_none(raw.get("style"), "The style")

    radius = raw.get("radius")
    if radius is not None:
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not 0 <= radius <= 1:
            raise AppearanceError("The corner radius must be between 0 and 1.")
        radius = round(float(radius), 3)
    out["radius"] = radius

    out["density"] = _choice(raw.get("density", "comfortable"), DENSITIES, "Density")

    scale = raw.get("scale", 100)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not 85 <= scale <= 125:
        raise AppearanceError("The interface size must be between 85 and 125 percent.")
    out["scale"] = int(round(scale))

    out["contrast"] = _choice(raw.get("contrast", "standard"), CONTRASTS, "Contrast")
    out["motion"] = _choice(raw.get("motion", "full"), MOTIONS, "Motion")
    out["gradient"] = _flag_or_none(raw.get("gradient"), "Gradients")
    out["ambient"] = _flag_or_none(raw.get("ambient"), "The background glow")
    out["experience"] = _choice(raw.get("experience", "classic"), EXPERIENCES, "The interface")
    return out


def dump_appearance(raw: Any) -> str:
    """The checked settings as the text to store."""
    text = json.dumps(clean_appearance(raw), separators=(",", ":"))
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise AppearanceError("The appearance settings are too large.")
    return text


def load_appearance(stored: Any) -> dict[str, Any] | None:
    """The stored settings for the browser, or None when there are none (or they are no longer valid)."""
    if not stored:
        return None
    try:
        return clean_appearance(stored)
    except AppearanceError:
        return None
