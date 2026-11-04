"""Google Drive in the Document Center: the stand-in Drive, Google's client against a pretend server, which Drive is chosen, how the token is kept,
and the rules for what may be sent. No database and no network are needed."""

import inspect
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402

from app import gdrive, gdrive_client as gc, startup_checks  # noqa: E402
from app.entities import GDRIVE_MIGRATE, SQL_MIGRATIONS  # noqa: E402
from app.gdrive_client import FOLDER, DriveError, FakeDrive, GoogleDrive  # noqa: E402
from app.routers import gdrive_router  # noqa: E402


class TheFakeDrive(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.drive = FakeDrive(Path(self.temp.name))

    def test_folders_files_and_the_way_in(self):
        clients = self.drive.create_folder("root", "Clients")
        acme = self.drive.create_folder(clients.id, "Acme")
        made = self.drive.upload(acme.id, "agreement.pdf", b"%PDF-1", "application/pdf")
        items, more = self.drive.list(acme.id)
        self.assertEqual([i.name for i in items], ["agreement.pdf"])
        self.assertIsNone(more)
        self.assertEqual([i.name for i in self.drive.path(acme.id)], ["Clients", "Acme"])
        self.assertEqual(self.drive.download(made.id), ("agreement.pdf", "application/pdf", b"%PDF-1"))

    def test_folders_come_first_then_names(self):
        self.drive.upload("root", "b.txt", b"x", "text/plain")
        self.drive.create_folder("root", "Zed")
        self.drive.upload("root", "a.txt", b"x", "text/plain")
        self.assertEqual([i.name for i in self.drive.list("root")[0]], ["Zed", "a.txt", "b.txt"])

    def test_search_looks_everywhere_and_ignores_the_trash(self):
        folder = self.drive.create_folder("root", "Clients")
        hit = self.drive.upload(folder.id, "Acme agreement.txt", b"x", "text/plain")
        self.drive.upload("root", "Other.txt", b"x", "text/plain")
        self.assertEqual([i.name for i in self.drive.list("root", "acme agree")[0]], ["Acme agreement.txt"])
        self.drive.trash(hit.id)
        self.assertEqual(self.drive.list("root", "acme")[0], [])

    def test_rename_replace_and_move(self):
        a = self.drive.create_folder("root", "A")
        b = self.drive.create_folder("root", "B")
        f = self.drive.upload(a.id, "old.txt", b"1", "text/plain")
        self.assertEqual(self.drive.rename(f.id, "new.txt").name, "new.txt")
        self.drive.replace(f.id, b"two", "text/plain", "newer.txt")
        self.assertEqual(self.drive.download(f.id)[::2], ("newer.txt", b"two"))
        self.assertEqual(self.drive.move(f.id, b.id).parent, b.id)
        self.assertEqual(self.drive.list(a.id)[0], [])

    def test_a_folder_cannot_be_moved_into_itself_or_below(self):
        a = self.drive.create_folder("root", "A")
        inner = self.drive.create_folder(a.id, "Inner")
        for target in (a.id, inner.id):
            with self.assertRaises(DriveError):
                self.drive.move(a.id, target)

    def test_a_file_is_not_a_place_to_put_things(self):
        f = self.drive.upload("root", "a.txt", b"x", "text/plain")
        with self.assertRaises(DriveError):
            self.drive.upload(f.id, "b.txt", b"x", "text/plain")

    def test_the_trash_hides_and_nothing_is_deleted(self):
        f = self.drive.upload("root", "a.txt", b"x", "text/plain")
        self.drive.trash(f.id)
        with self.assertRaises(DriveError) as caught:
            self.drive.get(f.id)
        self.assertEqual(caught.exception.status, 404)
        self.assertTrue((Path(self.temp.name) / "blobs" / f.id).exists())

    def test_names_are_made_safe(self):
        self.assertEqual(self.drive.create_folder("root", " a/b\\c  d ").name, "a-b-c d")
        with self.assertRaises(DriveError):
            self.drive.create_folder("root", "   ")

    def test_a_large_file_is_refused(self):
        with mock.patch.object(gc, "MAX_FILE_BYTES", 1024), self.assertRaises(DriveError):
            self.drive.upload("root", "big.bin", b"0" * (gc.MAX_FILE_BYTES + 1), "application/octet-stream")

    def test_a_long_list_is_paged(self):
        for i in range(gc.MAX_PAGE + 5):
            self.drive.upload("root", f"f{i:04d}.txt", b"x", "text/plain")
        first, token = self.drive.list("root")
        second, token2 = self.drive.list("root", None, token)
        self.assertEqual((len(first), len(second), token2), (gc.MAX_PAGE, 5, None))


def pretend(handler):
    """A GoogleDrive whose server is ``handler(request) -> httpx.Response``."""
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return GoogleDrive(lambda: "ACCESS", http)


class GoogleOverRest(unittest.TestCase):
    def test_listing_asks_for_the_folders_children_and_sends_the_token(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"files": [{"id": "1", "name": "Docs", "mimeType": FOLDER, "parents": ["root"]},
                                                       {"id": "2", "name": "a.pdf", "mimeType": "application/pdf", "size": "12", "parents": ["root"]}],
                                             "nextPageToken": "NEXT"})

        items, more = pretend(handler).list("root")
        self.assertEqual([(i.name, i.is_folder, i.size) for i in items], [("Docs", True, None), ("a.pdf", False, 12)])
        self.assertEqual(more, "NEXT")
        request = seen[0]
        self.assertEqual(request.headers["Authorization"], "Bearer ACCESS")
        self.assertIn("'root' in parents and trashed = false", request.url.params["q"])

    def test_a_quote_in_a_search_cannot_break_out_of_the_query(self):
        seen = []

        def handler(request):
            seen.append(request.url.params["q"])
            return httpx.Response(200, json={"files": []})

        pretend(handler).list("root", "o'brien\\x")
        self.assertIn("name contains 'o\\'brien\\\\x'", seen[0])

    def test_upload_is_one_multipart_request_with_the_name_and_folder(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"id": "9", "name": "a.pdf", "mimeType": "application/pdf", "parents": ["F"]})

        item = pretend(handler).upload("F", "a.pdf", b"BYTES", "application/pdf")
        self.assertEqual(item.id, "9")
        body = seen[0].content
        self.assertIn(b'"name": "a.pdf"', body)
        self.assertIn(b'"parents": ["F"]', body)
        self.assertIn(b"BYTES", body)
        self.assertTrue(seen[0].headers["Content-Type"].startswith("multipart/related; boundary="))

    def test_google_answers_become_sentences_without_google_text_or_tokens(self):
        for status, words in ((401, "connect Google Drive again"), (404, "no longer in Drive"), (429, "busy"), (403, "would not allow")):
            drive = pretend(lambda request, status=status: httpx.Response(status, json={"error": {"message": "secret-ish detail"}}))
            with self.assertRaises(DriveError) as caught:
                drive.get("x")
            self.assertIn(words, str(caught.exception), status)
            self.assertNotIn("ACCESS", str(caught.exception))

    def test_a_busy_google_is_tried_again(self):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503) if len(calls) < 2 else httpx.Response(200, json={"id": "1", "name": "n", "mimeType": "text/plain"})

        with mock.patch("app.gdrive_client.time.sleep"):
            self.assertEqual(pretend(handler).get("1").name, "n")
        self.assertEqual(len(calls), 2)

    def test_a_google_doc_is_exported_and_a_shortcut_is_refused(self):
        def handler(request):
            if request.url.path.endswith("/export"):
                self.assertEqual(request.url.params["mimeType"], "application/pdf")
                return httpx.Response(200, content=b"%PDF-export")
            kind = "application/vnd.google-apps.shortcut" if request.url.path.endswith("/s") else "application/vnd.google-apps.document"
            return httpx.Response(200, json={"id": "d", "name": "Plan", "mimeType": kind})

        drive = pretend(handler)
        self.assertEqual(drive.download("d"), ("Plan.pdf", "application/pdf", b"%PDF-export"))
        with self.assertRaises(DriveError):
            drive.download("s")

    def test_a_move_names_the_old_and_the_new_folder(self):
        seen = []

        def handler(request):
            seen.append(request)
            if request.method == "GET":
                return httpx.Response(200, json={"id": "f", "name": "a", "mimeType": "text/plain", "parents": ["OLD"]})
            return httpx.Response(200, json={"id": "f", "name": "a", "mimeType": "text/plain", "parents": ["NEW"]})

        self.assertEqual(pretend(handler).move("f", "NEW").parent, "NEW")
        patch = seen[-1]
        self.assertEqual((patch.url.params["addParents"], patch.url.params["removeParents"]), ("NEW", "OLD"))

    def test_the_path_stops_at_the_top_of_my_drive(self):
        tree = {"root-real": None, "a": "root-real", "b": "a"}

        def handler(request):
            name = request.url.path.rsplit("/", 1)[1]
            if name == "root":
                return httpx.Response(200, json={"id": "root-real"})
            return httpx.Response(200, json={"id": name, "name": name.upper(), "mimeType": FOLDER, "parents": [tree[name]]})

        self.assertEqual([i.name for i in pretend(handler).path("b")], ["A", "B"])


class SigningIn(unittest.TestCase):
    def test_the_address_google_gets_names_the_scope_the_return_and_the_state(self):
        with mock.patch.dict("os.environ", {"ORION_GOOGLE_CLIENT_ID": "cid", "ORION_GOOGLE_CLIENT_SECRET": "sec", "ORION_APP_URL": "https://orion.example/"}):
            url = gc.authorize_url("STATE")
        for part in ("client_id=cid", "state=STATE", "access_type=offline", "prompt=consent", "response_type=code", "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive",
                     "redirect_uri=https%3A%2F%2Forion.example%2Fapi%2Fgdrive%2Fcallback"):
            self.assertIn(part, url)
        self.assertNotIn("sec", url.replace("scope", "").replace("response", ""))

    def test_a_refused_refresh_says_to_connect_again(self):
        http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(400, json={"error": "invalid_grant"})))
        with self.assertRaises(DriveError) as caught:
            gc.refresh_access_token("old", http)
        self.assertEqual(caught.exception.status, 401)

    def test_the_tokens_come_back_from_the_code(self):
        seen = []

        def handler(request):
            seen.append(request.content.decode())
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R", "expires_in": 3599})

        with mock.patch.dict("os.environ", {"ORION_GOOGLE_CLIENT_ID": "cid", "ORION_GOOGLE_CLIENT_SECRET": "sec"}):
            body = gc.exchange_code("CODE", httpx.Client(transport=httpx.MockTransport(handler)))
        self.assertEqual(body["refresh_token"], "R")
        self.assertIn("grant_type=authorization_code", seen[0])


class WhichDrive(unittest.TestCase):
    def mode(self, **env):
        return gc.configured_mode(env)

    def test_credentials_in_the_env_switch_to_google(self):
        self.assertEqual(self.mode(ORION_GOOGLE_CLIENT_ID="a", ORION_GOOGLE_CLIENT_SECRET="b"), "google")
        self.assertEqual(self.mode(ORION_GOOGLE_CLIENT_ID="a", ORION_GOOGLE_CLIENT_SECRET="b", ORION_ENV="production"), "google")

    def test_without_them_a_development_computer_gets_the_stand_in_and_production_none(self):
        self.assertEqual(self.mode(), "fake")
        self.assertEqual(self.mode(ORION_GOOGLE_CLIENT_ID="a"), "fake")  # half the credentials are none
        self.assertEqual(self.mode(ORION_ENV="production"), "off")

    def test_it_can_be_forced(self):
        self.assertEqual(self.mode(ORION_GDRIVE="off", ORION_GOOGLE_CLIENT_ID="a", ORION_GOOGLE_CLIENT_SECRET="b"), "off")
        self.assertEqual(self.mode(ORION_GDRIVE="fake"), "fake")

    def test_production_refuses_the_stand_in_and_half_set_credentials(self):
        self.assertIn("fake", startup_checks.google_drive_problem({"ORION_GDRIVE": "fake"}))
        self.assertIn("CLIENT_ID", startup_checks.google_drive_problem({"ORION_GDRIVE": "google"}))
        self.assertEqual(startup_checks.google_drive_problem({}), "")
        self.assertEqual(startup_checks.google_drive_problem({"ORION_GDRIVE": "google", "ORION_GOOGLE_CLIENT_ID": "a", "ORION_GOOGLE_CLIENT_SECRET": "b"}), "")
        problems = startup_checks.production_problems({"ORION_ENV": "production", "ORION_GDRIVE": "fake", "ORION_SESSION_SECRET": "x" * 60, "ORION_DB_PASSWORD": "a-private-one-1234"})
        self.assertTrue(any("ORION_GDRIVE" in p for p in problems))


class KeepingTheToken(unittest.TestCase):
    def test_a_sealed_token_opens_with_the_same_secret_and_not_otherwise(self):
        with mock.patch("app.gdrive.session_secret", return_value=b"one-secret"):
            sealed = gdrive.seal("refresh-token-123")
            self.assertNotIn(b"refresh-token-123", sealed)
            self.assertEqual(gdrive.unseal(sealed), "refresh-token-123")
        with mock.patch("app.gdrive.session_secret", return_value=b"another-secret"):
            with self.assertRaises(DriveError) as caught:
                gdrive.unseal(sealed)
        self.assertEqual(caught.exception.status, 401)


class WhatMayLeave(unittest.TestCase):
    def test_a_file_in_drive_is_named_after_the_document_with_its_own_extension(self):
        self.assertEqual(gdrive._file_name("Work order", "scan 12.pdf"), "Work order.pdf")
        self.assertEqual(gdrive._file_name("Work order.pdf", "x.pdf"), "Work order.pdf")
        self.assertEqual(gdrive._file_name("", "x.pdf"), "x.pdf")

    def test_a_new_bill_follows_the_ticks_and_then_the_company(self):
        connected = {"connected": True, "mode": "fake", "bills_mode": "on", "bills_folder_id": "FOLDER"}
        with mock.patch("app.gdrive._load", return_value=connected), mock.patch("app.gdrive.mode", return_value="fake"), mock.patch("app.gdrive.save_bill") as save:
            gdrive.after_bill_created("BILL-1", None, None, 1)  # the company says always
            save.assert_called_once_with("BILL-1", "FOLDER", 1)
            save.reset_mock()
            gdrive.after_bill_created("BILL-1", False, None, 1)  # the person unticked it
            save.assert_not_called()
            gdrive.after_bill_created("BILL-1", True, "MINE", 1)  # the person chose a folder
            save.assert_called_once_with("BILL-1", "MINE", 1)

    def test_a_company_that_asks_does_nothing_unless_ticked(self):
        asking = {"connected": True, "mode": "fake", "bills_mode": "ask", "bills_folder_id": None}
        with mock.patch("app.gdrive._load", return_value=asking), mock.patch("app.gdrive.mode", return_value="fake"), mock.patch("app.gdrive.save_bill") as save:
            gdrive.after_bill_created("BILL-1", None, None, 1)
            save.assert_not_called()

    def test_nothing_happens_when_drive_is_not_connected_and_a_failure_never_reaches_the_bill(self):
        with mock.patch("app.gdrive._load", return_value=None), mock.patch("app.gdrive.save_bill") as save:
            gdrive.after_bill_created("BILL-1", True, "F", 1)
            save.assert_not_called()
        connected = {"connected": True, "mode": "fake", "bills_mode": "on", "bills_folder_id": "F"}
        with mock.patch("app.gdrive._load", return_value=connected), mock.patch("app.gdrive.mode", return_value="fake"), \
                mock.patch("app.gdrive.save_bill", side_effect=RuntimeError("boom")):
            gdrive.after_bill_created("BILL-1", None, None, 1)  # does not raise

    def test_a_connection_made_in_the_other_mode_is_not_a_connection(self):
        with mock.patch("app.gdrive.mode", return_value="google"):
            self.assertFalse(gdrive._connected({"connected": True, "mode": "fake"}))
            self.assertTrue(gdrive._connected({"connected": True, "mode": "google"}))
            self.assertFalse(gdrive._connected(None))

    def test_the_fake_drive_has_no_web_page(self):
        with mock.patch("app.gdrive.mode", return_value="fake"):
            self.assertIsNone(gdrive.web_url("abc"))
        with mock.patch("app.gdrive.mode", return_value="google"):
            self.assertIn("/file/d/abc/", gdrive.web_url("abc"))
            self.assertIn("/folders/abc", gdrive.web_url("abc", True))


class TheRoutes(unittest.TestCase):
    def routes(self):
        return {(route.path, tuple(sorted(route.methods))): route for route in gdrive_router.router.routes if isinstance(route, APIRoute)}

    def test_every_route_has_a_permission_dependency(self):
        for (path, _methods), route in self.routes().items():
            self.assertTrue(route.dependant.dependencies, path)

    def test_connecting_and_the_settings_are_for_admins(self):
        source = inspect.getsource(gdrive_router)
        for name in ("def connect", "def callback", "def disconnect", "def save_settings"):
            block = source[source.index(name):].split("\n\n\n")[0]
            self.assertIn("require_admin", block, name)

    def test_changing_things_needs_permission_to_change_documents(self):
        source = inspect.getsource(gdrive_router)
        for name in ("def new_folder", "def change_file", "def trash_file", "def upload", "def copy_to_drive", "def copy_from_drive"):
            block = source[source.index(name):].split("\n\n\n")[0]
            self.assertIn("require_documents_write", block, name)

    def test_googles_refusal_never_signs_the_person_out(self):
        self.assertEqual(gdrive_router._fail(DriveError("x", 401)).status_code, 409)
        self.assertEqual(gdrive_router._fail(DriveError("x", 404)).status_code, 404)

    def test_a_file_from_drive_is_only_ever_a_download(self):
        source = inspect.getsource(gdrive_router.download)
        self.assertIn("attachment", source)
        self.assertIn("nosniff", source)

    def test_the_schema_is_registered_where_it_must_be(self):
        self.assertIn(GDRIVE_MIGRATE, SQL_MIGRATIONS)
        for script in ("init_db_windows.ps1", "init_db_mac.sh"):
            self.assertIn("migrate_gdrive.sql", (ROOT / "scripts" / script).read_text(encoding="utf-8"), script)
        sql = GDRIVE_MIGRATE.read_text(encoding="utf-8")
        for needed in ("gdrive_connection", "drive_link", "ux_drive_link_bill", "GRANT ALL"):
            self.assertIn(needed, sql)

    def test_no_token_or_google_answer_is_ever_written_to_a_log(self):
        for module in (gdrive, gc):
            for line in inspect.getsource(module).splitlines():
                if re.search(r"logger[.](debug|info|warning|error|exception)[(]", line):
                    for word in ("refresh", "access", "secret", "response.text", "response.content", "response.json", "tokens"):
                        self.assertNotIn(word, line.lower(), line)


if __name__ == "__main__":
    unittest.main()
