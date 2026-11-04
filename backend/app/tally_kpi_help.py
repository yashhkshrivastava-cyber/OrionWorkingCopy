"""Plain-language help for every Tally dashboard figure.

``means`` says what the number is in business terms; ``calc`` says exactly how it is
worked out, including the caveats that change how it should be read. Keep these in step
with the queries in ``tally_dashboard`` when a definition changes.
"""

from __future__ import annotations

KPI_HELP: dict[str, dict[str, str]] = {
    "billed": {
        "means": "The total value of everything invoiced, including GST, after credit notes.",
        "calc": "Sum of the invoice value of every sales, debit-note and credit-note voucher in the selection. "
        "Credit notes are negative, so they reduce it.",
    },
    "revenue": {
        "means": "What was earned from billing, before GST.",
        "calc": "Sum of the taxable value (invoice value minus GST) of the same vouchers as Billed. "
        "Credit notes reduce it.",
    },
    "gst": {
        "means": "The GST charged on the billed documents.",
        "calc": "CGST plus SGST posted on those vouchers. Credit notes reduce it.",
    },
    "gst_pct": {
        "means": "How much of the billed value is GST.",
        "calc": "GST divided by Billed (which includes GST), as a percentage.",
    },
    "invoices": {
        "means": "How many billing documents were issued.",
        "calc": "Count of sales, credit-note and debit-note vouchers. This includes vouchers with no amount "
        "(often cancelled or blank invoices); the 'What stands out' strip says how many there are.",
    },
    "clients": {
        "means": "How many different clients were billed.",
        "calc": "Number of distinct client ledgers on those vouchers.",
    },
    "avg_invoice": {
        "means": "The typical size of a billing document.",
        "calc": "Billed divided by the number of documents. Credit notes lower it and vouchers with no amount "
        "are counted, so it reads lower than the average sales invoice. The Billing tab charts the sales-only average.",
    },
    "avg_revenue": {
        "means": "The typical revenue per billing document, before GST.",
        "calc": "Revenue divided by the number of documents, with the same caveats as Avg invoice.",
    },
    "latest_month": {
        "means": "What was billed in the most recent month in this selection.",
        "calc": "Billed for that single month. The change compares it with the month before it in the selection. "
        "If the month is only partly billed, the figure is partial.",
    },
    "mom_revenue": {
        "means": "Revenue (before GST) in the most recent month in this selection.",
        "calc": "Revenue for that single month, compared with the month before it. A partly billed month reads low.",
    },
    "sales": {
        "means": "What was invoiced before any credit or debit notes.",
        "calc": "Invoice value including GST of sales vouchers only.",
    },
    "credit_notes": {
        "means": "Value given back to clients through credit notes.",
        "calc": "Invoice value of credit-note vouchers, shown negative. An increase is treated as unfavourable.",
    },
    "cn_rate": {
        "means": "How much of what was invoiced came back as credit notes.",
        "calc": "Credit notes divided by Sales, as a percentage.",
    },
    "debit_notes": {
        "means": "Extra value charged to clients through debit notes.",
        "calc": "Invoice value of debit-note vouchers.",
    },
    "debtors": {
        "means": "What clients owed at the last warehouse load.",
        "calc": "Sum of the closing balance of every Sundry Debtor ledger. Tally stores debit balances as negative, "
        "so money owed to you shows with a minus sign. This is not an ageing of unpaid invoices.",
    },
    "top_share": {
        "means": "How much of the revenue comes from the single biggest client.",
        "calc": "Revenue from the largest client divided by total revenue, in the selected period.",
    },
    "gst_payable": {
        "means": "GST owed to the government according to the books.",
        "calc": "Closing balance of the Duties & Taxes ledgers (CGST, SGST, IGST) at the last warehouse load.",
    },
    "loans": {
        "means": "Borrowings on the books.",
        "calc": "Closing balance of ledgers under Loans (Liability), Bank OD, Secured and Unsecured Loans.",
    },
    "creditors": {
        "means": "What is owed to suppliers.",
        "calc": "Closing balance of Sundry Creditor ledgers at the last warehouse load.",
    },
    "statutory": {
        "means": "Provident fund, ESIC and similar statutory liabilities.",
        "calc": "Closing balance of the statutory and provision ledgers at the last warehouse load.",
    },
    "cash": {
        "means": "Cash and bank balances on the books.",
        "calc": "Closing balance of Cash-in-Hand and Bank Account ledgers. Tally stores debit balances as negative, "
        "so a bank balance in credit to you can show with a minus sign.",
    },
    "profit_loss": {
        "means": "The Profit & Loss account balance in Tally.",
        "calc": "Closing balance of the Profit & Loss A/c ledger. This is Tally's figure, not a margin calculated here.",
    },
    "companies": {
        "means": "How many Tally companies issued the billed documents.",
        "calc": "Number of distinct companies on those vouchers.",
    },
    "cgst": {"means": "Central GST on the billed documents.", "calc": "Sum of CGST posted on those vouchers."},
    "sgst": {"means": "State GST on the billed documents.", "calc": "Sum of SGST posted on those vouchers."},
    "manpower": {
        "means": "Revenue from manpower supply.",
        "calc": "Income-ledger postings whose ledger name mentions manpower or security. Grouping is by ledger name, "
        "so a renamed ledger would land in Other income.",
    },
    "vehicle": {
        "means": "Revenue from vehicle rent.",
        "calc": "Income-ledger postings whose name mentions vehicle or rent. Grouped by ledger name.",
    },
    "service": {
        "means": "Revenue from service charges.",
        "calc": "Income-ledger postings whose name mentions SG service or service charge. Grouped by ledger name.",
    },
    "epf": {
        "means": "Provident fund amounts billed to clients.",
        "calc": "Income-ledger postings whose name mentions EPF.",
    },
    "esic": {
        "means": "ESIC amounts billed to clients.",
        "calc": "Income-ledger postings whose name mentions ESIC.",
    },
    "other_income": {
        "means": "Revenue that does not fit the other income lines.",
        "calc": "Income-ledger postings whose name matches none of the other lines.",
    },
}

SCOPE_PERIOD = "Follows the period and segment filters."
SCOPE_SNAPSHOT = "A balance at the last warehouse load. The period and billing filters do not change it."
