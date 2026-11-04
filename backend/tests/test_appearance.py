"""A person's saved appearance (theme, mode, accent ...): what is accepted, what is refused, and how it is stored.

The browser applies these settings (frontend/src/theme); the server only keeps them, so everything here is about never
storing anything but a few short, known values. None of it needs a database. Run from the repo root:
    python -m pytest backend/tests
"""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import appearance, auth  # noqa: E402
from app.appearance import AppearanceError  # noqa: E402
from app.routers import auth_router  # noqa: E402

GOOD = {
    "v": 1, "theme": "midnight", "mode": "dark", "accent": "#e3b866", "style": "glass", "radius": 0.4,
    "density": "compact", "scale": 110, "contrast": "high", "motion": "reduced", "gradient": True, "ambient": None, "experience": "lumen",
}


class Accepted(unittest.TestCase):
    def test_a_full_set_of_settings_is_kept_as_given(self):
        self.assertEqual(appearance.clean_appearance(GOOD), GOOD)

    def test_a_missing_setting_takes_its_default(self):
        kept = appearance.clean_appearance({"theme": "ivory"})
        self.assertEqual(
            kept,
            {"v": 1, "theme": "ivory", "mode": "system", "accent": None, "style": None, "radius": None,
             "density": "comfortable", "scale": 100, "contrast": "standard", "motion": "full", "gradient": None, "ambient": None, "experience": "classic"},
        )

    def test_it_can_arrive_as_json_text_and_is_stored_compactly(self):
        text = appearance.dump_appearance(json.dumps(GOOD))
        self.assertEqual(json.loads(text), GOOD)
        self.assertNotIn(" ", text)
        self.assertLess(len(text), appearance.MAX_BYTES)

    def test_an_older_save_without_an_interface_is_the_classic_one_and_an_unknown_one_is_refused(self):
        self.assertEqual(appearance.clean_appearance({"theme": "ivory"})["experience"], "classic")
        with self.assertRaises(AppearanceError):
            appearance.clean_appearance({"experience": "neon"})

    def test_an_accent_is_lower_cased(self):
        self.assertEqual(appearance.clean_appearance({"accent": "#E3B866"})["accent"], "#e3b866")

    def test_a_theme_or_style_this_server_has_never_heard_of_is_kept_so_a_newer_browser_still_works(self):
        kept = appearance.clean_appearance({"theme": "sixth-theme", "style": "brutalist"})
        self.assertEqual((kept["theme"], kept["style"]), ("sixth-theme", "brutalist"))

    def test_what_is_stored_comes_back_and_nothing_is_not_an_error(self):
        self.assertEqual(appearance.load_appearance(appearance.dump_appearance(GOOD)), GOOD)
        self.assertIsNone(appearance.load_appearance(None))
        self.assertIsNone(appearance.load_appearance(""))
        self.assertIsNone(appearance.load_appearance("not json"))
        self.assertIsNone(appearance.load_appearance('{"mode": "sepia"}'))


class Refused(unittest.TestCase):
    def check(self, **change):
        with self.assertRaises(AppearanceError, msg=str(change)):
            appearance.clean_appearance({**GOOD, **change})

    def test_values_outside_the_known_choices(self):
        self.check(mode="sepia")
        self.check(density="huge")
        self.check(contrast="extreme")
        self.check(motion="wild")

    def test_a_colour_that_is_not_a_plain_hex_colour(self):
        for bad in ("red", "#fff", "#12345g", "rgb(1,2,3)", "javascript:alert(1)", "#e3b866; background:url(x)", 5):
            self.check(accent=bad)

    def test_names_that_could_carry_anything_but_a_name(self):
        for bad in ("../../etc", "Midnight", "a b", "x" * 40, "<script>", "", 5):
            self.check(theme=bad)
        self.check(style="<b>")

    def test_numbers_out_of_range_and_things_that_are_not_numbers(self):
        for bad in (-0.1, 1.1, "0.5", True, float("nan")):
            self.check(radius=bad)
        for bad in (84, 126, "100", True, None):
            self.check(scale=bad)

    def test_flags_that_are_not_true_false_or_unset(self):
        self.check(gradient="yes")
        self.check(ambient=1)

    def test_something_that_is_not_a_set_of_settings(self):
        for bad in ([], "[]", 7, "{"):
            with self.assertRaises(AppearanceError, msg=str(bad)):
                appearance.clean_appearance(bad)

    def test_extra_keys_are_dropped_not_stored(self):
        kept = appearance.clean_appearance({**GOOD, "evil": "<script>alert(1)</script>", "css": "body{}"})
        self.assertEqual(set(kept), set(GOOD))


class WiredIn(unittest.TestCase):
    def test_a_person_can_save_it_through_their_profile_and_gets_it_back(self):
        self.assertIn("appearance", auth_router.UpdateProfileRequest.model_fields)
        self.assertIn("appearance", auth.USER_SELECT_COLUMNS)
        shown = auth.public_user({
            "id": 1, "username": "a", "display_name": "A", "role": "viewer", "appearance": appearance.dump_appearance(GOOD),
            **{flag: False for flag in auth.ACCESS_FLAGS},
        })
        self.assertEqual(shown["appearance"], GOOD)

    def test_a_person_who_never_chose_has_none(self):
        shown = auth.public_user({"id": 1, "username": "a", "display_name": "A", "role": "viewer", **{flag: False for flag in auth.ACCESS_FLAGS}})
        self.assertIsNone(shown["appearance"])

    def test_the_column_exists_in_the_schema_and_is_added_to_existing_databases(self):
        self.assertIn("appearance", (ROOT / ".cursor" / "db" / "schema.sql").read_text(encoding="utf-8"))
        source = (ROOT / "backend" / "app" / "auth.py").read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS appearance TEXT", source)


class ThemeEngine(unittest.TestCase):
    """The browser's theme engine has its own checks (contrast of every theme, and Default matching the stylesheet).
    They run in Node because the engine is TypeScript; this runs them with the rest, and is skipped where Node or the
    frontend's packages are not installed (a backend-only machine)."""

    def test_every_theme_is_readable_and_the_default_theme_matches_the_stylesheet(self):
        node = shutil.which("node")
        frontend = ROOT / "frontend"
        if not node or not (frontend / "node_modules" / "esbuild").exists():
            self.skipTest("Node and the frontend packages are not installed")
        done = subprocess.run([node, "scripts/check-themes.mjs"], cwd=frontend, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
