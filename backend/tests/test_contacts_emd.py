"""Contacts at clients, and the EMDs deposited for cases: the rules on their forms, their documents, and where they reach the warehouse and dashboards.
No database is needed."""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import dw_sync, emd_documents as docs  # noqa: E402
from app.dashboard import explore, records  # noqa: E402
from app.dashboard.filters import SCOPES  # noqa: E402
from app.entities import (  # noqa: E402
    CONTACT_METHODS, CONTACT_ROLES, CONTACT_STATUSES, CONTACTS_EMD_MIGRATE, EMD_MODES, EMD_OPEN_STATUSES, EMD_STATUSES, ENTITIES, MERGE_KEYS,
    invalid_reason,
)
from app.payload import PayloadError, clean_payload  # noqa: E402

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


def check_in_sql(constraint: str) -> list[str]:
    """The values a CHECK constraint of the migration allows, read from the SQL itself."""
    sql = CONTACTS_EMD_MIGRATE.read_text(encoding="utf-8")
    found = re.search(rf"CONSTRAINT {constraint}\s+CHECK \((.*?)\)\s*(?:,|\))", sql, re.S)
    assert found, constraint
    return re.findall(r"'([^']+)'", found.group(1))


class TheListsMatchTheDatabase(unittest.TestCase):
    def test_every_choice_on_a_form_is_one_the_database_accepts(self):
        for constraint, options in (
            ("contact_role_known", CONTACT_ROLES), ("contact_status_known", CONTACT_STATUSES), ("contact_method_known", CONTACT_METHODS),
            ("emd_mode_known", EMD_MODES), ("emd_status_known", EMD_STATUSES),
        ):
            self.assertEqual(sorted(check_in_sql(constraint)), sorted(options), constraint)

    def test_the_forms_offer_those_lists(self):
        contact, emd = ENTITIES["Contact"]["form_fields"], ENTITIES["EMD"]["form_fields"]
        self.assertEqual(contact["contact_role"]["options"], CONTACT_ROLES)
        self.assertEqual(contact["contact_status"]["options"], CONTACT_STATUSES)
        self.assertEqual(emd["payment_mode"]["options"], EMD_MODES)
        self.assertEqual(emd["emd_status"]["options"], EMD_STATUSES)

    def test_an_emd_still_out_is_one_of_the_statuses(self):
        for status in EMD_OPEN_STATUSES:
            self.assertIn(status, EMD_STATUSES)

    def test_the_dashboards_and_the_database_agree_on_which_emds_are_out(self):
        from app.dashboard import views_ops

        for status in EMD_OPEN_STATUSES:
            self.assertIn(f"'{status}'", views_ops.EMD_OPEN)
            self.assertIn(f"'{status}'", explore._EMD_OPEN)
        for status in EMD_STATUSES:
            if status not in EMD_OPEN_STATUSES:
                self.assertNotIn(f"'{status}'", views_ops.EMD_OPEN)


class TheContactForm(unittest.TestCase):
    entity = ENTITIES["Contact"]

    def test_a_contact_needs_a_client_and_a_name(self):
        for missing in ("client_code", "contact_name"):
            data = {"client_code": "CL-0001", "contact_name": "Asha Rao", "contact_status": "Active", "is_primary_contact": "No"}
            data.pop(missing)
            with self.assertRaises(PayloadError, msg=missing):
                clean_payload(self.entity, data)

    def test_email_and_phone_are_trimmed_and_a_bad_one_is_refused(self):
        cleaned = clean_payload(self.entity, {
            "client_code": "CL-0001", "contact_name": "Asha Rao", "contact_status": "Active", "is_primary_contact": "No",
            "email": " Asha@Example.COM ", "phone": "98765 43210",
        })
        self.assertEqual((cleaned["email"], cleaned["phone"]), ("Asha@Example.COM", "98765 43210"))
        for field, bad in (("email", "not an email"), ("phone", "12")):
            with self.assertRaises(PayloadError, msg=field):
                clean_payload(self.entity, {
                    "client_code": "CL-0001", "contact_name": "Asha Rao", "contact_status": "Active", "is_primary_contact": "No", field: bad,
                })

    def test_a_contact_cannot_have_left_before_it_began_and_a_primary_one_must_be_active(self):
        self.assertIn("cannot be before", invalid_reason("Contact", None, {"contact_start_date": "2026-05-01", "contact_end_date": "2026-01-01"}))
        self.assertIn("primary", invalid_reason("Contact", None, {"is_primary_contact": "Yes", "contact_status": "Inactive"}).lower())
        self.assertIsNone(invalid_reason("Contact", None, {"is_primary_contact": "Yes", "contact_status": "Active", "contact_start_date": "2026-01-01"}))

    def test_the_same_person_at_the_same_client_is_one_contact(self):
        self.assertEqual(MERGE_KEYS["Contact"], ["client_code", "contact_name"])


class TheEmdForm(unittest.TestCase):
    entity = ENTITIES["EMD"]
    base = {"case_code": "CS-0001", "emd_amount": "2,50,000", "deposit_date": "2026-03-02", "emd_status": "Deposited"}

    def test_money_fields_are_typed_with_commas_and_kept_as_plain_numbers(self):
        self.assertEqual(clean_payload(self.entity, dict(self.base))["emd_amount"], 250000.0)
        for field in ("emd_amount", "refund_amount", "deduction_amount"):
            self.assertTrue(self.entity["form_fields"][field].get("money"), field)

    def test_the_amount_must_be_more_than_zero_and_a_refund_cannot_be_negative(self):
        with self.assertRaises(PayloadError):
            clean_payload(self.entity, {**self.base, "emd_amount": 0})
        with self.assertRaises(PayloadError):
            clean_payload(self.entity, {**self.base, "refund_amount": -5})

    def test_a_case_and_a_deposit_day_are_required(self):
        for missing in ("case_code", "deposit_date", "emd_amount", "emd_status"):
            data = dict(self.base)
            data.pop(missing)
            with self.assertRaises(PayloadError, msg=missing):
                clean_payload(self.entity, data)

    def test_what_comes_back_and_what_is_kept_cannot_be_more_than_was_paid(self):
        cleaned = {"emd_amount": 1000, "refund_amount": 800, "deduction_amount": 300}
        self.assertIn("together cannot be more", invalid_reason("EMD", None, cleaned))
        self.assertIsNone(invalid_reason("EMD", None, {"emd_amount": 1000, "refund_amount": 700, "deduction_amount": 300}))

    def test_an_amount_left_out_of_an_update_is_read_from_the_stored_record(self):
        stored = {"emd_amount": 1000, "deduction_amount": 200}
        self.assertIn("together cannot be more", invalid_reason("EMD", "EMD-0001", {"refund_amount": 900}, stored))

    def test_a_refunded_emd_says_when_the_refund_came(self):
        self.assertIn("refund was received", invalid_reason("EMD", None, {"emd_status": "Refunded"}))
        self.assertIsNone(invalid_reason("EMD", None, {"emd_status": "Refunded", "refund_received_date": "2026-09-01"}))

    def test_an_instrument_cannot_lapse_before_it_was_issued(self):
        self.assertIsNotNone(invalid_reason("EMD", None, {"instrument_date": "2026-03-01", "valid_until": "2026-02-01"}))
        self.assertIsNotNone(invalid_reason("EMD", None, {"deposit_date": "2026-03-01", "valid_until": "2026-02-01"}))


class TheDocuments(unittest.TestCase):
    def test_a_receipt_is_kept_with_its_type_worked_out_from_the_file(self):
        kept = docs.check_upload("dd.pdf", PDF, "Demand draft copy", None)
        self.assertEqual((kept["content_type"], kept["doc_type"]), ("application/pdf", "Demand draft copy"))
        self.assertEqual(docs.check_upload("receipt.png", PNG, "Payment receipt or acknowledgement", " Bank  receipt ")["title"], "Bank receipt")

    def test_a_file_must_be_what_its_name_says_and_of_a_kind_that_is_kept(self):
        for name, data in (("scan.pdf", b"MZ\x90\x00"), ("scan.png", PDF), ("page.html", b"<script>"), ("run.exe", b"MZ"), ("noextension", PDF)):
            with self.assertRaises(docs.DocumentError, msg=name):
                docs.check_upload(name, data, "Other", "x")

    def test_an_unknown_kind_an_empty_file_and_an_unnamed_other_are_refused(self):
        for args in (("a.pdf", PDF, "Aadhaar card", None), ("a.pdf", b"", "Other", "x"), ("a.pdf", PDF, "Other", "  ")):
            with self.assertRaises(docs.DocumentError, msg=args):
                docs.check_upload(*args)

    def test_a_file_over_the_limit_is_refused(self):
        with self.assertRaises(docs.DocumentError):
            docs.check_upload("a.pdf", PDF + b"0" * docs.MAX_BYTES, "Other", "x")

    def test_every_route_needs_a_permission_and_changes_need_the_write_one(self):
        from app.routers import emd_documents_router

        for route in emd_documents_router.router.routes:
            names = {dep.call.__name__ for dep in route.dependant.dependencies}
            self.assertTrue(names & {"require_ods", "require_ods_write"}, route.path)
            if route.methods & {"POST", "DELETE"} or route.path.endswith("document-options"):
                self.assertIn("require_ods_write", names, route.path)

    def test_the_kinds_of_document_are_the_same_in_the_table_and_the_code(self):
        sql = CONTACTS_EMD_MIGRATE.read_text(encoding="utf-8")
        self.assertIn("emd_document", sql)
        self.assertEqual(docs.DOC_TYPES[-1], "Other")


class TheWarehouse(unittest.TestCase):
    def test_contacts_and_emds_are_loaded_and_their_private_details_are_not(self):
        contact = dw_sync.TABLES["Contact"]
        for column in ("email", "phone", "alternate_phone", "address", "notes"):
            self.assertNotIn(column, contact["dw_cols"], column)
        self.assertIn("contact_status", contact["dw_cols"])
        self.assertEqual(dw_sync.TABLES["EMD"]["kind"], "fact")
        self.assertLess(dw_sync.REFRESH_ORDER.index("Client"), dw_sync.REFRESH_ORDER.index("Contact"))
        self.assertLess(dw_sync.REFRESH_ORDER.index("Case"), dw_sync.REFRESH_ORDER.index("EMD"))

    def test_the_calendar_reaches_the_day_an_emd_was_deposited(self):
        self.assertIn(("orion_ods.emd", "deposit_date"), dw_sync._FACT_DATES)


class TheDashboards(unittest.TestCase):
    def test_the_new_scopes_carry_the_case_and_client_dimensions(self):
        for scope in ("emd", "contact"):
            for key in ("client", "case", "state", "client_type", "priority", "case_status"):
                self.assertIn(key, SCOPES[scope]["fields"], f"{scope} lacks {key}")

    def test_cancelled_emds_never_count_as_money_out(self):
        self.assertTrue(any("Cancelled" in part for part in SCOPES["emd"]["base"]))

    def test_every_new_record_set_reads_a_scope_that_exists(self):
        for key in ("emds", "emds_open", "emds_overdue", "emds_not_returned", "contacts", "contacts_follow_up"):
            self.assertIn(records.DATASETS[key]["scope"], SCOPES, key)
            self.assertEqual(records.DATASETS[key]["needs"], "ods", key)

    def test_the_tiles_open_the_rows_they_add_up(self):
        for key, dataset in (("emd_held", "emds"), ("emd_overdue", "emds"), ("emd_lost", "emds"), ("contact_follow_ups", "contacts")):
            extra, _cancelled = explore.record_context(key, dataset)
            self.assertTrue(extra, key)
            self.assertIn(dataset, {d for d, _label in explore.MEASURES[key].records})


if __name__ == "__main__":
    unittest.main()
