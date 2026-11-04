"""Who may see and change each segment: the flags, their defaults, and that every route is guarded by its own.

None of this needs a database. Run from the repo root:  python -m pytest backend/tests
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import auth, dependencies  # noqa: E402
from app.routers import bank_router, billing_router, etl_router, users_router  # noqa: E402


def guards(router):
    """The permission dependency of every route of a router, by function name."""
    found = {}
    for route in router.routes:
        names = {dep.call.__name__ for dep in route.dependant.dependencies}
        found[f"{sorted(route.methods)[0]} {route.path}"] = names
    return found


class Flags(unittest.TestCase):
    def test_billing_and_etl_are_segments_with_a_view_and_a_change_flag(self):
        for flag in ("billing_access", "billing_write", "etl_access", "etl_write"):
            self.assertIn(flag, auth.ACCESS_FLAGS)

    def test_changing_implies_seeing(self):
        access = auth._resolved_access("viewer", billing_write=True, etl_write=True, ods_write=True)
        self.assertTrue(access["billing_access"] and access["etl_access"] and access["ods_access"])

    def test_a_flag_left_out_takes_the_role_default(self):
        self.assertTrue(auth._resolved_access("admin")["etl_write"])
        self.assertFalse(auth._resolved_access("viewer")["etl_access"])
        self.assertFalse(auth._resolved_access("viewer", etl_access=None)["billing_access"])
        self.assertFalse(auth._resolved_access("admin", etl_write=False)["etl_write"])

    def test_an_unknown_flag_is_refused(self):
        with self.assertRaises(TypeError):
            auth._resolved_access("viewer", etl_acess=True)

    def test_every_role_has_a_default_for_every_flag(self):
        for role, defaults in auth.ROLE_DEFAULT_DATA_ACCESS.items():
            self.assertEqual(set(defaults), set(auth.ACCESS_FLAGS), role)

    def test_every_write_flag_names_the_access_flag_it_implies(self):
        for write, access in auth.WRITE_IMPLIES_ACCESS:
            self.assertIn(write, auth.ACCESS_FLAGS)
            self.assertIn(access, auth.ACCESS_FLAGS)

    def test_the_admin_form_and_the_user_columns_list_every_flag(self):
        self.assertEqual(set(users_router.AccessFlags.model_fields), set(auth.ACCESS_FLAGS))
        for flag in auth.ACCESS_FLAGS:
            self.assertIn(flag, auth.USER_SELECT_COLUMNS)
        keys = (ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
        listed = re.search(r"ACCESS_FLAG_KEYS = \[(.*?)\] as const", keys, re.S).group(1)
        self.assertEqual(re.findall(r"'([a-z_]+)'", listed), list(auth.ACCESS_FLAGS))


class Segments(unittest.TestCase):
    def test_billing_follows_its_own_flags_not_operational_data(self):
        user = {"role": "editor", "ods_access": True, "ods_write": True, "billing_access": False, "billing_write": False}
        self.assertFalse(auth.can_access_billing(user))
        self.assertFalse(auth.can_access_page(user, "utility"))
        user = {"role": "viewer", "ods_access": False, "billing_access": True, "billing_write": False}
        self.assertTrue(auth.can_access_page(user, "utility"))
        self.assertFalse(auth.can_write_billing(user))

    def test_etl_follows_its_own_flags_not_the_warehouse_ones(self):
        user = {"role": "admin", "dw_access": True, "dw_write": True, "etl_access": False, "etl_write": False}
        self.assertFalse(auth.can_access_etl(user))
        self.assertFalse(auth.can_access_page(user, "etl"))
        user = {"role": "viewer", "dw_access": False, "etl_access": True, "etl_write": True}
        self.assertTrue(auth.can_access_page(user, "etl"))
        self.assertTrue(auth.can_write_etl(user))

    def test_a_user_record_without_the_new_flags_falls_back_to_what_it_used_to_follow(self):
        old = {"role": "editor", "ods_access": True, "ods_write": True, "dw_access": True, "dw_write": True}
        self.assertTrue(auth.can_write_billing(old))
        self.assertTrue(auth.can_write_etl(old))
        self.assertFalse(auth.can_access_billing({"role": "viewer", "ods_access": False}))


class Routes(unittest.TestCase):
    def test_every_billing_route_needs_the_billing_flags(self):
        allowed = {"require_billing", "require_billing_write", "require_admin"}
        for route, names in guards(billing_router.router).items():
            self.assertTrue(names, f"{route} has no permission dependency")
            self.assertLessEqual(names, allowed, f"{route} is guarded by {names}")

    def test_changing_a_bill_needs_the_change_flag(self):
        found = guards(billing_router.router)
        for route in ("POST /billing/bills", "PUT /billing/bills/{bill_code}", "POST /billing/bills/{bill_code}/cancel",
                      "POST /billing/bills/{bill_code}/payments", "POST /billing/bills/{bill_code}/email",
                      "POST /billing/receivables/{client_code}/email"):
            self.assertIn("require_billing_write", found[route], route)
        self.assertIn("require_admin", found["DELETE /billing/bills/{bill_code}/payments/{transaction_code}"])

    def test_every_etl_route_needs_the_etl_flags_and_running_needs_the_change_flag(self):
        found = guards(etl_router.router)
        for route, names in found.items():
            self.assertTrue(names & {"require_etl", "require_etl_write"}, route)
        self.assertIn("require_etl_write", found["POST /etl/pipelines/{key}/run"])
        self.assertNotIn("require_etl_write", found["GET /etl/pipelines"])

    def test_every_bank_route_needs_the_bank_flags_and_changing_needs_the_change_flag(self):
        found = guards(bank_router.router)
        self.assertGreater(len(found), 20)
        for route, names in found.items():
            self.assertEqual(len(names & {"require_bank", "require_bank_write"}), 1, f"{route} is guarded by {names}")
            if not route.startswith("GET "):
                self.assertIn("require_bank_write", names, route)
            else:
                self.assertIn("require_bank", names, route)

    def test_bank_follows_its_own_flags_and_is_for_admins_only_until_given(self):
        self.assertTrue(auth.can_access_bank({"role": "admin"}))
        self.assertFalse(auth.can_access_bank({"role": "editor"}))
        self.assertFalse(auth.can_access_bank({"role": "admin", "bank_access": False, "bank_write": False}))
        self.assertTrue(auth.can_access_page({"role": "viewer", "bank_access": True}, "bank"))
        self.assertFalse(auth.can_write_bank({"role": "viewer", "bank_access": True, "bank_write": False}))

    def test_the_dependencies_exist(self):
        for name in ("require_billing", "require_billing_write", "require_etl", "require_etl_write", "require_bank", "require_bank_write"):
            self.assertTrue(callable(getattr(dependencies, name)))


if __name__ == "__main__":
    unittest.main()
