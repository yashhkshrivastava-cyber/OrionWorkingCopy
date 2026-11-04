"""The linters are part of "the tests pass": a rule that nobody runs stops being true. CI runs the same two commands; these run them with
the rest of the suite, and are skipped on a machine that has not got the tool (a backend-only checkout, say)."""

import importlib.util
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Python(unittest.TestCase):
    def test_ruff_finds_nothing_in_the_backend(self):
        if importlib.util.find_spec("ruff") is None:
            self.skipTest("ruff is not installed (pip install -r backend/requirements-dev.txt)")
        done = subprocess.run([sys.executable, "-m", "ruff", "check", "backend"], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_the_rule_set_is_the_one_documented(self):
        text = (ROOT / "ruff.toml").read_text(encoding="utf-8")
        for rule in ('"F"', '"B"', '"PLE"', '"S110"'):
            self.assertIn(rule, text)
        self.assertNotIn("[format]", text, "formatting is deliberately not enforced: it would rewrite most of the code")

    def test_the_pinned_version_is_what_pre_commit_and_the_dev_requirements_agree_on(self):
        pinned = [line for line in (ROOT / "backend" / "requirements-dev.txt").read_text(encoding="utf-8").splitlines() if line.startswith("ruff==")]
        self.assertEqual(len(pinned), 1)
        version = pinned[0].split("==")[1].strip()
        self.assertIn(f"rev: v{version}", (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))


class Frontend(unittest.TestCase):
    def test_oxlint_finds_nothing_in_the_frontend(self):
        npm = shutil.which("npm")
        frontend = ROOT / "frontend"
        if not npm or not (frontend / "node_modules" / "oxlint").exists():
            self.skipTest("Node and the frontend packages are not installed")
        done = subprocess.run([npm, "run", "lint"], cwd=frontend, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_the_hooks_rules_cannot_be_switched_off(self):
        config = (ROOT / "frontend" / ".oxlintrc.json").read_text(encoding="utf-8")
        for rule in ("react-hooks/rules-of-hooks", "react-hooks/exhaustive-deps"):
            self.assertRegex(config, rf'"{rule}":\s*"error"')


if __name__ == "__main__":
    unittest.main()
