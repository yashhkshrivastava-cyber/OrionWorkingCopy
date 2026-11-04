import json
import logging
import threading
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app import bill_fonts, billing, billing_pdf, documents, documents_explorer, documents_filing, gdrive, idempotency, receivables
from app.ai import features as ai_features
from app.auth import can_write_documents
from app.dependencies import require_admin, require_billing, require_billing_write
from app.idempotency import Idempotency

log = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


class LineIn(BaseModel):
    particulars: str = ""
    qty: float | str | None = None
    rate: float | str | None = None
    days: float | str | None = None  # a day-based bill's days (or person-days); the amount is rate x days
    fields: dict[str, str] = {}  # the values of the bill's extra columns, by column key
    amount_manual: float | str | None = None  # the amount, entered instead of the worked-out one
    skip: list[str] = []  # charges (epf, esic, service) this line is left out of


class LineSetupIn(BaseModel):
    """How a bill's lines are laid out and worked out (billing.clean_line_setup). Left out, it is the original quantity x rate."""

    basis: str = "unit"
    qty_multiplies: bool = True
    month_days: Optional[int] = None
    totals_row: bool = False
    charge_by_line: bool = False
    service_on: str = "lines"
    labels: dict[str, str] = {}
    columns: list[dict[str, str]] = []


class ExtraChargeIn(BaseModel):
    label: str = ""
    kind: str = "pct"
    value: float | str | None = None


class HeaderFieldIn(BaseModel):
    label: str = ""
    value: str = ""


class BillIn(BaseModel):
    bill_date: date
    service_month: str = Field(description="YYYY-MM")
    case_code: str
    party_name: str
    party_gstin: Optional[str] = None
    party_address: Optional[str] = None
    party_state: Optional[str] = None
    ref_no: Optional[str] = None
    ref_date: Optional[date] = None
    tender_id: Optional[str] = None
    tender_start_date: Optional[date] = None
    location: Optional[str] = None
    service_description: Optional[str] = None
    lines: list[LineIn]
    rates: Optional[dict[str, float | str | None]] = None
    extra_charges: list[ExtraChargeIn] = []
    hidden: list[str] = []
    header_fields: list[HeaderFieldIn] = []
    party_fields: list[HeaderFieldIn] = []
    line_setup: LineSetupIn = LineSetupIn()
    profile_fields: dict[str, str | list[str]] = {}  # template details (bank, terms, company ...) this bill prints differently
    manual_figures: dict[str, float | str | None] = {}  # EPFO, ESIC, service, CGST or SGST amounts entered instead of calculated
    font_family: Optional[str] = None  # only a new bill takes these; an issued bill's are set by PUT /bills/{code}/font
    font_size: Optional[float] = None
    drive_save: Optional[bool] = None  # a new bill only: also save its PDF to Google Drive (None follows the company's setting, False does not)
    drive_folder_id: Optional[str] = None  # the Drive folder to save it in (empty: the company's folder)
    filing_node: Optional[str] = None  # a new bill only: the Document Center folder to keep it in (empty: where Orion files it)


class FontIn(BaseModel):
    font_family: Optional[str] = None
    font_size: Optional[float] = None


class BillEditIn(BillIn):
    reason: str


class CancelIn(BaseModel):
    reason: str


class GstPaymentIn(BaseModel):
    """A payment of GST to the government. A request that did not come from the confirmation screen has no ``confirm`` and is refused."""

    confirm: bool = False
    seen_paid: Optional[float | str] = None
    cgst: Optional[float | str] = None
    sgst: Optional[float | str] = None
    paid_date: Optional[date] = None
    reference: Optional[str] = Field(default=None, max_length=120)
    account_id: Optional[int] = None  # the account it was paid from; none means the default account


class StatutoryPaymentIn(BaseModel):
    """A payment of EPFO and/or ESIC made to the authority. A request that did not come from the confirmation screen has no ``confirm`` and is refused."""

    confirm: bool = False
    seen_paid: Optional[float | str] = None
    epfo: Optional[float | str] = None
    esic: Optional[float | str] = None
    paid_date: Optional[date] = None
    reference: Optional[str] = Field(default=None, max_length=120)
    account_id: Optional[int] = None  # the account it was paid from; none means the default account


class GstReversalIn(BaseModel):
    confirm: bool = False
    reason: Optional[str] = Field(default=None, max_length=600)


class DeductionIn(BaseModel):
    """Something the client held back from the payment: TDS (with its section), a penalty, rounding, or something else (with a reason)."""

    kind: str = Field(max_length=20)
    amount: float | str
    section: Optional[str] = Field(default=None, max_length=12)
    rate: Optional[float | str] = None
    reason: Optional[str] = Field(default=None, max_length=300)


class PaymentIn(BaseModel):
    amount: float | str  # the cash that came in; the bill is settled by this plus the deductions
    received_date: date
    account_id: Optional[int] = None  # the account it was received into; none means the default account
    deductions: list[DeductionIn] = Field(default_factory=list, max_length=billing.MAX_DEDUCTIONS)


def _bad_request(exc: billing.BillError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That bill does not exist.")


@router.get("/accounts")
def money_accounts(_user=Depends(require_billing)):
    """The accounts a payment can be received into or paid from. Only names: balances are on the Bank pages."""
    return {"accounts": billing.list_money_accounts()}


@router.get("/cases")
def cases(_user=Depends(require_billing)):
    return {"cases": billing.list_cases()}


@router.get("/profile")
def get_profile(_user=Depends(require_billing)):
    return billing.get_profile()


@router.put("/profile")
def put_profile(body: dict[str, Any], user=Depends(require_billing_write)):
    before = bill_fonts.company_font(billing.get_profile())
    try:
        saved = billing.save_profile(body, user["id"])
    except billing.BillError as exc:
        raise _bad_request(exc) from exc
    if bill_fonts.company_font(saved) != before:
        # Every bill that follows the company is drawn in another typeface or size now; the filed copies catch up in the background.
        threading.Thread(target=documents_filing.reconcile_quietly, daemon=True).start()
    return saved


@router.get("/fonts")
def fonts(_user=Depends(require_billing)):
    """The typefaces and sizes a bill can be printed in: the typefaces this computer can draw in the PDF, and the sizes."""
    options = bill_fonts.options()
    installed = set(billing_pdf.available_families()) | {bill_fonts.DEFAULT_FAMILY}
    return {**options, "families": [family for family in options["families"] if family["key"] in installed]}


@router.get("/next-number")
def next_number(day: Optional[date] = Query(default=None, alias="date"), _user=Depends(require_billing)):
    return billing.next_number(day or date.today())


@router.get("/years")
def years(_user=Depends(require_billing)):
    return {"years": billing.financial_years()}


@router.get("/bills")
def bills(
    fy: Optional[int] = None,
    q: Optional[str] = None,
    client_code: Optional[str] = None,
    case_code: Optional[str] = None,
    month: Optional[str] = Query(default=None, description="The month the bill is for, YYYY-MM"),
    _user=Depends(require_billing),
):
    """The register. Any of the financial year, a client, a case, the month a bill is for and a search may be given; none means every bill (newest 500)."""
    try:
        return {"bills": billing.list_bills(fy, q, client_code=client_code or None, case_code=case_code or None, month=month or None)}
    except billing.BillError as exc:
        raise _bad_request(exc) from exc


@router.get("/card")
def bill_card(code: Optional[str] = None, number: Optional[str] = None, _user=Depends(require_billing)):
    """What the hover card on a bill number shows. Found by the bill's code or by the number printed on it."""
    if not (code or "").strip() and not (number or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Give a bill code or a bill number.")
    found = billing.bill_card(code=code, number=number)
    if not found:
        raise _not_found()
    return found


@router.get("/bills/{bill_code}")
def bill(bill_code: str, _user=Depends(require_billing)):
    found = billing.get_bill(bill_code)
    if not found:
        raise _not_found()
    return found


def _once(request: Request, response: Response, user: dict, operation: str, *parts: Any) -> Optional[Idempotency]:
    """The request's one-time key, if it sent one (``Idempotency-Key``). With ``ORION_IDEMPOTENCY_REQUIRED=1`` it must."""
    try:
        key = idempotency.clean_key(request.headers.get("Idempotency-Key"))
    except idempotency.IdempotencyError as exc:
        raise _bad_request(exc) from exc
    if key is None:
        if idempotency.required():
            raise _bad_request(idempotency.IdempotencyError("This page is out of date. Reload it and try again."))
        log.info("%s arrived without an Idempotency-Key, so a repeat of it would not be caught", operation)
        return None
    return Idempotency(user["id"], key, operation, idempotency.fingerprint(operation, user["id"], *parts))


def _finish(idem: Optional[Idempotency], response: Response) -> None:
    if idem is not None and idem.replayed:
        response.headers["Idempotent-Replayed"] = "true"


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/bills", status_code=status.HTTP_201_CREATED)
def create(body: BillIn, request: Request, response: Response, user=Depends(require_billing_write)):
    data = body.model_dump()
    chosen = None
    if (body.drive_save or body.drive_folder_id) and not can_write_documents(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You may issue bills but not choose where documents are kept.")
    if body.filing_node:  # checked first, so a bad choice does not leave an issued bill behind
        if not can_write_documents(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You may issue bills but not choose where documents are kept.")
        try:
            chosen = documents_explorer.choice_destination(body.filing_node)
        except documents.DocumentCenterError as exc:
            raise _bad_request(exc) from exc
    idem = _once(request, response, user, "bill.create", data)
    try:
        saved = billing.create_bill(data, user["id"], idem)
    except billing.BillError as exc:
        raise _bad_request(exc) from exc
    except idempotency.IdempotencyConflict as exc:
        raise _conflict(exc) from exc
    _finish(idem, response)
    # The bill is filed in the Document Center (under its case and its client). A request that was answered again from its first
    # answer (a second click) has nothing new to file.
    code = str(saved.get("bill_code") or saved.get("id") or "") or None
    if chosen and code:
        try:
            documents_filing.set_choice(documents_filing.BILL, code, chosen, user["id"])
        except Exception:  # noqa: BLE001 - the bill is issued; it is filed where Orion files it, and the person can move it from the bill's page
            log.exception("Could not keep bill %s where it was chosen", code)
    documents_filing.reconcile_quietly(bill_code=code)
    if code:  # the company's setting applies to every bill; the person's own tick and folder only if they may choose where documents go
        gdrive.after_bill_created(code, body.drive_save if can_write_documents(user) else None, body.drive_folder_id if can_write_documents(user) else None, user["id"])
    return saved


@router.put("/bills/{bill_code}")
def update(bill_code: str, body: BillEditIn, request: Request, response: Response, user=Depends(require_billing_write)):
    data = body.model_dump(exclude={"reason"})
    idem = _once(request, response, user, "bill.update", bill_code, data, body.reason)
    try:
        saved = billing.update_bill(bill_code, data, body.reason, user["id"], idem)
    except billing.BillError as exc:
        raise _bad_request(exc) from exc
    except idempotency.IdempotencyConflict as exc:
        raise _conflict(exc) from exc
    _finish(idem, response)
    documents_filing.reconcile_quietly(bill_code=bill_code)  # the edit is a new version of the filed invoice
    gdrive.sync_bill_quietly(bill_code)  # and of its copy in Google Drive, if it has one
    return saved


@router.put("/bills/{bill_code}/font")
def set_font(bill_code: str, body: FontIn, user=Depends(require_billing_write)):
    """How the bill is printed: its own typeface and size (both empty: follow the company's). Not a new version of the bill."""
    try:
        saved = billing.set_bill_font(bill_code, body.font_family, body.font_size)
    except billing.BillError as exc:
        raise _bad_request(exc) from exc
    # The filed invoice is drawn again in the new typeface and size, in place: it is not a change, so it makes no new version.
    documents_filing.reconcile_quietly(bill_code=bill_code)
    gdrive.sync_bill_quietly(bill_code)
    return saved


@router.get("/bills/{bill_code}/versions")
def versions(bill_code: str, _user=Depends(require_billing)):
    found = billing.list_versions(bill_code)
    if not found:
        raise _not_found()
    return {"versions": found}


@router.get("/bills/{bill_code}/versions/{version_no}")
def version(bill_code: str, version_no: int, _user=Depends(require_billing)):
    found = billing.get_version(bill_code, version_no)
    if not found:
        raise _not_found()
    return found


@router.post("/bills/{bill_code}/cancel")
def cancel(bill_code: str, body: CancelIn, user=Depends(require_billing_write)):
    try:
        cancelled = billing.cancel_bill(bill_code, body.reason, user["id"])
    except billing.BillError as exc:
        raise _bad_request(exc) from exc
    documents_filing.reconcile_quietly(bill_code=bill_code)  # the filed invoice is archived, and shows as cancelled
    gdrive.sync_bill_quietly(bill_code)
    return cancelled


@router.post("/bills/{bill_code}/payments")
def record_payment(bill_code: str, body: PaymentIn, request: Request, response: Response, user=Depends(require_billing_write)):
    held = [item.model_dump() for item in body.deductions]
    idem = _once(request, response, user, "bill.payment", bill_code, str(body.amount), str(body.received_date), body.account_id, json.dumps(held, sort_keys=True, default=str))
    try:
        saved = billing.record_payment(bill_code, body.amount, body.received_date, user["id"], idem, body.account_id, held)
    except billing.BillError as exc:
        raise _bad_request(exc) from exc
    except idempotency.IdempotencyConflict as exc:
        raise _conflict(exc) from exc
    _finish(idem, response)
    return saved


@router.delete("/bills/{bill_code}/payments/{transaction_code}")
def reverse_payment(bill_code: str, transaction_code: str, user=Depends(require_admin)):
    try:
        return billing.reverse_payment(bill_code, transaction_code, user["id"])
    except billing.BillError as exc:
        raise _bad_request(exc) from exc


@router.post("/bills/{bill_code}/gst-payments")
def gst_payment(bill_code: str, body: GstPaymentIn, user=Depends(require_billing_write)):
    try:
        return billing.record_gst_payment(
            bill_code, user["id"], confirm=body.confirm, seen_paid=body.seen_paid, cgst=body.cgst, sgst=body.sgst,
            paid_date=body.paid_date, reference=body.reference, account_id=body.account_id,
        )
    except billing.GstConflict as exc:
        raise _conflict(exc) from exc
    except billing.BillError as exc:
        raise _bad_request(exc) from exc


@router.post("/bills/{bill_code}/gst-payments/{batch_id}/reverse")
def gst_payment_reverse(bill_code: str, batch_id: str, body: GstReversalIn, user=Depends(require_billing_write)):
    try:
        return billing.reverse_gst_payment(bill_code, batch_id, user["id"], confirm=body.confirm, reason=body.reason)
    except billing.GstConflict as exc:
        raise _conflict(exc) from exc
    except billing.BillError as exc:
        raise _bad_request(exc) from exc


@router.post("/bills/{bill_code}/statutory-payments")
def statutory_payment(bill_code: str, body: StatutoryPaymentIn, user=Depends(require_billing_write)):
    try:
        return billing.record_statutory_payment(
            bill_code, user["id"], confirm=body.confirm, seen_paid=body.seen_paid, epfo=body.epfo, esic=body.esic,
            paid_date=body.paid_date, reference=body.reference, account_id=body.account_id,
        )
    except billing.StatutoryConflict as exc:
        raise _conflict(exc) from exc
    except billing.BillError as exc:
        raise _bad_request(exc) from exc


@router.post("/bills/{bill_code}/statutory-payments/{batch_id}/reverse")
def statutory_payment_reverse(bill_code: str, batch_id: str, body: GstReversalIn, user=Depends(require_billing_write)):
    try:
        return billing.reverse_statutory_payment(bill_code, batch_id, user["id"], confirm=body.confirm, reason=body.reason)
    except billing.StatutoryConflict as exc:
        raise _conflict(exc) from exc
    except billing.BillError as exc:
        raise _bad_request(exc) from exc


# --------------------------------------------------------------------------- recurring bills


@router.get("/due")
def due(month: Optional[str] = Query(default=None, description="YYYY-MM"), _user=Depends(require_billing)):
    try:
        return billing.list_due_to_bill(month)
    except billing.BillError as exc:
        raise _bad_request(exc) from exc


# --------------------------------------------------------------------------- sending bills


class EmailIn(BaseModel):
    to: str
    message: str
    letterhead: bool = False  # attach the PDF drawn on the company letterhead


class WhatsAppIn(BaseModel):
    phone: str
    message: str


def _share_error(exc: receivables.ShareError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _pdf(document: tuple[str, bytes] | None, missing: str) -> Response:
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=missing)
    name, data = document
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


@router.get("/bills/{bill_code}/pdf")
def bill_pdf(bill_code: str, letterhead: bool = False, _user=Depends(require_billing)):
    return _pdf(receivables.invoice_document(bill_code, letterhead), "That bill does not exist.")


@router.get("/bills/{bill_code}/share")
def bill_share(bill_code: str, _user=Depends(require_billing_write)):
    try:
        return receivables.invoice_share(bill_code)
    except receivables.ShareError as exc:
        raise _share_error(exc) from exc


@router.post("/bills/{bill_code}/email")
def bill_email(bill_code: str, body: EmailIn, user=Depends(require_billing_write)):
    try:
        return receivables.email_invoice(bill_code, body.to, body.message, user, body.letterhead)
    except receivables.ShareError as exc:
        raise _share_error(exc) from exc


@router.post("/bills/{bill_code}/whatsapp")
def bill_whatsapp(bill_code: str, body: WhatsAppIn, user=Depends(require_billing_write)):
    try:
        return receivables.whatsapp_invoice(bill_code, body.phone, body.message, user)
    except receivables.ShareError as exc:
        raise _share_error(exc) from exc


# --------------------------------------------------------------------------- outstanding and reminders


@router.get("/receivables")
def receivables_report(_user=Depends(require_billing)):
    return receivables.list_receivables()


@router.get("/receivables/{client_code}/statement.pdf")
def statement_pdf(client_code: str, letterhead: bool = False, _user=Depends(require_billing)):
    return _pdf(receivables.statement_document(client_code, letterhead), "That client has nothing outstanding.")


@router.get("/receivables/{client_code}/share")
def reminder_share(client_code: str, _user=Depends(require_billing_write)):
    try:
        return receivables.reminder_share(client_code)
    except receivables.ShareError as exc:
        raise _share_error(exc) from exc


class ReminderAiIn(BaseModel):
    tone: str = Field(default="polite", max_length=10)
    allow_cloud_once: bool = False


@router.post("/receivables/{client_code}/reminder/ai")
def reminder_ai(client_code: str, body: ReminderAiIn, user=Depends(require_billing_write)):
    """The reminder re-worded in a tone. The bills, amounts and bank details are put in by the application, not the model."""
    statement = receivables.client_statement(client_code)
    if not statement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That client has nothing outstanding.")
    result = ai_features.word_reminder(user, statement, billing.get_profile(), tone=body.tone, allow_cloud_once=body.allow_cloud_once)
    if result.get("status") == "invalid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["message"])
    return result


@router.post("/receivables/{client_code}/email")
def reminder_email(client_code: str, body: EmailIn, user=Depends(require_billing_write)):
    try:
        return receivables.email_reminder(client_code, body.to, body.message, user, body.letterhead)
    except receivables.ShareError as exc:
        raise _share_error(exc) from exc


@router.post("/receivables/{client_code}/whatsapp")
def reminder_whatsapp(client_code: str, body: WhatsAppIn, user=Depends(require_billing_write)):
    try:
        return receivables.whatsapp_reminder(client_code, body.phone, body.message, user)
    except receivables.ShareError as exc:
        raise _share_error(exc) from exc
