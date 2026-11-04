"""The profit and loss statement shown at the top of the Profitability tab.

    Revenue
    - direct cost (payroll at cases, EPFO and ESIC paid on the bills of cases, running costs at cases, penalties and short payments)
    = Contribution margin
    - head office (payroll, EPFO and ESIC paid on bills with no case, running costs not tied to a case)
    = Operating profit   (this is the "Operating margin" on the dashboards: the two always agree)
    - bank charges + interest and other income          (from the bank book: only for someone with Bank access, and only when the selection is a period)
    = Profit before tax

A line is a cost of the case it is booked against; what has no case is head office. Everything reads the same scopes as the headline margin (the cost view
``orion_dw.expense_cost``), on the filters revenue, expenses and payroll all carry, so the statement cannot disagree with the figure above it.
Depreciation is not tracked, and income tax paid is shown as a memo (cash paid is not the tax expense).
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from app.dashboard.blocks import money_col, pct_col, table, text_col
from app.dashboard.engine import EXPENSE, PERIOD_KEYS, REVENUE, SALARY, Dash, pct
from app.dashboard.filters import common
from app.dashboard.measures import scalars

DIRECT = "c.case_code IS NOT NULL"
HEAD_OFFICE = "c.case_code IS NULL"
STATUTORY = "e.expense_type_code = 'STATUTORY'"
SHORTFALL = "e.expense_type_code = 'SHORTFALL'"
RUNNING = "COALESCE(e.expense_type_code, '') NOT IN ('STATUTORY', 'SHORTFALL')"

NOTE_NO_BANK = "Bank charges, interest and tax are not shown: they come from the bank book, which needs Bank access."
NOTE_SELECTION = "Bank charges, interest and tax are not shown for a selection of one client, case or business line: the bank book does not know them."
NOTE_DEPRECIATION = "Depreciation is not tracked, so it is not deducted. Income tax paid is shown as a memo: cash paid is not the tax expense."


def window(filters: dict[str, str]) -> tuple[date | None, date | None]:
    """The calendar days a selection covers, for the bank book (which is dated by day): the exact days, else the month, else the financial year."""
    start = date.fromisoformat(filters["from"]) if filters.get("from") else None
    end = date.fromisoformat(filters["to"]) if filters.get("to") else None
    if start or end:
        return start, end
    if filters.get("month"):
        year, month = (int(part) for part in filters["month"].split("-"))
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    if filters.get("fy", "").isdigit():
        year = int(filters["fy"])
        return date(year, 4, 1), date(year + 1, 3, 31)
    return None, None


def _bank_lines(cur, filters: dict[str, str]) -> dict[str, float]:
    from app import bank  # the bank book is the Bank's to read; this is the one place the dashboards ask it

    start, end = window(filters)
    return bank.entry_totals(cur, start, end, ("bank_charges", "interest", "other_income", "tax"))


def profit_and_loss(d: Dash, bank_access: bool) -> dict[str, Any]:
    cur = d.cur
    shared = common(d.filters, "bill", "expense", "payroll")

    revenue = scalars(cur, "bill", shared, {"v": REVENUE})["v"]

    def pay(where: str) -> float:
        return scalars(cur, "payroll", shared, {"v": SALARY}, extra=[where])["v"]

    def spend(*where: str) -> float:
        return scalars(cur, "expense", shared, {"v": EXPENSE}, extra=list(where))["v"]

    direct = {
        "payroll": pay(DIRECT),
        "employer": spend(DIRECT, STATUTORY),
        "running": spend(DIRECT, RUNNING),
        "shortfall": spend(DIRECT, SHORTFALL),
    }
    head = {
        "payroll": pay(HEAD_OFFICE),
        "employer": spend(HEAD_OFFICE, STATUTORY),
        "running": spend(HEAD_OFFICE, RUNNING),
        "shortfall": spend(HEAD_OFFICE, SHORTFALL),
    }
    direct_total = sum(direct.values())
    head_total = sum(head.values())
    contribution = revenue - direct_total
    operating = contribution - head_total

    lines: list[dict[str, Any]] = []

    def add(label: str, amount: float | None, kind: str = "line", indent: int = 0, note: str = "") -> None:
        row: dict[str, Any] = {"label": label, "kind": kind, "indent": indent, "note": note}
        if amount is None:
            row.update(amount="", pct="")
        else:
            row.update(amount=round(amount, 2), pct=round(pct(amount, revenue), 1) if revenue else "")
        lines.append(row)

    add("Revenue", revenue, "total", note="Taxable value of issued bills (EPFO and ESIC charged included), less credit notes. GST is not revenue.")
    add("Payroll at cases", direct["payroll"], indent=1)
    add("EPFO and ESIC paid", direct["employer"], indent=1, note="Paid to the authority, on the day paid, against the bill's case. Not linked to payroll.")
    add("Running costs at cases", direct["running"], indent=1)
    add("Penalties and short payments", direct["shortfall"], indent=1, note="Held back by clients: a loss. TDS is not.")
    add("Direct cost", direct_total, "subtotal")
    add("Contribution margin", contribution, "total", note="What the cases earn before head office.")
    add("Head-office payroll", head["payroll"], indent=1)
    add("Head-office EPFO and ESIC paid", head["employer"], indent=1, note="Paid on bills that have no case.")
    add("Head-office running costs", head["running"] + head["shortfall"], indent=1, note="Costs with no case behind them.")
    add("Head office", head_total, "subtotal")
    add("Operating profit", operating, "total", note="The Operating margin on every dashboard.")

    if not bank_access:
        add(NOTE_NO_BANK, None, "note")
    elif any(key not in PERIOD_KEYS for key in d.filters):
        add(NOTE_SELECTION, None, "note")
    else:
        bank = _bank_lines(cur, d.filters)
        charges = bank.get("bank_charges", 0.0)
        income = bank.get("interest", 0.0) + bank.get("other_income", 0.0)
        add("Bank charges", charges, indent=1)
        add("Interest and other income", income, indent=1, note="Earned, as entered in the Bank.")
        add("Profit before tax", operating - charges + income, "total")
        add("Income tax or TDS paid (memo)", bank.get("tax", 0.0), "memo", note="Cash paid in the period; not deducted above.")
    add(NOTE_DEPRECIATION, None, "note")

    columns = [text_col("label", "Line"), money_col("amount", "Amount"), pct_col("pct", "% of revenue")]
    return table(columns, lines)
