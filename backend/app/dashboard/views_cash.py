"""The Cash tab: the bank balance and its movements, with interest and other income, read from the Bank module rather than the warehouse.

The bank is the firm's own ledger, kept by ``app.bank`` (this file never queries a table itself), so this tab is current to the minute, not to the last warehouse load. It follows the
period chosen at the top like the other tabs. Only people with Bank access may open it (the router checks), because it shows the balance.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app import bank
from app.dashboard.blocks import money_col, table, text_col
from app.dashboard.engine import Dash, make_kpi
from app.dashboard.filters import day_label, inr, month_label, num, qty


def _month_end(first: date) -> date:
    return (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def _within(window: tuple[date, date, str] | None, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not window:
        return rows
    start, end = window[0], window[1]
    return [r for r in rows if r["month"] <= end and _month_end(r["month"]) >= start]


def _card(key: str, label: str, value: str, **extra: Any) -> dict[str, Any]:
    scope = extra.pop("scope", "period")
    card = make_kpi(key, label, value, scope=scope, **extra)
    card["full"] = None
    return card


def _expected_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "code": f"{i['source']}:{i['source_ref']}", "date": day_label(i["due_date"].isoformat()), "who": i.get("counterparty") or "—",
            "what": i.get("description") or i["category_label"], "money_in": num(i["amount"]) if i["direction"] == "in" else 0.0,
            "money_out": num(i["amount"]) if i["direction"] == "out" else 0.0,
        }
        for i in items
    ]


def cash(d: Dash) -> dict[str, Any]:
    data = bank.series(36)
    if not data.get("configured"):
        return {"kpis": [], "series": {"trend": []}, "categories": {}, "tables": {}}
    summary = bank.summary()
    forecast = bank.forecast()
    months = _within(d.window, data["months"])
    trend = [
        {
            "code": m["month"].strftime("%Y-%m"), "label": month_label(m["month"].strftime("%Y-%m")),
            "money_in": round(num(m["money_in"]), 2), "money_out": round(num(m["money_out"]), 2), "net": round(num(m["net"]), 2),
            "closing_balance": round(num(m["closing_balance"]), 2), "client_receipts": round(num(m["client_receipts"]), 2),
            "other_income": round(num(m["other_income"]), 2), "interest": round(num(m["interest"]), 2),
        }
        for m in months
    ]
    start = d.window[0] if d.window else (months[0]["month"] if months else date.today())
    end = d.window[1] if d.window else date.today()
    money_in = sum(m["money_in"] for m in trend)
    money_out = sum(m["money_out"] for m in trend)
    other = sum(m["other_income"] for m in trend)
    interest = sum(m["interest"] for m in trend)
    breakdown = bank.breakdown(start, end)

    def mix(direction: str) -> list[dict[str, Any]]:
        return [
            {"code": r["category"], "label": r["label"], "value": round(num(r["total"]), 2)}
            for r in breakdown if r["direction"] == direction and num(r["total"]) > 0
        ]

    rec = summary["reconciliation"]
    open_items = rec["book_unmatched"] + rec["lines_unmatched"] + rec.get("changed_after_matching", 0)
    next30 = forecast["windows"][0]
    opening = summary["account"]
    kpis = [
        _card("bank_balance", "Bank balance", inr(num(summary["balance"])), scope="snapshot", tone="teal",
              hint=f"Today. Opening {inr(num(opening['opening_balance']))} on {day_label(opening['opening_date'].isoformat())}"),
        _card("bank_in", "Money in", inr(money_in), current=money_in, tone="emerald", hint="Clients' payments, interest and other receipts",
              spark=d.spark("money_in", rows_=trend)),
        _card("bank_out", "Money out", inr(money_out), current=money_out, tone="rose", higher_is_better=False,
              hint="Expenses, GST paid, charges and other payments", spark=d.spark("money_out", rows_=trend)),
        _card("bank_net", "Net cash flow", inr(money_in - money_out), current=money_in - money_out, tone="blue", hint="Money in less money out",
              spark=d.spark("net", rows_=trend)),
        _card("bank_other_income", "Interest and other income", inr(other), current=other, tone="violet",
              hint=f"Interest {inr(interest)}; the rest is other income", spark=d.spark("other_income", rows_=trend)),
        _card("bank_unreconciled", "Not yet reconciled", qty(open_items), scope="snapshot", tone="amber", higher_is_better=False,
              hint=f"{qty(rec['book_unmatched'])} in the book, {qty(rec['lines_unmatched'])} on the statement, {qty(rec.get('changed_after_matching', 0))} changed after matching"),
        _card("bank_next30", "Expected in 30 days", inr(num(next30["money_in"]) - num(next30["money_out"])), scope="snapshot", tone="slate",
              hint=f"{inr(num(next30['money_in']))} due in, {inr(num(next30['money_out']))} due out"),
    ]
    weeks = [
        {
            "code": w["week_start"].isoformat(), "week": f"{day_label(w['week_start'].isoformat())} – {day_label(w['week_end'].isoformat())}",
            "money_in": num(w["money_in"]), "money_out": num(w["money_out"]), "balance": num(w["balance"]),
        }
        for w in forecast["weeks"]
    ]
    income_rows = [
        {
            "code": f"{r['move_date'].isoformat()}:{n}", "date": day_label(r["move_date"].isoformat()), "kind": r["category_label"],
            "who": r.get("counterparty") or "—", "what": r.get("description") or "—", "amount": num(r["amount"]),
        }
        for n, r in enumerate(bank.other_income(start, end))
    ]
    expected_cols = [text_col("date", "Due"), text_col("who", "Who"), text_col("what", "What"), money_col("money_in", "In"), money_col("money_out", "Out")]
    return {
        "kpis": kpis,
        "series": {"trend": trend},
        "categories": {"inflow": mix("in"), "outflow": mix("out")},
        "tables": {
            "weeks": table([text_col("week", "Week"), money_col("money_in", "In"), money_col("money_out", "Out"), money_col("balance", "Projected balance")], weeks),
            "expected": table(expected_cols, _expected_rows(forecast["upcoming"]), truncated=len(forecast["upcoming"]) >= 25),
            "overdue": table(expected_cols, _expected_rows(forecast["overdue"]["items"])),
            "income": table(
                [text_col("date", "Date"), text_col("kind", "Kind"), text_col("who", "From"), text_col("what", "Note"), money_col("amount", "Amount")],
                income_rows,
                totals={"amount": round(other, 2)},
            ),
        },
    }
