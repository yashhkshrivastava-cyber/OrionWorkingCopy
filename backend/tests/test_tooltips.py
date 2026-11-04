"""Tooltips stay readable in every theme.

A chart's colours are mid-tones picked to be seen as shapes on either surface. As *text* on a white card, amber, lime or
sky are close to invisible, which is what the library's default tooltip did (it paints each line in its series colour).
Every chart tooltip is therefore drawn by ChartTooltip.TipCard, which carries the colour in a swatch and writes in the
theme's own text colours, and every hover card is a solid surface: through a see-through one the figures behind showed.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

SRC = ROOT / "frontend" / "src"


def sources():
    return [p for p in SRC.rglob("*.tsx") if "node_modules" not in p.parts]


class ChartTooltips(unittest.TestCase):
    def test_no_chart_tooltip_uses_the_librarys_default_card(self):
        for path in sources():
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"<Tooltip\b(.*?)/>", text, flags=re.S):
                body = match.group(1)
                if "content={" not in body and "label=" not in body:  # ui/Tooltip takes `label`; a chart's takes `content`
                    self.fail(f"{path.relative_to(ROOT)}: a chart <Tooltip> without content={{...}} paints its lines in series colours")

    def test_the_text_of_a_tooltip_never_takes_a_series_colour(self):
        card = (SRC / "components" / "dashboard" / "ChartTooltip.tsx").read_text(encoding="utf-8")
        # the colour is only ever the swatch's background
        self.assertEqual(len(re.findall(r"color: row\.color|text-\[color:row", card)), 0)
        self.assertIn("background: row.color", card)

    def test_the_hover_card_is_a_solid_surface(self):
        card = (SRC / "components" / "dashboard" / "HoverCard.tsx").read_text(encoding="utf-8")
        self.assertIn("tip-surface", card)
        self.assertNotIn("overlay", card.split('role="tooltip"')[1])
        css = (SRC / "index.css").read_text(encoding="utf-8")
        block = css.split(".tip-surface", 1)[1].split("}", 1)[0]
        self.assertIn("background: var(--orion-surface);", block)

    def test_the_tooltip_over_the_donut_is_above_its_centre_label(self):
        donut = (SRC / "components" / "dashboard" / "CategoryDonut.tsx").read_text(encoding="utf-8")
        self.assertIn("zIndex", donut)

    def test_a_chart_of_several_series_talks_about_the_one_the_pointer_is_on(self):
        """The tooltip is shared by the whole month; only the series itself knows the pointer is on it."""
        for rel in ("components/dashboard/MonthlyChart.tsx", "components/assistant/ChartBlock.tsx"):
            text = (SRC / rel).read_text(encoding="utf-8")
            self.assertIn("useSeriesFocus", text, rel)
            self.assertIn("<SeriesTip", text, rel)
            self.assertIn("focusKey={focus}", text, rel)
            # every kind of series is bound, so the stack, the area and the line all report themselves
            self.assertGreaterEqual(text.count("{...bind("), 3, rel)

    def test_the_trend_is_not_tied_to_the_first_series(self):
        text = (SRC / "components" / "dashboard" / "MonthlyChart.tsx").read_text(encoding="utf-8")
        self.assertNotIn("shown[0]", text)
        self.assertNotIn("primary", text)

    def test_one_helper_words_a_change(self):
        fmt = (SRC / "components" / "dashboard" / "format.ts").read_text(encoding="utf-8")
        self.assertIn("export function movement", fmt)
        for rel in ("components/dashboard/ChartTooltip.tsx", "components/dashboard/Sparkline.tsx"):
            self.assertIn("movement", (SRC / rel).read_text(encoding="utf-8"), rel)


if __name__ == "__main__":
    unittest.main()
