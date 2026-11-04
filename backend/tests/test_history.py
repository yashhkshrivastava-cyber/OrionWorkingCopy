"""Record history: comparing warehouse versions, and the pieces that feed it.

Run from the repo root:  python -m pytest backend/tests
"""

import inspect
import re
import sys
import unittest
from unittest import mock
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import db_utils, dw_auto, dw_sync  # noqa: E402
from app.entities import ENTITIES, invalid_reason  # noqa: E402
from app.record_history import apply_lookup_labels, diff_versions  # noqa: E402

from test_contracts import SCHEMA  # noqa: E402

LABELS = {"client_name": "Client Name", "gstin": "GSTIN", "amount": "Amount", "start": "Start date"}


def when(day: int) -> datetime:
    return datetime(2026, 10, day, 10, 0, tzinfo=timezone.utc)


def version(**kw):
    base = {
        "client_name": "Acme", "gstin": None, "amount": Decimal("100.00"), "start": date(2026, 1, 1),
        "source_created_timestamp": when(1), "source_last_updated_timestamp": when(1),
        "source_created_by": 1, "source_last_updated_by": 1, "effective_from": when(1), "is_expired": False,
    }
    return {**base, **kw}


class Comparing(unittest.TestCase):
    def test_one_version_is_just_a_creation(self):
        entries = diff_versions([version()], LABELS)
        self.assertEqual([(e["kind"], e["by_id"], e["changes"]) for e in entries], [("created", 1, [])])

    def test_a_change_lists_each_field_that_differs_with_who_and_when(self):
        entries = diff_versions(
            [version(), version(gstin="23ABCDE1234F1Z5", client_name="Acme Ltd", source_last_updated_by=2,
                                source_last_updated_timestamp=when(3))],
            LABELS,
        )
        self.assertEqual([e["kind"] for e in entries], ["changed", "created"])
        changed = entries[0]
        self.assertEqual(changed["by_id"], 2)
        self.assertEqual(changed["when"], when(3).isoformat())
        self.assertEqual(
            [(c["label"], c["from"], c["to"]) for c in changed["changes"]],
            [("Client Name", "Acme", "Acme Ltd"), ("GSTIN", None, "23ABCDE1234F1Z5")],
        )

    def test_the_same_value_written_another_way_is_not_a_change(self):
        entries = diff_versions(
            [version(), version(amount=Decimal("100"), client_name="  Acme ", source_last_updated_timestamp=when(2))], LABELS
        )
        self.assertEqual(entries[0]["changes"], [])

    def test_money_and_dates_are_sent_as_plain_values(self):
        entries = diff_versions([version(), version(amount=Decimal("250.50"), start=date(2026, 2, 1))], LABELS)
        self.assertEqual(
            [(c["field"], c["from"], c["to"]) for c in entries[0]["changes"]],
            [("amount", 100.0, 250.5), ("start", "2026-01-01", "2026-02-01")],
        )

    def test_columns_that_are_not_labelled_are_not_compared(self):
        entries = diff_versions([version(), version(client_status="Inactive")], LABELS)
        self.assertEqual(entries[0]["changes"], [])

    def test_a_deleted_record_ends_with_who_deleted_it(self):
        entries = diff_versions(
            [version(), version(is_expired=True, expired_by=3, expired_when=when(9), source_last_updated_timestamp=when(1))],
            LABELS,
        )
        self.assertEqual([e["kind"] for e in entries], ["deleted", "changed", "created"])
        self.assertEqual((entries[0]["by_id"], entries[0]["when"]), (3, when(9).isoformat()))

    def test_a_row_saved_before_tracking_has_no_user(self):
        entries = diff_versions([version(source_created_by=None, source_last_updated_by=None)], LABELS)
        self.assertIsNone(entries[0]["by_id"])

    def test_nothing_in_the_warehouse_is_no_history(self):
        self.assertEqual(diff_versions([], LABELS), [])


class LookupNames(unittest.TestCase):
    """A change to a lookup field is stored as a code but read as a name."""

    def entries(self, old, new):
        return diff_versions([version(head=old), version(head=new)], {"head": "Capability Head"})

    def test_codes_get_names_and_keep_the_code(self):
        entries = self.entries("EMP-0001", "EMP-0002")
        apply_lookup_labels(entries, {"head": {"EMP-0001": "Anita Rao", "EMP-0002": "Ravi Shah"}})
        change = entries[0]["changes"][0]
        self.assertEqual((change["from"], change["to"]), ("EMP-0001", "EMP-0002"))
        self.assertEqual((change["from_label"], change["to_label"]), ("Anita Rao (EMP-0001)", "Ravi Shah (EMP-0002)"))

    def test_an_empty_side_has_no_label_and_a_missing_row_is_said_so(self):
        entries = self.entries(None, "EMP-0009")
        apply_lookup_labels(entries, {"head": {}})
        change = entries[0]["changes"][0]
        self.assertNotIn("from_label", change)
        self.assertEqual(change["to_label"], "EMP-0009 (no longer exists)")

    def test_a_name_that_already_carries_the_code_is_not_given_it_twice(self):
        entries = self.entries("CL-0001", None)
        apply_lookup_labels(entries, {"head": {"CL-0001": "Head Office — CL-0001"}})
        self.assertEqual(entries[0]["changes"][0]["from_label"], "Head Office — CL-0001")

    def test_a_field_that_is_not_a_lookup_is_left_alone(self):
        entries = self.entries("a", "b")
        apply_lookup_labels(entries, {"other": {}})
        self.assertNotIn("to_label", entries[0]["changes"][0])


class CapabilityHead(unittest.TestCase):
    """The head is an employee, chosen by name and stored by code, and it reaches the warehouse."""

    def test_the_form_picks_an_employee_and_stores_the_code(self):
        fields = ENTITIES["Capability"]["form_fields"]
        self.assertNotIn("capability_head", fields)
        head = fields["capability_head_code"]
        self.assertEqual(head["type"], "select")
        self.assertEqual(head["source_table"], "orion_ods.employee")
        self.assertEqual((head["source_pk_column"], head["source_display_column"]), ("employee_code", "employee_name"))

    def test_the_warehouse_versions_the_code_not_the_old_text(self):
        spec = dw_sync.TABLES["Capability"]
        self.assertIn("capability_head_code", spec["compare"])
        self.assertNotIn("capability_head", spec["ods_cols"])
        self.assertNotIn("capability_head", spec["dw_cols"])

    def test_the_old_text_column_is_gone_from_both_schemas_and_dropped_from_existing_databases(self):
        self.assertNotIn("capability_head", SCHEMA["orion_ods.capability"])
        self.assertNotIn("capability_head", SCHEMA["orion_dw.dim_capability"])
        self.assertIn("capability_head_code", SCHEMA["orion_ods.capability"] | SCHEMA["orion_dw.dim_capability"])
        for name in ("migrate_capability_head.sql", "dw_schema.sql"):
            text = (ROOT / ".cursor" / "db" / name).read_text(encoding="utf-8")
            self.assertIn("DROP COLUMN capability_head;", text, name)


class ClientGroup(unittest.TestCase):
    """A client's group is another client, chosen as "name — code", stored by code, and it reaches the warehouse."""

    def test_the_form_picks_a_client_and_stores_its_code(self):
        group = ENTITIES["Client"]["form_fields"]["client_group_code"]
        self.assertEqual((group["type"], group["source_table"], group["source_pk_column"]), ("select", "orion_ods.client", "client_code"))
        self.assertTrue(group["optional"])
        self.assertNotIn("required", group)
        # The option reads "name — code". The Excel upload splits on that dash to accept the name alone.
        self.assertIn("client_name", group["source_display_column"])
        self.assertIn("client_code", group["source_display_column"])
        self.assertIn("' — '", group["source_display_column"])

    def test_the_column_is_in_the_working_copy_and_the_warehouse(self):
        self.assertIn("client_group_code", SCHEMA["orion_ods.client"])
        self.assertIn("client_group_code", SCHEMA["orion_dw.dim_client"])

    def test_the_warehouse_versions_it(self):
        spec = dw_sync.TABLES["Client"]
        for part in ("ods_cols", "dw_cols", "compare"):
            self.assertIn("client_group_code", spec[part], part)

    def test_existing_databases_get_the_column_at_startup(self):
        from app import entities

        sql = entities.CLIENT_GROUP_MIGRATE.read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS client_group_code", sql)
        self.assertIn(entities.CLIENT_GROUP_MIGRATE, entities.SQL_MIGRATIONS)  # applied (and recorded) at every start by app.migrate
        warehouse = (ROOT / ".cursor" / "db" / "dw_schema.sql").read_text(encoding="utf-8")
        self.assertIn("ALTER TABLE orion_dw.dim_client ADD COLUMN IF NOT EXISTS client_group_code", warehouse)

    def test_a_client_is_never_its_own_group(self):
        # The loop check reads the database; this test is about the rules that need no database, so it is stubbed (CI has none).
        with mock.patch("app.entities._chain_reaches", return_value=False):
            self.assertIsNotNone(invalid_reason("Client", "CL-0007", {"client_group_code": "CL-0007"}))
            self.assertIsNotNone(invalid_reason("Client", "CL-0007", {"client_group_code": " CL-0007 "}))
            self.assertIsNone(invalid_reason("Client", "CL-0007", {"client_group_code": "CL-0002"}))
            self.assertIsNone(invalid_reason("Client", "CL-0007", {"client_group_code": None}))
            self.assertIsNone(invalid_reason("Client", "CL-0007", {"client_name": "No group sent"}))
            self.assertIsNone(invalid_reason("Client", None, {"client_group_code": "CL-0002"}))  # a new client has no code yet
            self.assertIsNone(invalid_reason("Case", "CS-0001", {"client_group_code": "CS-0001"}))
        with mock.patch("app.entities._chain_reaches", return_value=True):
            self.assertIn("circle", invalid_reason("Client", "CL-0007", {"client_group_code": "CL-0002"}))
        self.assertIn("client_group_not_self", (ROOT / ".cursor" / "db" / "migrate_client_group.sql").read_text(encoding="utf-8"))


class AutoLoadSetting(unittest.TestCase):
    def setUp(self):
        self._env = dw_auto.env

    def tearDown(self):
        dw_auto.env = self._env

    def minutes(self, raw):
        dw_auto.env = lambda name, default="": raw
        return dw_auto.autoload_minutes()

    def test_it_is_an_hour_unless_set(self):
        self.assertEqual(self.minutes(str(dw_auto.DEFAULT_MINUTES)), 60)
        self.assertEqual(self.minutes("15"), 15)

    def test_zero_turns_it_off_and_nonsense_falls_back(self):
        self.assertEqual(self.minutes("0"), 0)
        self.assertEqual(self.minutes("-5"), 0)
        self.assertEqual(self.minutes("soon"), 60)


class WhoIsRecorded(unittest.TestCase):
    """If a write path forgets the user, history silently shows no name. These keep that from happening."""

    def test_every_loaded_table_has_the_audit_columns_on_both_sides(self):
        for name, spec in dw_sync.TABLES.items():
            if "ods" not in spec:
                continue
            for column in spec["audit"]:
                self.assertIn(column, SCHEMA[spec["ods"]], f"{name}: {spec['ods']} has no {column}")
            for column in ("source_created_by", "source_last_updated_by", "expired_by"):
                self.assertIn(column, SCHEMA[spec["dw"]], f"{name}: {spec['dw']} has no {column}")

    def test_the_write_helpers_take_the_user(self):
        for function in (db_utils.insert, db_utils.update, db_utils.upsert_many, db_utils.delete_record):
            self.assertIn("user_id", inspect.signature(function).parameters, function.__name__)

    def test_the_record_routes_pass_the_user_on(self):
        text = (ROOT / "backend" / "app" / "routers" / "entities_router.py").read_text(encoding="utf-8")
        # create, edit and delete hand the user to the shared service; the Excel upload passes it to the database layer itself
        self.assertEqual(len(re.findall(r'entity_service\.(?:create|change|remove)\(name,.*user\["id"\]', text)), 3)
        self.assertEqual(text.count("user_id=user["), 1)
        # and the service (which the AI assistant's tools also use) passes it on to the insert, update and delete
        service = (ROOT / "backend" / "app" / "entity_service.py").read_text(encoding="utf-8")
        self.assertEqual(service.count("user_id=user_id"), 4)  # the insert (twice: on its own, and together with its payment), the update and the delete

    def test_billing_records_who_on_every_revenue_entry_it_writes(self):
        text = (ROOT / "backend" / "app" / "billing.py").read_text(encoding="utf-8")
        updates = re.findall(r"UPDATE orion_ods\.case_transaction(.*?)WHERE", text, re.S)
        inserts = re.findall(r"INSERT INTO orion_ods\.case_transaction \((.*?)\)\s*VALUES", text, re.S)
        self.assertTrue(updates and inserts)
        for body in updates:
            self.assertIn("last_updated_by", body)
        for body in inserts:
            self.assertIn("created_by", body)
            self.assertIn("last_updated_by", body)

    def test_client_billing_details_are_versioned(self):
        attrs = dw_sync.TABLES["Client"]["compare"]
        for column in ("billing_name", "gstin", "billing_address"):
            self.assertIn(column, attrs)


if __name__ == "__main__":
    unittest.main()
