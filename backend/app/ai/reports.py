"""Reports the assistant can make, built entirely from the same tool results the chat uses.

A report is a plain structure (a title, then sections of figures and tables) assembled from retrieved data, never from
anything the model wrote, and drawn as a PDF. So a report cannot contain a number that the dashboards do not.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.ai.tools.analytics import get_business_summary, get_top_items
from app.ai.tools.core import ToolContext
from app.ai.tools.records import get_receivables
from app.billing import get_profile
from app.dashboard.filters import inr

KINDS = {
    "monthly_summary": "Business summary",
    "receivables": "Receivables and ageing",
    "revenue_by_client": "Revenue by client",
}


def _rupees(value: Any) -> str:
    return inr(float(value or 0))


def build(kind: str, ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """The report as a structure. ``args`` are the period and filters, as the analytics tools take them."""
    sections: list[dict[str, Any]] = []
    if kind == "monthly_summary":
        data = get_business_summary(ctx, args).data
        subtitle = data["period"] + (f" · compared with {data['compared_with']}" if data.get("compared_with") else "")
        sections.append({
            "heading": "Headline figures",
            "table": {"columns": [{"label": "Figure"}, {"label": "Value", "align": "right"}, {"label": "Previous", "align": "right"}, {"label": "Change", "align": "right"}],
                      "rows": [[h["label"], h["display"], h.get("previous_display") or "—", (f"{h['change_pct']:+.1f}%" if h.get("change_pct") is not None else h.get("change_display") or "—")] for h in data["headline"]]},
        })
        sections.append({
            "heading": "Money owed now",
            "table": {"columns": [{"label": "Measure"}, {"label": "Value", "align": "right"}],
                      "rows": [["Outstanding", data["receivables_now"]["outstanding"]["display"]], ["Overdue more than 90 days", data["receivables_now"]["overdue_over_90_days"]["display"]],
                               ["Days sales outstanding", f"{data['receivables_now']['days_sales_outstanding']:.0f} days" if data["receivables_now"]["days_sales_outstanding"] is not None else "—"],
                               ["Unpaid bills", str(data["receivables_now"]["unpaid_bills"])]]},
        })
        if data["top_clients"]:
            sections.append({"heading": "Top clients by revenue", "table": {"columns": [{"label": "Client"}, {"label": "Revenue", "align": "right"}, {"label": "Share", "align": "right"}],
                                                                       "rows": [[c["client"], _rupees(c["revenue"]), f"{c['share_pct']:.1f}%" if c["share_pct"] is not None else "—"] for c in data["top_clients"]]}})
        if data["monthly"]:
            sections.append({"heading": "Month by month", "table": {"columns": [{"label": "Month"}, {"label": "Revenue", "align": "right"}, {"label": "Collected", "align": "right"}, {"label": "Bills", "align": "right"}],
                                                               "rows": [[m["month"], _rupees(m["revenue"]), _rupees(m["collected"]), str(m["bills"])] for m in data["monthly"][-12:]]}})
        if data["dashboard_findings"]:
            sections.append({"heading": "What the dashboard flags", "bullets": [f"{f['title']}. {f['detail']}" if f.get("detail") else f["title"] for f in data["dashboard_findings"]]})
        sources = ["Executive overview dashboard"]
    elif kind == "receivables":
        data = get_receivables(ctx, {"limit": 20}).data
        totals = data["totals"]
        sections.append({"heading": "Ageing", "table": {"columns": [{"label": "Age"}, {"label": "Owed", "align": "right"}], "rows": [[label, _rupees(v)] for label, v in zip(data["ageing_buckets"], totals["buckets"])] + [["Total", _rupees(totals["total"])]]}})
        sections.append({"heading": "By client", "table": {"columns": [{"label": "Client"}, {"label": "Owed", "align": "right"}, {"label": "Oldest (days)", "align": "right"}, {"label": "Unpaid bills", "align": "right"}],
                                                          "rows": [[c["client"], _rupees(c["total_owed"]), str(c["oldest_days"]), str(c["unpaid_bills"])] for c in data["clients"]]}})
        subtitle = f"As of {data['as_of']}"
        sources = ["Receivables"]
    elif kind == "revenue_by_client":
        data = get_top_items(ctx, {"by": "client", "metric": "revenue", "limit": 25, **{k: v for k, v in args.items() if k in ("period", "from", "to", "filters")}}).data
        sections.append({"heading": "Revenue by client", "table": {"columns": [{"label": "Client"}, {"label": "Revenue", "align": "right"}, {"label": "Share", "align": "right"}],
                                                              "rows": [[i["name"], _rupees(i["value"]), f"{i['share_pct']:.1f}%" if i.get("share_pct") is not None else "—"] for i in data["items"]]}})
        subtitle = data["period"]
        sources = ["Executive overview dashboard"]
    else:
        raise ValueError(f"Unknown report '{kind}'")
    return {"title": KINDS[kind], "subtitle": subtitle, "kind": kind, "generated": date.today().isoformat(), "sections": sections, "sources": sources}


def render_pdf(report: dict[str, Any], company: str | None = None) -> bytes:
    """The report as an A4 PDF."""
    company = company or get_profile().get("company_name") or "Prakash Securities"
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm, title=report["title"], author="Orion")
    base = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, alignment=0, spaceAfter=2, textColor=colors.HexColor("#0e1726"))
    sub = ParagraphStyle("s", parent=base["Normal"], fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#4d5b73"), spaceAfter=10)
    head = ParagraphStyle("h", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12, spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#136967"))
    body = ParagraphStyle("b", parent=base["Normal"], fontName="Helvetica", fontSize=9.5, leading=13)
    small = ParagraphStyle("f", parent=base["Normal"], fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#6b778c"))
    story: list[Any] = [Paragraph(company.upper(), ParagraphStyle("c", parent=small, fontName="Helvetica-Bold", fontSize=8.5, spaceAfter=4)), Paragraph(report["title"], title), Paragraph(report["subtitle"], sub)]
    for section in report["sections"]:
        story.append(Paragraph(section["heading"], head))
        if "table" in section:
            table = section["table"]
            data = [[c["label"] for c in table["columns"]], *[[str(cell) for cell in row] for row in table["rows"]]]
            t = Table(data, repeatRows=1, hAlign="LEFT")
            style = [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f6")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#d5dbe6")), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
            for index, column in enumerate(table["columns"]):
                if column.get("align") == "right":
                    style.append(("ALIGN", (index, 0), (index, -1), "RIGHT"))
            t.setStyle(TableStyle(style))
            story.append(t)
        for line in section.get("bullets", []):
            story.append(Paragraph("• " + line.replace("&", "&amp;").replace("<", "&lt;"), body))
    story += [Spacer(1, 14), Paragraph(f"Made by the Orion Copilot on {report['generated']} from: {', '.join(report['sources'])}. Every figure is taken from the application's data.", small)]
    doc.build(story)
    return out.getvalue()
