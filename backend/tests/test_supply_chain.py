"""What gets installed, and what is checked before it reaches the office PC.

Without pins, every deploy installs whatever each package published that morning, so prod can differ from what was tested.
These keep requirements.txt, the lock (constraints.txt), the install scripts and the CI workflow in step.
None of this needs a database. Run from the repo root:  python -m pytest backend/tests
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def requirement_lines(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-")):
            yield line


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(path: Path) -> dict[str, str]:
    found = {}
    for line in requirement_lines(path):
        match = re.fullmatch(r"([A-Za-z0-9_.\-]+)(\[[^\]]*\])?==([^\s;#]+)", line)
        assert match, f"{path.name}: '{line}' is not pinned with =="
        found[canonical(match.group(1))] = match.group(3)
    return found


class Pinned(unittest.TestCase):
    def test_every_requirement_is_pinned_exactly(self):
        for name in ("requirements.txt", "requirements-dev.txt"):
            self.assertTrue(pins(BACKEND / name), name)  # pins() fails the test on a loose line

    def test_the_lock_agrees_with_the_requirements(self):
        direct, lock = pins(BACKEND / "requirements.txt"), pins(BACKEND / "constraints.txt")
        for name, version in direct.items():
            self.assertIn(name, lock, f"{name} is required but missing from constraints.txt")
            self.assertEqual(lock[name], version, f"{name}: requirements.txt says {version}, constraints.txt says {lock[name]}")

    def test_the_lock_holds_the_packages_the_requirements_pull_in(self):
        # Something to lock: a lock with only the direct requirements would pin nothing that matters.
        self.assertGreater(len(pins(BACKEND / "constraints.txt")), len(pins(BACKEND / "requirements.txt")))

    def test_every_install_uses_the_lock(self):
        scripts = list((ROOT / "scripts").glob("*.ps1")) + list((ROOT / "scripts").glob("*.sh"))
        installs = 0
        for path in scripts:
            for line in path.read_text(encoding="utf-8").splitlines():
                if "backend" in line and "requirements.txt" in line and "pip" in line and "install" in line:
                    installs += 1
                    self.assertIn("constraints.txt", line, f"{path.name}: {line.strip()}")
        self.assertGreaterEqual(installs, 4)  # deploy, install-windows, start-api (two flavours), install-mac


class Pipeline(unittest.TestCase):
    workflow = ROOT / ".github" / "workflows" / "ci.yml"

    def test_pull_requests_run_the_backend_the_frontend_and_the_audits(self):
        text = self.workflow.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^on:\s*\n\s+pull_request:")
        for job in ("backend", "frontend", "dependency-audit"):
            self.assertRegex(text, rf"(?m)^  {job}:", job)
        for command in ("pytest backend/tests", "npm run build", "npm run check:themes", "npm run lint", "ruff check", "npm run check:bundle", "npm run check:bill", "npm run check:links", "pip-audit", "npm audit"):
            self.assertIn(command, text, command)

    def test_the_workflow_file_is_valid_yaml(self):
        """A step name with an unquoted ": " is a YAML error, and GitHub then runs nothing at all ("workflow file issue")."""
        text = self.workflow.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            match = re.match(r"^\s*- name: (?!['\"])(.*)$", line)
            if match:
                self.assertNotIn(": ", match.group(1), f"ci.yml line {number}: quote a step name that holds a colon")
        try:
            import yaml
        except ImportError:
            return
        document = yaml.safe_load(text)
        self.assertEqual(set(document["jobs"]), {"backend", "frontend", "dependency-audit"})

    def test_ci_installs_the_same_pinned_set_as_deploy(self):
        text = self.workflow.read_text(encoding="utf-8")
        self.assertIn("-c backend/constraints.txt", text)

    def test_dependencies_are_watched_for_updates(self):
        text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        for ecosystem in ("pip", "npm", "github-actions"):
            self.assertIn(f"package-ecosystem: {ecosystem}", text)

    def test_actions_are_updated_in_one_pull_request_so_they_cannot_conflict(self):
        """Every action lives in ci.yml: separate pull requests for each edit the same file, and each merge conflicts the next."""
        text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        actions = text.split("package-ecosystem: github-actions", 1)[1]
        self.assertIn("groups:", actions)
        self.assertIn('patterns: ["*"]', actions)

    def test_the_upgrades_that_cannot_pass_alone_are_not_proposed(self):
        text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        for name in ("recharts", "vite", '"@vitejs/plugin-react"'):
            self.assertRegex(text, rf"dependency-name: {re.escape(name)}\s+update-types: \[\"version-update:semver-major\"\]", name)

    def test_the_routine_for_handling_them_is_written_down(self):
        text = (ROOT / "DEVELOPMENT.md").read_text(encoding="utf-8")
        self.assertIn("Dependabot pull requests", text)
        self.assertIn("@dependabot rebase", text)


if __name__ == "__main__":
    unittest.main()
