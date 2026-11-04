"""The Bank API. Reading needs Bank access; recording, importing and matching need permission to change the bank."""

import json
import logging
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field

from app import bank, bank_statement, idempotency
from app.ai import features as ai_features
from app.dependencies import require_bank, require_bank_write
from app.idempotency import Idempotency

log = logging.getLogger(__name__)

router = APIRouter(prefix="/bank", tags=["bank"])


def _bad(exc: Exception) -> HTTPException:
    code = status.HTTP_409_CONFLICT if isinstance(exc, (bank.BankConflict, idempotency.IdempotencyConflict)) else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


def _once(request: Request, user: dict, operation: str, *parts: Any) -> Optional[Idempotency]:
    """The request's one-time key, if it sent one (``Idempotency-Key``). With ``ORION_IDEMPOTENCY_REQUIRED=1`` it must."""
    try:
        key = idempotency.clean_key(request.headers.get("Idempotency-Key"))
    except idempotency.IdempotencyError as exc:
        raise _bad(exc) from exc
    if key is None:
        if idempotency.required():
            raise _bad(idempotency.IdempotencyError("This page is out of date. Reload it and try again."))
        log.info("%s arrived without an Idempotency-Key, so a repeat of it would not be caught", operation)
        return None
    return Idempotency(user["id"], key, operation, idempotency.fingerprint(operation, user["id"], *parts))


def _finish(idem: Optional[Idempotency], response: Response) -> None:
    if idem is not None and idem.replayed:
        response.headers["Idempotent-Replayed"] = "true"


def _read(file: UploadFile) -> bytes:
    # One byte more than the limit is read, so a file that is too big is refused without reading the rest of it.
    content = file.file.read(bank_statement.MAX_BYTES + 1)
    if len(content) > bank_statement.MAX_BYTES:
        raise HTTPException(status_code=413, detail="That file is too large for a bank statement.")
    return content


def _mapping(raw: Optional[str]) -> Optional[dict[str, int]]:
    """The column choices the person made, if any: ``{"date": 0, "description": 2 ...}``. Anything else is refused."""
    if not raw or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The column choices are not valid.") from None
    if (
        not isinstance(value, dict) or len(value) > 12
        or any(k not in bank_statement.SYNONYMS or isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < 200 for k, v in value.items())
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The column choices are not valid.")
    return value


class AccountIn(BaseModel):
    account_id: Optional[int] = None
    account_kind: str = Field(default="bank", max_length=10)
    account_name: str = Field(max_length=80)
    bank_name: Optional[str] = Field(default=None, max_length=80)
    account_last4: Optional[str] = Field(default=None, max_length=4)
    opening_balance: float | str
    opening_date: date
    #: Optional minimum balance. Left out it stays as it was; sent empty it is cleared.
    low_balance_floor: Optional[float | str] = None
    confirm: bool = False


class EntryIn(BaseModel):
    account_id: Optional[int] = None
    entry_date: date
    direction: str
    amount: float | str
    category: str
    counterparty: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=300)
    reference: Optional[str] = Field(default=None, max_length=120)


class LineEntryIn(BaseModel):
    category: str
    counterparty: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=300)
    reference: Optional[str] = Field(default=None, max_length=120)


class VoidIn(BaseModel):
    reason: str = Field(max_length=300)


class MovementRef(BaseModel):
    source: str = Field(max_length=20)
    source_ref: str = Field(max_length=80)


class MatchIn(BaseModel):
    movements: list[MovementRef] = Field(max_length=10)


class IgnoreIn(BaseModel):
    reason: str = Field(max_length=200)


class CategoriseIn(BaseModel):
    allow_cloud_once: bool = False


# --------------------------------------------------------------------------------------------------------------- reading


@router.get("/meta")
def meta(_user=Depends(require_bank)):
    return bank.meta()


@router.get("/account")
def account(account_id: Optional[int] = None, _user=Depends(require_bank)):
    return bank.get_account(account_id)


@router.get("/accounts")
def accounts(_user=Depends(require_bank)):
    """Every account with its balance, and the total."""
    return bank.list_accounts()


@router.get("/account/preview")
def account_preview(opening_balance: str, opening_date: date, account_id: Optional[int] = None, _user=Depends(require_bank)):
    try:
        return bank.preview_account_change(opening_balance, opening_date, account_id)
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.get("/summary")
def summary(account_id: Optional[int] = None, _user=Depends(require_bank)):
    try:
        return bank.summary(account_id)
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.get("/series")
def series(months: int = Query(default=12, ge=1, le=36), account_id: Optional[int] = None, _user=Depends(require_bank)):
    try:
        return bank.series(months, account_id)
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.get("/forecast")
def forecast(include_overdue: bool = False, _user=Depends(require_bank)):
    return bank.forecast(include_overdue=include_overdue)


@router.get("/alerts")
def alerts(_user=Depends(require_bank)):
    """Accounts below the minimum balance set on them, and the balance expected to fall below it within two weeks (empty when no minimum is set)."""
    return {"alerts": bank.alerts()}


def _ledger_args(
    date_from: Optional[date], date_to: Optional[date], direction: Optional[str], category: Optional[str], source: Optional[str],
    q: Optional[str], reconciled: Optional[str], account_id: Optional[int] = None,
) -> dict[str, Any]:
    return {
        "date_from": date_from, "date_to": date_to, "direction": direction, "category": category, "source": source, "q": q, "reconciled": reconciled,
        "account_id": account_id,
    }


@router.get("/ledger")
def ledger(
    date_from: Optional[date] = None, date_to: Optional[date] = None, direction: Optional[str] = None, category: Optional[str] = None,
    source: Optional[str] = None, q: Optional[str] = Query(default=None, max_length=80), reconciled: Optional[str] = None,
    oldest_first: bool = False, limit: int = Query(default=50, ge=1, le=bank.PAGE_MAX), page: int = Query(default=1, ge=1),
    account_id: Optional[int] = None, _user=Depends(require_bank),
):
    try:
        return bank.ledger(**_ledger_args(date_from, date_to, direction, category, source, q, reconciled, account_id), oldest_first=oldest_first, limit=limit, page=page)
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.get("/ledger.csv")
def ledger_csv(
    date_from: Optional[date] = None, date_to: Optional[date] = None, direction: Optional[str] = None, category: Optional[str] = None,
    source: Optional[str] = None, q: Optional[str] = Query(default=None, max_length=80), reconciled: Optional[str] = None,
    account_id: Optional[int] = None, _user=Depends(require_bank),
):
    try:
        text = bank.ledger_csv(**_ledger_args(date_from, date_to, direction, category, source, q, reconciled, account_id))
    except bank.BankError as exc:
        raise _bad(exc) from exc
    return Response(
        content="﻿" + text, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bank-ledger-{date.today().isoformat()}.csv"', "Cache-Control": "no-store"},
    )


@router.get("/entries/{entry_id}")
def entry(entry_id: int, _user=Depends(require_bank)):
    found = bank.get_entry(entry_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That entry does not exist.")
    return found


@router.get("/activity")
def activity(limit: int = Query(default=50, ge=1, le=200), _user=Depends(require_bank)):
    return {"activity": bank.activity(limit)}


@router.get("/reconciliation")
def reconciliation(account_id: Optional[int] = None, _user=Depends(require_bank)):
    return bank.reconciliation(account_id)


@router.get("/exceptions")
def exceptions(account_id: Optional[int] = None, _user=Depends(require_bank)):
    """Statement lines matched to something that has since been reversed, cancelled or edited in the book."""
    return {"exceptions": bank.exceptions(account_id)}


@router.get("/statements")
def statements(account_id: Optional[int] = None, _user=Depends(require_bank)):
    return {"imports": bank.imports(account_id)}


@router.get("/lines")
def lines(
    status_: Optional[str] = Query(default=None, alias="status"), q: Optional[str] = Query(default=None, max_length=80),
    date_from: Optional[date] = None, date_to: Optional[date] = None, account_id: Optional[int] = None,
    limit: int = Query(default=50, ge=1, le=bank.PAGE_MAX), page: int = Query(default=1, ge=1), _user=Depends(require_bank),
):
    try:
        return bank.lines(status=status_, q=q, date_from=date_from, date_to=date_to, limit=limit, page=page, account_id=account_id)
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.get("/lines/{line_id}/suggestions")
def suggestions(line_id: int, _user=Depends(require_bank)):
    try:
        return bank.suggestions(line_id)
    except bank.BankError as exc:
        raise _bad(exc) from exc


# --------------------------------------------------------------------------------------------------------------- changing


@router.put("/account")
def save_account(body: AccountIn, user=Depends(require_bank_write)):
    """Set up the first account, or change one (the first, unless ``account_id`` names it)."""
    try:
        return bank.save_account(body.model_dump(exclude={"confirm", "account_id"}, exclude_unset=True), user["id"], confirm=body.confirm, account_id=body.account_id)
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(body: AccountIn, user=Depends(require_bank_write)):
    """Add another account: a bank account, or cash."""
    try:
        return bank.save_account(body.model_dump(exclude={"confirm", "account_id"}, exclude_unset=True), user["id"], create=True)
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.post("/entries", status_code=status.HTTP_201_CREATED)
def create_entry(body: EntryIn, request: Request, response: Response, user=Depends(require_bank_write)):
    data = body.model_dump()
    idem = _once(request, user, "bank.entry", data)
    try:
        saved = bank.create_entry(data, user["id"], idem)
    except (bank.BankError, idempotency.IdempotencyConflict) as exc:
        raise _bad(exc) from exc
    _finish(idem, response)
    return saved


@router.post("/entries/{entry_id}/void")
def void_entry(entry_id: int, body: VoidIn, user=Depends(require_bank_write)):
    try:
        return bank.void_entry(entry_id, body.reason, user["id"])
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.post("/statements/preview")
def preview_statement(
    file: UploadFile = File(...), mapping: Optional[str] = Form(default=None), header_row: Optional[int] = Form(default=None, ge=0, le=500),
    account_id: Optional[int] = Form(default=None), _user=Depends(require_bank_write),
):
    try:
        return bank.preview_statement(file.filename or "statement", _read(file), _mapping(mapping), header_row, account_id)
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.post("/statements", status_code=status.HTTP_201_CREATED)
def import_statement(
    file: UploadFile = File(...), mapping: Optional[str] = Form(default=None), header_row: Optional[int] = Form(default=None, ge=0, le=500),
    account_id: Optional[int] = Form(default=None), user=Depends(require_bank_write),
):
    try:
        return bank.import_statement(file.filename or "statement", _read(file), user["id"], _mapping(mapping), header_row, account_id)
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.delete("/statements/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_statement(import_id: int, user=Depends(require_bank_write)):
    try:
        bank.remove_import(import_id, user["id"])
    except bank.BankError as exc:
        raise _bad(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/match/auto")
def auto_match(account_id: Optional[int] = None, user=Depends(require_bank_write)):
    return bank.run_auto_match(user["id"], account_id)


@router.post("/lines/categorise")
def categorise(body: CategoriseIn, user=Depends(require_bank_write)):
    """Ask the AI to name the unmatched lines Orion's rules could not. Suggestions only: nothing is saved."""
    return ai_features.categorise_bank_lines(user, bank.categorisation_candidates(), allow_cloud_once=body.allow_cloud_once)


@router.post("/lines/{line_id}/match")
def match_line(line_id: int, body: MatchIn, user=Depends(require_bank_write)):
    try:
        return bank.match_line(line_id, [m.model_dump() for m in body.movements], user["id"])
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.post("/exceptions/{line_id}/clear")
def clear_exception(line_id: int, user=Depends(require_bank_write)):
    try:
        return bank.clear_exception(line_id, user["id"])
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.post("/lines/{line_id}/unmatch")
def unmatch_line(line_id: int, user=Depends(require_bank_write)):
    try:
        return bank.unmatch_line(line_id, user["id"])
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.post("/lines/{line_id}/ignore")
def ignore_line(line_id: int, body: IgnoreIn, user=Depends(require_bank_write)):
    try:
        return bank.ignore_line(line_id, body.reason, user["id"])
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.post("/lines/{line_id}/unignore")
def unignore_line(line_id: int, user=Depends(require_bank_write)):
    try:
        return bank.unignore_line(line_id, user["id"])
    except bank.BankError as exc:
        raise _bad(exc) from exc


@router.post("/lines/{line_id}/entry", status_code=status.HTTP_201_CREATED)
def entry_from_line(line_id: int, body: LineEntryIn, request: Request, response: Response, user=Depends(require_bank_write)):
    data = body.model_dump()
    idem = _once(request, user, "bank.line_entry", line_id, data)
    try:
        saved = bank.entry_from_line(line_id, data, user["id"], idem)
    except (bank.BankError, idempotency.IdempotencyConflict) as exc:
        raise _bad(exc) from exc
    _finish(idem, response)
    return saved
