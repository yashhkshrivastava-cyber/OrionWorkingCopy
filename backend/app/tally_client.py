"""Tally Prime HTTP XML client (localhost XML server)."""

from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import env

logger = logging.getLogger(__name__)

_INVALID_CHARREF = re.compile(
    r"&#(?:x0*[0-8bceBCEF]|0{0,7}(?:[0-8]|1[1-2]|1[4-9]|2[0-9]|3[01]));",
    re.IGNORECASE,
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

VOUCHER_REGISTER_TYPES = (
    "Sales",
    "Purchase",
    "Payment",
    "Receipt",
    "Journal",
    "Contra",
    "Credit Note",
    "Debit Note",
    "Payroll",
    "Attendance",
    "Stock Journal",
    "Delivery Note",
    "Receipt Note",
    "Physical Stock",
    "Sales Order",
    "Purchase Order",
    "Memorandum",
    "Reversing Journal",
)


class TallyError(RuntimeError):
    pass


def tally_settings() -> dict:
    return {
        "host": env("ORION_TALLY_HOST", "127.0.0.1"),
        "port": int(env("ORION_TALLY_PORT", "9000")),
        "company": env("ORION_TALLY_COMPANY", "").strip(),
        "from_date": env("ORION_TALLY_FROM_DATE", "2000-04-01").strip() or "2000-04-01",
        "to_date": env("ORION_TALLY_TO_DATE", "").strip(),
    }


def _base_url() -> str:
    settings = tally_settings()
    return f"http://{settings['host']}:{settings['port']}"


def sanitize_xml(text: str) -> str:
    text = _INVALID_CHARREF.sub("", text)
    return _CONTROL_CHARS.sub("", text)


def parse_xml(text: str) -> ET.Element:
    return ET.fromstring(sanitize_xml(text))


def local_tag(tag: str) -> str:
    return tag.split("}")[-1] if tag else ""


def _post(body: str, timeout: int = 180) -> str:
    req = Request(
        _base_url(),
        data=body.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except HTTPError as exc:
        raise TallyError(f"Tally Prime returned HTTP {exc.code} on {_base_url()}.") from exc
    except URLError as exc:
        raise TallyError(
            f"Cannot reach Tally Prime at {_base_url()}. "
            "Start Tally Prime and enable the XML/HTTP server on port 9000."
        ) from exc
    except TimeoutError as exc:
        raise TallyError(f"Tally Prime at {_base_url()} did not respond in time.") from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def _get(timeout: int = 10) -> str:
    req = Request(_base_url(), method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise TallyError(
            f"Cannot reach Tally Prime at {_base_url()}. "
            "Start Tally Prime and enable the XML/HTTP server on port 9000."
        ) from exc


def ping() -> dict:
    settings = tally_settings()
    body = _get()
    running = "tallyprime server is running" in body.lower() or "tally" in body.lower()
    return {
        "running": running,
        "host": settings["host"],
        "port": settings["port"],
        "message": body.strip(),
    }


def xml_escape(value: str) -> str:
    return html.escape(value, quote=True)


def collection_request(company: str, name: str, tally_type: str, fetch: str) -> str:
    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>{xml_escape(name)}</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        <SVCURRENTCOMPANY>{xml_escape(company)}</SVCURRENTCOMPANY>
      </STATICVARIABLES>
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="{xml_escape(name)}" ISMODIFY="No">
            <TYPE>{xml_escape(tally_type)}</TYPE>
            <FETCH>{xml_escape(fetch)}</FETCH>
          </COLLECTION>
        </TDLMESSAGE>
      </TDL>
    </DESC>
  </BODY>
</ENVELOPE>"""


def voucher_register_request(company: str, voucher_type: str, from_date: str, to_date: str) -> str:
    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Data</TYPE>
    <ID>Voucher Register</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        <SVCURRENTCOMPANY>{xml_escape(company)}</SVCURRENTCOMPANY>
        <SVFROMDATE TYPE="Date">{xml_escape(from_date)}</SVFROMDATE>
        <SVTODATE TYPE="Date">{xml_escape(to_date)}</SVTODATE>
        <VOUCHERTYPENAME>{xml_escape(voucher_type)}</VOUCHERTYPENAME>
      </STATICVARIABLES>
    </DESC>
  </BODY>
</ENVELOPE>"""


def list_companies_request() -> str:
    return """<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>List of Companies</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
      </STATICVARIABLES>
    </DESC>
  </BODY>
</ENVELOPE>"""


def companies_on_disk_request() -> str:
    return """<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>CmpOnDisk</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
      </STATICVARIABLES>
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="CmpOnDisk" ISMODIFY="No">
            <TYPE>Company On Disk</TYPE>
            <FETCH>Name, StartingFrom, EndingAt, BooksFrom, Number</FETCH>
          </COLLECTION>
        </TDLMESSAGE>
      </TDL>
    </DESC>
  </BODY>
</ENVELOPE>"""


def voucher_collection_request(company: str, from_date: str, to_date: str) -> str:
    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>AllVouchers</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        <SVCURRENTCOMPANY>{xml_escape(company)}</SVCURRENTCOMPANY>
        <SVFROMDATE TYPE="Date">{xml_escape(from_date)}</SVFROMDATE>
        <SVTODATE TYPE="Date">{xml_escape(to_date)}</SVTODATE>
      </STATICVARIABLES>
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="AllVouchers" ISMODIFY="No">
            <TYPE>Voucher</TYPE>
            <FETCH>Date, VoucherNumber, VoucherTypeName, PartyLedgerName, Narration, GUID, AllLedgerEntries, LedgerEntries, InventoryEntries, AllInventoryEntries, BillAllocations, CategoryAllocations</FETCH>
          </COLLECTION>
        </TDLMESSAGE>
      </TDL>
    </DESC>
  </BODY>
</ENVELOPE>"""


def child_text(el: ET.Element, *names: str) -> str | None:
    wanted = {name.upper() for name in names}
    for child in el:
        if local_tag(child.tag).upper() in wanted:
            text = (child.text or "").strip()
            if text:
                return text
    for child in el.iter():
        if child is el:
            continue
        if local_tag(child.tag).upper() in wanted:
            text = (child.text or "").strip()
            if text:
                return text
    return None


def direct_children(el: ET.Element, tag: str) -> list[ET.Element]:
    needle = tag.upper()
    return [child for child in list(el) if local_tag(child.tag).upper() == needle]


def first_present_lists(el: ET.Element, *tags: str) -> list[ET.Element]:
    """Tally often emits the same voucher lines under both FOO.LIST and ALLFOO.LIST.

    Use the first alias that has children. Concatenating aliases doubles every line.
    """
    for tag in tags:
        children = direct_children(el, tag)
        if children:
            return children
    return []


def _useful_inventory_entries(entries: list[ET.Element]) -> list[ET.Element]:
    return [
        entry
        for entry in entries
        if child_text(entry, "STOCKITEMNAME") or child_text(entry, "AMOUNT")
    ]


def element_name(el: ET.Element) -> str | None:
    attr = (el.get("NAME") or "").strip()
    if attr:
        return attr
    return child_text(el, "NAME")


def parse_bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in {"yes", "true", "1"}:
        return True
    if lowered in {"no", "false", "0"}:
        return False
    return None


def parse_amount(value: str | None) -> Decimal | None:
    if value is None:
        return None
    text = value.strip().replace(",", "")
    if not text:
        return None
    text = re.sub(r"/.*$", "", text).strip()
    text = re.sub(r"\s*(dr|cr)$", "", text, flags=re.IGNORECASE).strip()
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def parse_int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    try:
        return int(Decimal(value.strip()))
    except (InvalidOperation, ValueError):
        return None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    return None


def tally_date_param(value: str) -> str:
    parsed = parse_date(value)
    if parsed:
        return parsed.strftime("%Y%m%d")
    compact = re.sub(r"[^0-9]", "", value)
    if len(compact) == 8:
        return compact
    return value


def default_to_date() -> str:
    settings = tally_settings()
    if settings["to_date"]:
        return tally_date_param(settings["to_date"])
    return date.today().strftime("%Y%m%d")


def default_from_date() -> str:
    return tally_date_param(tally_settings()["from_date"])


def resolve_company() -> str:
    return companies_to_load()[0]


def _norm_company(name: str) -> str:
    text = " ".join(str(name or "").replace("&", " and ").lower().split())
    return text.replace(" and ", " and ")


def match_company_name(configured: str, names: list[str]) -> str | None:
    """Return the Tally company name that matches the configured filter.

    Exact / normalised match only. A shorter sibling such as
    "Prakash Security Service & Worker Contractor" must not match
    "... Contractor - (from 1-Apr-25)".
    """
    if not configured:
        return None
    if configured in names:
        return configured
    target = _norm_company(configured)
    if not target:
        return None
    exact = [name for name in names if _norm_company(name) == target]
    if exact:
        return exact[0]
    return None


def companies_to_load() -> list[str]:
    """Companies Tally can actually export: currently open, optionally filtered by .env."""
    configured = tally_settings()["company"]
    names = [row["name"] for row in list_companies() if row.get("name")]
    if configured:
        matched = match_company_name(configured, names)
        if matched:
            return [matched]
        disk_names = [row["name"] for row in list_companies_on_disk() if row.get("name")]
        disk_match = match_company_name(configured, disk_names)
        if disk_match:
            raise TallyError(
                f"Company {disk_match!r} is on disk but not open in Tally Prime. "
                "Press F1 (Select Company), open it, then load again."
            )
        raise TallyError(
            f"Company {configured!r} is not open in Tally Prime. Open now: {', '.join(names) or 'none'}."
        )
    if not names:
        closed = [row["name"] for row in list_companies_on_disk()]
        extra = f" On disk: {', '.join(closed)}." if closed else ""
        raise TallyError("Tally Prime is running but no company is open." + extra)
    return names


def list_companies() -> list[dict[str, Any]]:
    xml = _post(list_companies_request(), timeout=30)
    root = parse_xml(xml)
    rows = []
    for el in root.iter():
        if local_tag(el.tag).upper() != "COMPANY":
            continue
        name = element_name(el)
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "gst_on": parse_bool(child_text(el, "ISGSTON")),
                "gst_tax_unit_count": parse_int(child_text(el, "NUMGSTTAXUNIT")),
                "state_name": child_text(el, "REMOTECMPSTATE", "STATENAME"),
            }
        )
    return rows


def list_companies_on_disk() -> list[dict[str, Any]]:
    xml = _post(companies_on_disk_request(), timeout=30)
    root = parse_xml(xml)
    rows = []
    for el in root.iter():
        if local_tag(el.tag).upper() != "COMPANYONDISK":
            continue
        name = child_text(el, "NAME") or element_name(el)
        if not name:
            continue
        number = child_text(el, "CMPNUMSTR", "COMPANYNUMBER")
        rows.append(
            {
                "name": name,
                "starting_from": parse_date(child_text(el, "STARTINGFROM")),
                "ending_at": parse_date(child_text(el, "ENDINGAT")),
                "books_from": parse_date(child_text(el, "BOOKSFROM")),
                "company_number": (number or "").strip() or None,
            }
        )
    return rows


def fetch_collection(company: str, tally_type: str, fetch: str, tag: str) -> list[ET.Element]:
    xml = _post(collection_request(company, f"{tally_type}Coll", tally_type, fetch))
    root = parse_xml(xml)
    needle = tag.upper()
    return [el for el in root.iter() if local_tag(el.tag).upper() == needle]


def mapped_master(
    el: ET.Element,
    company: str,
    fields: dict[str, tuple[str, ...]],
) -> dict[str, Any] | None:
    name = element_name(el)
    if not name:
        return None
    row: dict[str, Any] = {"company_name": company, "name": name}
    for column, tags in fields.items():
        if column == "name":
            continue
        if column == "address":
            lines = [(c.text or "").strip() for c in el.iter() if local_tag(c.tag).upper() == "ADDRESS"]
            raw = ", ".join(line.strip(" ,") for line in lines if line.strip(" ,")) or None
        else:
            raw = child_text(el, *tags)
        if column.endswith("_balance") or column in {"gst_rate", "rate", "amount"}:
            row[column] = parse_amount(raw)
        elif column.startswith("is_") or column.endswith("_on"):
            row[column] = parse_bool(raw)
        elif column in {"decimal_places", "gst_tax_unit_count"}:
            row[column] = parse_int(raw)
        elif column.endswith("_from") or column.endswith("_date"):
            row[column] = parse_date(raw)
        else:
            row[column] = raw
    guid = row.get("tally_guid")
    row["natural_key"] = f"{company}|{guid or name}"
    return row


@dataclass
class ParsedVoucher:
    header: dict[str, Any]
    ledger_entries: list[dict[str, Any]] = field(default_factory=list)
    inventory_entries: list[dict[str, Any]] = field(default_factory=list)
    bill_allocations: list[dict[str, Any]] = field(default_factory=list)
    cost_centre_allocations: list[dict[str, Any]] = field(default_factory=list)


def _parse_voucher_element(el: ET.Element, company: str) -> ParsedVoucher | None:
    remote_id = (el.get("REMOTEID") or "").strip() or None
    vch_key = (el.get("VCHKEY") or "").strip() or None
    vch_type = (el.get("VCHTYPE") or "").strip() or child_text(el, "VOUCHERTYPENAME")
    guid = child_text(el, "GUID")
    number = child_text(el, "VOUCHERNUMBER")
    voucher_date = parse_date(child_text(el, "DATE"))
    identity = remote_id or guid or "|".join(
        part for part in (vch_type, number, voucher_date.isoformat() if voucher_date else "") if part
    )
    if not identity:
        return None
    natural_key = f"{company}|{identity}"
    header = {
        "company_name": company,
        "natural_key": natural_key,
        "tally_guid": guid,
        "remote_id": remote_id,
        "vch_key": vch_key,
        "voucher_type_name": vch_type,
        "voucher_number": number,
        "voucher_date": voucher_date,
        "effective_date": parse_date(child_text(el, "EFFECTIVEDATE")),
        "party_ledger_name": child_text(el, "PARTYLEDGERNAME"),
        "narration": child_text(el, "NARRATION"),
        "reference": child_text(el, "REFERENCE"),
        "persisted_view": child_text(el, "PERSISTEDVIEW") or (el.get("OBJVIEW") or "").strip() or None,
        "is_invoice": parse_bool(child_text(el, "ISINVOICE")),
        "is_optional": parse_bool(child_text(el, "ISOPTIONAL")),
    }
    parsed = ParsedVoucher(header=header)

    ledger_lists = first_present_lists(el, "ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST")
    for index, entry in enumerate(ledger_lists, start=1):
        ledger_name = child_text(entry, "LEDGERNAME")
        line_key = f"{natural_key}|L|{index}"
        parsed.ledger_entries.append(
            {
                "company_name": company,
                "natural_key": line_key,
                "voucher_natural_key": natural_key,
                "line_no": index,
                "ledger_name": ledger_name,
                "amount": parse_amount(child_text(entry, "AMOUNT")),
                "is_deemed_positive": parse_bool(child_text(entry, "ISDEEMEDPOSITIVE")),
                "is_party_ledger": parse_bool(child_text(entry, "ISPARTYLEDGER")),
            }
        )
        for bill_index, bill in enumerate(direct_children(entry, "BILLALLOCATIONS.LIST"), start=1):
            parsed.bill_allocations.append(
                {
                    "company_name": company,
                    "natural_key": f"{line_key}|B|{bill_index}",
                    "voucher_natural_key": natural_key,
                    "ledger_entry_natural_key": line_key,
                    "line_no": bill_index,
                    "bill_name": child_text(bill, "NAME", "BILLNAME"),
                    "bill_type": child_text(bill, "BILLTYPE"),
                    "amount": parse_amount(child_text(bill, "AMOUNT")),
                }
            )
        cc_index = 0
        for category in direct_children(entry, "CATEGORYALLOCATIONS.LIST"):
            category_name = child_text(category, "CATEGORY", "NAME")
            centres = direct_children(category, "COSTCENTREALLOCATIONS.LIST")
            if not centres:
                cc_index += 1
                parsed.cost_centre_allocations.append(
                    {
                        "company_name": company,
                        "natural_key": f"{line_key}|C|{cc_index}",
                        "voucher_natural_key": natural_key,
                        "ledger_entry_natural_key": line_key,
                        "line_no": cc_index,
                        "category_name": category_name,
                        "cost_centre_name": None,
                        "amount": parse_amount(child_text(category, "AMOUNT")),
                    }
                )
                continue
            for centre in centres:
                cc_index += 1
                parsed.cost_centre_allocations.append(
                    {
                        "company_name": company,
                        "natural_key": f"{line_key}|C|{cc_index}",
                        "voucher_natural_key": natural_key,
                        "ledger_entry_natural_key": line_key,
                        "line_no": cc_index,
                        "category_name": category_name,
                        "cost_centre_name": child_text(centre, "NAME"),
                        "amount": parse_amount(child_text(centre, "AMOUNT")),
                    }
                )

    inventory_lists = _useful_inventory_entries(
        first_present_lists(el, "ALLINVENTORYENTRIES.LIST", "INVENTORYENTRIES.LIST")
    )
    if not inventory_lists:
        # In/out are complementary transfer views, not aliases of ALLINVENTORYENTRIES.
        inventory_lists = _useful_inventory_entries(
            direct_children(el, "INVENTORYENTRIESIN.LIST")
            + direct_children(el, "INVENTORYENTRIESOUT.LIST")
        )
    for index, entry in enumerate(inventory_lists, start=1):
        parsed.inventory_entries.append(
            {
                "company_name": company,
                "natural_key": f"{natural_key}|I|{index}",
                "voucher_natural_key": natural_key,
                "line_no": index,
                "stock_item_name": child_text(entry, "STOCKITEMNAME"),
                "godown_name": child_text(entry, "GODOWNNAME"),
                "actual_qty": child_text(entry, "ACTUALQTY"),
                "billed_qty": child_text(entry, "BILLEDQTY"),
                "rate": parse_amount(child_text(entry, "RATE")),
                "amount": parse_amount(child_text(entry, "AMOUNT")),
            }
        )
    return parsed


def _ingest_voucher_xml(xml: str, company: str, found: dict[str, ParsedVoucher]) -> None:
    try:
        root = parse_xml(xml)
    except ET.ParseError:
        logger.exception("Could not parse Tally vouchers for %s", company)
        return
    for el in root.iter():
        if local_tag(el.tag).upper() != "VOUCHER":
            continue
        parsed = _parse_voucher_element(el, company)
        if parsed:
            found[parsed.header["natural_key"]] = parsed


def voucher_type_names(company: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for el in fetch_collection(company, "VoucherType", "Name, Parent", "VOUCHERTYPE"):
        name = element_name(el)
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names or list(VOUCHER_REGISTER_TYPES)


def fetch_vouchers(company: str | None = None) -> list[ParsedVoucher]:
    company = company or resolve_company()
    from_date = default_from_date()
    to_date = default_to_date()
    found: dict[str, ParsedVoucher] = {}
    for voucher_type in voucher_type_names(company):
        xml = _post(voucher_register_request(company, voucher_type, from_date, to_date))
        _ingest_voucher_xml(xml, company, found)
    try:
        xml = _post(voucher_collection_request(company, from_date, to_date), timeout=300)
        _ingest_voucher_xml(xml, company, found)
    except Exception:
        logger.exception("Could not fetch Tally voucher collection for %s", company)
    return list(found.values())


class TallySession:
    """Caches company + voucher XML for one load/refresh so child tables reuse it."""

    def __init__(self):
        self.companies = companies_to_load()
        self.company = self.companies[0]
        self._vouchers: list[ParsedVoucher] | None = None
        self._masters: dict[str, list[dict[str, Any]]] = {}

    def vouchers(self) -> list[ParsedVoucher]:
        if self._vouchers is None:
            found: dict[str, ParsedVoucher] = {}
            for company in self.companies:
                for parsed in fetch_vouchers(company):
                    found[parsed.header["natural_key"]] = parsed
            self._vouchers = list(found.values())
        return self._vouchers

    def masters(self, key: str, tally_type: str, fetch: str, tag: str, fields: dict[str, tuple[str, ...]]) -> list[dict[str, Any]]:
        if key not in self._masters:
            rows = []
            for company in self.companies:
                for el in fetch_collection(company, tally_type, fetch, tag):
                    row = mapped_master(el, company, fields)
                    if row:
                        rows.append(row)
            self._masters[key] = rows
        return self._masters[key]
