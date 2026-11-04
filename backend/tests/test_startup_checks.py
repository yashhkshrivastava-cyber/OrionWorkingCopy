"""A production server never starts with the secrets that are published in this repository.

None of this needs a database. Run from the repo root:  python -m pytest backend/tests
"""

import inspect
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import auth, config, main, startup_checks  # noqa: E402
from app.startup_checks import StartupConfigError  # noqa: E402

STRONG = {
    "ORION_ENV": "production",
    "ORION_SESSION_SECRET": "k3Zr9-Qm1x_Vb7Tn5Wp2Ld8Hf4Js6Yc0GaUeRiOyNtMw",
    "ORION_DB_PASSWORD": "vX8!pQ2#nL5@kR9$",
}


def settings(**changes):
    return {**STRONG, **changes}


class Production(unittest.TestCase):
    def test_good_settings_pass(self):
        self.assertEqual(startup_checks.production_problems(STRONG), [])
        startup_checks.verify_production(STRONG)

    def test_the_published_defaults_are_refused(self):
        found = startup_checks.production_problems(
            settings(ORION_SESSION_SECRET=config.DEV_SESSION_SECRET, ORION_DB_PASSWORD=config.DEV_DB_PASSWORD)
        )
        self.assertEqual(len(found), 2)
        self.assertTrue(any("ORION_SESSION_SECRET" in item for item in found))
        self.assertTrue(any("ORION_DB_PASSWORD" in item for item in found))

    def test_nothing_set_is_refused(self):
        # The same as the defaults: config.py would fall back to the published values.
        found = startup_checks.production_problems({"ORION_ENV": "production"})
        self.assertEqual(len(found), 2)

    def test_the_wording_of_the_example_files_is_refused(self):
        for value in ("change-me-to-a-long-random-string", "your-postgres-install-password", "Change-Me-Please", "<paste here>"):
            self.assertTrue(startup_checks.session_secret_problem(value + "x" * 40), value)
            self.assertTrue(startup_checks.database_password_problem(value), value)

    def test_a_short_session_secret_is_refused(self):
        self.assertTrue(startup_checks.session_secret_problem("a-private-but-short-one"))
        self.assertIsNone(startup_checks.session_secret_problem("x" * startup_checks.MIN_SESSION_SECRET_CHARS))

    def test_one_error_lists_everything_to_fix(self):
        with self.assertRaises(StartupConfigError) as caught:
            startup_checks.verify_production({"ORION_ENV": " Production "})
        message = str(caught.exception)
        self.assertIn("ORION_SESSION_SECRET", message)
        self.assertIn("ORION_DB_PASSWORD", message)
        self.assertIn("token_urlsafe", message)  # and how to make a secret

    def test_development_is_left_alone(self):
        for env in ({}, {"ORION_ENV": "development"}, {"ORION_ENV": "staging"}):
            self.assertEqual(startup_checks.production_problems(env), [])
            startup_checks.verify_production(env)

    def test_the_example_env_files_cannot_be_used_as_they_are(self):
        """Copying deploy/env.prod.example without filling it in must not start a server."""
        values = {}
        for line in (ROOT / "deploy" / "env.prod.example").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, _, value = line.partition("=")
                values[name.strip()] = value.strip()
        self.assertEqual(values.get("ORION_ENV"), "production")
        self.assertTrue(startup_checks.production_problems(values))


class FirstAdministrator(unittest.TestCase):
    def test_a_published_password_is_refused(self):
        for password in ("", config.DEV_ADMIN_PASSWORD, "change-me-admin-password", "short1!"):
            self.assertTrue(startup_checks.admin_password_problem(password), repr(password))
        self.assertIsNone(startup_checks.admin_password_problem("a long private pass phrase"))

    def test_production_does_not_create_the_default_admin_with_the_default_password(self):
        with mock.patch.object(auth, "_user_count", return_value=0), mock.patch.object(auth, "create_user") as create:
            with mock.patch.dict("os.environ", {"ORION_ENV": "production"}) as env:
                env.pop("ORION_ADMIN_PASSWORD", None)  # put back when the block ends
                with self.assertRaises(StartupConfigError):
                    auth.ensure_default_admin()
            create.assert_not_called()

    def test_production_creates_it_with_a_private_password(self):
        with mock.patch.object(auth, "_user_count", return_value=0), mock.patch.object(auth, "create_user") as create:
            with mock.patch.dict("os.environ", {"ORION_ENV": "production", "ORION_ADMIN_PASSWORD": "a long private pass phrase"}):
                auth.ensure_default_admin()
            create.assert_called_once()

    def test_development_still_needs_no_setup(self):
        with mock.patch.object(auth, "_user_count", return_value=0), mock.patch.object(auth, "create_user") as create:
            with mock.patch.dict("os.environ", {"ORION_ENV": "development"}):
                auth.ensure_default_admin()
            create.assert_called_once()

    def test_an_existing_installation_is_never_blocked_by_it(self):
        with mock.patch.object(auth, "_user_count", return_value=3), mock.patch.object(auth, "create_user") as create:
            with mock.patch.dict("os.environ", {"ORION_ENV": "production"}):
                auth.ensure_default_admin()
            create.assert_not_called()


class Wiring(unittest.TestCase):
    def test_startup_checks_run_before_the_database_is_touched(self):
        source = inspect.getsource(main.lifespan)
        self.assertLess(source.index("verify_production()"), source.index("ensure_user_profile_columns()"))

    def test_the_fallbacks_in_config_are_the_ones_the_check_refuses(self):
        self.assertIn("DEV_SESSION_SECRET", inspect.getsource(config.session_secret))
        self.assertIn("DEV_DB_PASSWORD", inspect.getsource(config.db_settings))
        self.assertIn("DEV_ADMIN_PASSWORD", inspect.getsource(auth.ensure_default_admin))

    def test_deploy_checks_the_settings_before_it_stops_the_running_server(self):
        script = (ROOT / "scripts" / "deploy.ps1").read_text(encoding="utf-8")
        self.assertIn("app.startup_checks", script)
        self.assertLess(script.index('@("app.startup_checks")'), script.index("$switchedServer = $true"))


if __name__ == "__main__":
    unittest.main()
