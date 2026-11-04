"""Read tools over the Bank module: the balance, where the money came from and went, what is expected, and the ledger.

Every figure comes from ``app.bank``, the same functions the Bank pages use, so an answer and the page it came from agree. Nothing here writes:
entries, uploads and matching are made on the Bank pages by a person. Access is the Bank permission, checked for each call.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app import bank
from app.ai.tools.core import READ, ToolContext, ToolError, ToolResult, tool
from app.auth import can_access_bank
from app.dashboard.filters import inr


def _needs_bank(user: dict[str, Any]) -> bool:
    return can_access_bank(user)


def _f(value: Any) -> float:
    return round(float(value or 0), 2)


def _configured(found: dict[str, Any]) -> None:
    if not found.get("configured"):
        raise ToolError("The bank account has not been set up yet. Someone with permission to change the bank must enter its opening balance on the Bank page.")


@tool(
    name="get_bank_balance",
    label="Reading the bank",
    kind=READ,
    needs=_needs_bank,
    description=(
        "The firm's bank balance today and how it got there: this month and this financial year, money in and out, interest and other income "
        "earned, bank charges, and whether the book agrees with the latest bank statement. Use for 'what is our bank balance', 'how much cash "
        "do we have', 'how much interest have we earned', 'is the bank reconciled'. The balance is the opening balance plus clients' payments, "
        "expenses, GST paid and the entries made on the Bank page; it is not read from the bank itself."
    ),
    schema={"properties": {}},
)
def get_bank_balance(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    summary = bank.summary()
    _configured(summary)
    fy, month, rec = summary["financial_year"], summary["month"], summary["reconciliation"]
    state = bank.reconciliation()
    data: dict[str, Any] = {
        "source": "Bank book",
        "as_of": summary["as_of"].isoformat(),
        "balance": _f(summary["balance"]),
        "balance_display": inr(float(summary["balance"])),
        "accounts": [{"name": a["account_name"], "kind": a["account_kind"], "balance": _f(a["balance"])} for a in summary.get("accounts", [])],
        "opening": {"balance": _f(summary["account"]["opening_balance"]), "date": summary["account"]["opening_date"].isoformat()},
        "this_month": {"money_in": _f(month["money_in"]), "money_out": _f(month["money_out"]), "net": _f(month["net"])},
        "this_financial_year": {
            "from": fy["from"].isoformat(), "money_in": _f(fy["money_in"]), "money_out": _f(fy["money_out"]), "net": _f(fy["net"]),
            "client_receipts": _f(fy["client_receipts"]), "interest_earned": _f(fy["interest"]), "other_income": _f(fy["other_income"]),
            "interest_and_other_income": _f(fy["interest_and_other_income"]), "bank_charges": _f(fy["bank_charges"]),
        },
        "reconciliation": {
            "book_movements_not_on_a_statement_line": rec["book_unmatched"], "statement_lines_not_in_the_book": rec["lines_unmatched"],
            "matched_lines_whose_match_no_longer_holds": rec.get("changed_after_matching", 0),
            "statement_covers": [rec["statement_from"].isoformat() if rec["statement_from"] else None, rec["statement_to"].isoformat() if rec["statement_to"] else None],
        },
    }
    if state.get("state") in ("reconciled", "explained", "unexplained"):
        data["against_latest_statement"] = {
            "as_of": state["as_of"].isoformat(), "statement_balance": _f(state["statement_balance"]), "book_balance": _f(state["book_balance"]),
            "difference": _f(state["difference"]), "unexplained": _f(state["unexplained"]), "state": state["state"],
        }
    else:
        data["against_latest_statement"] = None
    data["minimum_balance_alerts"] = [{"title": a["title"], "detail": a["detail"]} for a in bank.alerts()]
    ctx.source("Bank", "balance and this financial year", "/bank")
    ctx.remember(data)
    return ToolResult(data, f"Read the bank balance ({data['balance_display']})")


@tool(
    name="get_bank_forecast",
    label="Looking ahead at the bank",
    kind=READ,
    needs=_needs_bank,
    description=(
        "Where the bank balance is heading, from what Orion already knows is coming: bills clients still have to pay, costs still to come, and "
        "GST still to pay (estimated for the 20th of the month after the bill). Gives the next 30, 60 and 90 days, what is overdue, and the "
        "lowest projected week. Use for 'will we have enough cash', 'what is coming in next month', 'cash forecast'. Only what is already entered "
        "is in it."
    ),
    schema={"properties": {"include_overdue": {"type": "boolean", "description": "Count money already overdue as arriving in the first week."}}},
)
def get_bank_forecast(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    found = bank.forecast(include_overdue=bool(args.get("include_overdue")))
    _configured(found)
    data = {
        "source": "Bank book",
        "balance_today": _f(found["balance"]),
        "windows": [
            {"next_days": w["days"], "expected_in": _f(w["money_in"]), "expected_out": _f(w["money_out"]), "projected_balance": _f(w["projected_balance"])}
            for w in found["windows"]
        ],
        "overdue": {"count": found["overdue"]["count"], "owed_to_us": _f(found["overdue"]["money_in"]), "we_owe": _f(found["overdue"]["money_out"])},
        "lowest_projected_balance": {"balance": _f(found["lowest"]["balance"]), "week_starting": found["lowest"]["week_start"].isoformat()},
        "overdue_counted_in_projection": found["include_overdue"],
        "note": found["note"],
    }
    ctx.source("Bank", "cash forecast", "/bank/forecast")
    ctx.remember(data)
    return ToolResult(data, "Read the cash forecast")


@tool(
    name="search_bank_ledger",
    label="Searching the bank book",
    kind=READ,
    needs=_needs_bank,
    description=(
        "Movements in the bank book (money in and out) between two dates, newest first, with totals. Filter by direction, category or words in "
        "the name or note. Use for 'what did we pay in bank charges', 'payments from Acme last month', 'show interest credits'. Returns at most 15 rows."
    ),
    schema={
        "properties": {
            "date_from": {"type": "string", "description": "YYYY-MM-DD"},
            "date_to": {"type": "string", "description": "YYYY-MM-DD"},
            "direction": {"type": "string", "enum": ["in", "out"]},
            "category": {"type": "string", "enum": sorted(bank.CATEGORY_LABELS)},
            "q": {"type": "string", "maxLength": 60},
        },
    },
)
def search_bank_ledger(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    for key in ("date_from", "date_to"):
        if args.get(key):
            try:
                date.fromisoformat(str(args[key]))
            except ValueError:
                raise ToolError(f"{key} must be a date like 2026-04-30.") from None
    try:
        found = bank.ledger(
            date_from=args.get("date_from"), date_to=args.get("date_to"), direction=args.get("direction"), category=args.get("category"),
            q=args.get("q"), limit=15,
        )
    except bank.BankError as exc:
        raise ToolError(str(exc)) from exc
    _configured(found)
    rows = [
        {
            "date": r["move_date"].isoformat(), "direction": r["direction"], "amount": _f(r["amount"]), "kind": r["category_label"],
            "who": r["counterparty"], "note": r["description"], "reference": r["reference"], "reconciled": r["reconciled"],
        }
        for r in found["rows"]
    ]
    data = {
        "source": "Bank book", "matching": found["total"], "shown": len(rows), "total_in": _f(found["totals"]["in"]), "total_out": _f(found["totals"]["out"]),
        "rows": rows,
    }
    ctx.source("Bank", "ledger", "/bank/ledger")
    ctx.remember(data)
    return ToolResult(data, f"Found {found['total']} movement(s) in the bank book")
