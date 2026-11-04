"""A deploy takes a safety dump, applies the schema before it touches the server, proves the new code is answering, and goes back if not.

None of this needs a database. (The whole of deploy.ps1 was also run for real against a rehearsal of production: a good deploy,
one with a broken migration, one that would not start, and a good one again; see docs/features.md, "Deploying safely".)
"""

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import deploy_tools as dt  # noqa: E402

SCRIPT = ROOT / "scripts" / "deploy.ps1"
HEAD = "a" * 40


class TheDump(unittest.TestCase):
    def test_a_label_cannot_escape_the_folder_or_break_the_name(self):
        self.assertEqual(dt.safe_label("v1.2.3"), "v1.2.3")
        self.assertEqual(dt.safe_label("origin/main"), "origin-main")
        self.assertEqual(dt.safe_label("../../evil name!"), "evil-name")
        self.assertEqual(dt.safe_label("///"), "release")
        self.assertLessEqual(len(dt.safe_label("x" * 500)), 60)

    def test_the_name_says_which_database_what_for_and_when(self):
        name = dt.dump_name("orion_prod", "v1.2.3", datetime(2026, 10, 19, 14, 5, 9))
        self.assertEqual(name, "orion_orion_prod_before_v1.2.3_20261019-140509.dump")
        self.assertTrue(Path(name).match(dt.DUMP_PATTERN.format(db="orion_prod")))

    def test_only_the_newest_few_are_kept_and_nothing_else_is_touched(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for index in range(7):
                path = directory / f"orion_orion_prod_before_v{index}_2026101{index}-000000.dump"
                path.write_bytes(b"x")
                os.utime(path, (1_700_000_000 + index * 100, 1_700_000_000 + index * 100))
            others = [directory / "orion_orion_before_x_1.dump", directory / "notes.txt", directory / "orion_prod_manual.dump"]
            for other in others:
                other.write_bytes(b"keep me")
            gone = dt.prune(directory, "orion_prod", keep=3)
            self.assertEqual(len(gone), 4)
            left = sorted(p.name for p in directory.glob("orion_orion_prod_before_*.dump"))
            self.assertEqual(left, [f"orion_orion_prod_before_v{i}_2026101{i}-000000.dump" for i in (4, 5, 6)])  # the newest three
            self.assertTrue(all(other.exists() for other in others), "a file that is not a safety dump of this database must never be deleted")

    def test_it_never_deletes_everything(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "orion_d_before_a_1.dump").write_bytes(b"x")
            self.assertEqual(dt.prune(Path(folder), "d", keep=0), [])

    def test_a_dump_is_only_trusted_if_it_reads_back_with_all_four_schemas(self):
        good = "; Archive created at 2026-10-19\n" + "".join(f"1; 2615 100 SCHEMA - {name} owner\n" for name in dt.SCHEMAS)
        self.assertIsNone(dt.listing_covers_the_schemas(good))
        self.assertIn("PostgreSQL archive", dt.listing_covers_the_schemas("garbage"))
        partial = "; Archive created at x\n1; 2615 100 SCHEMA - orion_ods o\n"
        self.assertIn("orion_dw", dt.listing_covers_the_schemas(partial))

    def test_a_missing_tool_is_a_clear_error_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch("app.backup.find_pg_tool", return_value=None):
            with self.assertRaises(RuntimeError) as caught:
                dt.backup(Path(folder), "v1")
            self.assertIn("pg_dump", str(caught.exception))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_a_failed_pg_dump_leaves_no_half_file_behind(self):
        with tempfile.TemporaryDirectory() as folder:
            failing = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"password authentication failed")
            with mock.patch("app.backup.find_pg_tool", return_value="pg"), mock.patch.object(dt, "_database_size", return_value=None), \
                 mock.patch.object(dt.subprocess, "run", return_value=failing):
                with self.assertRaises(RuntimeError) as caught:
                    dt.backup(Path(folder), "v1")
            self.assertIn("password authentication failed", str(caught.exception))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_a_dump_that_cannot_be_read_back_is_deleted_and_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            def fake_run(command, **kw):
                if "pg_dump" in command[0]:
                    Path(command[command.index("-f") + 1]).write_bytes(b"not a real archive")
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                return subprocess.CompletedProcess(command, 0, stdout=b"nonsense", stderr=b"")

            with mock.patch("app.backup.find_pg_tool", side_effect=lambda name: name), mock.patch.object(dt, "_database_size", return_value=None), \
                 mock.patch.object(dt.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(RuntimeError) as caught:
                    dt.backup(Path(folder), "v1")
            self.assertIn("cannot be trusted", str(caught.exception))
            self.assertEqual(list(Path(folder).iterdir()), [], "an unreadable dump must not be left looking like a safety net")

    def test_it_will_not_start_a_dump_without_the_room_for_it(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch("app.backup.find_pg_tool", return_value="pg"), \
             mock.patch.object(dt, "_database_size", return_value=10**15):
            with self.assertRaises(RuntimeError) as caught:
                dt.backup(Path(folder), "v1")
        self.assertIn("Not enough free disk space", str(caught.exception))


def responses(table):
    """A fake dt.fetch: url path -> (status, headers, body)."""
    def fake(url, timeout=10.0):
        path = "/" + url.split("//", 1)[1].split("/", 1)[1] if url.count("/") > 2 else "/"
        return table.get(path, (404, {}, b""))
    return fake


INDEX = b'<html><body><div id="root"></div><script type="module" src="/assets/index-abc.js"></script></body></html>'
HEALTHY = {
    "/api/health": (200, {"content-security-policy": "x", "x-request-id": "r"}, b'{"status":"ok"}'),
    "/api/health/ready": (200, {}, b'{"status":"ok","database":"ok"}'),
    "/api/health/version": (200, {}, json.dumps({"commit": HEAD}).encode()),
    "/": (200, {}, INDEX),
    "/assets/index-abc.js": (200, {}, b"x" * 5000),
    "/api/auth/config": (200, {}, b'{"roles":[],"authenticated":false}'),
}


class TheSmokeTest(unittest.TestCase):
    def run_smoke(self, table, commit=HEAD):
        with mock.patch.object(dt, "fetch", responses(table)), mock.patch.object(dt, "wait_until_up", return_value=True):
            return dt.smoke("http://127.0.0.1:8100", commit, seconds=1)

    def failed(self, checks):
        return [c.name for c in checks if not c.ok]

    def test_a_healthy_new_version_passes_every_check(self):
        checks = self.run_smoke(HEALTHY)
        self.assertEqual(self.failed(checks), [])
        self.assertGreaterEqual(len(checks), 7)

    def test_the_old_server_still_answering_is_not_a_pass(self):
        """The most dangerous failure of a deploy: the new server never started and the old one kept serving."""
        old = {**HEALTHY, "/api/health/version": (200, {}, json.dumps({"commit": "b" * 40}).encode())}
        self.assertEqual(self.failed(self.run_smoke(old)), ["it is the new code"])

    def test_a_server_with_no_version_endpoint_is_not_the_new_code(self):
        older = {k: v for k, v in HEALTHY.items() if k != "/api/health/version"}
        self.assertEqual(self.failed(self.run_smoke(older)), ["it is the new code"])

    def test_a_bad_schema_or_database_fails_it(self):
        broken = {**HEALTHY, "/api/health/ready": (503, {}, b'{"status":"degraded","database":"ok","schema":"problem"}')}
        self.assertEqual(self.failed(self.run_smoke(broken)), ["database and schema ready"])

    def test_a_missing_frontend_build_fails_it(self):
        empty = {**HEALTHY, "/": (404, {}, b"")}
        names = self.failed(self.run_smoke(empty))
        self.assertIn("the web app is served", names)
        self.assertIn("its script loads", names)

    def test_a_script_that_does_not_load_fails_it(self):
        self.assertEqual(self.failed(self.run_smoke({**HEALTHY, "/assets/index-abc.js": (404, {}, b"")})), ["its script loads"])

    def test_missing_security_headers_fail_it(self):
        bare = {**HEALTHY, "/api/health": (200, {}, b'{"status":"ok"}')}
        self.assertEqual(self.failed(self.run_smoke(bare)), ["security headers and request id are on"])

    def test_liveness_must_still_be_exactly_what_the_launchers_expect(self):
        changed = {**HEALTHY, "/api/health": (200, {"content-security-policy": "x", "x-request-id": "r"}, b'{"status":"ok","extra":1}')}
        self.assertEqual(self.failed(self.run_smoke(changed)), ["liveness unchanged"])

    def test_a_server_that_never_comes_up_is_one_clear_failure(self):
        with mock.patch.object(dt, "wait_until_up", return_value=False):
            checks = dt.smoke("http://127.0.0.1:8100", HEAD, seconds=5)
        self.assertEqual([(c.name, c.ok) for c in checks], [("server answers", False)])
        self.assertIn("within 5 seconds", checks[0].detail)

    def test_waiting_gives_up_after_the_time_and_stops_as_soon_as_it_is_up(self):
        clock = {"now": 0.0}
        sleeps = []
        with mock.patch.object(dt, "fetch", return_value=(0, {}, b"")):
            up = dt.wait_until_up("http://x", 3, sleep=lambda s: (sleeps.append(s), clock.update(now=clock["now"] + s)), clock=lambda: clock["now"])
        self.assertFalse(up)
        self.assertEqual(len(sleeps), 3)
        with mock.patch.object(dt, "fetch", return_value=(200, {}, b"{}")):
            self.assertTrue(dt.wait_until_up("http://x", 3, sleep=lambda s: self.fail("it was up: no need to wait")))

    def test_the_command_exits_1_when_any_check_fails(self):
        import io
        from contextlib import redirect_stdout

        with mock.patch.object(dt, "smoke", return_value=[dt.Check("a", True), dt.Check("b", False, "why")]), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(dt.main(["smoke", "--url", "http://x", "--commit", HEAD]), 1)
        self.assertIn("FAIL  b", out.getvalue())
        with mock.patch.object(dt, "smoke", return_value=[dt.Check("a", True)]), redirect_stdout(io.StringIO()):
            self.assertEqual(dt.main(["smoke", "--url", "http://x"]), 0)


def _running(record_path, started):
    """Patch what the module knows: the record's place, and the commit this process 'started' on (None: git is not available)."""
    return contextlib.ExitStack(), [
        mock.patch.object(dt, "RELEASE_FILE", record_path),
        mock.patch.object(dt, "_release_cache", None),
        mock.patch.object(dt, "_started_commit", started),
        mock.patch.object(dt, "_started_looked", True),
    ]


class TheReleaseRecord(unittest.TestCase):
    def info(self, record_path, started):
        stack, patches = _running(record_path, started)
        with stack:
            for patch in patches:
                stack.enter_context(patch)
            return dt.release_info()

    def test_it_is_written_and_read_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data" / "release.json"
            record = dt.write_release("v1.2.3", HEAD, "b" * 40, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["commit"], HEAD)
            self.assertEqual((record["ref"], record["previous"]), ("v1.2.3", "b" * 40))
            info = self.info(path, HEAD)
        self.assertEqual((info["commit"], info["ref"], info["source"]), (HEAD, "v1.2.3", "deploy"))

    def test_a_stale_record_never_makes_new_code_look_like_the_old_release(self):
        """The record is written after the smoke test, so while a release is being checked it still names the previous one."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "release.json"
            dt.write_release("vA", "a" * 40, "", path)
            info = self.info(path, "d" * 40)  # this process started on a different commit
        self.assertEqual(info["commit"], "d" * 40)
        self.assertIsNone(info["ref"])

    def test_a_record_written_after_it_was_first_asked_for_is_seen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "release.json"
            stack, patches = _running(path, HEAD)
            with stack:
                for patch in patches:
                    stack.enter_context(patch)
                self.assertIsNone(dt.release_info()["ref"])
                dt.write_release("v2", HEAD, "b" * 40, path)
                os.utime(path, (time.time() + 5, time.time() + 5))  # a file system's timestamps can be coarse
                after = dt.release_info()
        self.assertEqual((after["source"], after["ref"]), ("deploy", "v2"))

    def test_without_git_the_record_alone_is_used(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "release.json"
            dt.write_release("v3", HEAD, "", path)
            info = self.info(path, None)
        self.assertEqual((info["commit"], info["source"]), (HEAD, "deploy"))

    def test_without_a_record_it_says_what_git_said_and_never_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            info = self.info(Path(folder) / "none.json", HEAD)
        self.assertEqual((info["commit"], info["source"]), (HEAD, "git"))

    def test_a_broken_record_does_not_take_the_endpoint_down(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "release.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertEqual(self.info(bad, None)["source"], "unknown")

    def test_the_server_notes_its_commit_as_it_starts(self):
        import inspect

        from app import main

        self.assertIn("deploy_tools.warm()", inspect.getsource(main.lifespan))

    def test_the_version_endpoint_is_public_and_names_the_commit(self):
        from fastapi.testclient import TestClient

        from app.main import app

        info = {"commit": HEAD, "ref": "v1", "previous": None, "deployed": "t", "source": "deploy"}
        with mock.patch.object(dt, "release_info", return_value=info):
            response = TestClient(app).get("/api/health/version")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"commit": HEAD, "ref": "v1", "previous": None, "deployed": "t"})


class TheScript(unittest.TestCase):
    text = SCRIPT.read_text(encoding="utf-8")

    def at(self, needle: str, start: int = 0) -> int:
        position = self.text.find(needle, start)
        self.assertGreaterEqual(position, 0, f"deploy.ps1 does not contain {needle!r}")
        return position

    @unittest.skipUnless(sys.platform == "win32", "PowerShell parses it on Windows")
    def test_it_is_valid_powershell(self):
        command = (
            "$errors = $null; $null = [System.Management.Automation.Language.Parser]::ParseFile('%s', [ref]$null, [ref]$errors); "
            "if ($errors.Count) { $errors | ForEach-Object { $_.Message + ' at line ' + $_.Extent.StartLineNumber }; exit 1 }" % str(SCRIPT).replace("'", "''")
        )
        done = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_the_steps_are_in_the_safe_order(self):
        order = [
            "git fetch",  # find out what the new version is
            "git checkout --detach $target",  # the new code (and its tools)
            'Write-Host "==> Installing backend dependencies"',  # its packages: the dump below runs the new version's tools
            '"backup"',  # the safety dump: after the packages, but before ANYTHING touches the database
            "startup_checks",  # production settings
            '@("app.migrate")',  # the schema, before the server is touched
            "dist.new",  # the web app built to the side
            "$switchedServer = $true",  # only now is the running server stopped (right after Stop-ProdServer)
            "Test-Smoke $newSha",  # and the new one proven
            '"release", "--ref", $Ref',  # recorded only after it passed
        ]
        positions = [self.at(step) for step in order]
        self.assertEqual(positions, sorted(positions), "a step moved out of order: " + ", ".join(order))

    def test_the_dump_is_taken_before_the_schema_is_changed(self):
        self.assertLess(self.at('"backup"'), self.at('@("app.migrate")'))

    def test_a_release_that_changes_the_script_continues_with_the_new_copy(self):
        """The script that runs is the one on disk BEFORE the checkout, i.e. the old one. Without this every improvement to the deploy
        would only apply one deploy late, and the very first release with a safety dump could not take it."""
        self.assertIn("Get-FileHash $PSCommandPath", self.text)
        self.assertLess(self.at("$scriptBefore ="), self.at("git checkout --detach $target"))
        again = self.text[self.at("deploy.ps1 changed in this version"):self.at("Invoke-Native { git log -1 --oneline }")]
        for need in ('"-Resumed"', '"-PreviousSha"', "exit $LASTEXITCODE"):
            self.assertIn(need, again)
        self.assertIn("[switch]$Resumed", self.text)
        self.assertIn("if (-not $Resumed)", self.text)  # the new copy must not fetch and check out again

    def test_the_continued_run_still_knows_what_to_go_back_to(self):
        self.assertIn('$previousSha = if ($Resumed -and $PreviousSha) { $PreviousSha }', self.text)
        self.assertIn("$checkedOut = [bool]$Resumed", self.text)

    def test_verify_with_no_earlier_release_still_records_it(self):
        """Windows PowerShell 5.1 drops an empty argument, so `"--previous", ""` reached argparse as a bare --previous and the first
        -Verify (no data/release.json yet) failed after its smoke test had passed. The value rides in the flag's own argument."""
        self.assertNotIn('"--previous", "$before"', self.text)
        self.assertIn('"--previous=$before"', self.text)

    def test_a_failure_goes_back_and_exits_with_an_error(self):
        catch = self.text[self.at("} catch {"):]
        self.assertIn("Invoke-Rollback", catch)
        self.assertIn("exit 1", catch)
        self.assertIn("$dumpPath", catch, "the way back for damaged data must be printed")

    def test_the_rollback_restores_the_code_the_web_app_and_the_packages_and_proves_it(self):
        rollback = self.text[self.at("function Invoke-Rollback"):self.at("# ---", self.at("function Invoke-Rollback"))]
        for step in ("git checkout --detach $Sha", "Restore-Frontend", "Install-Packages", "Start-ProdServer", "Test-Smoke $Sha"):
            self.assertIn(step, rollback)

    def test_a_failed_migration_cannot_reach_the_server_stop(self):
        self.assertLess(self.at('@("app.migrate")'), self.at("Stop-ProdServer\n    $switchedServer"))

    def test_the_old_web_app_is_kept_for_an_instant_rollback_and_not_wiped_during_the_build(self):
        self.assertIn("--outDir dist.new", self.text)
        self.assertIn("dist.previous", self.text)

    def test_verify_checks_a_server_started_by_the_shortcut_and_changes_nothing(self):
        """The usual routine here is deploy.ps1 -NoRestart, then the desktop shortcut: the script never starts that server, so it needs a
        way to prove it afterwards."""
        self.assertIn("[switch]$Verify", self.text)
        block = self.text[self.at("if ($Verify) {"):self.at("# ---", self.at("if ($Verify) {"))]
        self.assertIn("Test-Smoke $head", block)
        for must_not in ("Stop-ProdServer", "Start-ProdServer", "git checkout", "app.migrate", '"backup"'):
            self.assertNotIn(must_not, block, "-Verify only looks: it must not change anything")
        self.assertIn("exit 1", block)
        self.assertIn("To go back", block, "a failed verification must say which version to return to")
        self.assertLess(self.at("if ($Verify) {"), self.at("if (-not $Resumed)"), "it must run before any deploy step")

    def test_a_deploy_cannot_be_started_from_a_development_folder(self):
        self.assertIn("ORION_ENV -ne \"production\"", self.text)

    def test_skipping_the_dump_is_loud_and_explicit(self):
        self.assertIn("[switch]$SkipBackup", self.text)
        self.assertRegex(self.text, r'Write-Warning "-SkipBackup')

    def test_the_build_folders_are_not_committed(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("frontend/dist.new/", ignore)
        self.assertIn("frontend/dist.previous/", ignore)


if __name__ == "__main__":
    unittest.main()
