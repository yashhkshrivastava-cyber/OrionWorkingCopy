"""Entity registry — metadata-driven CRUD definitions."""

import logging
import re
from decimal import Decimal
from pathlib import Path

from app import employee_ids, gstin
from app.database import db_cursor
from app.payload import PayloadError

logger = logging.getLogger(__name__)


def _not_negative(label: str):
    """A field rule: the value is a number that is not below zero (kilometres, readings, a price per kilometre)."""

    def rule(value):
        number = float(value)
        if number < 0:
            raise PayloadError(f"{label} cannot be negative.")
        return value

    return rule

def _positive(label: str):
    """A field rule: the value is a number above zero (an amount that must be something)."""

    def rule(value):
        if float(value) <= 0:
            raise PayloadError(f"{label} must be more than zero.")
        return value

    return rule


def _supplier_gstin(value):
    """A field rule: the supplier's GSTIN, tidied (capitals, no spaces) and checked, including its check digit."""
    try:
        return gstin.clean(value)
    except gstin.GstinError as exc:
        raise PayloadError(str(exc)) from exc


def _email(value):
    """A field rule: a plain e-mail address (something@something.tld), tidied."""
    text = str(value).strip()
    if len(text) > 120 or not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", text):
        raise PayloadError("E-mail is not a valid address, for example name@company.com.")
    return text


def _phone(label: str):
    """A field rule: a phone number as people write it (digits, spaces, + - ( ) and a point), with between 7 and 15 digits."""

    def rule(value):
        text = " ".join(str(value).split())
        digits = re.sub(r"\D", "", text)
        if not re.fullmatch(r"[0-9 +()./-]+", text) or not 7 <= len(digits) <= 15:
            raise PayloadError(f"{label} is not a valid number: use 7 to 15 digits, with an optional + and spaces or hyphens.")
        return text

    return rule


BILL_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_bill.sql"
CASE_TRANSACTION_BILL_MIGRATE = (
    Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_case_transaction_bill.sql"
)
OPPORTUNITY_FIELDS_MIGRATE = (
    Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_opportunity_fields.sql"
)

AUDIT_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_audit.sql"
CAPABILITY_HEAD_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_capability_head.sql"
ETL_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_etl.sql"
BACKUP_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_backup.sql"
LETTERHEAD_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_letterhead.sql"
CLIENT_GROUP_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_client_group.sql"
EMPLOYEE_DOCUMENTS_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_employee_documents.sql"
DOCUMENTS_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_documents.sql"
AI_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_ai.sql"
CHAT_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_chat.sql"
DATA_RULES_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_data_rules.sql"
AUTH_SECURITY_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_auth_security.sql"
IDEMPOTENCY_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_idempotency.sql"
BILL_GST_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_bill_gst.sql"
BILL_STATUTORY_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_bill_statutory.sql"
PAYROLL_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_payroll.sql"
EXPENSE_PAYMENTS_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_expense_payments.sql"
CREDIT_NOTES_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_credit_notes.sql"
INPUT_TAX_CREDIT_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_input_tax_credit.sql"
DEDUCTIONS_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_deductions.sql"
BANK_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_bank.sql"
TENDERS_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_tenders.sql"
CONTACTS_EMD_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_contacts_emd.sql"
DOCUMENTS_FILING_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_documents_filing.sql"
FOLLOWUPS_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_followups.sql"
ATTENDANCE_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_attendance.sql"
GDRIVE_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_gdrive.sql"
TASKS_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_tasks.sql"
SQL_LAB_MIGRATE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "migrate_sql_lab.sql"

# The schema files the API applies, in this order (app/migrate.py applies and records them; a new file goes here, in both init
# scripts, and nowhere else needs to know). The other .cursor/db files are applied by the init scripts only, or by their own
# ensure_* function (the base schema, the warehouse schemas, grants, the legacy app_user and sign-up files).
SQL_MIGRATIONS = (
    BILL_MIGRATE, CASE_TRANSACTION_BILL_MIGRATE, OPPORTUNITY_FIELDS_MIGRATE, AUDIT_MIGRATE, CAPABILITY_HEAD_MIGRATE, ETL_MIGRATE,
    BACKUP_MIGRATE, LETTERHEAD_MIGRATE, CLIENT_GROUP_MIGRATE, EMPLOYEE_DOCUMENTS_MIGRATE, DOCUMENTS_MIGRATE, AI_MIGRATE,
    CHAT_MIGRATE, DATA_RULES_MIGRATE, AUTH_SECURITY_MIGRATE, IDEMPOTENCY_MIGRATE, BILL_GST_MIGRATE, BILL_STATUTORY_MIGRATE,
    EXPENSE_PAYMENTS_MIGRATE, INPUT_TAX_CREDIT_MIGRATE, CREDIT_NOTES_MIGRATE, PAYROLL_MIGRATE, DEDUCTIONS_MIGRATE, BANK_MIGRATE, TENDERS_MIGRATE, CONTACTS_EMD_MIGRATE,
    DOCUMENTS_FILING_MIGRATE, FOLLOWUPS_MIGRATE, ATTENDANCE_MIGRATE, GDRIVE_MIGRATE, SQL_LAB_MIGRATE, TASKS_MIGRATE,
)

CONTACT_ROLES = ["Decision maker", "Influencer", "Accounts / Billing", "Procurement / Tender", "Site in-charge", "Technical", "HR / Admin", "Escalation", "Other"]
CONTACT_STATUSES = ["Active", "Inactive", "Left organisation"]
CONTACT_METHODS = ["Phone", "Email", "WhatsApp", "In person"]
EMD_MODES = ["Online / NEFT / RTGS", "Demand draft", "Bank guarantee", "Fixed deposit (FDR)", "Cheque", "Cash", "Other"]
EMD_STATUSES = ["Deposited", "Refund requested", "Refunded", "Adjusted against security deposit", "Forfeited", "Cancelled"]
#: What an EMD still has with the authority: the money is out until it is refunded, adjusted or forfeited.
EMD_OPEN_STATUSES = ("Deposited", "Refund requested")

OPPORTUNITY_STATUSES = [
    "Proposal",
    "Financial Bid",
    "Technical Bid",
    "Closed Won",
    "Closed Lost",
    "Disqualified",
    "Qualified",
]

# Natural keys used by Excel upload (insert or update). Codes are generated on insert.
MERGE_KEYS = {
    "Business Domain": ["business_domain_name"],
    "Capability": ["capability_name"],
    "Expense Type": ["expense_type_name"],
    "Client": ["client_name"],
    "Case": ["case_name", "client_code"],
    "Opportunity": ["tender_id"],
    "Employee": ["employee_name"],
    "Employee Transaction": ["employee_code", "month_year"],
    "Car": ["car_number"],
    # A car can be driven more than once a day, and one case can buy the same kind of thing twice in a day. Those rows are
    # told apart by the reading and the amount, so an upload for a different one adds a row instead of replacing the first.
    # To correct an existing row, put its code in the file.
    "Car Transaction": ["car_code", "driving_date", "initial_reading"],
    "Transaction": ["case_code", "transaction_date", "transaction_amount"],
    "Expense Transaction": ["case_code", "transaction_date", "expense_type_code", "transaction_amount"],
    # The same person at the same client is one contact; an EMD is told apart by the case and its document number.
    "Contact": ["client_code", "contact_name"],
    "EMD": ["case_code", "instrument_number"],
}

# When a row leaves its merge key blank it has nothing to match on. These are matched on something else instead, so that
# uploading the same file twice does not add every such row twice.
MERGE_FALLBACK = {
    "Opportunity": ["opportunity_name"],
}


def merge_columns(name: str, entity: dict | None = None) -> list[str]:
    if entity and entity.get("merge_key"):
        return list(entity["merge_key"])
    return list(MERGE_KEYS.get(name, []))


def merge_fallback(name: str) -> list[str]:
    return list(MERGE_FALLBACK.get(name, []))

ENTITIES = {
    "Business Domain": {
        "table": "orion_ods.business_domain",
        "primary_key": "business_domain_code",
        "display_column": "business_domain_name",
        "form_fields": {
            "business_domain_name": {"label": "Business Domain Name", "type": "text", "required": True},
        },
    },
    "Capability": {
        "table": "orion_ods.capability",
        "primary_key": "capability_code",
        "display_column": "capability_name",
        "form_fields": {
            "capability_name": {"label": "Capability Name", "type": "text", "required": True},
            "capability_head_code": {
                "label": "Capability Head",
                "type": "select",
                "source_table": "orion_ods.employee",
                "source_display_column": "employee_name",
                "source_pk_column": "employee_code",
                "optional": True,
            },
        },
    },
    "Expense Type": {
        "table": "orion_ods.expense_type",
        "primary_key": "expense_type_code",
        "display_column": "expense_type_name",
        "form_fields": {
            "expense_type_name": {"label": "Expense Type Name", "type": "text", "required": True},
        },
    },
    "Client": {
        "table": "orion_ods.client",
        "primary_key": "client_code",
        "display_column": "client_name",
        "option_label": "CONCAT_WS(' — ', NULLIF(BTRIM(client_name), ''), NULLIF(BTRIM(client_status), ''))",
        "form_fields": {
            "client_name": {"label": "Client Name", "type": "text", "required": True},
            # The group a client belongs to is another client. The form shows "name — code" and stores the code.
            "client_group_code": {
                "label": "Client Group",
                "type": "select",
                "source_table": "orion_ods.client",
                "source_display_column": "CONCAT_WS(' — ', NULLIF(BTRIM(client_name), ''), client_code)",
                "source_pk_column": "client_code",
                "optional": True,
            },
            "client_status": {"label": "Status", "type": "select", "options": ["Active", "Inactive"]},
            "client_start_date": {"label": "Start Date", "type": "date"},
            "client_end_date": {"label": "End Date", "type": "date"},
            "client_location_state": {"label": "State", "type": "state"},
            "client_location_city": {
                "label": "City",
                "type": "dependent_select",
                "depends_on": "client_location_state",
            },
            "client_type": {"label": "Client Type", "type": "select", "options": ["Govt", "Private", "MSME"]},
            "firm_priority": {"label": "Priority", "type": "select", "options": ["P1", "P2", "P3"]},
            "client_onboarded": {"label": "Onboarded Date", "type": "date"},
            # Printed on this client's bills. Billing copies them onto each bill it raises.
            "billing_name": {"label": "Name on Bills", "type": "text", "optional": True},
            "gstin": {"label": "GSTIN", "type": "text", "optional": True},
            "billing_address": {"label": "Billing Address", "type": "text", "optional": True},
        },
    },
    "Case": {
        "table": "orion_ods.case",
        "primary_key": "case_code",
        "display_column": "case_name",
        "field_rules": {
            "monthly_allowed_km": _not_negative("Monthly Allowed KM"),
        },
        "option_from": """
            orion_ods.case t
            LEFT JOIN orion_ods.client c ON c.client_code = t.client_code
        """,
        "option_pk": "t.case_code",
        "option_label": "CONCAT_WS(' — ', NULLIF(BTRIM(t.case_name), ''), NULLIF(BTRIM(c.client_name), ''))",
        "form_fields": {
            "case_name": {"label": "Case Name", "type": "text", "required": True},
            "client_code": {
                "label": "Client",
                "type": "select",
                "source_table": "orion_ods.client",
                "source_display_column": "client_name",
                "source_pk_column": "client_code",
            },
            "opportunity_code": {
                "label": "Opportunity",
                "type": "select",
                "source_table": "orion_ods.opportunity",
                "source_display_column": "CONCAT_WS(' — ', NULLIF(BTRIM(tender_id), ''), NULLIF(BTRIM(opportunity_name), ''))",
                "source_pk_column": "opportunity_code",
                "optional": True,
            },
            "case_start_date": {"label": "Start Date", "type": "date"},
            "case_status": {"label": "Status", "type": "select", "options": ["Active", "Inactive"]},
            "case_end_date": {"label": "End Date", "type": "date"},
            "capability_code": {
                "label": "Capability",
                "type": "select",
                "source_table": "orion_ods.capability",
                "source_display_column": "capability_name",
                "source_pk_column": "capability_code",
            },
            "monthly_expected_revenue": {"label": "Monthly Expected Revenue", "type": "number", "money": True},
            "monthly_allowed_km": {"label": "Monthly Allowed KM", "type": "integer"},
            "business_domain_code": {
                "label": "Business Domain",
                "type": "select",
                "source_table": "orion_ods.business_domain",
                "source_display_column": "business_domain_name",
                "source_pk_column": "business_domain_code",
            },
            "case_onboarded": {"label": "Onboarded", "type": "boolean"},
        },
    },
    "Opportunity": {
        "table": "orion_ods.opportunity",
        "primary_key": "opportunity_code",
        "display_column": "opportunity_name",
        "option_from": """
            orion_ods.opportunity t
            LEFT JOIN orion_ods.case cs ON cs.case_code = t.opportunity_case_code
        """,
        "option_pk": "t.opportunity_code",
        "option_label": "CONCAT_WS(' — ', NULLIF(BTRIM(t.tender_id), ''), NULLIF(BTRIM(t.opportunity_name), ''), NULLIF(BTRIM(cs.case_name), ''), NULLIF(BTRIM(t.opportunity_status), ''))",
        "form_fields": {
            "opportunity_name": {"label": "Opportunity Name", "type": "text", "required": True},
            "tender_id": {"label": "Tender ID", "type": "text"},
            "opportunity_case_code": {
                "label": "Case",
                "type": "select",
                "source_table": "orion_ods.case",
                "source_display_column": "case_name",
                "source_pk_column": "case_code",
            },
            "opportunity_start_date": {"label": "Start Date", "type": "date"},
            "opportunity_end_date": {"label": "End Date", "type": "date"},
            "opportunity_status": {
                "label": "Status",
                "type": "select",
                "options": OPPORTUNITY_STATUSES,
            },
            "opportunity_type": {
                "label": "Opportunity Type",
                "type": "select_or_custom",
                "options": ["State", "National"],
                "custom_option": "Custom",
            },
            "required_quantity": {"label": "Required Quantity", "type": "number"},
            "workers": {"label": "Workers", "type": "number"},
            "state": {"label": "State", "type": "state"},
            "city": {
                "label": "City",
                "type": "dependent_select",
                "depends_on": "state",
            },
            "reason": {"label": "Reason", "type": "text"},
            "last_sub_stage_change_date": {
                "label": "Last Sub-stage Change Date",
                "type": "date",
                "readonly": True,
            },
        },
    },
    "Contact": {
        "table": "orion_ods.contact",
        "primary_key": "contact_code",
        "display_column": "contact_name",
        "field_rules": {"email": _email, "phone": _phone("Phone"), "alternate_phone": _phone("Alternate phone")},
        "option_from": """
            orion_ods.contact t
            LEFT JOIN orion_ods.client c ON c.client_code = t.client_code
        """,
        "option_pk": "t.contact_code",
        "option_label": "CONCAT_WS(' — ', NULLIF(BTRIM(t.contact_name), ''), NULLIF(BTRIM(c.client_name), ''), NULLIF(BTRIM(t.designation), ''))",
        "form_fields": {
            "client_code": {
                "label": "Client",
                "type": "select",
                "required": True,
                "source_table": "orion_ods.client",
                "source_display_column": "client_name",
                "source_pk_column": "client_code",
            },
            "case_code": {
                "label": "Case",
                "type": "select",
                "optional": True,
                "source_table": "orion_ods.case",
                "source_display_column": "case_name",
                "source_pk_column": "case_code",
                "hint": "Only if this person is the contact for one case (the site in-charge of it). Leave empty for a contact of the client as a whole.",
            },
            "contact_name": {"label": "Name", "type": "text", "required": True},
            "designation": {"label": "Designation", "type": "text", "optional": True},
            "department": {"label": "Department", "type": "text", "optional": True},
            "contact_role": {"label": "Role in the relationship", "type": "select", "options": CONTACT_ROLES, "optional": True},
            "contact_status": {"label": "Status", "type": "select", "options": CONTACT_STATUSES, "required": True},
            "is_primary_contact": {
                "label": "Primary contact",
                "type": "select",
                "options": ["Yes", "No"],
                "optional": True,
                "hint": "The person to call first. A primary contact must be Active.",
            },
            "contact_start_date": {"label": "Known since", "type": "date", "optional": True},
            "contact_end_date": {"label": "Until", "type": "date", "optional": True, "hint": "The day they left the client or the role, when they have."},
            "email": {"label": "E-mail", "type": "text", "optional": True},
            "phone": {"label": "Phone", "type": "text", "optional": True},
            "alternate_phone": {"label": "Alternate phone", "type": "text", "optional": True},
            "preferred_contact_method": {"label": "Prefers to be reached by", "type": "select", "options": CONTACT_METHODS, "optional": True},
            "location_state": {"label": "State", "type": "state", "optional": True},
            "location_city": {"label": "City", "type": "dependent_select", "depends_on": "location_state", "optional": True},
            "address": {"label": "Office address", "type": "text", "optional": True},
            "relationship_owner_code": {
                "label": "Looked after by",
                "type": "select",
                "optional": True,
                "source_table": "orion_ods.employee",
                "source_display_column": "employee_name",
                "source_pk_column": "employee_code",
                "hint": "The person here who keeps in touch with them.",
            },
            "last_contacted_date": {"label": "Last spoke on", "type": "date", "optional": True},
            "next_follow_up_date": {"label": "Follow up on", "type": "date", "optional": True},
            "notes": {"label": "Notes", "type": "textarea", "optional": True},
        },
    },
    "Employee": {
        "table": "orion_ods.employee",
        "primary_key": "employee_code",
        "display_column": "employee_name",
        "option_from": """
            orion_ods.employee t
            LEFT JOIN orion_ods.case cs ON cs.case_code = t.employee_case_code
        """,
        "option_pk": "t.employee_code",
        "option_label": "CONCAT_WS(' — ', NULLIF(BTRIM(t.employee_name), ''), NULLIF(BTRIM(t.employee_designation), ''), NULLIF(BTRIM(cs.case_name), ''))",
        "form_fields": {
            "employee_name": {"label": "Employee Name", "type": "text", "required": True},
            "employee_status": {"label": "Status", "type": "select", "options": ["Active", "Inactive"]},
            "emp_start_date": {"label": "Start Date", "type": "date"},
            "emp_end_date": {"label": "End Date", "type": "date"},
            "employee_type": {
                "label": "Employee Type",
                "type": "select",
                "options": ["Full-time", "Part-time", "Contract", "Intern"],
            },
            "client_facing": {"label": "Client Facing", "type": "boolean"},
            "employee_designation": {"label": "Designation", "type": "text"},
            "manager_code": {
                "label": "Manager",
                "type": "select",
                "source_table": "orion_ods.employee",
                "source_display_column": "employee_name",
                "source_pk_column": "employee_code",
                "optional": True,
            },
            "employee_case_code": {
                "label": "Case",
                "type": "select",
                "source_table": "orion_ods.case",
                "source_display_column": "case_name",
                "source_pk_column": "case_code",
                "optional": True,
            },
            # Personal details. Private: see "private_columns" below.
            "aadhaar_no": {
                "label": "Aadhaar Number",
                "type": "text",
                "optional": True,
                "hint": "12 digits. Spaces between the groups are fine.",
            },
            "pan_no": {
                "label": "PAN No",
                "type": "text",
                "optional": True,
                "hint": "For example ABCDE1234F.",
            },
            "monthly_salary": {
                "label": "Monthly Salary (Decided)",
                "type": "number",
                "money": True,
                "optional": True,
                "hint": "The monthly salary agreed with the employee.",
            },
        },
        # Checked, and tidied, wherever an employee is saved: the form and the Excel upload.
        "field_rules": {
            "aadhaar_no": employee_ids.clean_aadhaar,
            "pan_no": employee_ids.clean_pan,
            "monthly_salary": employee_ids.clean_salary,
        },
        # Left out of the table preview and the Excel export for people who can only view operational data, and
        # never loaded into the warehouse. Employee documents (app.employee_documents) follow the same rule.
        "private_columns": ["aadhaar_no", "pan_no", "monthly_salary"],
    },
    "Employee Transaction": {
        "table": "orion_ods.employee_transaction",
        "primary_key": "employee_transaction_code",
        "display_column": "employee_transaction_code",
        "option_from": """
            orion_ods.employee_transaction t
            LEFT JOIN orion_ods.employee e ON e.employee_code = t.employee_code
        """,
        "option_pk": "t.employee_transaction_code",
        "option_label": "CONCAT_WS(' — ', NULLIF(BTRIM(e.employee_name), ''), t.month_year, t.transaction_date::text, NULLIF(BTRIM(t.salary_paid), ''))",
        "form_fields": {
            "employee_code": {
                "label": "Employee",
                "type": "select",
                "source_table": "orion_ods.employee",
                "source_display_column": "employee_name",
                "source_pk_column": "employee_code",
            },
            "transaction_date": {"label": "Transaction Date", "type": "date"},
            "month_year": {
                "label": "Month Year",
                "type": "text",
                "compute_from": ["transaction_date"],
                "compute_op": "month_year",
            },
            "days_worked": {"label": "No of Days Worked", "type": "number"},
            "salary_amount": {"label": "Salary Amount", "type": "number", "money": True},
            # Not typed in: a line starts as No and becomes Yes only when its month is marked paid in Bank > Payroll (a pay run), so the form, the Excel upload and the
            # Copilot never write it. The database sets it to No when it is left out (migrate_payroll.sql) and refuses to set it to Yes any other way.
            "salary_paid": {
                "label": "Salary Paid",
                "type": "text",
                "readonly": True,
                "hint": "Set by Bank > Payroll when the month is marked paid (one transfer, one pay run). A new line starts as No.",
            },
        },
    },
    "Car": {
        "table": "orion_ods.car",
        "primary_key": "car_code",
        "display_column": "car_number",
        "field_rules": {
            "per_km_price": _not_negative("Per KM Price"),
        },
        "option_from": """
            orion_ods.car t
            LEFT JOIN orion_ods.case cs ON cs.case_code = t.case_code
        """,
        "option_pk": "t.car_code",
        "option_label": "CONCAT_WS(' — ', NULLIF(BTRIM(t.car_number), ''), NULLIF(BTRIM(t.car_model), ''), NULLIF(BTRIM(cs.case_name), ''))",
        "form_fields": {
            "car_number": {"label": "Car Number", "type": "text", "required": True},
            "car_model": {"label": "Car Model", "type": "text", "required": True},
            "case_code": {
                "label": "Case",
                "type": "select",
                "source_table": "orion_ods.case",
                "source_display_column": "case_name",
                "source_pk_column": "case_code",
            },
            "per_km_price": {"label": "Per KM Price", "type": "number", "money": True},
            "car_driven_by": {
                "label": "Driven By",
                "type": "select",
                "source_table": "orion_ods.employee",
                "source_display_column": "employee_name",
                "source_pk_column": "employee_code",
            },
        },
    },
    "Car Transaction": {
        "table": "orion_ods.car_transaction",
        "primary_key": "car_transaction_code",
        "display_column": "car_transaction_code",
        "field_rules": {
            "initial_reading": _not_negative("Initial Reading"),
            "final_reading": _not_negative("Final Reading"),
        },
        "option_from": """
            orion_ods.car_transaction t
            LEFT JOIN orion_ods.car c ON c.car_code = t.car_code
        """,
        "option_pk": "t.car_transaction_code",
        "option_label": "CONCAT_WS(' — ', NULLIF(BTRIM(c.car_number), ''), NULLIF(BTRIM(c.car_model), ''), t.driving_date::text)",
        "form_fields": {
            "car_code": {
                "label": "Car Number",
                "type": "select",
                "source_table": "orion_ods.car",
                "source_display_column": "CONCAT_WS(' — ', NULLIF(BTRIM(car_number), ''), NULLIF(BTRIM(car_model), ''))",
                "source_pk_column": "car_code",
            },
            "driving_date": {"label": "Driving Date", "type": "date"},
            "initial_reading": {"label": "Initial Reading", "type": "number"},
            "final_reading": {"label": "Final Reading", "type": "number"},
            "driven_km": {
                "label": "Driven KM",
                "type": "number",
                "compute_from": ["final_reading", "initial_reading"],
                "compute_op": "difference",
            },
        },
    },
    "Transaction": {
        "table": "orion_ods.case_transaction",
        "primary_key": "transaction_code",
        "display_column": "transaction_description",
        # An uploaded row never overwrites an entry that a bill owns.
        "merge_filter": "bill_code IS NULL",
        "option_from": """
            orion_ods.case_transaction t
            LEFT JOIN orion_ods.case cs ON cs.case_code = t.case_code
        """,
        "option_pk": "t.transaction_code",
        "option_label": "CONCAT_WS(' — ', NULLIF(BTRIM(cs.case_name), ''), t.transaction_date::text, NULLIF(BTRIM(t.transaction_status), ''), TRIM(TO_CHAR(COALESCE(t.amount_after_tax_gst, t.transaction_amount), 'FM999999990.00')))",
        "form_fields": {
            "case_code": {
                "label": "Case",
                "type": "select",
                "source_table": "orion_ods.case",
                "source_display_column": "case_name",
                "source_pk_column": "case_code",
            },
            "transaction_date": {"label": "Transaction Date", "type": "date"},
            "received_date": {
                "label": "Received Date",
                "type": "date",
                "readonly": True,
                "hint": "Set when a payment is recorded on the bill.",
            },
            "transaction_status": {
                "label": "Status",
                "type": "select",
                "options": ["Committed", "Prospective", "Cancelled"],
                "hint": "Money received is recorded on its bill (Utility > Billing > Record payment), not here. A Committed entry already here counts in the bank balance: changing its amount or date changes the balance.",
            },
            "transaction_amount": {"label": "Transaction Amount", "type": "number", "breakdown": True, "money": True},
            "tax": {"label": "Tax", "type": "number", "breakdown": True, "money": True},
            "gst": {"label": "GST", "type": "number", "breakdown": True, "money": True},
            "amount_after_tax_gst": {
                "label": "Amount After Tax & GST",
                "type": "number",
                "compute_from": ["transaction_amount", "tax", "gst"],
                "breakdown": True,
                "money": True,
            },
            "transaction_description": {
                "label": "Description",
                "type": "text",
                "optional": True,
                "auto_parts": ["case_code", "transaction_amount", "transaction_date"],
            },
        },
    },
    "Expense Transaction": {
        "table": "orion_ods.expense_transaction",
        "primary_key": "expense_code",
        "field_rules": {"vendor_gstin": _supplier_gstin},
        # Adding one that looks like another (same type, case and amount within a week) shows a warning first: it never blocks (see find_possible_duplicates).
        "duplicate_check": True,
        "display_column": "transaction_description",
        "option_from": """
            orion_ods.expense_transaction t
            LEFT JOIN orion_ods.case cs ON cs.case_code = t.case_code
            LEFT JOIN orion_ods.expense_type et ON et.expense_type_code = t.expense_type_code
        """,
        "option_pk": "t.expense_code",
        "option_label": "CONCAT_WS(' — ', NULLIF(BTRIM(cs.case_name), ''), NULLIF(BTRIM(et.expense_type_name), ''), t.transaction_date::text, TRIM(TO_CHAR(COALESCE(t.amount_after_tax_gst, t.transaction_amount), 'FM999999990.00')))",
        "form_fields": {
            "case_code": {
                "label": "Case",
                "type": "select",
                "source_table": "orion_ods.case",
                "source_display_column": "case_name",
                "source_pk_column": "case_code",
            },
            "transaction_date": {"label": "Transaction Date", "type": "date"},
            "due_date": {
                "label": "Pay By",
                "type": "date",
                "optional": True,
                "hint": "The day the supplier is to be paid by. Empty: the transaction date. Payments are recorded in Bank > Payables, not here.",
            },
            "transaction_amount": {"label": "Transaction Amount", "type": "number", "breakdown": True, "money": True},
            "tax": {"label": "Tax", "type": "number", "breakdown": True, "money": True},
            "gst": {"label": "GST", "type": "number", "breakdown": True, "money": True},
            "amount_after_tax_gst": {
                "label": "Amount After Tax & GST",
                "type": "number",
                "compute_from": ["transaction_amount", "tax", "gst"],
                "breakdown": True,
                "money": True,
            },
            "vendor_gstin": {
                "label": "Supplier GSTIN",
                "type": "text",
                "optional": True,
                "hint": "Needed whenever the expense has GST: the GST is claimed back as input tax credit only against the supplier's GSTIN and invoice. The check digit is verified.",
            },
            "vendor_invoice_no": {
                "label": "Supplier Invoice No",
                "type": "text",
                "optional": True,
                "hint": "The number on the supplier's tax invoice. Needed whenever the expense has GST.",
            },
            "transaction_status": {
                "label": "Status",
                "type": "select",
                "options": ["Committed", "Prospective", "Cancelled"],
                # What a person sees and types. The stored values are unchanged, so every report, the warehouse and the forecast read the same words as before.
                "option_labels": {"Committed": "Incurred (a real cost)", "Prospective": "Planned (not happened yet)", "Cancelled": "Cancelled"},
                "option_aliases": {"incurred": "Committed", "planned": "Prospective"},
                "hint": (
                    "Incurred: the cost has happened and is owed. It leaves the bank when it is paid: fill in Paid On below, or record the payment later in "
                    "Bank > Payables. Planned: expected but not yet happened (it is in the forecast, and cannot be paid until it is Incurred)."
                ),
            },
            "expense_type_code": {
                "label": "Expense Type",
                "type": "select",
                "source_table": "orion_ods.expense_type",
                "source_display_column": "expense_type_name",
                "source_pk_column": "expense_type_code",
            },
            "is_regular_expense": {
                "label": "Regular Expense",
                "type": "select",
                "options": ["Yes", "No"],
            },
            "transaction_description": {
                "label": "Description",
                "type": "text",
                "optional": True,
                "auto_parts": ["case_code", "transaction_amount", "transaction_date"],
            },
        },
        # Asked only when an expense is ADDED (the form, and the Excel upload), never stored on the expense: they record its payment in the same save, so
        # an expense that was paid when it was entered needs no second step. Shown only to people who may change the bank.
        "create_fields": {
            "paid_on": {
                "label": "Paid On",
                "type": "date",
                "optional": True,
                "hint": "Fill this in if the expense has already been paid in full: the payment is recorded with it and the bank moves on this day. Leave it empty to pay it later in Bank > Payables.",
            },
            "paid_from": {
                "label": "Paid From",
                "type": "select",
                "optional": True,
                "source_table": "orion_ods.bank_account",
                "source_display_column": "account_name",
                "source_pk_column": "account_id",
                "hint": "The account the money left. Needed when there is more than one account.",
            },
            "payment_reference": {"label": "Payment Reference", "type": "text", "optional": True},
        },
    },
    "EMD": {
        "table": "orion_ods.emd",
        "primary_key": "emd_code",
        "display_column": "emd_code",
        "field_rules": {"emd_amount": _positive("EMD amount"), "refund_amount": _not_negative("Refund amount"), "deduction_amount": _not_negative("Deduction")},
        "option_from": """
            orion_ods.emd t
            LEFT JOIN orion_ods.case cs ON cs.case_code = t.case_code
        """,
        "option_pk": "t.emd_code",
        "option_label": "CONCAT_WS(' — ', t.emd_code, NULLIF(BTRIM(cs.case_name), ''), TRIM(TO_CHAR(t.emd_amount, 'FM999999999990.00')), NULLIF(BTRIM(t.emd_status), ''))",
        "form_fields": {
            "case_code": {
                "label": "Case",
                "type": "select",
                "required": True,
                "source_table": "orion_ods.case",
                "source_display_column": "case_name",
                "source_pk_column": "case_code",
            },
            "opportunity_code": {
                "label": "Opportunity",
                "type": "select",
                "optional": True,
                "source_table": "orion_ods.opportunity",
                "source_display_column": "CONCAT_WS(' — ', NULLIF(BTRIM(tender_id), ''), NULLIF(BTRIM(opportunity_name), ''))",
                "source_pk_column": "opportunity_code",
            },
            "tender_reference": {"label": "Tender / bid number", "type": "text", "optional": True},
            "beneficiary": {"label": "Paid to (department or authority)", "type": "text", "optional": True},
            "emd_amount": {"label": "EMD Amount", "type": "number", "required": True, "money": True},
            "payment_mode": {"label": "Mode of payment", "type": "select", "options": EMD_MODES, "optional": True},
            "instrument_number": {
                "label": "Document number",
                "type": "text",
                "optional": True,
                "hint": "The demand draft, FDR or bank guarantee number, the cheque number, or the UTR of the transfer.",
            },
            "instrument_date": {"label": "Document date", "type": "date", "optional": True},
            "bank_name": {"label": "Bank", "type": "text", "optional": True},
            "bank_branch": {"label": "Branch", "type": "text", "optional": True},
            "deposit_date": {"label": "Deposited on", "type": "date", "required": True},
            "valid_until": {"label": "Valid until", "type": "date", "optional": True, "hint": "When a bank guarantee or FDR lapses. Leave empty for a payment that does not."},
            "emd_status": {"label": "Status", "type": "select", "options": EMD_STATUSES, "required": True},
            "refund_due_date": {"label": "Refund due on", "type": "date", "optional": True, "hint": "When it is expected back (the tender's validity or the contract's start)."},
            "refund_requested_date": {"label": "Refund asked for on", "type": "date", "optional": True},
            "refund_received_date": {"label": "Refund received on", "type": "date", "optional": True, "hint": "Needed when the status is Refunded."},
            "refund_amount": {"label": "Refund Amount", "type": "number", "optional": True, "money": True},
            "deduction_amount": {
                "label": "Deduction",
                "type": "number",
                "optional": True,
                "money": True,
                "hint": "What was kept back (a forfeit, or adjusted against the security deposit). The refund and the deduction together cannot be more than the EMD.",
            },
            "refund_reference": {"label": "Refund reference", "type": "text", "optional": True, "hint": "The UTR or credit advice of the refund."},
            "remarks": {"label": "Remarks", "type": "textarea", "optional": True},
        },
    },
}


#: An expense this close in time (days either side) to another of the same type, case and amount looks like the same one entered twice.
DUPLICATE_WINDOW_DAYS = 7


def find_possible_duplicates(name: str, cleaned: dict, *, other_days_only: bool = False, limit: int = 5) -> list[dict]:
    """Expenses already recorded that look like the one about to be added: the same expense type and case, the same amount (with tax and GST, to the
    paisa), and a date within a week either side. A warning for a person to look at, never a refusal. ``other_days_only`` leaves out the same day (an Excel
    upload merges a row with an expense of the same type, case, day and amount on purpose, so that one is not a surprise)."""
    if name != "Expense Transaction":
        return []
    total = cleaned.get("amount_after_tax_gst")
    if total is None:
        total = cleaned.get("transaction_amount")
    day = cleaned.get("transaction_date")
    if total is None or day is None:
        return []
    try:
        amount = round(Decimal(str(total)), 2)
    except Exception:  # noqa: BLE001 - an amount that is not a number is refused by validation; there is nothing to compare
        return []
    if amount <= 0:
        return []
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT e.expense_code, e.transaction_date, ROUND(COALESCE(e.amount_after_tax_gst, e.transaction_amount), 2) AS amount, e.transaction_status,
                   e.transaction_description, cs.case_name, et.expense_type_name,
                   EXISTS (SELECT 1 FROM orion_ods.expense_payment p WHERE p.expense_code = e.expense_code AND p.reversed_timestamp IS NULL) AS paid
              FROM orion_ods.expense_transaction e
              LEFT JOIN orion_ods.case cs ON cs.case_code = e.case_code
              LEFT JOIN orion_ods.expense_type et ON et.expense_type_code = e.expense_type_code
             WHERE e.transaction_status <> 'Cancelled'
               AND e.expense_type_code IS NOT DISTINCT FROM %s
               AND e.case_code IS NOT DISTINCT FROM %s
               AND ROUND(COALESCE(e.amount_after_tax_gst, e.transaction_amount), 2) = %s
               AND ABS(e.transaction_date - %s::date) <= %s
               {"AND e.transaction_date <> %s::date" if other_days_only else ""}
             ORDER BY ABS(e.transaction_date - %s::date), e.expense_code
             LIMIT %s
            """,
            (cleaned.get("expense_type_code"), cleaned.get("case_code"), amount, day, DUPLICATE_WINDOW_DAYS, *((day,) if other_days_only else ()), day, limit),
        )
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def duplicate_note(match: dict) -> str:
    """One match in words: which expense, when, how much, and whether it has been paid."""
    when = match["transaction_date"]
    shown = when.strftime("%d %b %Y") if hasattr(when, "strftime") else str(when)
    what = " · ".join(str(x) for x in (match.get("expense_type_name"), match.get("case_name"), match.get("transaction_description")) if x)
    return f"{match['expense_code']} on {shown}, ₹{match['amount']:,.2f}{' (paid)' if match.get('paid') else ''}{': ' + what if what else ''}"


def create_fields(entity: dict) -> dict:
    """The extra questions asked only when a record is added (see ``create_fields`` on the entity)."""
    return entity.get("create_fields") or {}


def with_create_fields(entity: dict) -> dict:
    """The entity as it is when a record is being added: its fields, and the extra questions."""
    extra = create_fields(entity)
    return {**entity, "form_fields": {**entity["form_fields"], **extra}} if extra else entity


def _chain_reaches(table: str, column: str, key: str, start: str, target: str) -> bool:
    """Whether following ``column`` upward from ``start`` (a manager, a group) arrives at ``target``."""
    with db_cursor() as cur:
        cur.execute(
            f"""
            WITH RECURSIVE up(code, depth) AS (
                SELECT %s::text, 0
                UNION ALL
                SELECT t.{column}, up.depth + 1
                  FROM {table} t JOIN up ON t.{key} = up.code
                 WHERE t.{column} IS NOT NULL AND up.depth < 200
            )
            SELECT 1 FROM up WHERE code = %s LIMIT 1
            """,
            (start, target),
        )
        return cur.fetchone() is not None


def expense_has_payments(expense_code: str) -> bool:
    """Whether any payment, reversed or not, has ever been recorded on this expense (payments are kept for ever)."""
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM orion_ods.expense_payment WHERE expense_code = %s LIMIT 1", (expense_code,))
        return cur.fetchone() is not None


def _paid_on_expense(expense_code: str) -> Decimal:
    with db_cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(amount), 0) FROM orion_ods.expense_payment WHERE expense_code = %s AND reversed_timestamp IS NULL", (expense_code,))
        return Decimal(str(cur.fetchone()[0]))


def _itc_problem(merged: dict, existing: dict | None, cleaned: dict, record_id: str | None) -> str | None:
    """An expense that has GST needs the supplier's GSTIN and invoice number: the GST is input tax credit only against them. An expense stored before this
    rule, with GST and neither, may still be corrected for something else; the moment its GST is changed (or a supplier detail is given) it meets the rule."""
    gst = merged.get("gst")
    if gst is None or float(gst) <= 0 or merged.get("transaction_status") == "Cancelled":
        return None
    if merged.get("vendor_gstin") and merged.get("vendor_invoice_no"):
        return None
    before = existing or {}
    legacy = (
        record_id is not None and before and float(before.get("gst") or 0) > 0 and not before.get("vendor_gstin") and not before.get("vendor_invoice_no")
        and float(cleaned.get("gst", before.get("gst")) or 0) == float(before.get("gst") or 0)
        and not cleaned.get("vendor_gstin") and not cleaned.get("vendor_invoice_no")
    )
    if legacy:
        return None
    missing = " and ".join(label for label, key in (("the supplier's GSTIN", "vendor_gstin"), ("the supplier's invoice number", "vendor_invoice_no")) if not merged.get(key))
    return (
        f"This expense has GST, so it needs {missing} (the GST can be claimed back only against them). "
        "If it has none because the supplier is not registered, enter the amount with no GST."
    )


def invalid_reason(name: str, record_id: str | None, cleaned: dict, existing: dict | None = None) -> str | None:
    """Why what was entered cannot be saved for this record, or None when it can.

    ``record_id`` is the record being changed, or None for a new one; ``existing`` is its stored values, so a rule that
    compares two fields can use the one that was not sent. The database holds the same rules (migrate_data_rules.sql),
    so an upload meets them too; this gives the person the reason before the save.
    """
    merged = {**(existing or {}), **cleaned}
    if name == "Client" and record_id and cleaned.get("client_group_code"):
        group = str(cleaned["client_group_code"]).strip()
        if group == str(record_id).strip():
            return (
                "A client cannot be its own group. Pick another client, or leave Client Group empty for a "
                "client that stands on its own."
            )
        if _chain_reaches("orion_ods.client", "client_group_code", "client_code", group, str(record_id).strip()):
            return (
                "That group already belongs to this client, directly or through other groups, so the groups would "
                "go round in a circle. Pick a group that is not under this client."
            )
    if name == "Employee" and record_id and cleaned.get("manager_code"):
        manager = str(cleaned["manager_code"]).strip()
        if manager == str(record_id).strip():
            return "An employee cannot be their own manager. Pick another manager, or leave Manager empty."
        if _chain_reaches("orion_ods.employee", "manager_code", "employee_code", manager, str(record_id).strip()):
            return (
                "That manager already reports to this employee, directly or through other managers, so the managers "
                "would go round in a circle. Pick a manager who is not under this employee."
            )
    if name == "Transaction" and merged.get("transaction_status") == "Committed" and not merged.get("bill_code"):
        # Only what is new: an entry stored as received with no bill before this rule keeps its place (the database holds the same rule).
        before = existing or {}
        if record_id is None or before.get("transaction_status") != "Committed" or before.get("bill_code"):
            return (
                "Money received is recorded on its bill: open the bill in Utility > Billing and choose Record payment. Money that has no bill (an advance, a deposit) is entered in Bank > Ledger > Add entry, as a receipt with no bill."
            )
    if name == "Expense Transaction":
        problem = _itc_problem(merged, existing, cleaned, record_id)
        if problem:
            return problem
    if name == "Expense Transaction" and record_id:
        # The database holds the same rule (migrate_expense_payments.sql); this tells the person which payments are in the way.
        paid = _paid_on_expense(str(record_id))
        if paid > 0:
            if merged.get("transaction_status") != "Committed":
                return "Payments have been recorded on this expense, so it stays Committed. Reverse them first (Bank > Payables), with a reason, if it was entered by mistake."
            total = merged.get("amount_after_tax_gst")
            if total is None:
                total = merged.get("transaction_amount")
            if total is not None and round(Decimal(str(total)), 2) < paid:
                return f"₹{paid:,.2f} has already been paid on this expense, so it cannot be less than that. Reverse a payment first (Bank > Payables) to lower it."
    if name == "Contact":
        start, end = merged.get("contact_start_date"), merged.get("contact_end_date")
        if start and end and end < start:
            return "The day they left cannot be before the day you came to know them."
        if merged.get("is_primary_contact") == "Yes" and merged.get("contact_status") not in (None, "Active"):
            return "A primary contact must be Active. Make another person the primary contact, or set this one to No."
    if name == "EMD":
        amount = float(merged.get("emd_amount") or 0)
        returned = float(merged.get("refund_amount") or 0) + float(merged.get("deduction_amount") or 0)
        if amount and returned > amount + 0.004:
            return "The refund and the deduction together cannot be more than the EMD."
        started = merged.get("instrument_date") or merged.get("deposit_date")
        if merged.get("valid_until") and started and merged["valid_until"] < started:
            return "Valid until cannot be before the day the document was issued or the EMD was deposited."
        if merged.get("emd_status") == "Refunded" and not merged.get("refund_received_date"):
            return "Say the day the refund was received (Refund received on), or leave the status as Refund requested."
    if name == "Car Transaction":
        initial, final = merged.get("initial_reading"), merged.get("final_reading")
        if initial is not None and final is not None and float(final) < float(initial):
            return "The final reading cannot be lower than the initial reading."
    return None


def locked_reason(name: str, record: dict) -> str | None:
    """Why a record cannot be changed through the generic forms, or None when it can.

    A revenue entry that belongs to a bill is written only by app.billing: raising,
    editing or cancelling the bill, and recording a payment on it.
    """
    if name == "Transaction" and record.get("bill_code"):
        if record.get("transaction_status") == "Committed":
            return (
                "This revenue was received against a bill and can no longer be changed. "
                "An admin can reverse the payment from the bill in Utility > Billing."
            )
        return (
            "This revenue entry belongs to a bill, so its case, date, status and amounts follow the bill. "
            "Edit the bill, or record a payment on it, in Utility > Billing."
        )
    if name in ("Employee Transaction", "Expense Transaction") and record.get("attendance_line_id"):
        return (
            "This line was entered by an attendance register, so its amount follows the register. To change it, reopen the register in Attendance "
            "(possible until it is paid), change it there and post it again."
        )
    if name == "Employee Transaction" and record.get("salary_run_id"):
        return "This salary line has been paid in a pay run and can no longer be changed. To correct it, reverse the pay run in Bank > Payroll (with a reason), change the line, and mark the month paid again."
    return None


def dropdown_spec(entity: dict) -> tuple[str, str, str, str | None]:
    """id stored in the DB, label shown in the update/delete record picker only."""
    return (
        entity["table"],
        entity.get("option_label") or entity["display_column"],
        entity.get("option_pk") or entity["primary_key"],
        entity.get("option_from"),
    )


def ensure_bill_table() -> None:
    """Apply the schema files (the bill tables, the who-changed columns and the other additive ODS columns) through app.migrate,
    which records each result. A failure is logged and recorded here; a deploy and production start-up stop on it (migrate.py).

    Bills are raised and edited only through app.billing, so there is no "Bill" entry in
    ENTITIES. app.billing also writes each bill's revenue entries into case_transaction.
    """
    from app import migrate

    migrate.run(warehouse=False)
