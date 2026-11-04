"""Tenders: reading GeM's answers and bid documents, deciding which bids a search wants, the check's steps, and who may see and change
the searches. No network and no database: GeM is a stand-in transport and the storage functions are replaced."""

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, gem_client, mptenders_client, tenders  # noqa: E402
from app.dependencies import get_current_user  # noqa: E402
from app.gem_client import GemError, GemSession  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import tenders_router  # noqa: E402

NOW = datetime.now(timezone.utc)


def gem_doc(bid_id, number, category, end_days=5, **extra):
    """One bid as GeM's search index returns it: most fields are one-item lists."""
    doc = {
        "b_id": [bid_id], "b_bid_number": [number], "b_category_name": [category], "b_total_quantity": [4],
        "ba_official_details_minName": ["Ministry of Defence"], "ba_official_details_deptName": ["Department of Military Affairs"],
        "is_high_value": [False], "final_start_date_sort": [(NOW - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")],
        "final_end_date_sort": [(NOW + timedelta(days=end_days)).strftime("%Y-%m-%dT%H:%M:%SZ")],
    }
    doc.update(extra)
    return doc


def gem_answer(docs, total=None):
    return json.dumps({"code": 200, "response": {"response": {"numFound": len(docs) if total is None else total, "start": 0, "docs": docs}}})


DOCUMENT_TEXT = (
    "Bid Document Bid Details Bid End Date/Time 04-11-2026 Contract Period 2 Year(s) "
    "Minimum Average Annual Turnover of the bidder (For 3 Years) 25 Lakh (s) + + / / 56 56 % % "
    "/Years of Past Experience Required for same/similar service 3 Year (s) % % "
    "Estimated Bid Value in INR (Inclusive of all taxes) 2394580 T T X X Bid Details /EMD Detail N /Advisory Bank State Bank of India "
    "/EMD Amount 47892 /ePBG Detail N /Advisory Bank State Bank of India 2 / 14 < (%) /ePBG Percentage(%) 3.00 : ( ) "
    "/Duration of ePBG required (Months). 30 (a). /EMD EXEMPTION: The bidder seeking EMD exemption, must submit the document "
    "Consignees/Reporting Officer and Quantity S.No. Consignee Reporting/Officer Address Number of Resources to be hired "
    "1 Jitendra Kumar 474010,SOFTWARE TECHNOLOGY PARKS OF INDIA, VILLAGE GANGA MALANPUR, MURENA LINK ROAD, GWALIOR 3 "
    "Buyer Added Bid Specific Terms and Conditions 1. Generic OPTION CLAUSE"
)


def search(**changes):
    data = {"search_id": 1, "portal": "gem", "name": "Gwalior security", "tender_types": ["security", "manpower"], "cities": ["Gwalior"],
            "bid_kind": "service", "min_value": None, "max_value": None, "include_unpriced": True, "is_active": True}
    data.update(changes)
    return data


class ReadingGeMsAnswers(unittest.TestCase):
    def test_a_search_answer_becomes_rows(self):
        page = gem_client.search_answer(gem_answer([gem_doc(10057535, "GEM/2026/B/8117724", "Security Manpower Service (Version 2.0)")], total=34))
        self.assertEqual(page.total, 34)
        row = page.rows[0]
        self.assertEqual((row["bid_id"], row["bid_number"], row["quantity"]), (10057535, "GEM/2026/B/8117724", 4))
        self.assertEqual(row["category"], "Security Manpower Service (Version 2.0)")
        self.assertEqual(row["department"], "Department of Military Affairs")
        self.assertIsNotNone(row["end_timestamp"].tzinfo)

    def test_a_bid_without_an_id_or_number_is_left_out(self):
        page = gem_client.search_answer(gem_answer([{"b_bid_number": ["GEM/1"]}, {"b_id": [5]}]))
        self.assertEqual(page.rows, [])

    def test_a_refusal_a_captcha_and_a_changed_page_each_say_so(self):
        with self.assertRaises(GemError) as refused:
            gem_client.search_answer(json.dumps({"code": 500}))
        self.assertEqual(refused.exception.kind, "refused")
        with self.assertRaises(GemError) as captcha:
            gem_client.search_answer("<html>Please solve the CAPTCHA</html>")
        self.assertEqual(captcha.exception.kind, "captcha")
        with self.assertRaises(GemError) as changed:
            gem_client.search_answer(json.dumps({"code": 200, "response": None}))
        self.assertEqual(changed.exception.kind, "changed")

    def test_a_bid_document_gives_value_emd_period_turnover_experience_and_place(self):
        found = gem_client.document_fields(DOCUMENT_TEXT)
        self.assertEqual(found["estimated_value"], Decimal("2394580"))
        self.assertEqual(found["emd_amount"], Decimal("47892"))
        self.assertEqual(found["contract_period"], "2 Year(s)")
        self.assertEqual(found["min_turnover"], "25 Lakh")  # not the 3 of "(For 3 Years)"
        self.assertEqual(found["experience_years"], Decimal("3"))
        self.assertEqual(found["location_source"], "consignee")
        self.assertIn("MALANPUR", found["location_text"])
        self.assertNotIn("OPTION CLAUSE", found["location_text"])
        self.assertEqual(found["location_districts"], ["Gwalior"])  # from the PIN code 474010
        self.assertEqual((found["emd_required"], found["epbg_required"], found["epbg_percent"], found["epbg_months"]), (True, True, Decimal("3.00"), 30))

    def test_what_a_seller_must_put_up_is_read_as_gem_writes_it(self):
        none = gem_client.security_fields("Bid Details /EMD Detail C /Required No /ePBG Detail C /Required No < / Bid splitting not applied.")
        self.assertEqual(none, {"emd_required": False, "epbg_required": False, "epbg_percent": None, "epbg_months": None})
        guarantee_only = gem_client.security_fields(
            "/EMD Detail B /Required No /ePBG Detail > /Advisory Bank State Bank of India 4 (%) /ePBG Percentage(%) 5.00 B ( ) "
            "/Duration of ePBG required (Months). 21 (a). EMD & Performance security should be in favour of Beneficiary"
        )
        self.assertEqual((guarantee_only["emd_required"], guarantee_only["epbg_percent"], guarantee_only["epbg_months"]), (False, Decimal("5.00"), 21))
        self.assertEqual(gem_client.security_fields("Nothing about it"), {"emd_required": None, "epbg_required": None, "epbg_percent": None, "epbg_months": None})

    def test_a_document_that_states_nothing_gives_nothing_and_is_searched_whole(self):
        found = gem_client.document_fields("Bid Document Item Category Security Manpower Service")
        for key in ("estimated_value", "emd_amount", "contract_period", "min_turnover", "experience_years"):
            self.assertIsNone(found[key], key)
        self.assertEqual((found["location_source"], found["location_districts"]), ("document", []))

    def test_what_is_not_a_pdf_is_refused(self):
        with self.assertRaises(GemError):
            gem_client.document_text(b"<html>not found</html>")


class TalkingToGeM(unittest.TestCase):
    def session(self, handler):
        calls = []

        def record(request):
            calls.append(request)
            return handler(request)

        client = httpx.Client(transport=httpx.MockTransport(record))
        return GemSession(gap=0, client=client), calls

    def test_the_listing_page_gives_the_token_the_search_sends_back(self):
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, text="<script>data: {'csrf_bd_gem_nk': 'c3ce3dae70c201ee00c1ef31a34180f5'}</script>")
            return httpx.Response(200, text=gem_answer([gem_doc(1, "GEM/1", "Security")]))

        gem, calls = self.session(handler)
        page = gem.search("Gwalior", "service", 2)
        self.assertEqual(len(page.rows), 1)
        form = dict(httpx.QueryParams(calls[1].content.decode()))
        self.assertEqual(form["csrf_bd_gem_nk"], "c3ce3dae70c201ee00c1ef31a34180f5")
        payload = json.loads(form["payload"])
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["param"]["searchBid"], "Gwalior")
        self.assertEqual(payload["filter"]["byType"], "service")
        self.assertEqual(payload["filter"]["bidStatusType"], "ongoing_bids")
        self.assertEqual(gem.requests, 2)

    def test_no_token_or_a_refusal_stops_with_a_reason(self):
        gem, _ = self.session(lambda request: httpx.Response(200, text="<html>nothing here</html>"))
        with self.assertRaises(GemError):
            gem.search("Gwalior")
        gem, _ = self.session(lambda request: httpx.Response(429))
        with self.assertRaises(GemError) as refused:
            gem.open()
        self.assertEqual(refused.exception.kind, "refused")

    def test_a_document_gem_no_longer_has_is_missing_not_a_refusal(self):
        gem, _ = self.session(lambda request: httpx.Response(404))
        with self.assertRaises(GemError) as missing:
            gem.document(1)
        self.assertEqual(missing.exception.kind, "missing")

    def test_a_search_that_finds_nothing_is_empty_not_an_error(self):
        """GeM answers a search with no results ("Sheopur") with HTTP 404, not an empty list."""
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, text="<script>{'csrf_bd_gem_nk': 'c3ce3dae70c201ee00c1ef31a34180f5'}</script>")
            return httpx.Response(404)

        gem, _ = self.session(handler)
        page = gem.search("Sheopur", "all", 1)
        self.assertEqual((page.total, page.rows), (0, []))

    def test_a_network_blip_is_tried_again_and_a_lasting_one_says_what_happened(self):
        """MP Tenders once connected and sent nothing back for an evening: each request gets two more tries, then the check stops."""
        tries = {"n": 0}

        def flaky(request):
            tries["n"] += 1
            if tries["n"] < 3:
                raise httpx.ReadTimeout("no answer", request=request)
            return httpx.Response(200, content=b"%PDF-1.4")

        gem, _ = self.session(flaky)
        with mock.patch.object(gem_client.time, "sleep") as sleep:
            self.assertEqual(gem.document(1), b"%PDF-1.4")
        self.assertEqual([c.args[0] for c in sleep.call_args_list], list(gem_client.RETRY_PAUSES))

        def down(request):
            raise httpx.ReadTimeout("no answer", request=request)

        gem, calls = self.session(down)
        gem.portal = "MP Tenders"
        with mock.patch.object(gem_client.time, "sleep"), self.assertRaises(GemError) as failed:
            gem.document(1)
        self.assertEqual(len(calls), 1 + len(gem_client.RETRY_PAUSES))
        self.assertEqual(failed.exception.kind, "unreachable")
        self.assertIn("MP Tenders connected but sent nothing back in time", str(failed.exception))

    def test_an_answer_even_a_refusal_is_not_tried_again(self):
        gem, calls = self.session(lambda request: httpx.Response(429))
        with mock.patch.object(gem_client.time, "sleep") as sleep, self.assertRaises(GemError):
            gem.document(1)
        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    def test_requests_are_spaced_out(self):
        gem, _ = self.session(lambda request: httpx.Response(200, content=b"%PDF-1.4"))
        gem.gap = 5
        with mock.patch.object(gem_client.time, "sleep") as sleep, mock.patch.object(gem_client.time, "monotonic", side_effect=[100.0, 100.0, 101.0, 106.0]):
            gem.document(1)
            gem.document(2)
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 4.0)


class DecidingWhatASearchWants(unittest.TestCase):
    def test_types_match_the_start_of_a_word_anywhere_in_the_category(self):
        self.assertTrue(tenders.type_matches("Security Manpower Service (Version 2.0)", ["security"]))
        self.assertTrue(tenders.type_matches("Hiring of Guards", ["guard"]))
        self.assertTrue(tenders.type_matches("Manpower Outsourcing Services - Minimum wage", ["manpower outsourcing"]))
        self.assertFalse(tenders.type_matches("Foreman services", ["man"]))
        self.assertFalse(tenders.type_matches("Repair of trucks", ["security"]))
        self.assertTrue(tenders.type_matches("Anything", []))

    def test_a_city_is_a_whole_word_and_a_district_may_be_spelt_a_little_differently(self):
        self.assertEqual(tenders.city_in("***********GWALIOR 11", ["Bhopal", "Gwalior"]), "Gwalior")
        self.assertIsNone(tenders.city_in("Gwaliorpur", ["Gwalior"]))
        self.assertTrue(tenders.same_place("Visakhapatnam", "Visakhapatanam"))
        self.assertFalse(tenders.same_place("Bhopal", "Gwalior"))
        self.assertFalse(tenders.same_place("Una", "Pune"))

    def test_the_value_range(self):
        self.assertTrue(tenders.value_ok(Decimal(5), Decimal(1), Decimal(10), False))
        self.assertFalse(tenders.value_ok(Decimal(50), Decimal(1), Decimal(10), True))
        self.assertTrue(tenders.value_ok(None, Decimal(1), None, True))
        self.assertFalse(tenders.value_ok(None, Decimal(1), None, False))
        self.assertTrue(tenders.value_ok(None, None, None, False))  # no range: a missing value is not a reason to leave it out

    def test_a_read_document_decides_the_city_by_pin_first(self):
        read = {"category": "Security Manpower Service", "estimated_value": None, "document_status": "read",
                "location_districts": ["Gwalior"], "location_text": "474005,INSTITUTE OF HOTEL MANAGEMENT, AIRPORT ROAD, MAHARAJPURA"}
        self.assertEqual(tenders.decide(search(), read, set()), {"matched_city": "Gwalior", "location_confirmed": True})
        elsewhere = {**read, "location_districts": ["Bhopal"], "location_text": "462002,SHYAMLA HILLS, BHOPAL"}
        self.assertIsNone(tenders.decide(search(), elsewhere, {"Gwalior"}), "GeM found it for Gwalior, but the work is in Bhopal")

    def test_an_unread_document_falls_back_to_the_city_gem_matched_unconfirmed(self):
        unread = {"category": "Security Manpower Service", "estimated_value": None, "document_status": "failed", "location_text": None}
        self.assertEqual(tenders.decide(search(), unread, {"gwalior"}), {"matched_city": "Gwalior", "location_confirmed": False})
        self.assertIsNone(tenders.decide(search(), unread, set()))

    def test_type_and_value_can_each_rule_a_bid_out(self):
        bid = {"category": "Repair of trucks", "estimated_value": Decimal(1000), "document_status": "read", "location_districts": ["Gwalior"]}
        self.assertIsNone(tenders.decide(search(), bid, set()))
        bid["category"] = "Security Manpower Service"
        self.assertIsNone(tenders.decide(search(min_value=Decimal(5000)), bid, set()))
        self.assertIsNotNone(tenders.decide(search(min_value=Decimal(500)), bid, set()))

    def test_no_cities_means_anywhere(self):
        bid = {"category": "Security", "estimated_value": None, "document_status": "pending"}
        self.assertEqual(tenders.decide(search(cities=[]), bid, set()), {"matched_city": None, "location_confirmed": False})

    def test_gem_is_asked_by_city_when_there_are_cities_else_by_type(self):
        self.assertEqual(tenders.questions(search()), [("Gwalior", "service")])
        self.assertEqual(tenders.questions(search(cities=[], bid_kind="all")), [("security", "all"), ("manpower", "all")])


class WhatASearchMayBe(unittest.TestCase):
    def test_terms_are_tidied_and_repeats_dropped(self):
        self.assertEqual(tenders.clean_terms(["  Security  manpower ", "security manpower", "", None, "Gwalior"], "type"),
                         ["Security manpower", "Gwalior"])

    def test_odd_characters_long_terms_and_too_many_are_refused(self):
        for bad in (["<script>"], ["x" * 61], [f"t{i}" for i in range(21)]):
            with self.assertRaises(tenders.TenderError, msg=str(bad)[:30]):
                tenders.clean_terms(bad, "type")

    def test_a_search_may_name_every_city_of_a_state_but_not_that_many_tender_types(self):
        from app.location import get_cities_for_state

        every = get_cities_for_state("Uttar Pradesh")  # the largest state
        self.assertGreater(len(every), tenders.MAX_TERMS)  # more than the limit on types, so the limit on cities is its own
        self.assertLessEqual(len(every), tenders.MAX_CITIES)
        base = {"name": "x", "tender_types": ["security"], "bid_kind": "service"}
        self.assertEqual(len(tenders._clean_search({**base, "cities": every}, "gem")["cities"]), len(every))
        with self.assertRaises(tenders.TenderError) as too_many_cities:
            tenders._clean_search({**base, "cities": [f"City {i}" for i in range(tenders.MAX_CITIES + 1)]}, "gem")
        self.assertIn(f"at most {tenders.MAX_CITIES} cities", str(too_many_cities.exception))
        with self.assertRaises(tenders.TenderError) as too_many_types:
            tenders._clean_search({**base, "tender_types": [f"type {i}" for i in range(tenders.MAX_TERMS + 1)]}, "gem")
        self.assertIn(f"at most {tenders.MAX_TERMS} tender types", str(too_many_types.exception))

    def test_a_search_needs_a_name_and_something_to_look_for_and_a_sensible_range(self):
        good = {"name": "x", "tender_types": ["security"], "cities": [], "bid_kind": "service"}
        self.assertEqual(tenders._clean_search(good, "gem")["bid_kind"], "service")
        for bad in ({**good, "name": " "}, {**good, "tender_types": []}, {**good, "bid_kind": "works"},
                    {**good, "min_value": 10, "max_value": 5}, {**good, "min_value": -1}, {**good, "min_value": "lots"}):
            with self.assertRaises(tenders.TenderError, msg=str(bad)):
                tenders._clean_search(bad, "gem")


class QuestionMemory:
    """Stands in for tender_question_bid and tender_question: which bids each question to GeM has returned, and how far back its
    list was last followed to the end."""

    def __init__(self, known=None, covered=None):
        self.known = {key: set(ids) for key, ids in (known or {}).items()}
        self.covered = dict(covered or {})

    def remember(self, key, ids):
        seen = self.known.setdefault(key, set())
        before = len(seen)
        seen.update(ids)
        return len(seen) - before

    def bids(self, texts, kind):
        found = {}
        for (text, bid_kind), ids in self.known.items():
            if bid_kind == kind and text in texts:
                for bid_id in ids:
                    found.setdefault(bid_id, set()).add(text)
        return found

    def set_coverage(self, key, complete_from):
        if complete_from is not None or key not in self.covered:
            self.covered[key] = complete_from

    def patches(self):
        return (mock.patch.object(tenders, "_coverage", side_effect=lambda key: self.covered.get(key)),
                mock.patch.object(tenders, "_set_coverage", side_effect=self.set_coverage),
                mock.patch.object(tenders, "_remember", side_effect=self.remember),
                mock.patch.object(tenders, "_question_bids", side_effect=self.bids))


def pending(bid_id, category="Security Manpower Service", closes_in_days=5):
    return {"bid_id": bid_id, "category": category, "estimated_value": None, "location_text": None, "document_status": "pending",
            "document_read_timestamp": None, "location_districts": [], "end_timestamp": NOW + timedelta(days=closes_in_days)}


def listed(bid_id, category="Security Manpower Service", published_days_ago=2):
    return gem_client.listing_row(gem_doc(bid_id, f"GEM/{bid_id}", category,
                                          final_start_date_sort=[(NOW - timedelta(days=published_days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")]))


class TheCheck(unittest.TestCase):
    """The steps of one check, with GeM and the database replaced."""

    def run_check_steps(self, gem, searches, state, memory=None, store_document=None, recorded=None, dropped=None):
        memory = memory or QuestionMemory()
        recorded = {} if recorded is None else recorded

        def store_matches(search_id, found, saved_at=None):
            recorded.setdefault(search_id, {}).update(found)
            return len(found)

        def store_doc(bid_id, fields, error):
            if store_document:
                store_document(bid_id, fields, error)
            elif fields is not None:
                state[bid_id].update(document_status="read", reader_version=gem_client.READER_VERSION,
                                     location_districts=fields["location_districts"], location_text=fields["location_text"])

        coverage, set_coverage, remember, question_bids = memory.patches()
        with coverage, set_coverage, remember, question_bids, \
             mock.patch.object(tenders, "_store_listing", return_value=0), \
             mock.patch.object(tenders, "_bids", side_effect=lambda ids: {i: dict(state[i]) for i in list(ids) if i in state}), \
             mock.patch.object(tenders, "_store_document", side_effect=store_doc), \
             mock.patch.object(tenders, "_store_matches", side_effect=store_matches), \
             mock.patch.object(tenders, "_drop_match", side_effect=lambda sid, bid_id: (dropped if dropped is not None else []).append(bid_id)), \
             mock.patch.object(gem_client, "document_text", return_value=DOCUMENT_TEXT):
            stats = tenders.RunStats()
            tenders._check(gem, searches, stats)
        return stats

    def test_it_asks_once_per_question_reads_only_wanted_documents_and_records_each_search(self):
        gem = mock.Mock()
        gem.search.return_value = gem_client.SearchPage(total=2, rows=[listed(1), listed(2, "Repair of trucks")])
        gem.document.return_value = b"%PDF"
        state = {1: pending(1), 2: pending(2, "Repair of trucks")}
        recorded = {}
        two_searches = [search(search_id=1), search(search_id=2, name="Same city again", tender_types=["security"])]
        stats = self.run_check_steps(gem, two_searches, state, recorded=recorded)
        gem.search.assert_called_once_with("Gwalior", "service", 1)  # the same question for both searches, asked once
        gem.document.assert_called_once_with(1)  # the truck repair is not what either search wants
        self.assertEqual(recorded[1], {1: {"matched_city": "Gwalior", "location_confirmed": True}})
        self.assertEqual(recorded[2], {1: {"matched_city": "Gwalior", "location_confirmed": True}})
        self.assertEqual((stats.bids_seen, stats.documents_read), (2, 1))

    def test_gems_list_is_followed_back_to_the_lookback_and_no_further(self):
        pages = {1: [listed(i, published_days_ago=10) for i in range(1, 11)],
                 2: [listed(i, published_days_ago=60) for i in range(11, 21)],
                 3: [listed(i, published_days_ago=95) for i in range(21, 31)],
                 4: [listed(i, published_days_ago=120) for i in range(31, 41)]}
        gem = mock.Mock()
        gem.search.side_effect = lambda text, kind, page: gem_client.SearchPage(total=400, rows=pages[page])
        memory = QuestionMemory()
        self.run_check_steps(gem, [search(tender_types=["nothing matches this"])], {}, memory)
        self.assertEqual(gem.search.call_count, 3, "page 3 reaches bids published more than 90 days ago")
        self.assertIsNotNone(memory.covered[("gwalior", "service")], "the window was covered all the way")

    def test_a_question_followed_all_the_way_before_stops_at_the_first_page_with_nothing_new(self):
        gem = mock.Mock()
        gem.search.return_value = gem_client.SearchPage(total=300, rows=[listed(i) for i in range(1, 11)])
        memory = QuestionMemory({("gwalior", "service"): set(range(1, 11))}, {("gwalior", "service"): NOW - timedelta(days=100)})
        self.run_check_steps(gem, [search(tender_types=["nothing matches this"])], {i: pending(i) for i in range(1, 11)}, memory)
        self.assertEqual(gem.search.call_count, 1, "everything on page 1 was returned before, and everything older was seen then")

    def test_a_pass_cut_short_is_followed_again_next_time_not_stopped_early(self):
        gem = mock.Mock()
        gem.search.return_value = gem_client.SearchPage(total=3000, rows=[listed(i) for i in range(1, 11)])
        memory = QuestionMemory({("gwalior", "service"): set(range(1, 11))}, {("gwalior", "service"): None})
        with mock.patch.object(tenders, "MAX_PAGES", 4):
            stats = self.run_check_steps(gem, [search(tender_types=["nothing matches this"])], {}, memory)
        self.assertEqual(gem.search.call_count, 4, "never followed to the end, so known bids are no reason to stop")
        self.assertIsNone(memory.covered[("gwalior", "service")])
        self.assertTrue(any("next check goes on" in note for note in stats.notes))

    def test_a_new_question_pages_until_gem_has_no_more(self):
        pages = {p: [listed(p * 100 + i, "x") for i in range(10)] for p in (1, 2, 3)}
        gem = mock.Mock()
        gem.search.side_effect = lambda text, kind, page: gem_client.SearchPage(total=25, rows=pages[page])
        self.run_check_steps(gem, [search(tender_types=["nothing matches this"])], {})
        self.assertEqual(gem.search.call_count, 3)

    def test_a_search_sees_older_bids_its_question_returned_in_an_earlier_check(self):
        """A new or changed search sharing a question that stops at page 1 is still decided on everything the question returned."""
        gem = mock.Mock()
        gem.search.return_value = gem_client.SearchPage(total=50, rows=[listed(1)])
        memory = QuestionMemory({("gwalior", "service"): {1, 2}}, {("gwalior", "service"): NOW - timedelta(days=100)})
        state = {1: pending(1), 2: pending(2)}
        for bid in state.values():
            bid.update(document_status="read", reader_version=gem_client.READER_VERSION, location_districts=["Gwalior"])
        recorded = {}
        self.run_check_steps(gem, [search()], state, memory, recorded=recorded)
        self.assertEqual(sorted(recorded[1]), [1, 2])
        gem.document.assert_not_called()

    def test_documents_are_read_closing_soonest_first_and_a_ruled_out_bid_is_dropped(self):
        gem = mock.Mock()
        gem.search.return_value = gem_client.SearchPage(total=2, rows=[listed(1), listed(2)])
        gem.document.return_value = b"%PDF"
        state = {1: pending(1, closes_in_days=20), 2: pending(2, closes_in_days=2)}
        dropped = []

        def store_document(bid_id, fields, error):
            state[bid_id].update(document_status="read", reader_version=gem_client.READER_VERSION,
                                 location_districts=["Gwalior"] if bid_id == 2 else ["Bhopal"], location_text="")

        recorded = {}
        self.run_check_steps(gem, [search()], state, store_document=store_document, recorded=recorded, dropped=dropped)
        self.assertEqual([c.args[0] for c in gem.document.call_args_list], [2, 1], "the bid closing in 2 days first")
        self.assertEqual(sorted(recorded[1]), [2])
        self.assertEqual(dropped, [1], "the work is in Bhopal")

    def test_a_search_deleted_or_changed_during_the_check_gets_nothing_recorded(self):
        """A check takes minutes: a person may delete or change a search meanwhile (this once failed the whole check)."""
        from contextlib import contextmanager

        saved = NOW - timedelta(hours=1)

        def cursor_finding(row):
            cur = mock.Mock()
            cur.fetchone.side_effect = [row, (True,)]

            @contextmanager
            def fake(commit=False):
                yield cur

            return cur, fake

        found = {7: {"matched_city": "Gwalior", "location_confirmed": True}}
        for row, expected in ((None, 0), ((NOW,), 0), ((saved,), 1)):
            cur, fake = cursor_finding(row)
            with mock.patch.object(tenders, "db_cursor", fake):
                self.assertEqual(tenders._store_matches(1, found, saved), expected, row)
            inserted = any("INSERT INTO" in str(call.args[0]) for call in cur.execute.call_args_list)
            self.assertEqual(inserted, bool(expected), row)

    def test_a_document_that_failed_is_tried_again_after_a_day_only(self):
        now = NOW
        self.assertTrue(tenders.needs_reading({"document_status": "pending"}, now))
        self.assertFalse(tenders.needs_reading({"document_status": "read", "reader_version": gem_client.READER_VERSION}, now))
        self.assertFalse(tenders.needs_reading({"document_status": "failed", "document_read_timestamp": now - timedelta(hours=2)}, now))
        self.assertTrue(tenders.needs_reading({"document_status": "failed", "document_read_timestamp": now - timedelta(hours=25)}, now))

    def test_a_document_read_by_an_older_reader_is_read_again(self):
        self.assertTrue(tenders.needs_reading({"document_status": "read", "reader_version": gem_client.READER_VERSION - 1}, NOW))
        self.assertFalse(tenders.needs_reading({"document_status": "read", "reader_version": gem_client.READER_VERSION}, NOW))

    def test_a_missing_document_is_recorded_and_the_check_goes_on(self):
        gem = mock.Mock()
        gem.search.return_value = gem_client.SearchPage(total=2, rows=[listed(1), listed(2)])
        gem.document.side_effect = [GemError("gone", "missing"), b"%PDF"]
        stored = {}
        stats = self.run_check_steps(gem, [search()], {i: pending(i) for i in (1, 2)},
                                     store_document=lambda bid_id, fields, error: stored.setdefault(bid_id, error))
        self.assertEqual(gem.document.call_count, 2, "the second document is still read")
        self.assertEqual(stats.documents_read, 1)
        self.assertEqual(sorted("ok" if error is None else error for error in stored.values()), ["gone", "ok"])

    def test_the_document_budget_is_shared_and_what_is_left_is_noted(self):
        gem = mock.Mock()
        gem.search.return_value = gem_client.SearchPage(total=3, rows=[listed(i, "Security") for i in (1, 2, 3)])
        gem.document.return_value = b"%PDF"
        with mock.patch.object(tenders, "MAX_DOCUMENTS", 2):
            stats = self.run_check_steps(gem, [search()], {i: pending(i, "Security") for i in (1, 2, 3)})
        self.assertEqual(gem.document.call_count, 2)
        self.assertIn("1 bid documents are left for the next check.", stats.notes)

    def test_a_captcha_stops_the_check_and_is_recorded_not_raised(self):
        gem = mock.Mock(requests=1)
        gem.search.side_effect = GemError("captcha", "captcha")
        with mock.patch.object(tenders, "active_searches", return_value=[search()]), \
             mock.patch.object(tenders, "_start_run", return_value=7), \
             mock.patch.object(tenders, "_coverage", return_value=None), \
             mock.patch.object(tenders, "_report"), \
             mock.patch.object(tenders, "_forget_old_bids"), \
             mock.patch.object(tenders, "_finish_run") as finish:
            self.assertEqual(tenders.run_check("gem", "manual", 1, session=gem), 7)
        self.assertEqual(finish.call_args.args[3], "captcha")
        self.assertEqual(gem.search.call_count, 1, "a captcha is not retried")

    def test_one_check_at_a_time_and_nothing_to_do_is_not_a_run(self):
        with mock.patch.object(tenders, "active_searches", return_value=[]), mock.patch.object(tenders, "_start_run") as start:
            self.assertIsNone(tenders.run_check("gem", "manual", 1, session=mock.Mock()))
        start.assert_not_called()
        tenders._locks["gem"].acquire()
        try:
            with self.assertRaises(tenders.CheckBusy):
                tenders.run_check("gem", "manual", 1, session=mock.Mock())
            with mock.patch.object(tenders, "active_searches", return_value=[]):
                self.assertIsNone(tenders.run_check("mptenders", "manual", 1, session=mock.Mock()), "MP's checks are separate from GeM's")
        finally:
            tenders._locks["gem"].release()


# Shaped like MP Tenders' real pages (mptenders.gov.in, NIC's GePNIC), cut down to what is read.
MP_ORGANISATIONS = """
<table><tr><td>S.No</td><td>Organisation Name</td><td>Tender Count</td></tr>
<tr class="even" id="informal">
 <td align="left">1</td> <td align="left">Bhopal City Link Limited</td>
 <td align="right"><a id="DirectLink" class="link2" href="/nicgep/app?component=%24DirectLink&amp;page=FrontEndTendersByOrganisation&amp;service=direct&amp;session=T&amp;sp=AAA">16</a></td>
</tr>
<tr class="odd" id="informal_0">
 <td align="left">2</td> <td align="left">Department of Higher Education</td>
 <td align="right"> <a id="DirectLink_0" class="link2" href="/nicgep/app?component=%24DirectLink&amp;page=FrontEndTendersByOrganisation&amp;service=direct&amp;session=T&amp;sp=BBB"> 44 </a> </td>
</tr></table>"""


def mp_row(number, title, tender_id, published="19-Oct-2026 09:00 AM", closing="12-Nov-2026 06:00 PM", chain="Department of Higher Education||Rewa - Govt Thakur Ranmat Singh College Rewa"):
    return f"""<tr class="even" id="informal_{number}">
 <td align="center">{number}</td> <td align="center">{published}</td> <td align="center">{closing}</td> <td align="center">14-Nov-2026 09:00 AM</td>
 <!-- <td align="center"><span jwcid="@Insert" value="ognl:currentRow.tenderRefNo" /></td> -->
 <td align="center"><a id="DirectLink_{number}" title="View Tender Information" href="/nicgep/app?component=%24DirectLink&amp;page=FrontEndViewTender&amp;service=direct&amp;session=T&amp;sp=V{number}">[{title}]</a> [4413/trs/date/07-10-26][{tender_id}] </td>
 <td align="center">{chain}</td>
</tr>"""


MP_DETAILS = """
<td class="textbold1">Tender Fee Details, [Total Fee in &#8377; <span class="mandatory">*</span> - 1,475]</td>
<tr><td class="td_caption" width="35%">Tender Fee in &#8377; </td> <td class="td_field" valign="top">1,180</td></tr>
<tr><td class="td_caption">Tender Fee Exemption Allowed</td><td class="td_field">No</td></tr>
<tr><td class="td_caption">EMD Amount in &#8377;</td><td class="td_field">10,000</td></tr>
<tr><td class="td_caption">EMD Exemption Allowed</td><td class="td_field">Yes</td></tr>
<tr><td class="td_caption">Title</td><td class="td_field">Security guard services at college campus</td></tr>
<tr><td class="td_caption">Work Description</td><td class="td_field">Providing 12 unarmed security guards</td></tr>
<tr><td class="td_caption">Tender Value in &#8377;</td><td class="td_field">18,50,000</td></tr>
<tr><td class="td_caption">Product Category</td><td class="td_field">Security Services</td></tr>
<tr><td class="td_caption">Tender Category</td><td class="td_field">Services</td></tr>
<tr><td class="td_caption">Period Of Work(Days)</td><td class="td_field">365</td></tr>
<tr><td class="td_caption">Location</td><td class="td_field">PRINCIPAL TRS COLLEGE REWA MP</td></tr>
<tr><td class="td_caption">Pincode</td><td class="td_field">486001</td></tr>
"""


class ReadingMpTenders(unittest.TestCase):
    def test_the_organisations_and_their_links(self):
        found = mptenders_client.organisations(MP_ORGANISATIONS)
        self.assertEqual([(o.name, o.count) for o in found], [("Bhopal City Link Limited", 16), ("Department of Higher Education", 44)])
        self.assertIn("&sp=BBB", found[1].link)
        self.assertNotIn("&amp;", found[1].link)

    def test_an_organisations_tenders_despite_the_commented_out_column(self):
        rows = mptenders_client.tender_rows("<table>" + mp_row(1, "desktop computer", "2026_HED_543972_1") + "</table>")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["source_ref"], row["title"], row["reference"]), ("2026_HED_543972_1", "desktop computer", "4413/trs/date/07-10-26"))
        self.assertEqual((row["ministry"], row["department"]), ("Department of Higher Education", "Rewa - Govt Thakur Ranmat Singh College Rewa"))
        self.assertEqual(row["end_timestamp"].isoformat(), "2026-11-12T18:00:00+05:30")
        self.assertIn("page=FrontEndViewTender", row["details_link"])

    def test_a_tenders_details_give_fees_value_kind_and_place(self):
        found = mptenders_client.details(MP_DETAILS)
        self.assertEqual((found["tender_fee"], found["tender_fee_total"], found["tender_fee_exempt"]), (Decimal("1180"), Decimal("1475"), False))
        self.assertEqual((found["emd_amount"], found["emd_exempt"]), (Decimal("10000"), True))
        self.assertEqual(found["estimated_value"], Decimal("1850000"))
        self.assertEqual((found["category"], found["tender_category"], found["contract_period"]), ("Security Services", "Services", "365 days"))
        self.assertEqual(found["pincode"], "486001")
        self.assertEqual(mptenders_client.district_of(found["pincode"]), ["Rewa"])

    def test_not_applicable_is_nothing_and_an_expired_visit_is_noticed(self):
        self.assertIsNone(mptenders_client.rupees("NA"))
        self.assertTrue(mptenders_client.stale("<h1>Stale Session</h1> Your session has timed out."))


class MpTendersInACheck(unittest.TestCase):
    def test_tenders_whose_title_fits_are_opened_and_decided_by_their_pin(self):
        mp = mock.Mock(requests=0)
        mp.open.return_value = mptenders_client.organisations(MP_ORGANISATIONS)[1:]
        org_page = "<table>" + mp_row(1, "Security guard services at college campus", "2026_HED_1_1") + mp_row(2, "desktop computer", "2026_HED_2_1") + "</table>"
        mp.page.side_effect = lambda link: MP_DETAILS if "FrontEndViewTender" in link else org_page
        state = {}

        def store_listing(rows, stats):
            ids = {}
            for i, row in enumerate(rows, start=1):
                ids[row["source_ref"]] = 10**12 + i
                state.setdefault(10**12 + i, {"bid_id": 10**12 + i, "category": None, "title": row["title"], "estimated_value": None,
                                              "location_text": None, "document_status": "pending", "location_districts": [],
                                              "end_timestamp": row["end_timestamp"], "source": "mptenders", "tender_category": None,
                                              "match_text": row["title"]})
            return ids

        def store_details(bid_id, fields, chain):
            state[bid_id].update(document_status="read", reader_version=gem_client.READER_VERSION, estimated_value=fields["estimated_value"],
                                 tender_category=fields["tender_category"], location_text=fields["location_text"] + " " + chain,
                                 location_districts=mptenders_client.district_of(fields["pincode"]),
                                 match_text=" ".join(x for x in (fields["title"], fields["category"], fields["work_description"]) if x))

        recorded = {}
        searches = [search(portal="mptenders", cities=["Rewa"], tender_types=["security"]),
                    search(search_id=2, portal="mptenders", cities=["Bhopal"], tender_types=["security"])]
        with mock.patch.object(tenders, "_store_mp_listing", side_effect=store_listing), \
             mock.patch.object(tenders, "_store_mp_details", side_effect=store_details), \
             mock.patch.object(tenders, "_bids", side_effect=lambda ids: {i: dict(state[i]) for i in ids if i in state}), \
             mock.patch.object(tenders, "_store_matches", side_effect=lambda sid, found, saved_at=None: recorded.setdefault(sid, {}).update(found) or len(found)):
            tenders._check_mp(mp, searches, tenders.RunStats())
        opened = [c.args[0] for c in mp.page.call_args_list if "FrontEndViewTender" in c.args[0]]
        self.assertEqual(len(opened), 1, "only the security tender's details, not the desktop computer's")
        self.assertEqual(list(recorded), [1], "Rewa's search found it; Bhopal's did not")
        self.assertEqual(recorded[1][10**12 + 1], {"matched_city": "Rewa", "location_confirmed": True})

    def test_the_kind_of_bid_follows_mp_tenders_category(self):
        bid = {"source": "mptenders", "tender_category": "Works", "match_text": "Security guard", "document_status": "read",
               "estimated_value": None, "location_districts": ["Rewa"]}
        self.assertIsNone(tenders.decide(search(cities=["Rewa"], tender_types=["security"], bid_kind="service"), bid, set()))
        self.assertIsNotNone(tenders.decide(search(cities=["Rewa"], tender_types=["security"], bid_kind="all"), bid, set()))

    def test_a_search_belongs_to_one_portal_and_its_kinds_are_that_portals(self):
        base = {"name": "x", "tender_types": ["security"], "cities": ["Rewa"]}
        self.assertEqual(tenders._clean_search({**base, "bid_kind": "works"}, "mptenders")["portal"], "mptenders")
        with self.assertRaises(tenders.TenderError):
            tenders._clean_search({**base, "bid_kind": "works"}, "gem")  # GeM has no works
        with self.assertRaises(tenders.TenderError):
            tenders._clean_search({**base, "tender_types": []}, "mptenders")  # MP needs a tender type
        with self.assertRaises(tenders.TenderError):
            tenders.portal_of("cppp")
        self.assertEqual(tenders.MP_CATEGORY_FOR_KIND["works"], "works")


class WhoMaySeeAndChange(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        self.addCleanup(app.dependency_overrides.clear)

    def routes(self):
        found = []
        for route in tenders_router.router.routes:
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                found.append((method, "/api" + route.path))
        return found

    def call(self, method, path):
        concrete = path.replace("{search_id}", "1").replace("{bid_id}", "1")
        body = {"name": "x", "tender_types": ["security"], "status": "shortlisted"} if method in ("POST", "PUT") else None
        return TestClient(app).request(method, concrete, json=body)

    def test_every_route_is_guarded_and_changing_needs_the_change_flag(self):
        from tests.test_access import guards

        found = guards(tenders_router.router)
        self.assertGreaterEqual(len(found), 7)
        for route, names in found.items():
            self.assertEqual(len(names & {"require_tenders", "require_tenders_write"}), 1, f"{route} is guarded by {names}")
            self.assertIn("require_tenders" if route.startswith("GET ") else "require_tenders_write", names, route)

    def test_nobody_signed_out_and_nobody_without_the_flag_gets_anything(self):
        for method, path in self.routes():
            self.assertIn(self.call(method, path).status_code, (401, 403), f"{method} {path}")
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "admin", "tenders_access": False, "tenders_write": False}
        for method, path in self.routes():
            self.assertEqual(self.call(method, path).status_code, 403, f"{method} {path}")

    def test_a_person_who_can_only_look_cannot_change_anything(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "tenders_access": True, "tenders_write": False}
        for method, path in self.routes():
            if method != "GET":
                self.assertEqual(self.call(method, path).status_code, 403, f"{method} {path}")

    def test_a_mistake_is_a_400_a_missing_search_a_404_and_a_running_check_a_409(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "tenders_access": True, "tenders_write": True}
        client = TestClient(app)
        with mock.patch.object(tenders, "create_search", side_effect=tenders.TenderError("no")):
            self.assertEqual(client.post("/api/tenders/searches", json={"name": "x"}).status_code, 400)
        with mock.patch.object(tenders, "update_search", side_effect=LookupError("gone")):
            self.assertEqual(client.put("/api/tenders/searches/9", json={"name": "x"}).status_code, 404)
        with mock.patch.object(tenders, "start_check", side_effect=tenders.CheckBusy("busy")):
            self.assertEqual(client.post("/api/tenders/check").status_code, 409)

    def test_the_flags_follow_the_pattern_of_the_other_areas(self):
        self.assertIn(("tenders_write", "tenders_access"), auth.WRITE_IMPLIES_ACCESS)
        self.assertTrue(auth.can_access_tenders({"role": "editor"}))
        self.assertFalse(auth.can_access_tenders({"role": "viewer"}))
        self.assertTrue(auth.can_access_page({"role": "viewer", "tenders_access": True}, "tenders"))
        self.assertFalse(auth.can_write_tenders({"role": "admin", "tenders_access": True, "tenders_write": False}))


if __name__ == "__main__":
    unittest.main()
