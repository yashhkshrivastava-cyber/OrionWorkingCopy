"""Deleting a folder together with what is in it: what the person is told first, what is refused, and what is left behind.

The rules run against the development database (set ORION_DOC_DB_TESTS=1); the routes and the page are read without one."""

import inspect
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.routing import APIRoute  # noqa: E402

from app import documents  # noqa: E402
from app.documents import DocumentCenterError  # noqa: E402
from app.routers import documents_router  # noqa: E402

RUN = os.environ.get("ORION_DOC_DB_TESTS") == "1"
FRONTEND = ROOT / "frontend" / "src"


class TheRoutes(unittest.TestCase):
    def test_looking_is_reading_and_dropping_needs_permission_to_change_documents(self):
        source = inspect.getsource(documents_router)
        for name, guard in (("def folder_contents", "Depends(require_documents)"), ("def drop_folder", "Depends(require_documents_write)")):
            block = source[source.index(name):].split("\n\n\n")[0]
            self.assertIn(guard, block, name)
        found = {route.path: route for route in documents_router.router.routes if isinstance(route, APIRoute)}
        for path in ("/documents/folders/{folder_id}/contents", "/documents/folders/{folder_id}/drop"):
            self.assertIn(path, found)
            self.assertTrue(found[path].dependant.dependencies, path)

    def test_the_page_shows_what_would_be_lost_before_it_deletes_anything(self):
        page = (FRONTEND / "pages" / "documents" / "DocumentCenterPage.tsx").read_text(encoding="utf-8")
        self.assertIn("documentFolderContents", page)
        self.assertIn("dropDocumentFolder", page)
        client = (FRONTEND / "api" / "client.ts").read_text(encoding="utf-8")
        self.assertIn("seen_documents", client)  # what was shown goes back with the confirmation


@unittest.skipUnless(RUN, "set ORION_DOC_DB_TESTS=1 to run the folder tests against the development database")
class DroppingAFolder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.database import db_cursor

        cls.db = staticmethod(db_cursor)
        with db_cursor() as cur:
            cur.execute("select current_database()")
            assert cur.fetchone()[0] == "orion", "development database only"
        cls.folders: list[int] = []
        cls.documents: list[int] = []

    @classmethod
    def tearDownClass(cls):
        with cls.db(commit=True) as cur:
            if cls.documents:
                cur.execute("delete from orion_ods.document where document_id = any(%s)", (cls.documents,))
                # the files the test documents held (what a purge from the trash does too)
                cur.execute("delete from orion_ods.document_blob b where not exists (select 1 from orion_ods.document_version v where v.sha256 = b.sha256)")
            if cls.folders:
                cur.execute("update orion_ods.doc_folder set parent_id = null where folder_id = any(%s)", (cls.folders,))
                cur.execute("delete from orion_ods.doc_folder where folder_id = any(%s)", (cls.folders,))

    def folder(self, name, parent=None, system_key=None):
        with self.db(commit=True) as cur:
            cur.execute(
                "insert into orion_ods.doc_folder (scope, parent_id, name, system_key) values ('company', %s, %s, %s) returning folder_id",
                (parent, name, system_key),
            )
            found = cur.fetchone()[0]
        self.folders.append(found)
        return found

    def document(self, folder, title, source_type=None, confidentiality="Standard"):
        made = documents.create_document(None, {"scope": "company", "folder_id": folder, "title": title, "category": "Other", "confidentiality": confidentiality}, f"{title}.txt", f"text of {title}".encode())
        self.documents.append(made["id"])
        if source_type:
            with self.db(commit=True) as cur:
                cur.execute("update orion_ods.document set source_type = %s, source_ref = %s where document_id = %s", (source_type, f"t-{made['id']}", made["id"]))
        return made["id"]

    def state(self, document_id):
        with self.db() as cur:
            cur.execute("select is_deleted, folder_id from orion_ods.document where document_id = %s", (document_id,))
            return cur.fetchone()

    def test_the_warning_counts_what_would_go_and_the_drop_trashes_documents_and_removes_folders(self):
        top = self.folder("zz drop top")
        inner = self.folder("zz drop inner", top)
        first, second = self.document(top, "zz drop one"), self.document(inner, "zz drop two")
        seen = documents.folder_contents(top, True)
        self.assertEqual((seen["subfolders"], seen["documents"], seen["versions"], seen["can_drop"]), (1, 2, 2, True))
        self.assertEqual(seen["subfolder_names"], ["zz drop inner"])
        self.assertEqual(sorted(seen["document_titles"]), ["zz drop one", "zz drop two"])
        self.assertGreater(seen["size_bytes"], 0)
        done = documents.drop_folder(None, top, seen["documents"], seen["subfolders"], True)
        self.assertEqual(done, {"documents": 2, "folders": 2})
        for document_id in (first, second):
            self.assertEqual(self.state(document_id), (True, None))  # in the trash, at the top level, restorable
        self.assertIsNone(documents.folder_contents(top, True))
        self.assertIsNone(documents.folder_contents(inner, True))
        with self.db() as cur:
            cur.execute("select action from orion_ods.document_activity where document_id = %s order by 1", (first,))
            self.assertIn("deleted", [row[0] for row in cur.fetchall()])
        self.assertEqual(documents.set_deleted(None, [first], False, True), 1)  # and it comes back
        self.assertEqual(self.state(first), (False, None))

    def test_a_folder_that_changed_while_the_person_read_the_warning_is_not_emptied(self):
        top = self.folder("zz drop changed")
        kept = self.document(top, "zz drop kept")
        seen = documents.folder_contents(top, True)
        late = self.document(top, "zz drop late")  # somebody adds a document after the warning was drawn
        with self.assertRaises(DocumentCenterError):
            documents.drop_folder(None, top, seen["documents"], seen["subfolders"], True)
        self.assertEqual(self.state(kept), (False, top))
        self.assertEqual(self.state(late), (False, top))

    def test_papers_orion_filed_and_orions_own_folders_are_never_dropped(self):
        top = self.folder("zz drop filed")
        self.document(top, "zz drop mine")
        filed = self.document(top, "zz drop bill", source_type="bill")
        seen = documents.folder_contents(top, True)
        self.assertFalse(seen["can_drop"])
        self.assertEqual(seen["filed"], 1)
        self.assertIn("filed automatically", seen["reason"])
        with self.assertRaises(DocumentCenterError):
            documents.drop_folder(None, top, seen["documents"], seen["subfolders"], True)
        self.assertEqual(self.state(filed), (False, top))
        system = self.folder("zz drop system", system_key="zz-test-key")
        refused = documents.folder_contents(system, True)
        self.assertFalse(refused["can_drop"])
        self.assertIn("Orion keeps", refused["reason"])

    def test_documents_you_may_not_see_stop_a_drop_and_are_never_named(self):
        top = self.folder("zz drop secret")
        self.document(top, "zz drop secret paper", confidentiality="Confidential")
        self.document(top, "zz drop open paper")
        self.assertTrue(documents.folder_contents(top, True)["can_drop"])
        seen = documents.folder_contents(top, False)
        self.assertFalse(seen["can_drop"])
        self.assertIn("confidential", seen["reason"])
        self.assertEqual(seen["document_titles"], ["zz drop open paper"])  # the secret one is not named or counted
        self.assertEqual(seen["documents"], 1)

    def test_what_was_already_in_the_trash_stays_there(self):
        top = self.folder("zz drop trash")
        old = self.document(top, "zz drop old")
        documents.set_deleted(None, [old], True, True)
        seen = documents.folder_contents(top, True)
        self.assertEqual((seen["documents"], seen["trashed"]), (0, 1))
        documents.drop_folder(None, top, 0, 0, True)
        self.assertEqual(self.state(old), (True, None))

    def test_an_empty_folder_is_still_deleted_the_plain_way(self):
        top = self.folder("zz drop empty")
        self.assertTrue(documents.delete_folder(top))
        self.assertIsNone(documents.folder_contents(top, True))


if __name__ == "__main__":
    unittest.main()
