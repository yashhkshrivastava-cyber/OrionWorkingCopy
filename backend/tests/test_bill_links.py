"""A bill number is a link with a card, and screens that would take you away from where you are open in a new tab. The logic behind it
is TypeScript, so it is checked in Node (frontend/scripts/check-bill-links.mjs); this runs that with the rest, and checks that the
screens use it."""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"


def source(path: str) -> str:
    return (SRC / path).read_text(encoding="utf-8")


class TheLogic(unittest.TestCase):
    def test_the_node_checks_pass(self):
        node = shutil.which("node")
        frontend = ROOT / "frontend"
        if not node or not (frontend / "node_modules" / "esbuild").exists():
            self.skipTest("Node and the frontend packages are not installed")
        done = subprocess.run([node, "scripts/check-bill-links.mjs"], cwd=frontend, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


class WhereABillNumberIsShown(unittest.TestCase):
    """The places that show bills draw them with BillNumber. A new table of bills that prints the plain number would be a miss, so the
    ones that exist are listed here, and a new one belongs in this list."""

    def test_the_tables_that_take_a_column_format_draw_bill_columns_as_bill_numbers(self):
        for name in ("components/dashboard/ReportTable.tsx", "components/dashboard/DataGrid.tsx", "components/dashboard/RecordTable.tsx", "components/assistant/Blocks.tsx"):
            text = source(name)
            self.assertIn("BillNumber", text, name)
            self.assertIn("'bill'", text, name)

    def test_the_generic_record_tables_find_bill_columns_by_name(self):
        text = source("components/ui/DataTable.tsx")
        self.assertIn("billColumn(", text)
        self.assertIn("BillNumber", text)

    def test_the_billing_pages_use_it(self):
        for name in ("pages/utility/ReceivablesPage.tsx", "pages/utility/DueToBillPage.tsx", "pages/utility/BillEditorPage.tsx"):
            self.assertIn("<BillNumber", source(name), name)
        self.assertIn("format: 'bill'", source("pages/utility/BillingPage.tsx"))

    def test_text_that_names_a_bill_links_it(self):
        self.assertIn("splitBillNumbers", source("components/assistant/Markdown.tsx"))
        self.assertIn("splitBillNumbers", source("components/messages/MessageBubble.tsx"))

    def test_the_server_marks_its_bill_columns(self):
        for name in ("views.py", "views_ops.py", "records.py"):
            text = (ROOT / "backend" / "app" / "dashboard" / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r'text_col\("(number|bill)", "Bill"\)', name)
            self.assertNotRegex(text, r'_col\("(number|bill)", "Bill", "text"', name)
        self.assertIn('"format": "bill"', (ROOT / "backend" / "app" / "ai" / "tools" / "records.py").read_text(encoding="utf-8"))


class WhereANewTabIsUsed(unittest.TestCase):
    def test_a_bill_opened_from_a_dashboard_row_opens_in_a_new_tab(self):
        self.assertIn("go: (path) => openInNewTab(path)", source("pages/dashboards/DashboardShell.tsx"))

    def test_the_links_that_leave_a_dashboard_or_an_answer_are_tab_links(self):
        for name in (
            "components/dashboard/RecordTable.tsx", "components/dashboard/WarehouseFreshness.tsx", "components/assistant/Frame.tsx",
            "components/assistant/Blocks.tsx", "components/assistant/Markdown.tsx", "components/assistant/MessageView.tsx",
        ):
            self.assertIn("<TabLink", source(name), name)

    def test_a_tab_link_is_a_real_link_that_cannot_reach_back(self):
        text = source("components/ui/TabLink.tsx")
        self.assertIn('target="_blank"', text)
        self.assertIn('rel="noopener noreferrer"', text)


if __name__ == "__main__":
    unittest.main()
