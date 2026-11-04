"""Tenders: saved searches for bids on GeM, a check that finds the bids each one wants, and what people decide about them.

The only writer of ``tender_search``, ``tender_bid``, ``tender_match`` and ``tender_run``.

A search names tender types (words matched against the bid's GeM category, such as "security" or "manpower outsourcing"), cities
(where the work must be), the kind of bid and a range of estimated value. A check runs every active search:

1. it asks GeM for ongoing bids, newest first: by city when the search names cities (a city's list is short, and GeM finds the
   city in the bid's consignee address), otherwise by each tender type; at most ``MAX_PAGES`` pages of 10 for each question;
2. it keeps the bids whose category contains one of the tender types;
3. it reads the public bid document of each kept bid it has not read before, for the estimated value, the EMD, the contract
   period, the turnover and experience asked for, and where the work is (at most ``MAX_DOCUMENTS`` documents a check);
4. it keeps a bid for the search when the work is in one of its cities (from the document: the district of the consignee's PIN
   code, else the city's name in the consignee table; when the document could not be read,
   the city GeM matched is used and the bid is marked "location not confirmed") and its value is in range (a bid that states no
   value is kept only if the search says so). Each new one is a match with the status "new".

A person then shortlists or dismisses a match. Editing a search clears its "new" matches (they are found again under the new
terms); shortlisted and dismissed ones stay. Bids that closed more than ``KEEP_CLOSED_DAYS`` ago are removed unless shortlisted.

Checks run by themselves every ``ORION_TENDERS_CHECK_HOURS`` (default 6; 0 turns the schedule off), and when a person asks. One at
a time: a second is refused while one runs. Network waits never hold a database connection.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional

from app import gem_client, mptenders_client
from app.config import env
from app.database import db_cursor
from app.gem_client import GemError, GemSession

logger = logging.getLogger(__name__)

SCHEMA = "orion_ods"
MAX_PAGES = 300  # of 10 bids: a safety stop for one question in one check (the lookback normally ends it long before)
MAX_DOCUMENTS = 300  # bid documents read in one check, closing soonest first; the rest are read by the next
DEFAULT_LOOKBACK_DAYS = 90  # how far back a question follows GeM's list: bids published in this many days (still open)
KEEP_CLOSED_DAYS = 30
PROGRESS_EVERY = 3.0  # seconds between writes of a running check's progress
RETRY_AFTER = timedelta(hours=24)  # a bid document that could not be read is tried again after this
STALE_RUN = timedelta(hours=2)  # a 'running' check older than this is taken to have died with its process
FAILURES_BEFORE_STOP = 3
MAX_TERMS = 20
#: Cities a search may name: enough for every district of the largest state (Uttar Pradesh has 75), so "all the cities of a state" can be chosen.
MAX_CITIES = 100
MAX_TERM_CHARS = 60
MAX_NAME_CHARS = 80
STATUSES = ("new", "shortlisted", "dismissed")
# The portals, kept apart: a search belongs to one, and each has its own checks, lock, status and schedule.
PORTALS = ("gem", "mptenders")
PORTAL_NAMES = {"gem": "GeM", "mptenders": "MP Tenders"}
KINDS = {"gem": ("service", "product", "all"), "mptenders": ("service", "product", "works", "all")}
# A search's kind of bid, as MP Tenders' Tender Category says it ('product' is Goods; 'all' takes any).
MP_CATEGORY_FOR_KIND = {"service": "services", "product": "goods", "works": "works"}
DEFAULT_HOURS = 6
FIRST_CHECK_DELAY_SECONDS = 600

_TERM_OK = re.compile(r"^[\w .,&()/'-]+$")
_locks = {portal: threading.Lock() for portal in PORTALS}
_next_check: Optional[datetime] = None


class TenderError(ValueError):
    """Something a person asked for that cannot be done, in words for them."""


class CheckBusy(RuntimeError):
    """A check is already running."""


# ------------------------------------------------------------------------------------------------- matching (no database)


def clean_terms(values: Optional[Iterable[Any]], what: str, limit: int = MAX_TERMS) -> list[str]:
    """Tender types or cities as a person typed them: trimmed, one space between words, no repeats (ignoring case)."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values or []:
        term = " ".join(str(value or "").split())
        if not term:
            continue
        if len(term) > MAX_TERM_CHARS:
            raise TenderError(f"A {what} can be at most {MAX_TERM_CHARS} characters: {term[:20]}...")
        if not _TERM_OK.match(term):
            raise TenderError(f"{term!r} has characters a {what} cannot have.")
        if term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    if len(out) > limit:
        raise TenderError(f"A search can have at most {limit} {what.replace('city', 'citie')}s.")
    return out


def _pattern(term: str, whole_word: bool) -> re.Pattern:
    words = r"\s+".join(re.escape(part) for part in term.split())
    return re.compile(r"\b" + words + (r"\b" if whole_word else ""), re.I)


def type_matches(category: Optional[str], tender_types: list[str]) -> bool:
    """Whether a bid's category contains one of the tender types. A type matches at the start of a word ("guard" finds
    "Guards"), anywhere in the category. No types means every category."""
    if not tender_types:
        return True
    text = category or ""
    return any(_pattern(term, whole_word=False).search(text) for term in tender_types)


def city_in(text: Optional[str], cities: list[str]) -> Optional[str]:
    """The first of ``cities`` named in ``text`` as a whole word, or None."""
    if not text:
        return None
    for city in cities:
        if _pattern(city, whole_word=True).search(text):
            return city
    return None


def _place_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"\([^)]*\)", "", name.lower()))


def same_place(city: str, district: str) -> bool:
    """A city as a person typed it and a district from a PIN code: the same name, allowing a small difference in spelling
    (India Post writes "Visakhapatanam")."""
    a, b = _place_key(city), _place_key(district)
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.88)


def city_of(bid: dict, cities: list[str]) -> Optional[str]:
    """Which of ``cities`` a bid's work is in, from its read document: the district of a consignee's PIN code first, then the
    city's name in the consignee table (or the document, when the table could not be found)."""
    for district in bid.get("location_districts") or []:
        for city in cities:
            if same_place(city, district):
                return city
    return city_in(bid.get("location_text"), cities)


def value_ok(value: Optional[Decimal], min_value: Optional[Decimal], max_value: Optional[Decimal], include_unpriced: bool) -> bool:
    if value is None:
        return include_unpriced or (min_value is None and max_value is None)
    if min_value is not None and value < min_value:
        return False
    if max_value is not None and value > max_value:
        return False
    return True


def decide(search: dict, bid: dict, hints: set[str]) -> Optional[dict]:
    """Whether ``bid`` belongs to ``search``, and with which city: {'matched_city', 'location_confirmed'} or None.
    ``hints`` are the cities whose GeM search returned the bid in this check."""
    if not type_matches(bid.get("match_text") or bid.get("category"), search["tender_types"]):
        return None
    wanted_category = MP_CATEGORY_FOR_KIND.get(search["bid_kind"])
    if bid.get("source") == "mptenders" and wanted_category and bid.get("tender_category"):
        if bid["tender_category"].strip().lower() != wanted_category:
            return None
    if not value_ok(bid.get("estimated_value"), search["min_value"], search["max_value"], search["include_unpriced"]):
        return None
    cities = search["cities"]
    if not cities:
        return {"matched_city": None, "location_confirmed": False}
    if bid.get("document_status") == "read":
        found = city_of(bid, cities)
        return {"matched_city": found, "location_confirmed": True} if found else None
    guessed = next((city for city in cities if city.lower() in {hint.lower() for hint in hints}), None)
    return {"matched_city": guessed, "location_confirmed": False} if guessed else None


def questions(search: dict) -> list[tuple[str, str]]:
    """What to ask GeM for one search: (text, bid kind) pairs. By city when it names cities, else by tender type."""
    terms = search["cities"] or search["tender_types"]
    return [(term, search["bid_kind"]) for term in terms]


# ------------------------------------------------------------------------------------------------- saved searches


def _search_row(row: tuple, columns: list[str]) -> dict:
    item = dict(zip(columns, row))
    for key in ("min_value", "max_value"):
        item[key] = Decimal(item[key]) if item[key] is not None else None
    item["tender_types"] = list(item.get("tender_types") or [])
    item["cities"] = list(item.get("cities") or [])
    return item


_SEARCH_COLUMNS = (
    "search_id, portal, name, tender_types, cities, bid_kind, min_value, max_value, include_unpriced, is_active, created_by, "
    "created_timestamp, last_updated_timestamp"
)


def portal_of(value: Any) -> str:
    if value not in PORTALS:
        raise TenderError("The portal must be gem or mptenders.")
    return value


def _clean_search(data: dict, portal: str) -> dict:
    name = " ".join(str(data.get("name") or "").split())
    if not name:
        raise TenderError("Give the search a name.")
    if len(name) > MAX_NAME_CHARS:
        raise TenderError(f"The name can be at most {MAX_NAME_CHARS} characters.")
    tender_types = clean_terms(data.get("tender_types"), "tender type")
    cities = clean_terms(data.get("cities"), "city", MAX_CITIES)
    if not tender_types and not cities:
        raise TenderError("Name at least one tender type or one city, or the search would ask for everything.")
    bid_kind = data.get("bid_kind") or "service"
    if bid_kind not in KINDS[portal]:
        raise TenderError(f"On {PORTAL_NAMES[portal]} the kind of bid must be one of: {', '.join(KINDS[portal])}.")
    if portal == "mptenders" and not tender_types:
        # MP Tenders is read organisation by organisation; without a tender type every one of its thousands of tenders would
        # have to be opened to see where it is.
        raise TenderError("A search on MP Tenders needs at least one tender type.")
    values = {}
    for key, label in (("min_value", "minimum value"), ("max_value", "maximum value")):
        raw = data.get(key)
        if raw in (None, ""):
            values[key] = None
            continue
        try:
            values[key] = Decimal(str(raw))
        except (ArithmeticError, ValueError) as exc:
            raise TenderError(f"The {label} must be a number of rupees.") from exc
        if values[key] < 0 or values[key] >= Decimal("1e14"):
            raise TenderError(f"The {label} must be between 0 and 99,999,999,999,999.")
    if values["min_value"] is not None and values["max_value"] is not None and values["min_value"] > values["max_value"]:
        raise TenderError("The minimum value is more than the maximum.")
    return {
        "name": name,
        "tender_types": tender_types,
        "cities": cities,
        "bid_kind": bid_kind,
        "min_value": values["min_value"],
        "max_value": values["max_value"],
        "include_unpriced": bool(data.get("include_unpriced", True)),
        "is_active": bool(data.get("is_active", True)),
        "portal": portal,
    }


def list_searches(portal: Optional[str] = None) -> list[dict]:
    """Every search (of one portal), with how many of its matches are new and shortlisted among bids still open."""
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT {', '.join('s.' + c.strip() for c in _SEARCH_COLUMNS.split(','))},
                   COUNT(*) FILTER (WHERE m.status = 'new' AND b.end_timestamp > now()) AS new_count,
                   COUNT(*) FILTER (WHERE m.status = 'shortlisted' AND b.end_timestamp > now()) AS shortlisted_count,
                   COUNT(*) FILTER (WHERE b.end_timestamp > now()) AS open_count
              FROM {SCHEMA}.tender_search s
              LEFT JOIN {SCHEMA}.tender_match m ON m.search_id = s.search_id
              LEFT JOIN {SCHEMA}.tender_bid b ON b.bid_id = m.bid_id
             WHERE %(portal)s::TEXT IS NULL OR s.portal = %(portal)s
             GROUP BY s.search_id
             ORDER BY s.is_active DESC, lower(s.name)
            """,
            {"portal": portal},
        )
        columns = [c.name for c in cur.description]
        return [_search_row(row, columns) for row in cur.fetchall()]


def get_search(search_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute(f"SELECT {_SEARCH_COLUMNS} FROM {SCHEMA}.tender_search WHERE search_id = %s", (search_id,))
        row = cur.fetchone()
        if not row:
            raise LookupError("No such search")
        return _search_row(row, [c.name for c in cur.description])


def create_search(data: dict, user_id: Optional[int]) -> dict:
    clean = _clean_search(data, portal_of(data.get("portal") or "gem"))
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            INSERT INTO {SCHEMA}.tender_search (portal, name, tender_types, cities, bid_kind, min_value, max_value, include_unpriced,
                                                is_active, created_by)
            VALUES (%(portal)s, %(name)s, %(tender_types)s, %(cities)s, %(bid_kind)s, %(min_value)s, %(max_value)s, %(include_unpriced)s,
                    %(is_active)s, %(user)s)
            RETURNING search_id
            """,
            {**clean, "user": user_id},
        )
        search_id = cur.fetchone()[0]
    return get_search(search_id)


def update_search(search_id: int, data: dict) -> dict:
    """Save a search's new terms (its portal stays). Its "new" matches were found under the old ones, so they go; shortlisted and
    dismissed stay."""
    clean = _clean_search(data, get_search(search_id)["portal"])
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE {SCHEMA}.tender_search
               SET name = %(name)s, tender_types = %(tender_types)s, cities = %(cities)s, bid_kind = %(bid_kind)s,
                   min_value = %(min_value)s, max_value = %(max_value)s, include_unpriced = %(include_unpriced)s,
                   is_active = %(is_active)s, last_updated_timestamp = CURRENT_TIMESTAMP
             WHERE search_id = %(search_id)s
            """,
            {**clean, "search_id": search_id},
        )
        if cur.rowcount == 0:
            raise LookupError("No such search")
        cur.execute(f"DELETE FROM {SCHEMA}.tender_match WHERE search_id = %s AND status = 'new'", (search_id,))
    return get_search(search_id)


def delete_search(search_id: int) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(f"DELETE FROM {SCHEMA}.tender_search WHERE search_id = %s", (search_id,))
        if cur.rowcount == 0:
            raise LookupError("No such search")


# ------------------------------------------------------------------------------------------------- what was found

_BID_COLUMNS = (
    "bid_id", "bid_number", "category", "quantity", "ministry", "department", "is_high_value", "start_timestamp", "end_timestamp",
    "estimated_value", "emd_amount", "emd_required", "epbg_required", "epbg_percent", "epbg_months", "contract_period", "min_turnover",
    "experience_years", "location_source", "location_districts", "source", "source_ref", "title", "reference", "work_description",
    "tender_category", "tender_fee", "tender_fee_total", "tender_fee_exempt", "emd_exempt", "document_status", "document_error",
)


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def search_bids(search_id: int, status: str = "new", include_closed: bool = False) -> list[dict]:
    """The bids a search found, soonest closing first. ``status`` is one of STATUSES or 'all'."""
    if status not in (*STATUSES, "all"):
        raise TenderError("Unknown status.")
    where = ["m.search_id = %s"]
    args: list[Any] = [search_id]
    if status != "all":
        where.append("m.status = %s")
        args.append(status)
    if not include_closed:
        where.append("b.end_timestamp > now()")
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT {', '.join('b.' + c for c in _BID_COLUMNS)}, m.matched_city, m.location_confirmed, m.status,
                   m.status_timestamp, m.first_matched_timestamp,
                   CASE WHEN b.location_source = 'consignee' THEN left(b.location_text, 600) END AS location_excerpt
              FROM {SCHEMA}.tender_match m
              JOIN {SCHEMA}.tender_bid b ON b.bid_id = m.bid_id
             WHERE {' AND '.join(where)}
             ORDER BY b.end_timestamp ASC NULLS LAST, b.bid_id DESC
             LIMIT 5000
            """,
            args,
        )
        columns = [c.name for c in cur.description]
        rows = [{key: _plain(value) for key, value in zip(columns, row)} for row in cur.fetchall()]
    for row in rows:
        if row["source"] == "mptenders":
            # The portal's links are good only in the visit that made them: a person opens the portal and finds the Tender ID.
            row["document_url"] = row["apply_url"] = mptenders_client.APP_URL
        else:
            row["document_url"] = gem_client.document_link(row["bid_id"])
            row["apply_url"] = gem_client.SELLER_SIGN_IN_URL
    return rows


def set_status(search_id: int, bid_id: int, status: str, user_id: Optional[int]) -> dict:
    if status not in STATUSES:
        raise TenderError("The status must be new, shortlisted or dismissed.")
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE {SCHEMA}.tender_match SET status = %s, status_by = %s, status_timestamp = CURRENT_TIMESTAMP
             WHERE search_id = %s AND bid_id = %s
            """,
            (status, user_id, search_id, bid_id),
        )
        if cur.rowcount == 0:
            raise LookupError("No such bid in this search")
    return {"search_id": search_id, "bid_id": bid_id, "status": status}


# ------------------------------------------------------------------------------------------------- the check


@dataclass
class RunStats:
    searches: int = 0
    bids_seen: int = 0
    bids_new: int = 0
    documents_read: int = 0
    matches_new: int = 0
    notes: list[str] = field(default_factory=list)
    run_id: Optional[int] = None
    seen: set[int] = field(default_factory=set)
    documents_left: int = field(default_factory=lambda: MAX_DOCUMENTS)
    documents_skipped: int = 0
    last_report: float = 0.0
    current_search_id: Optional[int] = None
    prefix: str = ""  # "Cleaning (2 of 5): ", put before what is being done
    sessions: list = field(default_factory=list)  # every portal's session in this check, for the count of requests
    other_seen: int = 0  # tenders looked at that are not kept (MP Tenders' that fit no search)


def _store_listing(rows: list[dict]) -> int:
    """Insert or refresh bids from a search answer. Returns how many were new to Orion."""
    if not rows:
        return 0
    new = 0
    with db_cursor(commit=True) as cur:
        for row in rows:
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.tender_bid (bid_id, source, source_ref, bid_number, category, quantity, ministry, department,
                                                 is_high_value, start_timestamp, end_timestamp)
                VALUES (%(bid_id)s, 'gem', %(bid_id)s::TEXT, %(bid_number)s, %(category)s, %(quantity)s, %(ministry)s, %(department)s,
                        %(is_high_value)s, %(start_timestamp)s, %(end_timestamp)s)
                ON CONFLICT (bid_id) DO UPDATE
                   SET bid_number = EXCLUDED.bid_number, category = EXCLUDED.category, quantity = EXCLUDED.quantity,
                       ministry = EXCLUDED.ministry, department = EXCLUDED.department, is_high_value = EXCLUDED.is_high_value,
                       start_timestamp = EXCLUDED.start_timestamp, end_timestamp = EXCLUDED.end_timestamp,
                       last_seen_timestamp = CURRENT_TIMESTAMP
                RETURNING (xmax = 0) AS inserted
                """,
                row,
            )
            new += 1 if cur.fetchone()[0] else 0
    return new


def _bids(bid_ids: Iterable[int]) -> dict[int, dict]:
    ids = list(bid_ids)
    if not ids:
        return {}
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT bid_id, category, estimated_value, location_text, document_status, document_read_timestamp, location_districts,
                       reader_version, end_timestamp, source, tender_category, concat_ws(' ', title, category, work_description)
                  FROM {SCHEMA}.tender_bid WHERE bid_id = ANY(%s)""",
            (ids,),
        )
        return {
            row[0]: {"bid_id": row[0], "category": row[1], "estimated_value": row[2], "location_text": row[3], "document_status": row[4],
                     "document_read_timestamp": row[5], "location_districts": list(row[6] or []),
                     "reader_version": row[7], "end_timestamp": row[8], "source": row[9], "tender_category": row[10],
                     "match_text": row[11]}
            for row in cur.fetchall()
        }


def needs_reading(bid: dict, now: datetime) -> bool:
    """A document never read, or one that failed more than RETRY_AFTER ago (GeM or the network may have been having a bad moment)."""
    if bid["document_status"] == "pending":
        return True
    if bid["document_status"] == "read" and (bid.get("reader_version") or 1) < gem_client.READER_VERSION:
        return True  # read before Orion learnt to read something it now shows
    read_at = bid.get("document_read_timestamp")
    return bid["document_status"] == "failed" and (read_at is None or now - read_at >= RETRY_AFTER)


def _store_document(bid_id: int, fields: Optional[dict], error: Optional[str]) -> None:
    with db_cursor(commit=True) as cur:
        if fields is None:
            cur.execute(
                f"""UPDATE {SCHEMA}.tender_bid SET document_status = 'failed', document_error = %s, document_read_timestamp = CURRENT_TIMESTAMP
                     WHERE bid_id = %s""",
                ((error or "")[:300], bid_id),
            )
            return
        cur.execute(
            f"""
            UPDATE {SCHEMA}.tender_bid
               SET estimated_value = %(estimated_value)s, emd_amount = %(emd_amount)s, contract_period = %(contract_period)s,
                   min_turnover = %(min_turnover)s, experience_years = %(experience_years)s, location_text = %(location_text)s,
                   location_source = %(location_source)s, location_districts = %(location_districts)s, emd_required = %(emd_required)s,
                   epbg_required = %(epbg_required)s, epbg_percent = %(epbg_percent)s, epbg_months = %(epbg_months)s,
                   reader_version = %(reader_version)s, document_status = 'read', document_error = NULL,
                   document_read_timestamp = CURRENT_TIMESTAMP
             WHERE bid_id = %(bid_id)s
            """,
            {**fields, "bid_id": bid_id, "reader_version": gem_client.READER_VERSION},
        )


def _store_matches(search_id: int, found: dict[int, dict], saved_at: Optional[datetime] = None) -> int:
    """Record what a search found. New bids become "new" matches; a match already there keeps its status but takes the newer
    location. Returns how many were new.

    A check takes minutes, and the search may be deleted or changed meanwhile: then nothing is recorded for it (what was found
    was found for terms that no longer exist; a changed search is checked under its new terms next time). The row is locked
    against deletion while its matches are written."""
    new = 0
    with db_cursor(commit=True) as cur:
        cur.execute(f"SELECT last_updated_timestamp FROM {SCHEMA}.tender_search WHERE search_id = %s FOR KEY SHARE", (search_id,))
        row = cur.fetchone()
        if not row or (saved_at is not None and row[0] != saved_at):
            logger.info("Tender search %s was deleted or changed during the check; its results are not recorded", search_id)
            return 0
        for bid_id, how in found.items():
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.tender_match (search_id, bid_id, matched_city, location_confirmed)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (search_id, bid_id) DO UPDATE
                   SET matched_city = EXCLUDED.matched_city, location_confirmed = EXCLUDED.location_confirmed
                RETURNING (xmax = 0) AS inserted
                """,
                (search_id, bid_id, how["matched_city"], how["location_confirmed"]),
            )
            new += 1 if cur.fetchone()[0] else 0
    return new


def _forget_old_bids() -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            DELETE FROM {SCHEMA}.tender_bid b
             WHERE b.end_timestamp < now() - make_interval(days => %s)
               AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.tender_match m WHERE m.bid_id = b.bid_id AND m.status = 'shortlisted')
            """,
            (KEEP_CLOSED_DAYS,),
        )


def _start_run(portal: str, trigger: str, user_id: Optional[int]) -> int:
    """Record the start of a check, unless another process has one running (the lock above is only this process's: a deploy
    briefly runs two servers, and a script can run a check too). A run older than STALE_RUN is not believed."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            INSERT INTO {SCHEMA}.tender_run (portal, trigger, started_by)
            SELECT %s, %s, %s
             WHERE NOT EXISTS (SELECT 1 FROM {SCHEMA}.tender_run
                                WHERE portal = %s AND status = 'running' AND started_timestamp > now() - make_interval(secs => %s))
            RETURNING run_id
            """,
            (portal, trigger, user_id, portal, STALE_RUN.total_seconds()),
        )
        row = cur.fetchone()
    if not row:
        raise CheckBusy(f"A {PORTAL_NAMES[portal]} check is already running.")
    return row[0]


def _finish_run(run_id: int, stats: RunStats, requests: int, error: Optional[str]) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE {SCHEMA}.tender_run
               SET status = %s, finished_timestamp = CURRENT_TIMESTAMP, searches = %s, requests = %s, bids_seen = %s, bids_new = %s,
                   documents_read = %s, matches_new = %s, note = %s, error = %s, progress = NULL, current_search_id = NULL
             WHERE run_id = %s
            """,
            ("failed" if error else "succeeded", stats.searches, requests, stats.bids_seen, stats.bids_new, stats.documents_read,
             stats.matches_new, " ".join(stats.notes)[:1000] or None, (error or "")[:1000] or None, run_id),
        )


def active_searches(portal: str) -> list[dict]:
    return [search for search in list_searches(portal) if search["is_active"]]


def _report(stats: RunStats, session: GemSession, progress: str, force: bool = False) -> None:
    """Write how far the check has got to its run, at most every PROGRESS_EVERY seconds, so the page can show it."""
    if stats.run_id is None:
        return
    now = time.monotonic()
    if not force and now - stats.last_report < PROGRESS_EVERY:
        return
    stats.last_report = now
    stats.bids_seen = len(stats.seen) + stats.other_seen
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                f"""UPDATE {SCHEMA}.tender_run SET requests = %s, bids_seen = %s, bids_new = %s, documents_read = %s, matches_new = %s,
                           progress = %s, current_search_id = %s
                     WHERE run_id = %s AND status = 'running'""",
                (sum(s.requests for s in stats.sessions) if stats.sessions else session.requests, stats.bids_seen, stats.bids_new,
                 stats.documents_read, stats.matches_new,
                 (stats.prefix + progress)[:300], stats.current_search_id, stats.run_id),
            )
    except Exception:  # noqa: BLE001 - progress is a courtesy; the check must not fail for it
        logger.debug("Could not record the tender check's progress", exc_info=True)


def question_key(text: str, bid_kind: str) -> tuple[str, str]:
    return " ".join(text.lower().split()), bid_kind


def _coverage(key: tuple[str, str]) -> Optional[datetime]:
    """How far back GeM's list for a question was last followed to its end (None: never all the way)."""
    with db_cursor() as cur:
        cur.execute(f"SELECT complete_from FROM {SCHEMA}.tender_question WHERE question = %s AND bid_kind = %s", key)
        row = cur.fetchone()
        return row[0] if row else None


def _set_coverage(key: tuple[str, str], complete_from: Optional[datetime]) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""INSERT INTO {SCHEMA}.tender_question (question, bid_kind, complete_from, checked_timestamp)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (question, bid_kind) DO UPDATE
                   SET complete_from = COALESCE(EXCLUDED.complete_from, {SCHEMA}.tender_question.complete_from),
                       checked_timestamp = CURRENT_TIMESTAMP""",
            (key[0], key[1], complete_from),
        )


def _remember(key: tuple[str, str], bid_ids: list[int]) -> int:
    """Record that a question returned these bids. Returns how many it had not returned before."""
    fresh = 0
    if not bid_ids:
        return 0
    with db_cursor(commit=True) as cur:
        for bid_id in bid_ids:
            cur.execute(
                f"INSERT INTO {SCHEMA}.tender_question_bid (question, bid_kind, bid_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (key[0], key[1], bid_id),
            )
            fresh += cur.rowcount or 0
    return fresh


def _question_bids(texts: list[str], bid_kind: str) -> dict[int, set[str]]:
    """Every open bid the questions have ever returned, with which of them returned it."""
    found: dict[int, set[str]] = {}
    if not texts:
        return found
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT q.bid_id, q.question FROM {SCHEMA}.tender_question_bid q JOIN {SCHEMA}.tender_bid b ON b.bid_id = q.bid_id
                 WHERE q.bid_kind = %s AND q.question = ANY(%s) AND (b.end_timestamp IS NULL OR b.end_timestamp > now())""",
            (bid_kind, texts),
        )
        for bid_id, question in cur.fetchall():
            found.setdefault(bid_id, set()).add(question)
    return found


def _ask(session: GemSession, text: str, bid_kind: str, stats: RunStats, cutoff: datetime) -> None:
    """Follow GeM's list for one question, newest first, back to ``cutoff`` (bids published since then) or its end.

    Once a question has been followed all the way back, a later check stops at the first page that holds nothing it returned
    before: everything older was seen then. A pass cut short by MAX_PAGES does not count as all the way, so the next check
    follows it again."""
    key = question_key(text, bid_kind)
    covered = _coverage(key)
    incremental = covered is not None and covered <= cutoff + timedelta(days=1)
    failures = 0
    for page in range(1, MAX_PAGES + 1):
        _report(stats, session, f"asking GeM about {text}, page {page}")
        try:
            answer = session.search(text, bid_kind, page)
        except GemError as exc:
            if exc.kind in ("captcha", "refused"):
                raise
            failures += 1
            if failures >= FAILURES_BEFORE_STOP:
                raise
            logger.warning("A GeM search page failed (%s), skipping it: %s", text, exc)
            continue
        ids = [row["bid_id"] for row in answer.rows]
        stats.bids_new += _store_listing(answer.rows)
        stats.seen.update(ids)
        fresh = _remember(key, ids)
        starts = [row["start_timestamp"] for row in answer.rows if row.get("start_timestamp")]
        if not answer.rows or page * gem_client.PAGE_SIZE >= answer.total or (starts and min(starts) < cutoff):
            _set_coverage(key, cutoff if covered is None else min(covered, cutoff))
            return
        if incremental and fresh == 0:
            _set_coverage(key, covered)
            return
    _set_coverage(key, None)
    stats.notes.append(
        f"GeM has more than {MAX_PAGES * gem_client.PAGE_SIZE} bids for {text!r} in the last {lookback_days()} days; the newest were "
        "checked, and the next check goes on from there."
    )


def _drop_match(search_id: int, bid_id: int) -> None:
    """A bid matched before its document was read, which the document now rules out. Only a New match goes."""
    with db_cursor(commit=True) as cur:
        cur.execute(f"DELETE FROM {SCHEMA}.tender_match WHERE search_id = %s AND bid_id = %s AND status = 'new'", (search_id, bid_id))


def _settle(session: GemSession, search: dict, texts: list[str], done: set[int], stats: RunStats) -> None:
    """Decide the bids these questions returned for a search, and record each match at once: those whose documents are already
    read first, then each one as soon as its document has been read (closing soonest first)."""
    returned = _question_bids(texts, search["bid_kind"])
    bids = _bids(bid_id for bid_id in returned if bid_id not in done)
    done.update(bids)
    wanted = [bid_id for bid_id, bid in bids.items() if type_matches(bid["category"], search["tender_types"])]
    hints = (lambda bid_id: returned.get(bid_id, set())) if search["cities"] else (lambda bid_id: set())
    now = datetime.now(timezone.utc)
    ready = {}
    unread = []
    for bid_id in wanted:
        if needs_reading(bids[bid_id], now):
            unread.append(bid_id)
            continue
        how = decide(search, bids[bid_id], hints(bid_id))
        if how:
            ready[bid_id] = how
    if ready:
        stats.matches_new += _store_matches(search["search_id"], ready, search.get("last_updated_timestamp"))
    far = datetime.max.replace(tzinfo=timezone.utc)
    unread.sort(key=lambda bid_id: bids[bid_id].get("end_timestamp") or far)
    if len(unread) > stats.documents_left:
        stats.documents_skipped += len(unread) - stats.documents_left
        unread = unread[:stats.documents_left]
    for index, bid_id in enumerate(unread, start=1):
        _report(stats, session, f"reading bid documents, {index} of {len(unread)}")
        stats.documents_left -= 1
        try:
            fields = gem_client.document_fields(gem_client.document_text(session.document(bid_id)))
        except GemError as exc:
            if exc.kind in ("captcha", "refused"):
                raise
            _store_document(bid_id, None, str(exc))
        else:
            _store_document(bid_id, fields, None)
            stats.documents_read += 1
        bid = _bids([bid_id]).get(bid_id)
        how = decide(search, bid, hints(bid_id)) if bid else None
        if how:
            stats.matches_new += _store_matches(search["search_id"], {bid_id: how}, search.get("last_updated_timestamp"))
        else:
            _drop_match(search["search_id"], bid_id)


def _check(session: GemSession, searches: list[dict], stats: RunStats) -> None:
    """Each search in turn and, within it, each city or tender type in turn: ask GeM, then record what fits at once, so bids
    appear while the rest is still being checked. A question two searches share is asked once."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days())
    asked: set[tuple[str, str]] = set()
    on_gem = searches
    for number, search in enumerate(on_gem, start=1):
        stats.current_search_id = search["search_id"]
        stats.prefix = f"{search['name']} ({number} of {len(on_gem)}): "
        done: set[int] = set()
        for text, kind in questions(search):
            key = question_key(text, kind)
            if key not in asked:
                _ask(session, text, kind, stats, cutoff)
                asked.add(key)
            _settle(session, search, [key[0]], done, stats)
        _report(stats, session, "done", force=True)
    stats.current_search_id = None
    stats.bids_seen = len(stats.seen) + stats.other_seen
    if stats.documents_skipped:
        stats.notes.append(f"{stats.documents_skipped} bid documents are left for the next check.")


# ------------------------------------------------------------------------------------------------- MP Tenders


def _store_mp_listing(rows: list[dict], stats: RunStats) -> dict[str, int]:
    """Insert or refresh MP tenders from an organisation's list. Returns their bid ids by Tender ID."""
    ids: dict[str, int] = {}
    if not rows:
        return ids
    with db_cursor(commit=True) as cur:
        for row in rows:
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.tender_bid (bid_id, source, source_ref, bid_number, title, reference, ministry, department,
                                                 start_timestamp, end_timestamp)
                VALUES (nextval('{SCHEMA}.tender_bid_local_seq'), 'mptenders', %(source_ref)s, %(bid_number)s, %(title)s, %(reference)s,
                        %(ministry)s, %(department)s, %(start_timestamp)s, %(end_timestamp)s)
                ON CONFLICT (source, source_ref) DO UPDATE
                   SET title = COALESCE({SCHEMA}.tender_bid.title, EXCLUDED.title), reference = EXCLUDED.reference,
                       ministry = EXCLUDED.ministry, department = EXCLUDED.department, start_timestamp = EXCLUDED.start_timestamp,
                       end_timestamp = EXCLUDED.end_timestamp, last_seen_timestamp = CURRENT_TIMESTAMP
                RETURNING bid_id, (xmax = 0) AS inserted
                """,
                row,
            )
            bid_id, inserted = cur.fetchone()
            ids[row["source_ref"]] = bid_id
            stats.bids_new += 1 if inserted else 0
    return ids


def _store_mp_details(bid_id: int, fields: dict, chain: str) -> None:
    """What an MP tender's details page said. Where the work is: the district of its PIN code, else the city's name in its
    location or organisation."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE {SCHEMA}.tender_bid
               SET title = COALESCE(%(title)s, title), work_description = %(work_description)s, category = %(category)s,
                   tender_category = %(tender_category)s, estimated_value = %(estimated_value)s, tender_fee = %(tender_fee)s,
                   tender_fee_total = %(tender_fee_total)s, tender_fee_exempt = %(tender_fee_exempt)s, emd_amount = %(emd_amount)s,
                   emd_exempt = %(emd_exempt)s, contract_period = %(contract_period)s, location_text = %(location_text)s,
                   location_districts = %(location_districts)s, location_source = 'consignee', reader_version = %(reader_version)s,
                   document_status = 'read', document_error = NULL, document_read_timestamp = CURRENT_TIMESTAMP
             WHERE bid_id = %(bid_id)s
            """,
            {**fields, "location_text": " ".join(part for part in (fields.get("location_text"), chain) if part)[:4000] or None,
             "location_districts": mptenders_client.district_of(fields.get("pincode")), "reader_version": gem_client.READER_VERSION,
             "bid_id": bid_id},
        )


def _check_mp(session: "mptenders_client.MpSession", searches: list[dict], stats: RunStats) -> None:
    """Every organisation on MP Tenders in turn: its active tenders published within the lookback, the details of those whose
    title fits a search (closing soonest first), and each match recorded as soon as it is known."""
    on_mp = searches
    if not on_mp:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days())
    stats.current_search_id = on_mp[0]["search_id"] if len(on_mp) == 1 else None
    stats.prefix = ""
    _report(stats, session, "opening the list of organisations", force=True)
    organisations = session.open()
    for number, organisation in enumerate(organisations, start=1):
        stats.prefix = f"{organisation.name} ({number} of {len(organisations)}): "
        _report(stats, session, "listing its tenders")
        try:
            page = session.page(organisation.link)
        except GemError as exc:
            if exc.kind != "stale":
                raise
            fresh = {item.name: item for item in session.open()}
            if organisation.name not in fresh:
                continue
            organisation = fresh[organisation.name]
            page = session.page(organisation.link)
        rows = [row for row in mptenders_client.tender_rows(page) if not row["start_timestamp"] or row["start_timestamp"] >= cutoff]
        stats.other_seen += len(rows)
        # Only tenders whose title fits a search are kept: the thousands of others would be stored only to be forgotten.
        rows = [row for row in rows if any(type_matches(row["title"] or "", s["tender_types"]) for s in on_mp)]
        if not rows:
            continue
        ids = _store_mp_listing(rows, stats)
        links = {ids[row["source_ref"]]: (row["details_link"], row["organisation_chain"]) for row in rows}
        candidates = list(links)
        bids = _bids(candidates)
        now = datetime.now(timezone.utc)
        far = datetime.max.replace(tzinfo=timezone.utc)
        unread = sorted((bid_id for bid_id in candidates if bid_id in bids and needs_reading(bids[bid_id], now)),
                        key=lambda bid_id: bids[bid_id].get("end_timestamp") or far)
        if len(unread) > stats.documents_left:
            stats.documents_skipped += len(unread) - stats.documents_left
            unread = unread[:stats.documents_left]
        for index, bid_id in enumerate(unread, start=1):
            _report(stats, session, f"reading tender details, {index} of {len(unread)}")
            stats.documents_left -= 1
            link, chain = links[bid_id]
            try:
                fields = mptenders_client.details(session.page(link))
            except GemError as exc:
                if exc.kind in ("captcha", "refused"):
                    raise
                _store_document(bid_id, None, str(exc))
                continue
            _store_mp_details(bid_id, fields, chain)
            stats.documents_read += 1
        bids = _bids(candidates)
        for search in on_mp:
            found = {}
            for bid_id in candidates:
                bid = bids.get(bid_id)
                if bid and bid["document_status"] == "read":
                    how = decide(search, bid, set())
                    if how:
                        found[bid_id] = how
            if found:
                stats.matches_new += _store_matches(search["search_id"], found, search.get("last_updated_timestamp"))
    _report(stats, session, "done", force=True)


def run_check(
    portal: str,
    trigger: str = "manual",
    user_id: Optional[int] = None,
    session: Optional[GemSession] = None,
) -> Optional[int]:
    """One check of a portal's active searches. Returns the run's id, or None when it has nothing to search. Raises CheckBusy when
    a check of that portal is running (the other portal's checks are separate and may run at the same time). Never raises for the
    portal's or the network's failures: the run records them."""
    lock = _locks[portal]
    if not lock.acquire(blocking=False):
        raise CheckBusy(f"A {PORTAL_NAMES[portal]} check is already running.")
    try:
        searches = active_searches(portal)
        if not searches:
            return None
        run_id = _start_run(portal, trigger, user_id)
        stats = RunStats(searches=len(searches), run_id=run_id)
        own = session is None
        if session is None:
            session = mptenders_client.MpSession() if portal == "mptenders" else GemSession()
        stats.sessions = [session]
        error = None
        try:
            if portal == "mptenders":
                _check_mp(session, searches, stats)
            else:
                _check(session, searches, stats)
        except GemError as exc:
            error = str(exc)
            logger.warning("The %s tender check stopped: %s", PORTAL_NAMES[portal], exc)
        except Exception as exc:  # noqa: BLE001 - recorded on the run and in the log with its traceback
            error = f"The check failed ({type(exc).__name__}). The log has the details."
            logger.exception("The %s tender check failed", PORTAL_NAMES[portal])
        finally:
            if own:
                session.close()
        stats.current_search_id = None
        stats.bids_seen = len(stats.seen) + stats.other_seen
        try:
            _forget_old_bids()
        except Exception:  # noqa: BLE001 - tidying up is not worth failing the check for
            logger.exception("Could not remove old tender bids")
        _finish_run(run_id, stats, session.requests, error)
        if not error:
            logger.info("%s check %s: %s seen, %s new matches, %s documents read", PORTAL_NAMES[portal], run_id, stats.bids_seen,
                        stats.matches_new, stats.documents_read)
        return run_id
    finally:
        lock.release()


def start_check(portal: str, user_id: Optional[int]) -> None:
    """Begin a check of one portal in the background for a person. Raises CheckBusy, or TenderError when it has no active search."""
    if is_running(portal):
        raise CheckBusy(f"A {PORTAL_NAMES[portal]} check is already running.")
    if not active_searches(portal):
        raise TenderError(f"No {PORTAL_NAMES[portal]} search is active. Add a search, or switch one on, first.")

    def work() -> None:
        try:
            run_check(portal, "manual", user_id)
        except CheckBusy:
            logger.info("A %s check was asked for while one was running", PORTAL_NAMES[portal])

    threading.Thread(target=work, name=f"orion-tender-check-{portal}", daemon=True).start()


def is_running(portal: str) -> bool:
    """A check of this portal is running here, or another process has recorded one as running (within STALE_RUN)."""
    if _locks[portal].locked():
        return True
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT EXISTS (SELECT 1 FROM {SCHEMA}.tender_run
                                WHERE portal = %s AND status = 'running' AND started_timestamp > now() - make_interval(secs => %s))""",
            (portal, STALE_RUN.total_seconds()),
        )
        return bool(cur.fetchone()[0])


def close_interrupted_runs() -> None:
    """A run left 'running' by a stopped server never finished."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                f"""UPDATE {SCHEMA}.tender_run SET status = 'failed', finished_timestamp = CURRENT_TIMESTAMP,
                           error = 'The server stopped while this check was running.'
                     WHERE status = 'running'"""
            )
    except Exception:  # noqa: BLE001 - the table may not exist yet on a database the migration has not reached
        logger.debug("Could not close interrupted tender checks", exc_info=True)


def latest_run(portal: str) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT run_id, portal, trigger, status, started_timestamp, finished_timestamp, searches, requests, bids_seen, bids_new,
                       documents_read, matches_new, note, error, progress, current_search_id
                  FROM {SCHEMA}.tender_run WHERE portal = %s ORDER BY started_timestamp DESC, run_id DESC LIMIT 1""",
            (portal,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {c.name: _plain(v) for c, v in zip(cur.description, row)}


def lookback_days() -> int:
    raw = env("ORION_TENDERS_LOOKBACK_DAYS", str(DEFAULT_LOOKBACK_DAYS)).strip()
    try:
        return min(max(int(raw), 7), 365)
    except ValueError:
        logger.warning("ORION_TENDERS_LOOKBACK_DAYS=%r is not a whole number; using %s", raw, DEFAULT_LOOKBACK_DAYS)
        return DEFAULT_LOOKBACK_DAYS


def check_hours() -> int:
    raw = env("ORION_TENDERS_CHECK_HOURS", str(DEFAULT_HOURS)).strip()
    try:
        return max(int(raw), 0)
    except ValueError:
        logger.warning("ORION_TENDERS_CHECK_HOURS=%r is not a whole number; using %s", raw, DEFAULT_HOURS)
        return DEFAULT_HOURS


def status(portal: str) -> dict:
    """One portal's checks, for its Tenders page."""
    run = latest_run(portal)
    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FILTER (WHERE is_active) FROM {SCHEMA}.tender_search WHERE portal = %s", (portal,))
        active = cur.fetchone()[0] or 0
    return {
        "portal": portal,
        "running": is_running(portal),
        "active_searches": active,
        "every_hours": check_hours(),
        "lookback_days": lookback_days(),
        "next_check": _next_check.isoformat() if _next_check else None,
        "last_run": run,
        "failing": bool(active and run and run["status"] == "failed"),
    }


def status_all() -> dict:
    """Every portal's checks, for the System page."""
    return {portal: status(portal) for portal in PORTALS}


def start(stop: threading.Event) -> Optional[threading.Thread]:
    """Check each portal every ``ORION_TENDERS_CHECK_HOURS`` while the server runs (only one with an active search), each as its
    own run."""
    hours = check_hours()
    close_interrupted_runs()
    if hours == 0:
        logger.info("Scheduled tender checks are off (ORION_TENDERS_CHECK_HOURS=0)")
        return None

    def wait(seconds: float) -> bool:
        global _next_check
        _next_check = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        try:
            return stop.wait(seconds)
        finally:
            _next_check = None

    def loop() -> None:
        if wait(FIRST_CHECK_DELAY_SECONDS):
            return
        while True:
            for portal in PORTALS:
                try:
                    last = latest_run(portal)
                    due = not last or not last.get("started_timestamp") or (
                        datetime.now(timezone.utc) - datetime.fromisoformat(last["started_timestamp"]) >= timedelta(hours=hours)
                    )
                    if due:
                        run_check(portal, "schedule")
                except CheckBusy:
                    pass
                except Exception:  # noqa: BLE001 - the schedule must outlive one bad check
                    logger.exception("The scheduled %s check failed", PORTAL_NAMES[portal])
            if wait(hours * 3600):
                return

    thread = threading.Thread(target=loop, name="orion-tender-schedule", daemon=True)
    thread.start()
    logger.info("Tender checks every %s hours", hours)
    return thread
