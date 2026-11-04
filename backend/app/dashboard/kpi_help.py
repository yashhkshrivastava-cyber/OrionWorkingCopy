"""Plain-language help for every Orion dashboard figure.

``means`` says what the number is in business terms; ``calc`` says exactly how it is worked out, including the
caveats that change how it should be read. Keep these in step with the queries in ``engine`` when a definition
changes. A figure without an entry here shows its one-line hint only, and a test fails if one is missing.
"""

from __future__ import annotations

KPI_HELP: dict[str, dict[str, str]] = {
    "revenue": {
        "means": "What was earned from billing for the service months in view, before GST.",
        "calc": "Sum of the taxable value of every issued bill (staff cost recovered, EPF and ESIC billed, and service "
        "charge), less what approved credit notes took off it. Cancelled bills are left out. A bill belongs to the month the service was for, "
        "not the day it was raised.",
    },
    "billed": {
        "means": "The total of the invoices raised, including GST.",
        "calc": "Sum of the grand total of issued bills for the service months in view, less what approved credit notes took off them.",
    },
    "gst": {
        "means": "GST charged on the bills, after credit notes.",
        "calc": "CGST plus SGST on issued bills for the service months in view, less the GST on their approved credit notes.",
    },
    "credit_notes": {
        "means": "How much credit notes and write-offs took off the bills in view.",
        "calc": "Sum of what approved credit notes (not reversed) credited against issued bills for the service months in view, GST included. The bill "
        "keeps its own figures; revenue, billed, GST and what is owed already have this taken off. The date of a note matters on the GST page, "
        "not here: a note counts in the month of its bill's service.",
    },
    "itc": {
        "means": "GST paid to suppliers that can be set against the GST owed on bills.",
        "calc": "GST on costs that have happened (Incurred, not planned or cancelled) in the period and carry both the supplier's GSTIN and invoice "
        "number. GST on a cost without them is not counted: add the details to the expense to claim it. Planning only: reverse charge and blocked "
        "credits are not modelled, and the return is filed on the GST portal.",
    },
    "net_gst": {
        "means": "GST on the bills less the input tax credit: roughly what is left to pay.",
        "calc": "GST on bills (after credit notes) minus input tax credit for the period. Below zero is a credit to carry forward, not a refund. "
        "Utility > GST shows it month by month with the credit notes dated in each month.",
    },
    "bills": {
        "means": "How many tax invoices were raised.",
        "calc": "Count of issued bills for the service months in view. An edited bill is still one bill.",
    },
    "avg_bill": {
        "means": "The typical size of an invoice.",
        "calc": "Billed (including GST) divided by the number of bills.",
    },
    "clients": {
        "means": "How many different clients were billed.",
        "calc": "Distinct clients on the issued bills in view, as they were when each bill was raised.",
    },
    "cases_billed": {
        "means": "How many sites or contracts were billed.",
        "calc": "Distinct cases on the issued bills in view.",
    },
    "collected": {
        "means": "Cash that reached the bank from clients in the period.",
        "calc": "Sum of the payments recorded against bills (committed revenue entries), dated the day each payment "
        "was received, less what the client held back (TDS and the like), which never reached the bank. It can include money for bills raised "
        "earlier, so it can exceed what was billed in the same months.",
    },
    "tds_held": {
        "means": "What clients deducted from their payments (TDS, a penalty, rounding) in the period.",
        "calc": "Sum of the deductions recorded with the payments (not reversed), dated the day each payment was received. It settles the bill but is "
        "not in the bank; the TDS part is claimed through Form 26AS (Utility > TDS).",
    },
    "collection_rate": {
        "means": "How much of what was billed was settled in the same period.",
        "calc": "Cash collected plus what clients held back (TDS and the like), divided by billed (including GST, after credit notes) for the period. "
        "Above 100% means older bills were being cleared; well below it means bills are building up unpaid. Read it over a quarter or longer.",
    },
    "payroll": {
        "means": "What was paid or owed to staff for the months in view.",
        "calc": "Sum of salary on payroll lines for those months, whether or not it has been paid yet. EPFO and ESIC are a separate cost "
        "(counted in running costs when they are paid over) and do not depend on payroll.",
    },
    "expenses": {
        "means": "Running costs other than salary.",
        "calc": "Sum of expense entries before GST, plus EPFO and ESIC paid over (recorded on the bills), plus penalties and short "
        "payments clients held back. Cancelled entries are left out; prospective entries (planned, not yet booked) are included.",
    },
    "cost": {
        "means": "Everything spent to deliver the work.",
        "calc": "Payroll plus operating expenses (before GST).",
    },
    "margin": {
        "means": "Operating profit: what is left of revenue after payroll and running costs, before interest, depreciation and tax.",
        "calc": "Revenue minus all payroll (head-office staff included) minus expenses (which include EPFO and ESIC paid over, and penalties and short payments held back by clients), on the dimensions all three have in common (period, client, case, "
        "domain, capability, state, client type, priority). The margin shown for a single case or domain is its contribution margin: before "
        "head-office cost, so it is higher; the \"Head office and unallocated\" row carries the rest. The profit and loss at the top of "
        "Profitability shows the same figure as Operating profit. Income tax and depreciation are not in the data.",
    },
    "margin_pct": {
        "means": "How much of each rupee of revenue is left after delivery cost.",
        "calc": "Margin divided by revenue. The change is shown in percentage points.",
    },
    "payroll_pct": {
        "means": "How much of revenue goes on salaries.",
        "calc": "Payroll divided by revenue. A rise is unfavourable.",
    },
    "expense_pct": {
        "means": "How much of revenue goes on running costs.",
        "calc": "Operating expenses divided by revenue. A rise is unfavourable.",
    },
    "heads": {
        "means": "How many people were on payroll in a typical month.",
        "calc": "Payroll lines divided by the number of months in view (one line per employee per month).",
    },
    "rev_per_head": {
        "means": "Revenue earned for each person on payroll, per month.",
        "calc": "Revenue divided by payroll lines (employee-months) in view.",
    },
    "days_worked": {
        "means": "How many days a month people are paid for.",
        "calc": "Average days worked across payroll lines in view.",
    },
    "salary_pending": {
        "means": "Salary on payroll but not yet marked paid.",
        "calc": "Sum of salary on payroll lines in view whose salary-paid flag is No.",
    },
    "km": {
        "means": "Distance driven by the fleet.",
        "calc": "Sum of driven kilometres on the car logs in view.",
    },
    "fleet_cost": {
        "means": "What the driving cost.",
        "calc": "Driven kilometres multiplied by the per-km price of the car at the time (the price on the car's "
        "record when the log was entered).",
    },
    "cost_per_km": {
        "means": "Average cost of one kilometre.",
        "calc": "Fleet cost divided by kilometres driven.",
    },
    "opps": {
        "means": "How many tenders and opportunities were opened.",
        "calc": "Opportunities whose start date falls in the period.",
    },
    "won": {
        "means": "Opportunities won.",
        "calc": "Opportunities in Closed Won among those started in the period.",
    },
    "win_rate": {
        "means": "How often a decided opportunity was won.",
        "calc": "Won divided by (won + lost + disqualified), among opportunities started in the period. Open ones are "
        "not counted either way.",
    },
    "outstanding": {
        "means": "Money clients still owe on issued bills.",
        "calc": "Grand total of issued bills less the payments recorded against them, as at the last warehouse load. "
        "Follows the client, case and segment filters but not the period.",
    },
    "overdue_90": {
        "means": "Money owed for more than 90 days.",
        "calc": "Outstanding on bills dated more than 90 days ago. Counted from the bill date, not from a due date.",
    },
    "overdue_pct": {
        "means": "How much of what is owed is old.",
        "calc": "Outstanding on bills over 90 days old divided by total outstanding.",
    },
    "dso": {
        "means": "How many days of billing are tied up in unpaid bills.",
        "calc": "Outstanding divided by what was billed in the last 90 days, multiplied by 90. Lower is better.",
    },
    "days_to_collect": {
        "means": "How long clients take to pay.",
        "calc": "Average days from bill date to the last payment, over fully paid bills in the period.",
    },
    "open_bills": {
        "means": "How many invoices are waiting to be paid.",
        "calc": "Issued bills with an unpaid balance of at least ₹1.",
    },
    "active_cases": {
        "means": "How many sites or contracts are running.",
        "calc": "Cases whose status is Active now.",
    },
    "run_rate": {
        "means": "What the running contracts should bill in a month.",
        "calc": "Sum of the expected monthly revenue (including GST) on active cases.",
    },
    "headcount": {
        "means": "People currently employed.",
        "calc": "Employees whose status is Active now.",
    },
    "unbilled_cases": {
        "means": "Active cases that were billed last month but not yet this month.",
        "calc": "Active cases with a bill for the month before the latest service month and none for the latest one.",
    },
    "cancelled_bills": {
        "means": "Invoices that were raised and then cancelled.",
        "calc": "Count of bills with status Cancelled in the period. Their numbers stay on record.",
    },
    "edited_bills": {
        "means": "Invoices changed after they were issued.",
        "calc": "Issued bills in the period that are on version 2 or later.",
    },
    "gst_unpaid": {
        "means": "GST charged on bills that has not been marked as paid to the government.",
        "calc": "CGST plus SGST on issued bills in the period (after credit notes) whose GST-paid flag is off.",
    },
    "epf_unpaid": {
        "means": "EPFO charged to clients on bills that has not been marked as paid over to the authority.",
        "calc": "EPFO on issued bills in the period less the EPFO payments recorded against them. Credit notes do not lower it. EPFO charged stays inside Revenue; once paid over it is a cost, on the day paid, and lowers the margin.",
    },
    "esic_unpaid": {
        "means": "ESIC charged to clients on bills that has not been marked as paid over to the authority.",
        "calc": "ESIC on issued bills in the period less the ESIC payments recorded against them. Credit notes do not lower it. ESIC charged stays inside Revenue; once paid over it is a cost, on the day paid, and lowers the margin.",
    },
    "open_pipeline": {
        "means": "Opportunities still being worked.",
        "calc": "Opportunities in Proposal, Qualified, Technical Bid or Financial Bid among those started in the period.",
    },
    "pipeline_staff": {
        "means": "Staff the open opportunities would need.",
        "calc": "Sum of the workers required on open opportunities.",
    },
    "cycle_days": {
        "means": "How long a tender takes to be decided.",
        "calc": "Average days from the start date to the close date, over won, lost and disqualified opportunities "
        "started in the period.",
    },
    "emd_held": {
        "means": "Earnest money the firm has deposited with clients and tender authorities and not yet got back.",
        "calc": "Sum of the amount of every EMD that is Deposited or Refund requested, as at today. Refunded, adjusted, forfeited and cancelled deposits "
        "are not counted. The period does not narrow it.",
    },
    "emd_overdue": {
        "means": "Earnest money that should already have come back.",
        "calc": "Sum of the amount of EMDs still Deposited or Refund requested whose refund due date is before today. An EMD with no refund due date "
        "is never counted here, so fill the date in when it is known.",
    },
    "emd_lost": {
        "means": "Earnest money that will not be returned in full.",
        "calc": "The whole amount of every forfeited EMD, plus the deduction taken from every other EMD (cancelled ones left out).",
    },
    "clients_no_contact": {
        "means": "Active clients where nobody is on record to call.",
        "calc": "Clients whose status is Active and who have no contact with the status Active. Add a contact under Clients & work > Contact.",
    },
    "contact_follow_ups": {
        "means": "People at clients who were due a call or visit and have not had one recorded.",
        "calc": "Active contacts whose next follow-up date is today or earlier. Updating the last-contacted and next follow-up dates clears it.",
    },
    "cars_active": {
        "means": "How many cars were on the road.",
        "calc": "Distinct cars with at least one log in the period.",
    },
    "km_per_day": {
        "means": "How far the fleet drives on a day it is used.",
        "calc": "Kilometres driven divided by the number of distinct days with a log, across all cars.",
    },
    "attrition": {
        "means": "How quickly people are leaving.",
        "calc": "Leavers in the period divided by average headcount, expressed over a year.",
    },
    "bank_balance": {
        "means": "What the firm's bank account holds today, according to Orion's bank book.",
        "calc": "The opening balance entered on the Bank page, plus every movement since the opening date: clients' payments, less expenses, "
        "less GST paid, plus or minus the entries made on the Bank page. It is worked out, not read from the bank; the Bank page's "
        "Reconcile tab checks it against an uploaded statement.",
    },
    "bank_in": {
        "means": "Money that reached the bank in the period.",
        "calc": "Clients' payments (on the day received), interest, other income, loans and every other receipt in the bank book for the months in view.",
    },
    "bank_out": {
        "means": "Money that left the bank in the period.",
        "calc": "Expenses, GST paid, bank charges, tax, loan repayments and every other payment in the bank book for the months in view.",
    },
    "bank_net": {
        "means": "Whether the bank gained or lost money in the period.",
        "calc": "Money in less money out, over the months in view.",
    },
    "bank_other_income": {
        "means": "Earnings on top of clients' payments: interest the bank paid and any other income.",
        "calc": "Entries recorded as Interest earned or Other income on the Bank page, over the months in view. Loans, refunds and the owner's capital are not income and are left out.",
    },
    "bank_unreconciled": {
        "means": "How many items the book and the bank statement do not yet agree on.",
        "calc": "Movements in the bank book that no statement line has been matched to, plus statement lines that nothing in the book has been matched to.",
    },
    "bank_next30": {
        "means": "The net money Orion expects to move in the next 30 days.",
        "calc": "Bills clients still have to pay and costs still to come, on the day they are expected, less GST still to pay (estimated for the 20th of the month after each bill). "
        "Only what is already entered; money overdue is not counted.",
    },
}

SCOPE_PERIOD = "Follows the period and segment filters."
SCOPE_SNAPSHOT = "As at the last warehouse load. The period filters do not change it; the segment filters do."
