"""Bill arithmetic is written twice: billing.py (what a person is billed) and billCalc.ts (what the editor shows while they type).
Both must produce exactly the figures in bill_vectors.json. This runs the server half, and the preview half through Node."""

import json
import shutil
import subprocess
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import billing  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VECTORS = Path(__file__).with_name("bill_vectors.json")
FIELDS = ["lines_total", "epf_amount", "esic_amount", "sub_total", "service_amount", "taxable_total", "cgst_amount", "sgst_amount", "round_off", "grand_total"]
FILE = json.loads(VECTORS.read_text(encoding="utf-8"))


def two(value) -> str:
    return f"{Decimal(value):.2f}"


def figures(vector: dict) -> dict:
    month = date.fromisoformat(vector["month"] + "-01") if vector.get("month") else None  # a monthly rate takes the days of this month
    try:
        bill = billing.compute_bill(vector["lines"], vector["rates"], vector["extras"], vector.get("setup"), month, vector.get("manual"))
    except billing.BillError:
        return {"ok": False}
    seen = {"ok": True, "lines": [two(row["amount"]) for row in bill["lines"]]}
    seen.update({field: two(bill[field]) for field in FIELDS})
    seen["extras"] = [two(charge["amount"]) for charge in bill["extra_charges"]]
    return seen


class TheServerFollowsTheVectors(unittest.TestCase):
    def test_every_vector(self):
        for vector in FILE["vectors"]:
            with self.subTest(vector["name"]):
                self.assertEqual(figures(vector), vector["expect"])

    def test_every_documented_difference_is_still_what_the_server_does(self):
        for vector in FILE["differences"]:
            with self.subTest(vector["name"]):
                self.assertEqual(figures(vector), vector["backend"])


class TheFileIsSound(unittest.TestCase):
    def test_it_covers_the_cases_that_matter(self):
        names = " ".join(vector["name"] for vector in FILE["vectors"]).lower()
        for part in ("9,19,149", "half paisa", "fifty paise", "extra charge", "refused", "million", "thirty lines", "100.004"):
            self.assertIn(part, names)
        self.assertGreaterEqual(sum(1 for v in FILE["vectors"] if v["expect"]["ok"]), 30)
        self.assertGreaterEqual(sum(1 for v in FILE["vectors"] if not v["expect"]["ok"]), 15)

    def test_every_difference_says_why_and_really_differs(self):
        for vector in FILE["differences"]:
            with self.subTest(vector["name"]):
                self.assertTrue(vector["why"].strip())
                self.assertNotEqual(vector["backend"], vector["frontend"])

    def test_figures_are_exact_two_decimal_text(self):
        for vector in FILE["vectors"]:
            expect = vector["expect"]
            if expect["ok"]:
                for field in FIELDS:
                    self.assertRegex(expect[field], r"^-?\d+\.\d{2}$", vector["name"])

    def test_a_bill_always_adds_up(self):
        """An identity that must hold for every bill, whatever the inputs: the vectors cannot hide a calculation that does not."""
        for vector in FILE["vectors"]:
            e = vector["expect"]
            if not e["ok"]:
                continue
            with self.subTest(vector["name"]):
                d = {key: Decimal(e[key]) for key in FIELDS}
                self.assertEqual(sum(Decimal(x) for x in e["lines"]), d["lines_total"])
                self.assertEqual(d["lines_total"] + d["epf_amount"] + d["esic_amount"], d["sub_total"])
                self.assertEqual(d["sub_total"] + d["service_amount"] + sum(Decimal(x) for x in e["extras"]), d["taxable_total"])
                self.assertEqual(d["taxable_total"] + d["cgst_amount"] + d["sgst_amount"] + d["round_off"], d["grand_total"])
                self.assertEqual(d["grand_total"], d["grand_total"].to_integral_value())
                self.assertLessEqual(abs(d["round_off"]), Decimal("0.50"))


class ThePreviewFollowsTheVectors(unittest.TestCase):
    """billCalc.ts is TypeScript, so it runs in Node (frontend/scripts/check-bill-vectors.mjs). Skipped where Node or the frontend's
    packages are not installed (a backend-only machine); CI runs it as `npm run check:bill`."""

    def test_the_editors_live_figures_are_the_servers(self):
        node = shutil.which("node")
        frontend = ROOT / "frontend"
        if not node or not (frontend / "node_modules" / "esbuild").exists():
            self.skipTest("Node and the frontend packages are not installed")
        done = subprocess.run([node, "scripts/check-bill-vectors.mjs"], cwd=frontend, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
