"""MP Tenders (mptenders.gov.in), the Government of Madhya Pradesh's e-procurement portal (NIC's GePNIC), read the way its public
pages are read in a browser.

Only public pages, and only those that ask for no captcha: "Tenders by Organisation" (every organisation with active tenders),
each organisation's list (all its active tenders on one page) and each tender's details. The portal's own search asks for a
captcha; Orion never uses it and never answers one. Nobody signs in.

The portal's links belong to the visit that produced them ("session=T": a link opened in another browser says "Stale Session").
So a check opens the organisation list, then follows its links within the same visit; and nothing links back to a tender: a
person finds it on the portal by its Tender ID.

Requests are spaced like GeM's (``gem_client.GemSession``): this is one more public site to be gentle with.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.gem_client import GemError, GemSession

logger = logging.getLogger(__name__)

PORTAL = "MP Tenders"
BASE_URL = "https://mptenders.gov.in"
APP_URL = f"{BASE_URL}/nicgep/app"
ORGANISATIONS_URL = f"{APP_URL}?page=FrontEndTendersByOrganisation&service=page"
IST = timezone(timedelta(hours=5, minutes=30))
SOURCE = "mptenders"

_ROW = re.compile(r'<tr[^>]*\bid="informal[^"]*"[^>]*>(.*?)</tr>', re.S | re.I)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_LINK = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_BRACKETS = re.compile(r"\[([^\]]*)\]")
_TENDER_ID = re.compile(r"^\d{4}_[A-Za-z0-9]+_\d+_\d+$")
_FIELD = re.compile(r'<td[^>]*class="td_caption"[^>]*>(.*?)</td>\s*<td[^>]*class="td_field"[^>]*>(.*?)</td>', re.S | re.I)
_TOTAL_FEE = re.compile(r"Total Fee in\s*(?:₹|&#8377;|Rs\.?)?.*?-\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*\]", re.S | re.I)
_PIN = re.compile(r"(?<![0-9])([1-9][0-9]{5})(?![0-9])")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def text_of(fragment: str) -> str:
    """The words of a piece of HTML, on one line."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment or "")).split())


def stale(page: str) -> bool:
    return "Stale Session" in page or "session has timed out" in page.lower()


def when(value: str) -> Optional[datetime]:
    """'19-Oct-2026 09:00 AM' (Indian time) as a moment."""
    try:
        return datetime.strptime(value.strip(), "%d-%b-%Y %I:%M %p").replace(tzinfo=IST)
    except ValueError:
        return None


def rupees(value: Optional[str]) -> Optional[Decimal]:
    text = (value or "").replace(",", "").replace("₹", "").strip()
    if not text or text.upper() in ("NA", "N/A", "NIL", "-"):
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return amount if amount >= 0 else None


def yes_no(value: Optional[str]) -> Optional[bool]:
    text = (value or "").strip().lower()
    return True if text == "yes" else False if text == "no" else None


@dataclass
class Organisation:
    name: str
    count: int
    link: str


def organisations(page: str) -> list[Organisation]:
    """Every organisation with active tenders, from "Tenders by Organisation"."""
    found = []
    for row in _ROW.findall(page):
        cells = _CELL.findall(row)
        if len(cells) < 3:
            continue
        link = _LINK.search(cells[-1])
        count = text_of(cells[-1])
        if not link or not count.isdigit():
            continue
        found.append(Organisation(name=text_of(cells[1]), count=int(count), link=html.unescape(link.group(1))))
    return found


def tender_rows(page: str) -> list[dict]:
    """An organisation's active tenders: Tender ID, title, reference, dates, organisation chain, and the details link (good only
    in this visit)."""
    rows = []
    for row in _ROW.findall(_COMMENT.sub("", page)):  # the portal leaves a commented-out column in each row
        cells = _CELL.findall(row)
        if len(cells) < 6:
            continue
        link = _LINK.search(cells[4])
        if not link:
            continue
        title = text_of(link.group(2)).strip()
        if title.startswith("[") and title.endswith("]"):
            title = title[1:-1].strip()
        rest = text_of(cells[4].replace(link.group(0), " "))  # "[ref][tender id]" after the title
        groups = [g.strip() for g in _BRACKETS.findall(rest)]
        tender_id = next((g for g in reversed(groups) if _TENDER_ID.match(g)), None)
        if not tender_id:
            continue
        reference = " ".join(g for g in groups if g != tender_id) or None
        chain = text_of(cells[5])
        parts = [part.strip() for part in chain.split("||") if part.strip()]
        rows.append({
            "source_ref": tender_id,
            "bid_number": tender_id,
            "title": title[:1000] or None,
            "reference": (reference or "")[:300] or None,
            "start_timestamp": when(text_of(cells[1])),
            "end_timestamp": when(text_of(cells[2])),
            "ministry": parts[0][:200] if parts else None,
            "department": " / ".join(parts[1:])[:200] if len(parts) > 1 else None,
            "organisation_chain": chain[:500],
            "details_link": html.unescape(link.group(1)),
        })
    return rows


def details(page: str) -> dict:
    """What a tender's details page says that a search filters or shows. A field it does not state is None."""
    fields: dict[str, str] = {}
    for caption, value in _FIELD.findall(page):
        key = text_of(caption).rstrip(" *").strip()
        if key and key not in fields:
            fields[key] = text_of(value)

    def field(*names: str) -> Optional[str]:
        for name in names:
            for key, value in fields.items():
                if key.lower().startswith(name.lower()):
                    return value if value.upper() not in ("NA", "N/A", "") else None
        return None

    location = field("Location")
    pincode = field("Pincode")
    total = _TOTAL_FEE.search(page)
    period = field("Period Of Work")
    return {
        "title": field("Title"),
        "work_description": (field("Work Description") or "")[:2000] or None,
        "category": field("Product Category"),
        "tender_category": field("Tender Category"),
        "estimated_value": rupees(field("Tender Value")),
        "tender_fee": rupees(field("Tender Fee in")),
        "tender_fee_total": rupees(total.group(1)) if total else None,
        "tender_fee_exempt": yes_no(field("Tender Fee Exemption Allowed")),
        "emd_amount": rupees(field("EMD Amount")),
        "emd_required": None,
        "emd_exempt": yes_no(field("EMD Exemption Allowed")),
        "contract_period": f"{period} days" if period and period.isdigit() else period,
        "location_text": " ".join(part for part in (location, pincode) if part) or None,
        "pincode": pincode if pincode and _PIN.fullmatch(pincode.strip()) else None,
    }


def district_of(pincode: Optional[str]) -> list[str]:
    if not pincode:
        return []
    import bharatpin

    try:
        district = bharatpin.get_district(pincode.strip())
    except Exception:  # noqa: BLE001 - a number that is not a PIN code is simply not one
        return []
    return [district] if district else []


class MpSession(GemSession):
    """One check's visit to MP Tenders. Its links are good only within it, so it is kept for the whole check and opened again
    when the portal says the visit has expired."""

    portal = PORTAL

    def open(self) -> list[Organisation]:  # type: ignore[override]
        page = self._send("GET", ORGANISATIONS_URL).text
        found = organisations(page)
        if not found and "captcha" in page.lower() and "Tenders By Organisation" not in page:
            raise GemError("MP Tenders asked to prove this is a person (a captcha). The check stops here.", "captcha")
        if not found:
            raise GemError("MP Tenders' list of organisations no longer looks the way Orion expects. Its pages may have changed.")
        self.token = "open"
        return found

    def page(self, link: str) -> str:
        """A page of this visit, by a link it gave. Raises GemError("stale") when the visit has expired."""
        url = link if link.startswith("http") else BASE_URL + link
        text = self._send("GET", url).text
        if stale(text):
            raise GemError("The MP Tenders visit expired.", "stale")
        return text
