"""A chart must never get its height from itself.

A chart that sizes itself to 100% of its container is measured from the container; if the chart is also what gives the container
its height, the two chase each other. On a whole-pixel screen it happens to settle, so it passed every check here. With display
scaling (125%, 150%: most office laptops) sizes are fractional and it never settles: opening a KPI's drill-down made every bar
chart grow without end. These pin the rule in the source; the behaviour itself was checked in a browser at 100%, 110%, 125% and
150% zoom on every dashboard page and every tile's drill-down (see docs/features.md, "No hole in a page").

None of this needs a database. Run from the repo root:  python -m pytest backend/tests
"""

import re
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"


def sources():
    return [p for p in SRC.rglob("*.tsx") if "node_modules" not in p.parts]


class ChartHeights(unittest.TestCase):
    bar = (SRC / "components" / "dashboard" / "CategoryBar.tsx").read_text(encoding="utf-8")

    def test_the_fill_box_draws_its_chart_out_of_the_flow(self):
        fill = self.bar.split("export function Fill", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("relative", fill)
        self.assertIn("absolute inset-0", fill, "the chart must be in a layer out of the flow, or it can set its own container's height")
        self.assertIn("minHeight", fill)  # the height comes from the minimum and from the card stretching it

    def test_a_percentage_height_chart_is_only_ever_inside_that_box(self):
        for path in sources():
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"<ResponsiveContainer\b([^>]*)>", text):
                height = re.search(r"height=(\{[^}]*\}|\"[^\"]*\")", match.group(1))
                self.assertIsNotNone(height, f"{path.name}: a chart with no height")
                if '"100%"' in height.group(1):
                    self.assertEqual(path.name, "CategoryBar.tsx", f"{path.name}: a 100%-high chart outside Fill grows without end under display scaling")
                    before = text[: match.start()]
                    self.assertGreater(before.rfind("<Fill"), before.rfind("</Fill>"), "it must be inside <Fill>")

    def test_every_other_chart_has_a_pixel_height(self):
        for path in sources():
            if path.name == "CategoryBar.tsx":
                continue
            for match in re.finditer(r"<ResponsiveContainer\b([^>]*)>", path.read_text(encoding="utf-8")):
                self.assertNotIn('"100%"', re.search(r"height=(\{[^}]*\}|\"[^\"]*\")", match.group(1)).group(1), path.name)

    def test_the_drill_down_card_is_a_flex_column_so_the_chart_takes_the_room_left(self):
        text = (SRC / "components" / "dashboard" / "MeasureExplorer.tsx").read_text(encoding="utf-8")
        card = text.split("<CategoryBar", 1)[0].rsplit("<div key={b.key}", 1)[1].split(">", 1)[0]
        self.assertIn("flex flex-col", card)

    def test_the_rule_is_written_down(self):
        text = (Path(__file__).resolve().parents[2] / "docs" / "features.md").read_text(encoding="utf-8")
        self.assertIn("out of the flow", text)


if __name__ == "__main__":
    unittest.main()
