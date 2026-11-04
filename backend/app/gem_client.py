"""GeM's public bid listing (bidplus.gem.gov.in), read the way its own "All Bids" page reads it, and the public bid documents.

Nothing here signs in, and nothing is sent to GeM but a search: the listing page and each bid's document are open to anyone. This is
not an API GeM publishes, so it can change without notice; when an answer is not what this code expects it raises ``GemError`` with
the reason in words, and the tender check says so on its page and on the System page instead of guessing. A page asking to prove the
visitor is a person stops the check: it is never answered or worked around.

Every request waits ``ORION_TENDERS_REQUEST_GAP_SECONDS`` (default 2) after the one before, so a check is a slow trickle, not a load.
"""

from __future__ import annotations

import io
import json
import logging
import re
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import httpx

from app.config import env

logger = logging.getLogger(__name__)

BASE_URL = "https://bidplus.gem.gov.in"
LIST_PAGE = f"{BASE_URL}/all-bids"
DATA_URL = f"{BASE_URL}/all-bids-data"
DOCUMENT_URL = BASE_URL + "/showbidDocument/{bid_id}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Orion-tender-search (Prakash Securities)"
PAGE_SIZE = 10  # GeM's page; it does not take a larger one
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024
RETRY_PAUSES = (15, 45)  # seconds before trying a request again after a network blip; then the check stops
# Where a seller signs in to GeM. After signing in, a bid is opened from Bids > Participate in Bids by its number: GeM
# publishes no link that opens one bid's participation page directly.
SELLER_SIGN_IN_URL = "https://sso.gem.gov.in/ARXSSO/oauth/doLogin"
# Raised when document_fields reads something new, so bids read by an older version are read again.
READER_VERSION = 2
BID_KINDS = ("all", "service", "product")

_TOKEN = re.compile(r"csrf_bd_gem_nk['\"]\s*[:,]\s*['\"]([0-9a-f]{16,})['\"]")


class GemError(RuntimeError):
    """GeM could not be read, in words a person can act on. ``kind``: unreachable, refused, changed, captcha (these stop a
    check) or missing (one item GeM no longer has, which does not)."""

    def __init__(self, message: str, kind: str = "changed") -> None:
        super().__init__(message)
        self.kind = kind


def request_gap_seconds() -> float:
    try:
        return max(1.0, float(env("ORION_TENDERS_REQUEST_GAP_SECONDS", "2")))
    except ValueError:
        return 2.0


# --------------------------------------------------------------------------------------------- reading GeM's answers


def _first(value: Any) -> Any:
    """GeM's search index returns most fields as one-item lists."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _text(value: Any, limit: int = 500) -> Optional[str]:
    value = _first(value)
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:limit] or None


def _int(value: Any) -> Optional[int]:
    try:
        return int(_first(value))
    except (TypeError, ValueError):
        return None


def _when(value: Any) -> Optional[datetime]:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def listing_row(doc: dict) -> Optional[dict]:
    """One bid of a search answer as Orion keeps it, or None when it has no id or number."""
    bid_id = _int(doc.get("b_id"))
    number = _text(doc.get("b_bid_number"), 60)
    if not bid_id or not number:
        return None
    return {
        "bid_id": bid_id,
        "bid_number": number,
        "category": _text(doc.get("b_category_name"), 1000) or _text(doc.get("bd_category_name"), 1000),
        "quantity": _int(doc.get("b_total_quantity")),
        "ministry": _text(doc.get("ba_official_details_minName"), 200),
        "department": _text(doc.get("ba_official_details_deptName"), 200),
        "is_high_value": bool(_first(doc.get("is_high_value"))) if doc.get("is_high_value") is not None else None,
        "start_timestamp": _when(doc.get("final_start_date_sort")),
        "end_timestamp": _when(doc.get("final_end_date_sort")),
    }


@dataclass
class SearchPage:
    total: int
    rows: list[dict] = field(default_factory=list)


def search_answer(body: str) -> SearchPage:
    """GeM's answer to one search request. Raises GemError when it is not the shape its page expects."""
    try:
        data = json.loads(body)
    except ValueError as exc:
        if "captcha" in body.lower():
            raise GemError("GeM asked to prove this is a person (a captcha). The check stops here; try again later.", "captcha") from exc
        raise GemError("GeM answered the search with something that is not its usual data. Its page may have changed.") from exc
    if not isinstance(data, dict) or data.get("code") != 200:
        raise GemError(f"GeM refused the search (code {data.get('code') if isinstance(data, dict) else '?'}).", "refused")
    try:
        inner = data["response"]["response"]
        total = int(inner.get("numFound") or 0)
        docs = inner.get("docs") or []
    except (KeyError, TypeError, ValueError) as exc:
        raise GemError("GeM's search answer no longer has the fields Orion reads. Its page may have changed.") from exc
    rows = [row for row in (listing_row(doc) for doc in docs if isinstance(doc, dict)) if row]
    return SearchPage(total=total, rows=rows)


# --------------------------------------------------------------------------------------------- reading a bid document

# The consignee table (where the work is) ends at the first of these headings.
_CONSIGNEE_START = re.compile(r"Consignees?\s*/\s*Reporting Officer", re.I)
_CONSIGNEE_END = re.compile(
    r"Buyer Added Bid Specific|Minimum daily wage|Disclaimer|Bid Specific Additional Terms|Special terms|Pre-Qualification", re.I
)
_VALUE = re.compile(r"Estimated Bid Value[^0-9]{0,60}?([0-9][0-9,]*(?:\.[0-9]+)?)", re.I)
_EMD = re.compile(r"EMD Amount[^0-9]{0,30}?([0-9][0-9,]*(?:\.[0-9]+)?)", re.I)
_PERIOD = re.compile(r"Contract Period\s*([0-9]+\s*(?:Year|Month|Day)\s*\(?s?\)?(?:\s*[0-9]+\s*(?:Month|Day)\s*\(?s?\)?)*)", re.I)
_TURNOVER = re.compile(
    r"Minimum Average Annual Turnover of the bidder\s*(?:\(\s*For\s+[0-9]+\s+Years?\s*\))?\s*([0-9][0-9.,]*\s*(?:Lakh|Crore|Thousand)?)", re.I
)
# A consignee's address starts with its PIN code ("474005,INSTITUTE OF ..."); any six-digit number is the fallback.
_PIN_FIRST = re.compile(r"(?<![0-9])([1-9][0-9]{5})(?=\s*,)")
_PIN_ANY = re.compile(r"(?<![0-9])([1-9][0-9]{5})(?![0-9])")
_EXPERIENCE = re.compile(r"Past Experience Required for same/similar \w+\s*([0-9]+(?:\.[0-9]+)?)\s*Year", re.I)
_NOT_REQUIRED = re.compile(r"^\W*\w?\W*Required\s*No\b", re.I)
_EPBG_PERCENT = re.compile(r"ePBG Percentage\s*\(%\)\s*([0-9]+(?:\.[0-9]+)?)", re.I)
_EPBG_MONTHS = re.compile(r"Duration of ePBG required \(Months\)\.?\s*([0-9]+)", re.I)

LOCATION_LIMIT = 4000
DOCUMENT_TEXT_LIMIT = 30000


def _amount(match: Optional[re.Match]) -> Optional[Decimal]:
    if not match:
        return None
    try:
        value = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    return value if value >= 0 else None


def districts_for(text: str) -> list[str]:
    """The districts of the PIN codes in a consignee table, in the order they appear (India Post's data, as Orion's city list uses)."""
    import bharatpin

    pins = _PIN_FIRST.findall(text) or _PIN_ANY.findall(text)
    found: list[str] = []
    for pin in pins:
        try:
            district = bharatpin.get_district(pin)
        except Exception:  # noqa: BLE001 - a number that is not a PIN code is simply not one
            district = None
        if district and district not in found:
            found.append(district)
    return found[:20]


def _block(text: str, heading: str, next_heading: str) -> Optional[str]:
    """The text after ``heading`` up to ``next_heading`` (or 300 characters), or None when the heading is not there."""
    start = text.find(heading)
    if start < 0:
        return None
    start += len(heading)
    end = text.find(next_heading, start)
    return text[start:end if 0 <= end - start <= 600 else start + 300]


def security_fields(text: str) -> dict:
    """What a seller must put up to bid: the EMD (earnest money, with the bid) and the ePBG (a performance bank guarantee, if the
    contract is won). GeM's bid document says "Required No" under a heading that does not apply. None means it does not say."""
    emd = _block(text, "EMD Detail", "ePBG Detail")
    epbg = _block(text, "ePBG Detail", "EMD EXEMPTION")
    emd_amount = _amount(_EMD.search(emd)) if emd else None
    percent = _EPBG_PERCENT.search(epbg) if epbg else None
    months = _EPBG_MONTHS.search(epbg) if epbg else None
    return {
        "emd_required": None if emd is None else (False if _NOT_REQUIRED.search(emd) else True if emd_amount is not None else None),
        "epbg_required": None if epbg is None else (False if _NOT_REQUIRED.search(epbg) else True if percent else None),
        "epbg_percent": Decimal(percent.group(1)) if percent else None,
        "epbg_months": int(months.group(1)) if months else None,
    }


def document_text(pdf: bytes) -> str:
    """The text of a bid document, on one line. GeM's documents are in Hindi and English; only the English is kept, which is
    what the fields are read from. Raises GemError when it is not a PDF that can be read."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if not pdf.startswith(b"%PDF"):
        raise GemError("GeM sent something that is not a PDF for this bid's document.")
    try:
        reader = PdfReader(io.BytesIO(pdf))
        parts = [(page.extract_text() or "") for page in reader.pages]
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise GemError(f"The bid document could not be read ({type(exc).__name__}).") from exc
    text = re.sub(r"[^\x20-\x7e]", " ", " ".join(parts))
    return " ".join(text.split())


def document_fields(text: str) -> dict:
    """What a tender search filters and shows, read from a bid document's text. A field the document does not state is None.
    ``location_text`` is the consignee table (where the work is); when it cannot be found it is the whole document, so a city can
    still be looked for, and ``location_source`` says which."""
    start = _CONSIGNEE_START.search(text)
    location, source = None, None
    if start:
        end = _CONSIGNEE_END.search(text, start.end())
        stop = end.start() if end else start.end() + LOCATION_LIMIT
        location, source = text[start.start():min(stop, start.start() + LOCATION_LIMIT)], "consignee"
    if not location:
        location, source = text[:DOCUMENT_TEXT_LIMIT], "document"
    period = _PERIOD.search(text)
    turnover = _TURNOVER.search(text)
    experience = _EXPERIENCE.search(text)
    return {
        "estimated_value": _amount(_VALUE.search(text)),
        "emd_amount": _amount(_EMD.search(text)),
        "contract_period": " ".join(period.group(1).split())[:60] if period else None,
        "min_turnover": " ".join(turnover.group(1).split())[:60] if turnover else None,
        "experience_years": Decimal(experience.group(1)) if experience else None,
        **security_fields(text),
        "location_text": location,
        "location_source": source,
        "location_districts": districts_for(location) if source == "consignee" else [],
    }


# --------------------------------------------------------------------------------------------- talking to GeM


class GemSession:
    """One check's conversation with GeM: the listing page once (for its cookie and form token), then searches and documents,
    each at least ``gap`` seconds after the last. ``requests`` counts what was asked. Close it when done."""

    portal = "GeM"  # how messages name the site; a session for another portal sets its own

    def __init__(self, gap: Optional[float] = None, client: Optional[httpx.Client] = None) -> None:
        self.gap = request_gap_seconds() if gap is None else gap
        # The computer's own certificate store, as a browser here uses: the bundle httpx carries does not accept every chain that
        # reaches GeM from this office. Certificates are still checked.
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            timeout=httpx.Timeout(45.0, connect=15.0),
            follow_redirects=True,
            verify=ssl.create_default_context(),
        )
        self.token: Optional[str] = None
        self.requests = 0
        self._last = 0.0

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "GemSession":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _wait(self) -> None:
        pause = self._last + self.gap - time.monotonic()
        if pause > 0:
            time.sleep(pause)
        self._last = time.monotonic()
        self.requests += 1

    def _network_error(self, exc: httpx.HTTPError) -> GemError:
        """A failure to get any answer, in words a person can act on."""
        if isinstance(exc, httpx.ConnectTimeout):
            return GemError(f"Could not connect to {self.portal} in time. Its site may be down, or this computer offline.", "unreachable")
        if isinstance(exc, httpx.TimeoutException):
            return GemError(f"{self.portal} connected but sent nothing back in time; its site may be down or busy.", "unreachable")
        if isinstance(exc, httpx.ConnectError):
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                return GemError(f"{self.portal}'s certificate was not trusted by this computer, so Orion did not send anything.", "unreachable")
            return GemError(f"Could not reach {self.portal}. Is this computer online?", "unreachable")
        if isinstance(exc, httpx.RemoteProtocolError):
            return GemError(f"{self.portal} dropped the connection; its site may be busy.", "unreachable")
        return GemError(f"Could not reach {self.portal} ({type(exc).__name__}). Is this computer online?", "unreachable")

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        """One request, after the gap. A network blip (a timeout, a dropped connection) is tried again after RETRY_PAUSES; an
        answer from the portal, even a refusal, is never retried here."""
        for attempt, pause in enumerate((*RETRY_PAUSES, None), start=1):
            self._wait()
            try:
                response = self.client.request(method, url, **kwargs)
                break
            except httpx.HTTPError as exc:
                error = self._network_error(exc)
                if pause is None or "certificate" in str(error):
                    raise error from exc
                logger.info("%s: %s Trying again in %s s (attempt %s).", self.portal, error, pause, attempt + 1)
                time.sleep(pause)
        if response.status_code in (403, 429):
            raise GemError(f"{self.portal} refused Orion's request (HTTP {response.status_code}). The check stops; it tries again later.", "refused")
        if response.status_code in (404, 410):
            # One page or document GeM no longer has (a withdrawn bid): that item fails, the check goes on.
            raise GemError(f"{self.portal} no longer has this (HTTP {response.status_code}).", "missing")
        if response.status_code >= 400:
            raise GemError(f"{self.portal} answered HTTP {response.status_code}.", "unreachable" if response.status_code >= 500 else "refused")
        return response

    def open(self) -> None:
        """Load the listing page, which sets the cookie and carries the token its searches send back."""
        page = self._send("GET", LIST_PAGE)
        found = _TOKEN.search(page.text)
        if not found:
            if "captcha" in page.text.lower():
                raise GemError("GeM asked to prove this is a person (a captcha). The check stops here; try again later.", "captcha")
            raise GemError("GeM's bid listing page no longer looks the way Orion expects (no search token). Its page may have changed.")
        self.token = found.group(1)

    def search(self, text: str, bid_kind: str = "all", page: int = 1) -> SearchPage:
        """One page of ongoing bids for ``text``, newest first."""
        if self.token is None:
            self.open()
        payload = {
            "page": page,
            "param": {"searchBid": text, "searchType": "fullText"},
            "filter": {
                "bidStatusType": "ongoing_bids",
                "byType": bid_kind if bid_kind in BID_KINDS else "all",
                "highBidValue": "",
                "byEndDate": {"from": "", "to": ""},
                "sort": "Bid-Start-Date-Latest",
            },
        }
        try:
            response = self._send(
                "POST",
                DATA_URL,
                data={"payload": json.dumps(payload), "csrf_bd_gem_nk": self.token},
                headers={"X-Requested-With": "XMLHttpRequest", "Referer": LIST_PAGE},
            )
        except GemError as exc:
            if exc.kind == "missing":
                return SearchPage(total=0, rows=[])  # GeM answers a search that finds nothing with HTTP 404
            raise
        return search_answer(response.text)

    def document(self, bid_id: int) -> bytes:
        """A bid's public document (a PDF)."""
        response = self._send("GET", DOCUMENT_URL.format(bid_id=int(bid_id)), headers={"Referer": LIST_PAGE})
        content = response.content
        if len(content) > MAX_DOCUMENT_BYTES:
            raise GemError("The bid document is larger than Orion reads.", "refused")
        return content


def document_link(bid_id: int) -> str:
    return DOCUMENT_URL.format(bid_id=int(bid_id))
