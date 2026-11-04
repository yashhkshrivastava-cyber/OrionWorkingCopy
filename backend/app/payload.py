"""Shared create/update payload coercion."""

import math
from datetime import date, datetime
from typing import Any

INT_MIN, INT_MAX = -2_147_483_648, 2_147_483_647  # a PostgreSQL integer
# A total may differ from amount + tax + GST by the rounding of a bill (never more than a rupee).
ROUND_OFF_TOLERANCE = 1.0


class PayloadError(ValueError):
    pass


def coerce_input(value: Any, field_type: str) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes", "y")
    if field_type == "integer":
        number = float(value)
        # int(float("inf")) is an OverflowError, and a number past the column's range is a database error: both are plain "invalid"
        if not math.isfinite(number) or not INT_MIN <= number <= INT_MAX:
            raise ValueError("integer out of range")
        return int(number)
    if field_type == "number":
        if isinstance(value, str):
            value = value.replace(",", "")
        number = float(value)
        # float("nan") and float("inf") parse happily and would be stored: NaN makes every total NaN and is never equal to itself
        if not math.isfinite(number):
            raise ValueError("not a finite number")
        return number
    if field_type == "date":
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            serial = float(value)
            if 20000 <= serial <= 80000:
                from app.xlsx_io import excel_serial_to_date

                return excel_serial_to_date(serial)
        text = str(value).strip()
        if "T" in text:
            text = text.replace("T", " ", 1)
        for fmt in (
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d-%m-%Y",
            "%d-%m-%Y %H:%M",
            "%d-%m-%Y %H:%M:%S",
            "%d/%m/%y",
            "%d-%m-%y",
            "%m/%d/%Y",
            "%d.%m.%Y",
        ):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        date_part = text.split(" ", 1)[0]
        if date_part != text:
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%m/%d/%Y", "%d.%m.%Y"):
                try:
                    return datetime.strptime(date_part, fmt).date()
                except ValueError:
                    continue
        raise PayloadError(f"Invalid date: {value}")
    return value


def check_option(config: dict, value: Any) -> Any:
    """A value for a dropdown must be one of its options. The option's own spelling is stored, whatever case was typed."""
    options = config.get("options")
    if config.get("type") != "select" or not options or value is None:
        return value
    value = (config.get("option_aliases") or {}).get(str(value).strip().lower(), value)  # the plainer words a screen may use
    for option in options:
        if str(value).strip().lower() == str(option).lower():
            return option
    raise PayloadError(f"{config['label']} must be one of: {', '.join(options)}")


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def apply_computed_fields(form_fields: dict, cleaned: dict, existing: dict | None = None) -> dict:
    """Fill the fields that are worked out from others.

    ``existing`` is the stored record when one is being updated. An update may send only some of the fields, so a source it
    does not send is read from what is stored; without that a changed amount would leave the old total behind.
    """
    existing = existing or {}
    for key, config in form_fields.items():
        sources = config.get("compute_from") or []
        if not sources:
            continue
        if existing and key not in cleaned and not any(src in cleaned for src in sources):
            continue  # nothing this total depends on is being changed
        values = [cleaned[src] if src in cleaned else existing.get(src) for src in sources]
        op = config.get("compute_op") or "sum"
        if op == "difference":
            if any(value is None for value in values):
                continue
            cleaned[key] = round(float(values[0]) - sum(float(value) for value in values[1:]), 2)
        elif op == "month_year":
            source = values[0]
            if source is None:
                continue
            if hasattr(source, "strftime"):
                cleaned[key] = source.strftime("%Y-%m")
            else:
                text = str(source)
                cleaned[key] = text[:7] if len(text) >= 7 else text
        else:
            if values[0] is None:
                continue  # no amount, so nothing to total
            # A blank tax or GST is nothing, not a reason to leave the total empty
            total = round(sum(float(value) if value is not None else 0.0 for value in values), 2)
            supplied = cleaned.get(key)
            if supplied is None:
                cleaned[key] = total
            elif existing and _number(existing.get(key)) == _number(supplied):
                pass  # a total that is not being changed is left as it is stored
            elif abs(float(supplied) - total) > ROUND_OFF_TOLERANCE:
                names = " + ".join(form_fields[src]["label"] for src in sources)
                raise PayloadError(f"{config['label']} must equal {names} (it can differ by up to 1 rupee for rounding)")
    return cleaned


def clean_payload(entity: dict, payload: dict, *, for_update: bool = False, existing: dict | None = None) -> dict:
    form_fields = entity["form_fields"]
    cleaned = {}
    for key, config in form_fields.items():
        if config.get("readonly"):
            continue
        if key not in payload:
            if for_update:
                continue
            if config.get("required"):
                raise PayloadError(f"{config['label']} is required")
            continue
        if isinstance(payload[key], str) and "\x00" in payload[key]:
            raise PayloadError(f"{config['label']} contains a character that cannot be saved")
        try:
            value = coerce_input(payload[key], config["type"])
        except PayloadError:
            raise
        except (TypeError, ValueError, OverflowError) as exc:
            raise PayloadError(f"{config['label']} is invalid") from exc
        if value is None and config.get("required"):
            if not for_update:
                raise PayloadError(f"{config['label']} is required")
        value = check_option(config, value)
        rule = (entity.get("field_rules") or {}).get(key)
        if rule and value is not None:
            value = rule(value)  # checks the value and returns it tidied, or raises PayloadError
        cleaned[key] = value
    return apply_computed_fields(form_fields, cleaned, existing if for_update else None)
