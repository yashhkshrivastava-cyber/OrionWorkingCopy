"""Tally billed dashboard.

Reads only ``tally_dw`` current sales facts. Orion dashboards stay on
``orion_ods`` and are not mixed in here.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date
from typing import Any

from app.dashboard.engine import full_change
from app.dashboard.filters import day_label, delta, inr, kpi, month_label, qty
from app.database import db_cursor
from app.tally_kpi_help import KPI_HELP, SCOPE_PERIOD, SCOPE_SNAPSHOT
from app.tally_insights import (
    build_insights,
    comparison_windows,
    resolve_fy,
    parse_day,
    selected_window,
    top_movers,
    validate_filters,
)

CLIENT_LIMIT = 200
NOTE_LIMIT = 200

FILTER_KEYS = (
    "month",
    "client",
    "company",
    "voucher_type",
    "fy",
    "from",
    "to",
    "cost_centre",
    "income_line",
    "bucket",
)

INCOME_GROUPS = (
    ("manpower", "Manpower", ("%manpower%", "%man power%", "%security%")),
    ("vehicle", "Vehicle rent", ("%vehicle%", "%rental%", "%rent reciv%", "%rent receiv%")),
    ("service", "SG service", ("%sg service%", "%service charge%")),
    ("epf", "EPF billed", ("%epf%",)),
    ("esic", "ESIC billed", ("%esic%",)),
    ("other_income", "Other income", ()),
)

INCOME_LINES = (
    ("manpower", "Manpower"),
    ("vehicle", "Vehicle rent"),
    ("service", "SG service"),
    ("epf", "EPF billed"),
    ("esic", "ESIC billed"),
    ("other_income", "Other income"),
)

_MEASURES = (
    "invoice_value_incl_gst",
    "revenue_ex_gst",
    "gst",
    "cgst",
    "sgst",
    "manpower_supply",
    "vehicle_rental",
    "service_charges",
    "epf_billed",
    "esic_billed",
    "other_income",
)


def build_tally_dashboard(raw_filters: dict[str, Any]) -> dict[str, Any]:
    payload = _build_tally_dashboard(raw_filters)
    from app.tally_explore import MEASURES

    for item in payload.get("kpis", []):
        item["explore"] = item["key"] in MEASURES
    return payload


def _build_tally_dashboard(raw_filters: dict[str, Any]) -> dict[str, Any]:
    with db_cursor() as cur:
        if not _warehouse_ready(cur):
            filters, invalid = validate_filters(_clean_filters(resolve_fy(raw_filters, None)))
            return _empty_payload(filters, "Tally warehouse has not been loaded yet.", invalid)
        bounds = _data_span(cur)
        lo, hi = parse_day(bounds["min"]), parse_day(bounds["max"])
        # "This financial year" and "every year" are asked for by name and become a year (or nothing) here.
        filters, invalid = validate_filters(_clean_filters(resolve_fy(raw_filters, hi)))
        totals = _aggregates(cur, filters)
        income = _income_from_lines(cur, filters)
        for key, value in income["totals"].items():
            totals[key] = value

        # Comparisons exist only where the data covers the comparison window.
        windows = comparison_windows(filters, lo, hi)

        def window_totals(window: dict[str, Any]) -> dict[str, Any] | None:
            """Every figure for a comparison window, income lines included, or None where nothing was billed in it."""
            found = _aggregates(cur, window["filters"])
            if not found["invoices"]:
                return None
            for key, value in _income_from_lines(cur, window["filters"])["totals"].items():
                found[key] = value
            return found

        previous = prev_label = None
        if windows["previous"]:
            candidate = window_totals(windows["previous"])
            if candidate:
                previous, prev_label = candidate, windows["previous"]["label"]
        yoy = yoy_label = None
        if windows["yoy"]:
            candidate = window_totals(windows["yoy"])
            if candidate:
                yoy, yoy_label = candidate, windows["yoy"]["label"]

        full = full_label = None
        if windows["full"]:
            candidate = window_totals(windows["full"])
            if candidate:
                full, full_label = candidate, windows["full"]["label"]

        window = selected_window(filters, lo, hi)
        if window:
            cur_range = _range_text(window[0], min(window[1], hi) if hi else window[1])
        elif lo and hi:
            cur_range = "All billed days, " + _range_text(lo, hi)
        else:
            cur_range = ""
        prev_range = _filters_range(windows["previous"]["filters"]) if previous is not None and windows["previous"] else ""
        yoy_range = _filters_range(windows["yoy"]["filters"]) if yoy is not None and windows["yoy"] else ""
        full_range = _filters_range(windows["full"]["filters"]) if full is not None and windows["full"] else ""
        if previous is not None:
            no_compare = ""
        elif not window:
            no_compare = (
                "All billed days are selected, so there is no earlier period to compare with. "
                "Choose a month, financial year or date range to see a change."
            )
        else:
            no_compare = "The billed data does not reach back far enough to compare this selection with an earlier one."

        # Charts keep every month in view so a clicked month can be seen in context.
        context = {key: value for key, value in filters.items() if key != "month"}
        monthly = _monthly(cur, filters)
        monthly_ctx = _monthly(cur, context)
        income_trend = _monthly_income(cur, context)
        doc_trend = _document_trend(cur, context)
        top_clients = _top_clients(cur, filters)

        def top_share_in(window: dict[str, Any] | None) -> float | None:
            """The largest client's share of revenue in a comparison window (None where it has no data)."""
            if window is None:
                return None
            found = _top_clients(cur, window["filters"], limit=1)
            revenue = _aggregates(cur, window["filters"])["revenue"]
            return _pct(float(found[0]["revenue"]), revenue) if found and revenue else None

        top_shares = {
            "previous": top_share_in(windows["previous"] if previous else None),
            "yoy": top_share_in(windows["yoy"] if yoy else None),
            "full": top_share_in(windows["full"] if full else None),
        }
        voucher_mix = _voucher_mix(cur, filters)
        note_rows = _note_documents(cur, filters)
        note_clients = _notes_by_client(cur, filters)
        companies = _by_company(cur, filters)
        fys = _by_fy(cur, filters)
        cost_centres = _by_cost_centre(cur, filters)
        client_rows = _client_month_rows(cur, filters)
        debtor_rows = _debtor_rows(cur, filters)
        income_rows = income["rows"]
        debtors = _debtor_snapshot(cur, filters)
        position = _books_position(cur, filters)
        options = _filter_options(cur)
        chips = _chips(filters)
        gainers, losers, mover_basis, mover_months = _movers(cur, filters, windows, previous, prev_label, monthly_ctx)

    insights = build_insights(
        totals=totals,
        previous=previous,
        previous_label=prev_label or "",
        yoy=yoy if windows["yoy"] else None,
        monthly=monthly_ctx,
        clients=[] if filters.get("client") else top_clients,
        gainers=gainers,
        losers=losers,
        mover_basis=mover_basis,
        mover_months=mover_months,
        notes=note_rows,
        income_groups=income["groups"],
        data_end=hi,
        window=selected_window(filters, lo, hi)[:2] if selected_window(filters, lo, hi) else None,
        month_selected=bool(filters.get("month")),
        like_for_like=bool(windows["previous"] and windows["previous"].get("like_for_like")),
        yoy_phrase="the " + (yoy_label or "vs same period last year")[3:],
        shorten=_short_label,
    )

    spark_window = monthly_ctx[-12:]
    docs_window = doc_trend[-12:]

    def spark(rows: list[dict[str, Any]], key: str, kind: str = "money") -> dict[str, Any] | None:
        values = [round(float(row[key]), 2) for row in rows]
        if len(values) < 3:
            return None
        return {"values": values, "labels": [row["label"] for row in rows], "kind": kind}

    avg_rows = [row for row in spark_window if row["invoices"]]
    avg_spark = (
        {
            "values": [round(float(row["billed"]) / float(row["invoices"]), 2) for row in avg_rows],
            "labels": [row["label"] for row in avg_rows],
            "kind": "money",
        }
        if len(avg_rows) >= 3
        else None
    )

    def compare(
        key: str,
        label: str,
        value: str,
        current: float,
        *,
        prev: Any = _UNSET,
        yoy_value: Any = _UNSET,
        full_value: Any = _UNSET,
        fmt=inr,
        sign: int = 1,
        **extra: Any,
    ) -> dict[str, Any]:
        """A KPI that carries its previous-period, year-on-year and whole-previous-year change when they exist."""
        if prev is _UNSET:
            prev = previous.get(key) if previous else None
        if yoy_value is _UNSET:
            yoy_value = yoy.get(key) if yoy else None
        if full_value is _UNSET:
            full_value = full.get(key) if full else None
        detail: dict[str, Any] = {"current_range": cur_range}
        if prev:
            detail.update(
                compare=prev_label or "",
                current_value=value,
                previous_value=fmt(sign * float(prev)),
                previous_range=prev_range,
            )
        if yoy_value:
            detail.update(
                yoy_label=yoy_label or "",
                current_value=value,
                yoy_value=fmt(sign * float(yoy_value)),
                yoy_range=yoy_range,
            )
        if full_value:
            detail.update(
                full_label=full_label or "",
                full_value=fmt(sign * float(full_value)),
                full_range=full_range,
            )
        if not prev and not yoy_value and not full_value:
            detail["note"] = no_compare or (
                "The earlier period had none of this (zero), so a percentage change cannot be worked out."
            )
        card = _kpi(
            key,
            label,
            value,
            current=current,
            previous=prev,
            yoy=yoy_value,
            compare=prev_label or "",
            yoy_label=yoy_label or "",
            detail=detail,
            **extra,
        )
        card["full"] = full_change(
            current,
            float(full_value) if full_value else None,
            label=full_label or "",
            value=fmt(sign * float(full_value)) if full_value else "",
            range_text=full_range,
            higher_is_better=extra.get("higher_is_better", True),
        )
        return card

    def share_kpi(
        key: str,
        label: str,
        value: str,
        current: float,
        shares: dict[str, float | None],
        *,
        higher_is_better: bool = True,
        **extra: Any,
    ) -> dict[str, Any]:
        """A percentage figure, set against the same share in each comparison window, in percentage points.

        ``shares`` holds the share in each window that has data: ``previous``, ``yoy`` and ``full``."""

        def points(base: float | None) -> tuple[str, str]:
            if base is None:
                return "", "neutral"
            diff = current - base
            if abs(diff) < 0.05:
                return "flat", "neutral"
            return f"{diff:+.1f} pts", "positive" if (diff > 0) == higher_is_better else "negative"

        change, change_type = points(shares.get("previous"))
        detail: dict[str, Any] = {"current_range": cur_range}
        if shares.get("previous") is not None:
            detail.update(
                compare=prev_label or "", current_value=value, previous_value=f"{shares['previous']:.1f}%", previous_range=prev_range
            )
        if shares.get("full") is not None:
            detail.update(full_label=full_label or "", full_value=f"{shares['full']:.1f}%", full_range=full_range)
        if shares.get("previous") is None and shares.get("full") is None:
            detail["note"] = no_compare or "There was nothing billed in the earlier period to set this against."
        card = _kpi(
            key, label, value, change=change, change_type=change_type, compare=prev_label if change else "",
            higher_is_better=higher_is_better, detail=detail, **extra,
        )
        card["full"] = full_change(
            current, shares.get("full"), label=full_label or "", value=f"{shares['full']:.1f}%" if shares.get("full") is not None else "",
            range_text=full_range, higher_is_better=higher_is_better, points=True,
        )
        return card

    mom_billed, mom_billed_type = _mom_from_series(monthly, "billed")
    mom_revenue, mom_revenue_type = _mom_from_series(monthly, "revenue")
    gst_pct = _pct(totals["gst"], totals["billed"])
    avg_invoice = totals["billed"] / totals["invoices"] if totals["invoices"] else 0
    avg_revenue = totals["revenue"] / totals["invoices"] if totals["invoices"] else 0
    prev_avg = previous["billed"] / previous["invoices"] if previous and previous["invoices"] else None
    yoy_avg = yoy["billed"] / yoy["invoices"] if yoy and yoy["invoices"] else None
    full_avg = full["billed"] / full["invoices"] if full and full["invoices"] else None

    def ratio(found: dict[str, Any] | None, part: str, whole: str) -> float | None:
        """``part`` as a share of ``whole`` in a window's figures, or None where there are none."""
        if found is None:
            return None
        return _pct(abs(found[part]), found[whole]) if found[whole] else None

    latest = monthly[-1] if monthly else None
    prior_month = monthly[-2] if len(monthly) > 1 else None
    latest_label = month_label(latest["code"]) if latest else "—"
    latest_billed = float(latest["billed"]) if latest else 0
    latest_partial = bool(
        latest and hi and latest["code"] == hi.strftime("%Y-%m") and hi.day < monthrange(hi.year, hi.month)[1]
    )

    income_window = income_trend[-12:]
    kpis = [
        compare(
            "billed",
            "Billed",
            inr(totals["billed"]),
            totals["billed"],
            hint="Invoice value including GST: sales plus debit notes, less credit notes",
            tone="blue",
            spark=spark(spark_window, "billed"),
        ),
        compare(
            "revenue",
            "Revenue",
            inr(totals["revenue"]),
            totals["revenue"],
            hint="Taxable value billed, excluding GST",
            tone="teal",
            spark=spark(spark_window, "revenue"),
        ),
        compare(
            "gst",
            "GST",
            inr(totals["gst"]),
            totals["gst"],
            hint=f"CGST {inr(totals['cgst'])} · SGST {inr(totals['sgst'])}",
            tone="violet",
            spark=spark(spark_window, "gst"),
        ),
        share_kpi(
            "gst_pct",
            "GST %",
            f"{gst_pct:.1f}%",
            gst_pct,
            {"previous": ratio(previous, "gst", "billed"), "yoy": ratio(yoy, "gst", "billed"), "full": ratio(full, "gst", "billed")},
            hint="GST ÷ billed including tax",
            tone="violet",
        ),
        compare(
            "invoices",
            "Documents",
            qty(totals["invoices"]),
            totals["invoices"],
            hint="Sales, credit and debit vouchers in this window",
            tone="slate",
            fmt=qty,
            spark=spark(spark_window, "invoices", "number"),
        ),
        compare(
            "clients",
            "Clients",
            qty(totals["clients"]),
            totals["clients"],
            hint="Distinct party ledgers billed in this window",
            tone="amber",
            fmt=qty,
        ),
        compare(
            "avg_invoice",
            "Avg invoice",
            inr(avg_invoice),
            avg_invoice,
            prev=prev_avg,
            yoy_value=yoy_avg,
            full_value=full_avg,
            hint="Net billed ÷ all documents, so credit notes lower it. Sales-only average is on the Billing tab",
            tone="blue",
            spark=avg_spark,
        ),
        compare(
            "avg_revenue",
            "Avg revenue",
            inr(avg_revenue),
            avg_revenue,
            prev=previous["revenue"] / previous["invoices"] if previous and previous["invoices"] else None,
            yoy_value=yoy["revenue"] / yoy["invoices"] if yoy and yoy["invoices"] else None,
            full_value=full["revenue"] / full["invoices"] if full and full["invoices"] else None,
            hint="Revenue excluding GST per document",
            tone="teal",
        ),
        _kpi(
            "latest_month",
            "Latest month",
            inr(latest_billed),
            change=mom_billed,
            change_type=mom_billed_type,
            compare=f"vs {prior_month['label']}" if prior_month else "",
            detail=_month_detail(latest, prior_month, "billed", latest_partial, hi),
            hint=(
                (f"{latest_label}, billed to {day_label(hi.isoformat())}" if latest_partial else latest_label)
                if latest
                else "No billed months in this selection"
            ),
            tone="emerald",
            spark=spark(spark_window, "billed"),
        ),
        _kpi(
            "mom_revenue",
            "Latest month revenue",
            inr(float(latest["revenue"])) if latest else "—",
            change=mom_revenue,
            change_type=mom_revenue_type,
            compare=f"vs {prior_month['label']}" if prior_month else "",
            detail=_month_detail(latest, prior_month, "revenue", latest_partial, hi),
            hint=f"{latest_label} revenue ex GST against the month before it in this window",
            tone="teal",
            spark=spark(spark_window, "revenue"),
        ),
        compare(
            "sales",
            "Sales",
            inr(totals["sales_billed"]),
            totals["sales_billed"],
            prev=previous["sales_billed"] if previous else None,
            yoy_value=yoy["sales_billed"] if yoy else None,
            full_value=full["sales_billed"] if full else None,
            hint=f"{qty(totals['sales_count'])} sales invoices, before credit and debit notes",
            tone="blue",
            spark=spark(docs_window, "sales"),
        ),
        compare(
            "credit_notes",
            "Credit notes",
            inr(totals["cn_billed"]),
            abs(totals["cn_billed"]),
            prev=abs(previous["cn_billed"]) if previous else None,
            yoy_value=abs(yoy["cn_billed"]) if yoy else None,
            full_value=abs(full["cn_billed"]) if full else None,
            higher_is_better=False,
            sign=-1,
            hint=f"{qty(totals['cn_count'])} notes. They reduce billed value",
            tone="rose",
            spark=spark(docs_window, "credit_notes"),
        ),
        share_kpi(
            "cn_rate",
            "Credit note rate",
            f"{_pct(abs(totals['cn_billed']), totals['sales_billed']):.1f}%",
            _pct(abs(totals["cn_billed"]), totals["sales_billed"]),
            {
                "previous": ratio(previous, "cn_billed", "sales_billed"),
                "yoy": ratio(yoy, "cn_billed", "sales_billed"),
                "full": ratio(full, "cn_billed", "sales_billed"),
            },
            higher_is_better=False,
            hint="Credit notes as a share of sales invoiced",
            tone="rose",
        ),
        compare(
            "debit_notes",
            "Debit notes",
            inr(totals["dn_billed"]),
            totals["dn_billed"],
            prev=previous["dn_billed"] if previous else None,
            yoy_value=yoy["dn_billed"] if yoy else None,
            full_value=full["dn_billed"] if full else None,
            hint=f"{qty(totals['dn_count'])} notes",
            tone="amber",
        ),
        _kpi(
            "debtors",
            "Debtors",
            inr(debtors["balance"]),
            hint=(
                f"{qty(debtors['count'])} Sundry Debtor ledgers at the last warehouse load. "
                "Tally shows debit balances as negative. Not aged receivables"
            ),
            tone="slate",
            scope="snapshot",
        ),
        share_kpi(
            "top_share",
            "Top client",
            f"{_pct(float(top_clients[0]['revenue']) if top_clients else 0, totals['revenue']):.0f}%",
            _pct(float(top_clients[0]["revenue"]) if top_clients else 0, totals["revenue"]),
            top_shares,
            higher_is_better=False,
            hint=(
                f"{_short_label(top_clients[0]['code'])} of revenue in this window"
                if top_clients
                else "Share of revenue from the largest client"
            ),
            tone="amber",
        ),
        _kpi(
            "gst_payable",
            "GST payable",
            inr(position["gst_payable"]),
            hint="Duties & Taxes closing on the books (CGST + SGST + IGST)",
            tone="violet",
            scope="snapshot",
        ),
        _kpi(
            "loans",
            "Loans",
            inr(position["loans"]),
            hint=(
                f"{qty(position['loan_ledgers'])} loan ledgers under Loans (Liability) / OD / secured / unsecured"
                if position["loan_ledgers"]
                else "No loan ledgers in Tally: the groups exist, but no accounts or balances yet"
            ),
            tone="rose",
            scope="snapshot",
        ),
        _kpi(
            "creditors",
            "Creditors",
            inr(position["creditors"]),
            hint=(
                f"{qty(position['creditor_ledgers'])} creditor ledgers"
                if position["creditor_ledgers"]
                else "Sundry Creditors group is empty: no supplier accounts in the books"
            ),
            tone="amber",
            scope="snapshot",
        ),
        _kpi(
            "statutory",
            "Statutory",
            inr(position["statutory"]),
            hint="EPF / ESIC / provisions closing, Tally snapshot",
            tone="amber",
            scope="snapshot",
        ),
        _kpi(
            "cash",
            "Cash & bank",
            inr(position["cash"]),
            hint="Cash-in-Hand and Bank Accounts closing. Tally shows debit balances as negative",
            tone="teal",
            scope="snapshot",
        ),
        _kpi(
            "profit_loss",
            "P&L",
            inr(position["profit_loss"]),
            hint="Tally Profit & Loss A/c snapshot, not Orion margin",
            tone="emerald",
            scope="snapshot",
        ),
        _kpi(
            "companies",
            "Companies billed",
            qty(totals["companies"]),
            hint="Tally companies with sales documents in this window",
            tone="slate",
        ),
        _kpi("cgst", "CGST", inr(totals["cgst"]), hint="Central GST on billed documents", tone="violet"),
        _kpi("sgst", "SGST", inr(totals["sgst"]), hint="State GST on billed documents", tone="violet"),
        compare(
            "manpower",
            "Manpower",
            inr(totals["manpower"]),
            totals["manpower"],
            hint=_share_hint(totals["manpower"], totals["revenue"]),
            tone="teal",
            spark=spark(income_window, "manpower"),
        ),
        compare(
            "vehicle",
            "Vehicle rent",
            inr(totals["vehicle"]),
            totals["vehicle"],
            hint=_share_hint(totals["vehicle"], totals["revenue"]),
            tone="blue",
            spark=spark(income_window, "vehicle"),
        ),
        compare(
            "service",
            "SG service",
            inr(totals["service"]),
            totals["service"],
            hint=_share_hint(totals["service"], totals["revenue"]),
            tone="amber",
            spark=spark(income_window, "service"),
        ),
        _kpi(
            "epf",
            "EPF billed",
            inr(totals["epf"]),
            hint=_share_hint(totals["epf"], totals["revenue"]),
            tone="slate",
        ),
        _kpi(
            "esic",
            "ESIC billed",
            inr(totals["esic"]),
            hint=_share_hint(totals["esic"], totals["revenue"]),
            tone="slate",
        ),
        compare(
            "other_income",
            "Other income",
            inr(totals["other_income"]),
            totals["other_income"],
            hint=_share_hint(totals["other_income"], totals["revenue"]),
            tone="slate",
        ),
    ]

    income_mix = income["groups"]
    voucher_cats = [
        {"code": row["code"], "label": row["label"], "value": round(float(row["billed"]), 2)}
        for row in voucher_mix
        if abs(float(row["billed"])) > 0.005
    ]
    client_cats = [
        {"code": row["code"], "label": row["label"], "value": round(float(row["revenue"]), 2)}
        for row in top_clients
    ]
    company_cats = [
        {"code": row["code"], "label": _short_label(row["label"], 36), "value": round(float(row["revenue"]), 2)}
        for row in companies
    ]
    fy_cats = [
        {"code": row["code"], "label": row["label"], "value": round(float(row["revenue"]), 2)}
        for row in fys
    ]
    cost_cats = [
        {"code": row["code"], "label": _short_label(row["label"], 22), "value": round(float(row["revenue"]), 2)}
        for row in cost_centres
    ]
    income_ledger_cats = [
        {"code": row["code"], "label": _short_label(row["ledger"], 28), "value": round(float(row["revenue"]), 2)}
        for row in income_rows[:12]
    ]
    debtor_cats = [
        {"code": row["code"], "label": row["label"], "value": round(abs(float(row["closing"])), 2)}
        for row in debtor_rows[:12]
        if abs(float(row["closing"])) > 0.005
    ]

    months = [point["code"] for point in monthly]
    start, end = filters.get("from"), filters.get("to")
    if start or end:
        range_label = f"{day_label(start) if start else '…'} – {day_label(end) if end else '…'}"
    elif months:
        range_label = f"{month_label(months[0])} – {month_label(months[-1])}"
    else:
        range_label = ""

    snapshot = _snapshot_line(totals, latest_label, latest_billed, debtors, position)

    return {
        "view": "tally",
        "filters": filters,
        "active_filters": chips,
        "kpis": kpis,
        "insights": insights,
        "series": {"trend": monthly_ctx, "income": income_trend, "documents": doc_trend},
        "categories": {
            "income_mix": income_mix,
            "income_ledgers": income_ledger_cats,
            "voucher_mix": voucher_cats,
            "top_clients": client_cats,
            "by_company": company_cats,
            "by_fy": fy_cats,
            "by_cost_centre": cost_cats,
            "position_balances": position["balances"],
            "debtors": debtor_cats,
            "notes_by_client": note_clients,
        },
        "tables": {
            "notes": {
                "filter_key": "client",
                "columns": [
                    {"key": "date", "label": "Date", "format": "text", "align": "left"},
                    {"key": "voucher", "label": "Voucher", "format": "text", "align": "left"},
                    {"key": "type", "label": "Type", "format": "text", "align": "left"},
                    {"key": "client", "label": "Client", "format": "text", "align": "left"},
                    {"key": "billed", "label": "Amount", "format": "money", "align": "right"},
                    {"key": "revenue", "label": "Ex GST", "format": "money", "align": "right"},
                    {"key": "gst", "label": "GST", "format": "money", "align": "right"},
                    {"key": "narration", "label": "Narration", "format": "text", "align": "left"},
                ],
                "rows": note_rows,
                "truncated": len(note_rows) >= NOTE_LIMIT,
                "totals": None
                if len(note_rows) >= NOTE_LIMIT
                else {
                    "billed": round(sum(r["billed"] for r in note_rows), 2),
                    "revenue": round(sum(r["revenue"] for r in note_rows), 2),
                    "gst": round(sum(r["gst"] for r in note_rows), 2),
                },
            },
            "clients": {
                "filter_key": "client",
                "columns": [
                    {"key": "client", "label": "Client", "format": "text", "align": "left"},
                    {"key": "invoices", "label": "Docs", "format": "number", "align": "right"},
                    {"key": "billed", "label": "Billed", "format": "money", "align": "right"},
                    {"key": "revenue", "label": "Revenue", "format": "money", "align": "right"},
                    {"key": "gst", "label": "GST", "format": "money", "align": "right"},
                    {"key": "share", "label": "Share", "format": "percent", "align": "right"},
                ],
                "rows": client_rows,
                "truncated": len(client_rows) >= CLIENT_LIMIT,
                "totals": {
                    "invoices": totals["invoices"],
                    "billed": totals["billed"],
                    "revenue": totals["revenue"],
                    "gst": totals["gst"],
                    "share": 100.0 if totals["revenue"] else 0.0,
                },
            },
            "income_ledgers": {
                "filter_key": "income_line",
                "columns": [
                    {"key": "ledger", "label": "Income ledger", "format": "text", "align": "left"},
                    {"key": "group", "label": "Group", "format": "text", "align": "left"},
                    {"key": "revenue", "label": "Amount", "format": "money", "align": "right"},
                    {"key": "share", "label": "Share", "format": "percent", "align": "right"},
                ],
                "rows": income_rows,
                "truncated": False,
                "totals": {
                    "revenue": round(sum(r["revenue"] for r in income_rows), 2),
                    "share": 100.0 if income_rows else 0.0,
                },
            },
            "debtors": {
                "filter_key": "client",
                "columns": [
                    {"key": "client", "label": "Debtor", "format": "text", "align": "left"},
                    {"key": "closing", "label": "Closing", "format": "money", "align": "right"},
                    {"key": "revenue", "label": "Billed rev.", "format": "money", "align": "right"},
                    {"key": "invoices", "label": "Docs", "format": "number", "align": "right"},
                ],
                "rows": debtor_rows,
                "truncated": len(debtor_rows) >= CLIENT_LIMIT,
                "totals": {"closing": debtors["balance"], "invoices": totals["invoices"], "revenue": totals["revenue"]}
                if not filters.get("client")
                else None,
            },
            "position": {
                "filter_key": "bucket",
                "columns": [
                    {"key": "ledger", "label": "Ledger", "format": "text", "align": "left"},
                    {"key": "closing", "label": "Closing", "format": "money", "align": "right"},
                    {"key": "group", "label": "Group", "format": "text", "align": "left"},
                    {"key": "bucket", "label": "Bucket", "format": "text", "align": "left"},
                ],
                "rows": position["rows"],
                "truncated": False,
                "totals": None,
            },
        },
        "meta": {
            "months": len(months),
            "range": range_label,
            "from": start,
            "to": end,
            "bounds": bounds,
            "snapshot": snapshot,
            "filter_options": options,
            "invalid_filters": invalid,
            "data_through": _data_through(bounds),
            "comparison": {
                "previous": prev_label or "",
                "yoy": yoy_label or "",
                "full": full_label or "",
                "kind": window[2] if window else "all",
            },
            "empty": not totals["invoices"],
        },
    }


def _warehouse_ready(cur) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'tally_dw' AND table_name = 'fact_voucher'
        """
    )
    return cur.fetchone() is not None


def _clean_filters(raw: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in FILTER_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out[key] = text
    return out


def _sales_where(filters: dict[str, str], alias: str = "v") -> tuple[str, list[Any]]:
    parts = [f"{alias}.is_current = TRUE", f"COALESCE({alias}.is_sales_document, FALSE) = TRUE"]
    params: list[Any] = []
    if filters.get("client"):
        parts.append(f"{alias}.party_ledger_name = %s")
        params.append(filters["client"])
    if filters.get("company"):
        parts.append(f"{alias}.company_name = %s")
        params.append(filters["company"])
    if filters.get("voucher_type"):
        parts.append(f"{alias}.voucher_type_name = %s")
        params.append(filters["voucher_type"])
    if filters.get("month"):
        parts.append(f"to_char(date_trunc('month', {alias}.voucher_date), 'YYYY-MM') = %s")
        params.append(filters["month"])
    if filters.get("fy"):
        try:
            fy_year = int(str(filters["fy"]).strip()[:4])
        except ValueError:
            fy_year = None
        if fy_year is not None:
            parts.append(
                f"""
                CASE WHEN EXTRACT(MONTH FROM {alias}.voucher_date) >= 4
                     THEN EXTRACT(YEAR FROM {alias}.voucher_date)
                     ELSE EXTRACT(YEAR FROM {alias}.voucher_date) - 1
                END = %s
                """
            )
            params.append(fy_year)
    if filters.get("from"):
        parts.append(f"{alias}.voucher_date >= %s::date")
        params.append(filters["from"])
    if filters.get("to"):
        parts.append(f"{alias}.voucher_date <= %s::date")
        params.append(filters["to"])
    if filters.get("cost_centre"):
        parts.append(
            f"""EXISTS (
                SELECT 1 FROM tally_dw.fact_cost_centre_allocation cc
                WHERE cc.is_current = TRUE
                  AND cc.source_voucher_sk = {alias}.source_voucher_sk
                  AND cc.cost_centre_name = %s
            )"""
        )
        params.append(filters["cost_centre"])
    if filters.get("income_line"):
        match_sql, match_params = _income_match_sql("lin", filters["income_line"])
        parts.append(
            f"""EXISTS (
                SELECT 1 FROM tally_dw.fact_ledger_line lin
                WHERE lin.is_current = TRUE
                  AND lin.line_role = 'income'
                  AND lin.source_voucher_sk = {alias}.source_voucher_sk
                  AND ({match_sql})
            )"""
        )
        params.extend(match_params)
    return " WHERE " + " AND ".join(parts), params


def _voucher_kind_sql(alias: str = "v") -> str:
    return f"""
        CASE
          WHEN {alias}.voucher_type_name ILIKE '%%credit note%%' THEN 'Credit note'
          WHEN {alias}.voucher_type_name ILIKE '%%debit note%%' THEN 'Debit note'
          ELSE 'Sales'
        END
    """


def _empty_measures() -> dict[str, float]:
    return {name: 0.0 for name in _MEASURES} | {
        "billed": 0.0,
        "revenue": 0.0,
        "invoices": 0.0,
        "clients": 0.0,
        "companies": 0.0,
        "sales_billed": 0.0,
        "sales_count": 0.0,
        "cn_billed": 0.0,
        "cn_count": 0.0,
        "dn_billed": 0.0,
        "dn_count": 0.0,
        "zero_docs": 0.0,
        "manpower": 0.0,
        "vehicle": 0.0,
        "service": 0.0,
        "epf": 0.0,
        "esic": 0.0,
        "other_income": 0.0,
    }


def _aggregates(cur, filters: dict[str, str] | None) -> dict[str, float]:
    if filters is None:
        return _empty_measures()
    where, params = _sales_where(filters)
    kind = _voucher_kind_sql("v")
    measure_sql = ",\n          ".join(f"COALESCE(SUM(v.{name}), 0)" for name in _MEASURES)
    cur.execute(
        f"""
        SELECT
          {measure_sql},
          COUNT(*)::float,
          COUNT(DISTINCT v.party_ledger_name)::float,
          COUNT(DISTINCT v.company_name)::float,
          COALESCE(SUM(CASE WHEN {kind} = 'Sales' THEN v.invoice_value_incl_gst ELSE 0 END), 0),
          COALESCE(SUM(CASE WHEN {kind} = 'Sales' THEN 1 ELSE 0 END), 0)::float,
          COALESCE(SUM(CASE WHEN {kind} = 'Credit note' THEN v.invoice_value_incl_gst ELSE 0 END), 0),
          COALESCE(SUM(CASE WHEN {kind} = 'Credit note' THEN 1 ELSE 0 END), 0)::float,
          COALESCE(SUM(CASE WHEN {kind} = 'Debit note' THEN v.invoice_value_incl_gst ELSE 0 END), 0),
          COALESCE(SUM(CASE WHEN {kind} = 'Debit note' THEN 1 ELSE 0 END), 0)::float,
          COALESCE(SUM(CASE WHEN COALESCE(v.invoice_value_incl_gst, 0) = 0 THEN 1 ELSE 0 END), 0)::float
        FROM tally_dw.fact_voucher v
        {where}
        """,
        params,
    )
    row = cur.fetchone() or ()
    values = [float(v or 0) for v in row]
    out = _empty_measures()
    for i, name in enumerate(_MEASURES):
        out[name] = values[i] if i < len(values) else 0.0
    offset = len(_MEASURES)
    out["billed"] = out["invoice_value_incl_gst"]
    out["revenue"] = out["revenue_ex_gst"]
    if len(values) > offset:
        out["invoices"] = values[offset]
        out["clients"] = values[offset + 1]
        out["companies"] = values[offset + 2]
        out["sales_billed"] = values[offset + 3]
        out["sales_count"] = values[offset + 4]
        out["cn_billed"] = values[offset + 5]
        out["cn_count"] = values[offset + 6]
        out["dn_billed"] = values[offset + 7]
        out["dn_count"] = values[offset + 8]
        out["zero_docs"] = values[offset + 9]
    return out


def _monthly(cur, filters: dict[str, str]) -> list[dict[str, Any]]:
    where, params = _sales_where(filters)
    cur.execute(
        f"""
        SELECT
          to_char(date_trunc('month', v.voucher_date), 'YYYY-MM') AS month_year,
          COALESCE(SUM(v.invoice_value_incl_gst), 0),
          COALESCE(SUM(v.revenue_ex_gst), 0),
          COALESCE(SUM(v.gst), 0),
          COUNT(*)::float
        FROM tally_dw.fact_voucher v
        {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )
    return [
        {
            "code": month,
            "label": month_label(month),
            "billed": float(billed or 0),
            "revenue": float(revenue or 0),
            "gst": float(gst or 0),
            "invoices": float(invoices or 0),
        }
        for month, billed, revenue, gst, invoices in cur.fetchall()
        if month
    ]


def _top_clients(cur, filters: dict[str, str], limit: int = 12) -> list[dict[str, Any]]:
    where, params = _sales_where(filters)
    cur.execute(
        f"""
        SELECT
          COALESCE(v.party_ledger_name, 'Unknown'),
          COALESCE(SUM(v.revenue_ex_gst), 0),
          COALESCE(SUM(v.invoice_value_incl_gst), 0)
        FROM tally_dw.fact_voucher v
        {where}
        GROUP BY 1
        ORDER BY 2 DESC NULLS LAST
        LIMIT %s
        """,
        [*params, limit],
    )
    return [
        {
            "code": name,
            "label": _short_label(name, 28),
            "revenue": float(revenue or 0),
            "billed": float(billed or 0),
        }
        for name, revenue, billed in cur.fetchall()
    ]


def _voucher_mix(cur, filters: dict[str, str]) -> list[dict[str, Any]]:
    where, params = _sales_where(filters)
    cur.execute(
        f"""
        SELECT
          COALESCE(v.voucher_type_name, 'Unknown'),
          COALESCE(SUM(v.invoice_value_incl_gst), 0),
          COUNT(*)::float
        FROM tally_dw.fact_voucher v
        {where}
        GROUP BY 1
        ORDER BY 2 DESC NULLS LAST
        """,
        params,
    )
    return [
        {"code": name, "label": name, "billed": float(billed or 0), "count": float(count or 0)}
        for name, billed, count in cur.fetchall()
    ]


def _by_company(cur, filters: dict[str, str]) -> list[dict[str, Any]]:
    scoped = {k: v for k, v in filters.items() if k != "company"}
    where, params = _sales_where(scoped)
    cur.execute(
        f"""
        SELECT
          COALESCE(v.company_name, 'Unknown'),
          COALESCE(SUM(v.revenue_ex_gst), 0)
        FROM tally_dw.fact_voucher v
        {where}
        GROUP BY 1
        ORDER BY 2 DESC NULLS LAST
        """,
        params,
    )
    return [
        {"code": name, "label": name, "revenue": float(revenue or 0)}
        for name, revenue in cur.fetchall()
    ]


def _fy_label(year: int) -> str:
    return f"FY {year}-{str(year + 1)[2:]}"


def _by_fy(cur, filters: dict[str, str]) -> list[dict[str, Any]]:
    scoped = {k: v for k, v in filters.items() if k != "fy"}
    where, params = _sales_where(scoped)
    cur.execute(
        f"""
        SELECT
          CASE WHEN EXTRACT(MONTH FROM v.voucher_date) >= 4
               THEN EXTRACT(YEAR FROM v.voucher_date)
               ELSE EXTRACT(YEAR FROM v.voucher_date) - 1
          END::int AS fy,
          COALESCE(SUM(v.revenue_ex_gst), 0)
        FROM tally_dw.fact_voucher v
        {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )
    return [
        {"code": str(year), "label": _fy_label(int(year)), "revenue": float(revenue or 0)}
        for year, revenue in cur.fetchall()
        if year is not None
    ]


def _document_trend(cur, filters: dict[str, str]) -> list[dict[str, Any]]:
    """Sales vs credit/debit notes per month. Ignores the type filter so both sides stay visible."""
    scoped = {key: value for key, value in filters.items() if key != "voucher_type"}
    where, params = _sales_where(scoped)
    kind = _voucher_kind_sql("v")
    cur.execute(
        f"""
        SELECT
          to_char(date_trunc('month', v.voucher_date), 'YYYY-MM'),
          COALESCE(SUM(CASE WHEN {kind} = 'Sales' THEN v.invoice_value_incl_gst END), 0),
          COALESCE(SUM(CASE WHEN {kind} = 'Credit note' THEN v.invoice_value_incl_gst END), 0),
          COALESCE(SUM(CASE WHEN {kind} = 'Debit note' THEN v.invoice_value_incl_gst END), 0),
          COALESCE(SUM(v.invoice_value_incl_gst), 0),
          COALESCE(SUM(CASE WHEN {kind} = 'Credit note' THEN 1 ELSE 0 END), 0)::float,
          COALESCE(SUM(CASE WHEN {kind} = 'Sales' THEN 1 ELSE 0 END), 0)::float
        FROM tally_dw.fact_voucher v
        {where}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )
    return [
        {
            "code": month,
            "label": month_label(month),
            "sales": float(sales or 0),
            "sales_count": float(sales_count or 0),
            # Credit notes are stored negative; shown as a positive amount so bars compare with sales.
            "credit_notes": abs(float(credit or 0)),
            "debit_notes": float(debit or 0),
            "net": float(net or 0),
            "notes": float(notes or 0),
        }
        for month, sales, credit, debit, net, notes, sales_count in cur.fetchall()
        if month
    ]


def _note_documents(cur, filters: dict[str, str], limit: int = NOTE_LIMIT) -> list[dict[str, Any]]:
    """Every credit and debit note in the selection, newest first."""
    where, params = _sales_where(filters)
    kind = _voucher_kind_sql("v")
    cur.execute(
        f"""
        SELECT
          v.voucher_date,
          COALESCE(v.voucher_number, ''),
          {kind},
          COALESCE(v.party_ledger_name, 'Unknown'),
          COALESCE(v.company_name, ''),
          COALESCE(v.invoice_value_incl_gst, 0),
          COALESCE(v.revenue_ex_gst, 0),
          COALESCE(v.gst, 0),
          COALESCE(NULLIF(BTRIM(v.reference), ''), ''),
          COALESCE(NULLIF(BTRIM(v.narration), ''), '')
        FROM tally_dw.fact_voucher v
        {where}
          AND {kind} <> 'Sales'
        ORDER BY v.voucher_date DESC, v.voucher_number DESC
        LIMIT %s
        """,
        [*params, limit],
    )
    return [
        {
            "code": client,
            "date": day.isoformat() if day else "",
            "voucher": number,
            "type": doc_type,
            "client": _short_label(client, 32),
            "company": _short_label(company, 24),
            "billed": float(billed or 0),
            "revenue": float(revenue or 0),
            "gst": float(gst or 0),
            "reference": reference,
            "narration": _short_label(narration, 60),
        }
        for day, number, doc_type, client, company, billed, revenue, gst, reference, narration in cur.fetchall()
    ]


def _notes_by_client(cur, filters: dict[str, str], limit: int = 12) -> list[dict[str, Any]]:
    where, params = _sales_where(filters)
    kind = _voucher_kind_sql("v")
    cur.execute(
        f"""
        SELECT COALESCE(v.party_ledger_name, 'Unknown'), COALESCE(SUM(ABS(v.invoice_value_incl_gst)), 0)
        FROM tally_dw.fact_voucher v
        {where}
          AND {kind} = 'Credit note'
        GROUP BY 1
        ORDER BY 2 DESC NULLS LAST
        LIMIT %s
        """,
        [*params, limit],
    )
    return [
        {"code": name, "label": _short_label(name, 28), "value": round(float(amount or 0), 2)}
        for name, amount in cur.fetchall()
        if abs(float(amount or 0)) > 0.005
    ]


def _client_month_rows(cur, filters: dict[str, str], limit: int = 200) -> list[dict[str, Any]]:
    where, params = _sales_where(filters)
    cur.execute(
        f"""
        SELECT
          COALESCE(v.party_ledger_name, 'Unknown'),
          COUNT(*)::float,
          COALESCE(SUM(v.invoice_value_incl_gst), 0),
          COALESCE(SUM(v.revenue_ex_gst), 0),
          COALESCE(SUM(v.gst), 0)
        FROM tally_dw.fact_voucher v
        {where}
        GROUP BY 1
        ORDER BY 4 DESC NULLS LAST
        LIMIT %s
        """,
        [*params, limit],
    )
    rows = cur.fetchall()
    total_revenue = sum(float(r[3] or 0) for r in rows) or 1.0
    return [
        {
            "code": name,
            "client": _short_label(name, 36),
            "invoices": float(invoices or 0),
            "billed": float(billed or 0),
            "revenue": float(revenue or 0),
            "gst": float(gst or 0),
            "share": round(float(revenue or 0) / total_revenue * 100, 1),
        }
        for name, invoices, billed, revenue, gst in rows
    ]


LOAN_PARENTS = (
    "Loans (Liability)",
    "Bank OD A/c",
    "Secured Loans",
    "Unsecured Loans",
)


def _position_bucket(parent: str, name: str) -> str:
    parent = parent or ""
    if parent == "Duties & Taxes":
        return "GST payable"
    if parent in LOAN_PARENTS:
        return "Loans"
    if parent == "Sundry Creditors":
        return "Sundry creditors"
    if parent in ("Current Liabilities", "Provisions"):
        return "Statutory / other liabilities"
    if parent in ("Cash-in-Hand", "Bank Accounts"):
        return "Cash and bank"
    if parent == "Sundry Debtors":
        return "Sundry debtors"
    if name == "Profit & Loss A/c" or parent in ("Capital Account", "Reserves & Surplus"):
        return "Capital / P&L"
    if parent in (
        "Fixed Assets",
        "Current Assets",
        "Loans & Advances (Asset)",
        "Deposits (Asset)",
        "Investments",
        "Stock-in-Hand",
        "Misc. Expenses (ASSET)",
    ):
        return "Assets"
    return "Other"


def _books_position(cur, filters: dict[str, str]) -> dict[str, Any]:
    """Tally ledger closing snapshot. Not filtered by billed month — it is the books today."""
    parts = ["c.is_current = TRUE"]
    params: list[Any] = []
    if filters.get("company"):
        parts.append("c.company_name = %s")
        params.append(filters["company"])
    cur.execute(
        f"""
        SELECT COALESCE(c.parent_name, ''), c.name, COALESCE(c.closing_balance, 0)
        FROM tally_dw.dim_ledger c
        WHERE {' AND '.join(parts)}
        ORDER BY c.parent_name, c.name
        """,
        params,
    )
    rows_raw = cur.fetchall()
    gst_payable = loans = creditors = statutory = cash = profit_loss = 0.0
    loan_ledgers = creditor_ledgers = 0
    group_sums: dict[str, float] = {}
    table_rows: list[dict[str, Any]] = []
    for parent, name, closing in rows_raw:
        amount = float(closing or 0)
        bucket = _position_bucket(parent, name)
        if bucket == "GST payable":
            gst_payable += amount
        elif bucket == "Loans":
            loans += amount
            loan_ledgers += 1
        elif bucket == "Sundry creditors":
            creditors += amount
            creditor_ledgers += 1
        elif bucket == "Statutory / other liabilities":
            statutory += amount
        elif bucket == "Cash and bank":
            cash += amount
        elif bucket == "Capital / P&L":
            profit_loss += amount
        if bucket in (
            "GST payable",
            "Loans",
            "Sundry creditors",
            "Statutory / other liabilities",
            "Cash and bank",
            "Sundry debtors",
            "Capital / P&L",
            "Assets",
        ):
            group_sums[bucket] = group_sums.get(bucket, 0.0) + amount
        if bucket in (
            "GST payable",
            "Loans",
            "Sundry creditors",
            "Statutory / other liabilities",
            "Cash and bank",
            "Sundry debtors",
            "Capital / P&L",
            "Assets",
        ):
            table_rows.append(
                {
                    "code": bucket,
                    "bucket": bucket,
                    "group": parent or "—",
                    "ledger": _short_label(name, 36),
                    "closing": amount,
                }
            )
    if filters.get("bucket"):
        table_rows = [row for row in table_rows if row["code"] == filters["bucket"]]
    # Signed, as Tally stores them. Buckets are different kinds of balance, so they are
    # compared side by side and never summed into one total.
    balances = [
        {"code": label, "label": label, "value": round(value, 2)}
        for label, value in group_sums.items()
        if abs(value) > 0.005
    ]
    balances.sort(key=lambda row: abs(row["value"]), reverse=True)
    return {
        "gst_payable": gst_payable,
        "loans": loans,
        "creditors": creditors,
        "statutory": statutory,
        "cash": cash,
        "profit_loss": profit_loss,
        "loan_ledgers": loan_ledgers,
        "creditor_ledgers": creditor_ledgers,
        "balances": balances,
        "rows": table_rows,
    }


def _debtor_snapshot(cur, filters: dict[str, str]) -> dict[str, float]:
    parts = ["c.is_current = TRUE", "c.ledger_class = 'client'"]
    params: list[Any] = []
    if filters.get("client"):
        parts.append("c.name = %s")
        params.append(filters["client"])
    if filters.get("company"):
        parts.append("c.company_name = %s")
        params.append(filters["company"])
    cur.execute(
        f"""
        SELECT COALESCE(SUM(c.closing_balance), 0), COUNT(*)::float
        FROM tally_dw.dim_ledger c
        WHERE {' AND '.join(parts)}
        """,
        params,
    )
    balance, count = cur.fetchone() or (0, 0)
    return {"balance": float(balance or 0), "count": float(count or 0)}


def _data_span(cur) -> dict[str, str]:
    cur.execute(
        """
        SELECT MIN(voucher_date), MAX(voucher_date)
        FROM tally_dw.fact_voucher
        WHERE is_current = TRUE AND COALESCE(is_sales_document, FALSE) = TRUE
        """
    )
    start, end = cur.fetchone() or (None, None)
    return {
        "min": start.isoformat() if start else "",
        "max": end.isoformat() if end else date.today().isoformat(),
    }


def _data_through(bounds: dict[str, str]) -> str:
    """The date of the latest billed document, or "" when there are none.

    With no sales documents ``_data_span`` still returns today as its upper bound, so the date pickers have a range to
    show; that is not a document's date and must not be reported as one.
    """
    return bounds["max"] if bounds["min"] else ""


_UNSET: Any = object()


def _range_text(start: date | None, end: date | None) -> str:
    if not start or not end:
        return ""
    if start == end:
        return day_label(start.isoformat())
    return f"{day_label(start.isoformat())} – {day_label(end.isoformat())}"


def _filters_range(filters: dict[str, str]) -> str:
    return _range_text(parse_day(filters.get("from")), parse_day(filters.get("to")))


def _month_detail(latest, prior, key: str, partial: bool, hi) -> dict[str, Any] | None:
    """Comparison detail for the single-month figures: latest month against the one before."""
    if not latest:
        return None
    detail: dict[str, Any] = {
        "current_range": latest["label"] + (f", billed to {day_label(hi.isoformat())}" if partial and hi else ""),
    }
    if prior:
        detail.update(
            compare=f"vs {prior['label']}",
            current_value=inr(float(latest[key])),
            previous_value=inr(float(prior[key])),
            previous_range=prior["label"],
        )
    else:
        detail["note"] = (
            "This selection covers a single month, so there is no earlier month inside it. "
            "The Billed figure compares that month with the one before."
        )
    return detail


def _kpi(
    key: str,
    label: str,
    value: str,
    *,
    current: float | None = None,
    previous: float | None = None,
    yoy: float | None = None,
    compare: str = "",
    yoy_label: str = "",
    higher_is_better: bool = True,
    spark: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    scope: str = "period",
    change: str = "",
    change_type: str = "neutral",
    hint: str = "",
    tone: str = "blue",
) -> dict[str, Any]:
    """The shared KPI plus what the redesigned card needs.

    ``delta_pct`` and ``yoy_pct`` are numbers so the card can draw its own arrow;
    ``scope`` says whether the figure follows the period filters or is a books snapshot.
    A rise is only shown as good when ``higher_is_better``.
    """
    out = kpi(key, label, value, change=change, change_type=change_type, hint=hint, tone=tone)
    pct = None
    if current is not None and previous:
        pct = round((current - previous) / abs(previous) * 100, 1)
        out["delta"], out["delta_type"] = delta(current, previous)
        if not higher_is_better and out["delta_type"] != "neutral":
            out["delta_type"] = "negative" if out["delta_type"] == "positive" else "positive"
    yoy_pct = None
    if current is not None and yoy:
        yoy_pct = round((current - yoy) / abs(yoy) * 100, 1)
    out.update(
        {
            "delta_pct": pct,
            "compare": compare if (pct is not None or change) else "",
            "yoy_pct": yoy_pct,
            "yoy_label": yoy_label if yoy_pct is not None else "",
            "higher_is_better": higher_is_better,
            "spark": spark["values"] if spark else [],
            "spark_labels": spark["labels"] if spark else [],
            "spark_kind": spark["kind"] if spark else "money",
            "scope": scope,
            "about": {
                **KPI_HELP.get(key, {"means": hint, "calc": ""}),
                "scope": SCOPE_SNAPSHOT if scope == "snapshot" else SCOPE_PERIOD,
            },
            "detail": detail,
        }
    )
    return out


def _client_revenue(cur, filters: dict[str, str]) -> dict[str, float]:
    where, params = _sales_where(filters)
    cur.execute(
        f"""
        SELECT COALESCE(v.party_ledger_name, 'Unknown'), COALESCE(SUM(v.revenue_ex_gst), 0)
        FROM tally_dw.fact_voucher v
        {where}
        GROUP BY 1
        """,
        params,
    )
    return {name: float(revenue or 0) for name, revenue in cur.fetchall()}


def _movers(cur, filters, windows, previous, prev_label, monthly_ctx):
    """Which clients drove the change: window vs its previous window, else the last two months."""
    if filters.get("client"):
        return [], [], "", None
    if previous is not None and windows["previous"]:
        now = _client_revenue(cur, filters)
        before = _client_revenue(cur, windows["previous"]["filters"])
        gainers, losers = top_movers(now, before)
        return gainers, losers, prev_label or "", None
    if len(monthly_ctx) >= 2:
        context = {key: value for key, value in filters.items() if key != "month"}
        last, prior = monthly_ctx[-1]["code"], monthly_ctx[-2]["code"]
        now = _client_revenue(cur, {**context, "month": last})
        before = _client_revenue(cur, {**context, "month": prior})
        gainers, losers = top_movers(now, before)
        return gainers, losers, f"{monthly_ctx[-1]['label']} vs {monthly_ctx[-2]['label']}", (last, prior)
    return [], [], "", None


def _mom_from_series(points: list[dict[str, Any]], key: str) -> tuple[str, str]:
    if len(points) < 2:
        return "", "neutral"
    return delta(float(points[-1][key]), float(points[-2][key]))


def _pct(part: float, whole: float) -> float:
    if not whole:
        return 0.0
    return part / whole * 100


def _share_hint(part: float, whole: float) -> str:
    if not whole:
        return "Share of revenue ex GST"
    return f"{_pct(part, whole):.1f}% of revenue ex GST"


def _chips(filters: dict[str, str]) -> list[dict[str, str]]:
    labels = {
        "month": "Month",
        "client": "Client",
        "company": "Company",
        "voucher_type": "Type",
        "fy": "FY",
        "cost_centre": "Cost centre",
        "income_line": "Income",
        "bucket": "Books",
        "from": "From",
        "to": "To",
    }
    chips = []
    for key, value in filters.items():
        if key in ("from", "to"):
            continue
        display = value
        if key == "month":
            display = month_label(value)
        elif key == "fy":
            try:
                display = _fy_label(int(value))
            except ValueError:
                display = value
        elif key == "income_line":
            display = dict(INCOME_LINES).get(value, _short_label(value, 28))
        elif key in ("client", "company", "cost_centre"):
            display = _short_label(value, 28)
        chips.append({"key": key, "label": labels.get(key, key), "value": value, "display": display})
    return chips


def _snapshot_line(
    totals: dict[str, float],
    latest_label: str,
    latest_billed: float,
    debtors: dict[str, float],
    position: dict[str, Any],
) -> str:
    if not totals["invoices"]:
        return "No billed sales documents in the Tally warehouse for this selection."
    loan_bit = (
        f"Loans on the books {inr(position['loans'])}."
        if position["loan_ledgers"]
        else "No loan accounts in Tally yet."
    )
    return (
        f"{inr(totals['billed'])} billed · {inr(totals['revenue'])} revenue · "
        f"{qty(totals['invoices'])} docs · {qty(totals['clients'])} clients · "
        f"{latest_label} {inr(latest_billed)} · debtors {inr(debtors['balance'])} · "
        f"GST payable {inr(position['gst_payable'])}. {loan_bit}"
    )


def _short_label(name: str, limit: int = 28) -> str:
    text = " ".join((name or "").split())
    swaps = (
        (r"BHARAT SANCHAR NIGAM LIMITED", "BSNL"),
        (r"CHIEF MEDICAL AND HEALTH OFFICER", "CMHO"),
        (r"DISTRICT HEALTH SOCIETY", "DHS"),
        (r"EMPLOYEES INSURANCE HOSPITAL", "ESIC Hosp."),
        (r"THE SUPRITENDENT", "Supt."),
        (r"SUPERINTENDENT", "Supt."),
        (r"SUPERITENDENT", "Supt."),
        (r"SUPERINTANDENT", "Supt."),
        (r"HOSPITAL", "Hosp."),
        (r"\(\s*M\.?\s*P\.?\s*\)", ""),
        (r"DISTT\.", "Dist."),
        (r"CUM CHIEF HOSPITAL SUPERITENDENT", ""),
        (r"CUM HOSPITAL", ""),
        (r"RANI DURGAWATI \(ELGIN\)", "Elgin"),
    )
    for pattern, repl in swaps:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    text = " ".join(text.split()).strip(" ,-")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _income_group(name: str) -> tuple[str, str]:
    lowered = (name or "").lower()
    for code, label, patterns in INCOME_GROUPS:
        if code == "other_income":
            continue
        if any(pattern.strip("%") in lowered for pattern in patterns):
            return code, label
    return "other_income", "Other income"


def _income_match_sql(alias: str, value: str) -> tuple[str, list[str]]:
    patterns = next((item[2] for item in INCOME_GROUPS if item[0] == value), None)
    if value == "other_income":
        others = [pattern for item in INCOME_GROUPS if item[0] != "other_income" for pattern in item[2]]
        if not others:
            return "TRUE", []
        sql = " AND ".join(f"{alias}.ledger_name NOT ILIKE %s" for _ in others)
        return sql, others
    if patterns:
        sql = " OR ".join(f"{alias}.ledger_name ILIKE %s" for _ in patterns)
        return sql, list(patterns)
    return f"{alias}.ledger_name = %s", [value]


def _income_from_lines(cur, filters: dict[str, str]) -> dict[str, Any]:
    scoped = {key: value for key, value in filters.items() if key != "income_line"}
    where, params = _sales_where(scoped)
    cur.execute(
        f"""
        SELECT COALESCE(l.ledger_name, 'Unknown'), COALESCE(SUM(l.amount), 0)
        FROM tally_dw.fact_ledger_line l
        JOIN tally_dw.fact_voucher v
          ON v.source_voucher_sk = l.source_voucher_sk AND v.is_current = TRUE
        {where}
          AND l.is_current = TRUE
          AND l.line_role = 'income'
        GROUP BY 1
        ORDER BY 2 DESC NULLS LAST
        """,
        params,
    )
    fetched = cur.fetchall()
    totals = {code: 0.0 for code, _label in INCOME_LINES}
    rows: list[dict[str, Any]] = []
    for name, amount in fetched:
        value = float(amount or 0)
        code, label = _income_group(name)
        totals[code] = totals.get(code, 0.0) + value
        rows.append({"code": name, "ledger": _short_label(name, 36), "group": label, "revenue": value})
    total_revenue = sum(row["revenue"] for row in rows) or 1.0
    for row in rows:
        row["share"] = round(row["revenue"] / total_revenue * 100, 1)
    groups = [
        {"code": code, "label": label, "value": round(totals[code], 2)}
        for code, label in INCOME_LINES
        if abs(totals[code]) > 0.005
    ]
    return {"totals": totals, "rows": rows, "groups": groups}


def _monthly_income(cur, filters: dict[str, str]) -> list[dict[str, Any]]:
    scoped = {key: value for key, value in filters.items() if key != "income_line"}
    where, params = _sales_where(scoped)
    cur.execute(
        f"""
        SELECT
          to_char(date_trunc('month', v.voucher_date), 'YYYY-MM'),
          COALESCE(l.ledger_name, 'Unknown'),
          COALESCE(SUM(l.amount), 0)
        FROM tally_dw.fact_ledger_line l
        JOIN tally_dw.fact_voucher v
          ON v.source_voucher_sk = l.source_voucher_sk AND v.is_current = TRUE
        {where}
          AND l.is_current = TRUE
          AND l.line_role = 'income'
        GROUP BY 1, 2
        ORDER BY 1
        """,
        params,
    )
    by_month: dict[str, dict[str, Any]] = {}
    for month, name, amount in cur.fetchall():
        if not month:
            continue
        point = by_month.setdefault(
            month,
            {
                "code": month,
                "label": month_label(month),
                **{code: 0.0 for code, _label in INCOME_LINES},
            },
        )
        code, _label = _income_group(name)
        point[code] = float(point.get(code, 0)) + float(amount or 0)
    return list(by_month.values())


def _by_cost_centre(cur, filters: dict[str, str]) -> list[dict[str, Any]]:
    scoped = {key: value for key, value in filters.items() if key != "cost_centre"}
    where, params = _sales_where(scoped)
    cur.execute(
        f"""
        SELECT COALESCE(cc.cost_centre_name, 'Unknown'), COALESCE(SUM(v.revenue_ex_gst), 0)
        FROM tally_dw.fact_voucher v
        JOIN tally_dw.fact_cost_centre_allocation cc
          ON cc.source_voucher_sk = v.source_voucher_sk AND cc.is_current = TRUE
        {where}
        GROUP BY 1
        ORDER BY 2 DESC NULLS LAST
        """,
        params,
    )
    return [
        {"code": name, "label": name, "revenue": float(revenue or 0)}
        for name, revenue in cur.fetchall()
        if name
    ]


def _debtor_rows(cur, filters: dict[str, str], limit: int = 200) -> list[dict[str, Any]]:
    billed: dict[str, tuple[float, float]] = {}
    where, params = _sales_where(filters)
    cur.execute(
        f"""
        SELECT COALESCE(v.party_ledger_name, 'Unknown'), COUNT(*)::float, COALESCE(SUM(v.revenue_ex_gst), 0)
        FROM tally_dw.fact_voucher v
        {where}
        GROUP BY 1
        """,
        params,
    )
    for name, invoices, revenue in cur.fetchall():
        billed[name] = (float(invoices or 0), float(revenue or 0))
    parts = ["c.is_current = TRUE", "c.ledger_class = 'client'"]
    snap_params: list[Any] = []
    if filters.get("company"):
        parts.append("c.company_name = %s")
        snap_params.append(filters["company"])
    if filters.get("client"):
        parts.append("c.name = %s")
        snap_params.append(filters["client"])
    cur.execute(
        f"""
        SELECT c.name, COALESCE(c.closing_balance, 0)
        FROM tally_dw.dim_ledger c
        WHERE {' AND '.join(parts)}
        ORDER BY ABS(COALESCE(c.closing_balance, 0)) DESC
        LIMIT %s
        """,
        [*snap_params, limit],
    )
    rows = []
    for name, closing in cur.fetchall():
        invoices, revenue = billed.get(name, (0.0, 0.0))
        rows.append(
            {
                "code": name,
                "label": _short_label(name, 28),
                "client": _short_label(name, 36),
                "closing": float(closing or 0),
                "revenue": revenue,
                "invoices": invoices,
            }
        )
    return rows


def _filter_options(cur) -> dict[str, list[dict[str, str]]]:
    cur.execute(
        """
        SELECT DISTINCT party_ledger_name
        FROM tally_dw.fact_voucher
        WHERE is_current = TRUE AND COALESCE(is_sales_document, FALSE) = TRUE
          AND party_ledger_name IS NOT NULL
        ORDER BY 1
        """
    )
    clients = [{"id": name, "label": _short_label(name, 40)} for (name,) in cur.fetchall()]
    cur.execute(
        """
        SELECT DISTINCT company_name
        FROM tally_dw.fact_voucher
        WHERE is_current = TRUE AND COALESCE(is_sales_document, FALSE) = TRUE
          AND company_name IS NOT NULL
        ORDER BY 1
        """
    )
    companies = [{"id": name, "label": _short_label(name, 40)} for (name,) in cur.fetchall()]
    cur.execute(
        """
        SELECT DISTINCT
          CASE WHEN EXTRACT(MONTH FROM voucher_date) >= 4
               THEN EXTRACT(YEAR FROM voucher_date)
               ELSE EXTRACT(YEAR FROM voucher_date) - 1
          END::int
        FROM tally_dw.fact_voucher
        WHERE is_current = TRUE AND COALESCE(is_sales_document, FALSE) = TRUE
        ORDER BY 1 DESC
        """
    )
    fys = [{"id": str(year), "label": _fy_label(int(year))} for (year,) in cur.fetchall() if year]
    cur.execute(
        """
        SELECT DISTINCT voucher_type_name
        FROM tally_dw.fact_voucher
        WHERE is_current = TRUE AND COALESCE(is_sales_document, FALSE) = TRUE
          AND voucher_type_name IS NOT NULL
        ORDER BY 1
        """
    )
    voucher_types = [{"id": name, "label": name} for (name,) in cur.fetchall()]
    cur.execute(
        """
        SELECT DISTINCT cc.cost_centre_name
        FROM tally_dw.fact_cost_centre_allocation cc
        WHERE cc.is_current = TRUE AND cc.cost_centre_name IS NOT NULL
        ORDER BY 1
        """
    )
    cost_centres = [{"id": name, "label": name} for (name,) in cur.fetchall()]
    income_lines = [{"id": code, "label": label} for code, label in INCOME_LINES]
    cur.execute(
        """
        SELECT DISTINCT l.ledger_name
        FROM tally_dw.fact_ledger_line l
        WHERE l.is_current = TRUE AND l.line_role = 'income' AND l.ledger_name IS NOT NULL
        ORDER BY 1
        """
    )
    for (name,) in cur.fetchall():
        income_lines.append({"id": name, "label": _short_label(name, 36)})
    return {
        "clients": clients,
        "companies": companies,
        "fys": fys,
        "voucher_types": voucher_types,
        "cost_centres": cost_centres,
        "income_lines": income_lines,
    }


def _empty_payload(
    filters: dict[str, str], message: str, invalid: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    return {
        "view": "tally",
        "filters": filters,
        "active_filters": _chips(filters),
        "kpis": [
            kpi("billed", "Billed incl. GST", inr(0), hint=message, tone="blue"),
            kpi("revenue", "Revenue ex GST", inr(0), hint=message, tone="teal"),
        ],
        "series": {"trend": [], "income": []},
        "categories": {
            "income_mix": [],
            "income_ledgers": [],
            "voucher_mix": [],
            "top_clients": [],
            "by_company": [],
            "by_fy": [],
            "by_cost_centre": [],
            "position_balances": [],
            "debtors": [],
        },
        "tables": {
            "clients": {"filter_key": "client", "columns": [], "rows": []},
            "income_ledgers": {"filter_key": "income_line", "columns": [], "rows": []},
            "debtors": {"filter_key": "client", "columns": [], "rows": []},
            "position": {"filter_key": "bucket", "columns": [], "rows": []},
        },
        "meta": {
            "months": 0,
            "range": "",
            "from": filters.get("from"),
            "to": filters.get("to"),
            "bounds": {"min": "", "max": date.today().isoformat()},
            "snapshot": message,
            "invalid_filters": invalid or [],
            "data_through": "",
            "comparison": {"previous": "", "yoy": "", "full": "", "kind": "all"},
            "empty": True,
            "filter_options": {
                "clients": [],
                "companies": [],
                "fys": [],
                "voucher_types": [],
                "cost_centres": [],
                "income_lines": [],
            },
        },
    }
