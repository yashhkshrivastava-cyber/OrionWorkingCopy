from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import (
    ACCESS_FLAGS,
    ROLE_DEFAULT_DATA_ACCESS,
    ROLE_LABELS,
    ROLES,
    create_user,
    delete_user,
    list_users,
    send_user_password_reset,
    set_user_active,
    update_user_contact,
    update_user_data_access,
    update_user_password,
    update_user_role,
)
from app import sessions, user_overview
from app.dependencies import require_admin
from app.signup import approve_signup, list_signup_requests, reject_signup

router = APIRouter(prefix="/users", tags=["users"])


class AccessFlags(BaseModel):
    """Every access flag, so a new one only has to be added to ACCESS_FLAGS and here. None means "not given"."""

    ods_access: Optional[bool] = None
    ods_write: Optional[bool] = None
    dw_access: Optional[bool] = None
    dw_write: Optional[bool] = None
    tally_access: Optional[bool] = None
    tally_write: Optional[bool] = None
    tally_dw_access: Optional[bool] = None
    tally_dw_write: Optional[bool] = None
    orion_dashboard_access: Optional[bool] = None
    tally_dashboard_access: Optional[bool] = None
    billing_access: Optional[bool] = None
    billing_write: Optional[bool] = None
    etl_access: Optional[bool] = None
    etl_write: Optional[bool] = None
    letterhead_access: Optional[bool] = None
    letterhead_write: Optional[bool] = None
    documents_access: Optional[bool] = None
    documents_write: Optional[bool] = None
    bank_access: Optional[bool] = None
    bank_write: Optional[bool] = None
    tenders_access: Optional[bool] = None
    tenders_write: Optional[bool] = None
    attendance_access: Optional[bool] = None
    attendance_write: Optional[bool] = None
    ai_access: Optional[bool] = None

    def given(self) -> dict[str, Optional[bool]]:
        return {flag: getattr(self, flag) for flag in ACCESS_FLAGS}


class CreateUserRequest(AccessFlags):
    username: str
    display_name: str
    password: str
    role: str = "viewer"
    email: Optional[str] = None
    phone: Optional[str] = None


class UpdateContactRequest(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None


class UpdateRoleRequest(BaseModel):
    role: str


class UpdateActiveRequest(BaseModel):
    is_active: bool


class UpdateDataAccessRequest(AccessFlags):
    pass


class UpdatePasswordRequest(BaseModel):
    password: str


class ApproveSignupRequest(AccessFlags):
    role: str = "viewer"


class RejectSignupRequest(BaseModel):
    reason: Optional[str] = None


def _serialize_ts(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _serialize_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "is_active": user["is_active"],
        "ods_access": user.get("ods_access", False),
        "ods_write": user.get("ods_write", False),
        "dw_access": user.get("dw_access", False),
        "dw_write": user.get("dw_write", False),
        "tally_access": user.get("tally_access", False),
        "tally_write": user.get("tally_write", False),
        "tally_dw_access": user.get("tally_dw_access", False),
        "tally_dw_write": user.get("tally_dw_write", False),
        "orion_dashboard_access": user.get("orion_dashboard_access", True),
        "tally_dashboard_access": user.get("tally_dashboard_access", False),
        "billing_access": user.get("billing_access", False),
        "billing_write": user.get("billing_write", False),
        "etl_access": user.get("etl_access", False),
        "etl_write": user.get("etl_write", False),
        "letterhead_access": user.get("letterhead_access", False),
        "letterhead_write": user.get("letterhead_write", False),
        "documents_access": user.get("documents_access", False),
        "documents_write": user.get("documents_write", False),
        "bank_access": user.get("bank_access", False),
        "bank_write": user.get("bank_write", False),
        "tenders_access": user.get("tenders_access", False),
        "tenders_write": user.get("tenders_write", False),
        "attendance_access": user.get("attendance_access", False),
        "attendance_write": user.get("attendance_write", False),
        "ai_access": user.get("ai_access", True),
        "created_timestamp": _serialize_ts(user.get("created_timestamp")),
        "has_avatar": bool(user.get("avatar_version")) and bool(user.get("avatar_ext")),
        "avatar_version": int(user.get("avatar_version") or 0),
        "avatar_url": (
            f"/api/media/avatars/{user['id']}.{user.get('avatar_ext')}?v={user.get('avatar_version')}"
            if user.get("avatar_version") and user.get("avatar_ext")
            else None
        ),
        "email": user.get("email"),
        "phone": user.get("phone"),
    }


@router.get("")
def get_users(_admin=Depends(require_admin)):
    return [_serialize_user(u) for u in list_users()]


@router.get("/{user_id}/overview")
def user_overview_page(user_id: int, _admin=Depends(require_admin)):
    """One account: what it may do, and when and where it was last used and what work is on it. Administrators only."""
    found = next((u for u in list_users() if u["id"] == user_id), None)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {"user": _serialize_user(found), **user_overview.overview(user_id)}


@router.get("/meta")
def users_meta(_admin=Depends(require_admin)):
    return {
        "roles": [{"id": r, "label": ROLE_LABELS[r]} for r in ROLES],
        "default_data_access": ROLE_DEFAULT_DATA_ACCESS,
    }


@router.get("/signups")
def get_signups(_admin=Depends(require_admin)):
    return list_signup_requests()


@router.post("/signups/{request_id}/approve")
def post_approve_signup(request_id: int, body: ApproveSignupRequest, admin=Depends(require_admin)):
    try:
        return approve_signup(request_id, admin["id"], body.role, **body.given())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/signups/{request_id}/reject")
def post_reject_signup(request_id: int, body: RejectSignupRequest, admin=Depends(require_admin)):
    try:
        reject_signup(request_id, admin["id"], reason=body.reason)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("")
def post_user(body: CreateUserRequest, admin=Depends(require_admin)):
    try:
        create_user(
            body.username,
            body.display_name,
            body.password,
            body.role,
            email=body.email,
            phone=body.phone,
            **body.given(),
        )
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{user_id}/role")
def patch_role(user_id: int, body: UpdateRoleRequest, admin=Depends(require_admin)):
    try:
        update_user_role(user_id, body.role, admin["id"])
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{user_id}/active")
def patch_active(user_id: int, body: UpdateActiveRequest, admin=Depends(require_admin)):
    try:
        set_user_active(user_id, body.is_active, admin["id"])
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{user_id}/data-access")
def patch_data_access(user_id: int, body: UpdateDataAccessRequest, admin=Depends(require_admin)):
    try:
        update_user_data_access(user_id, admin["id"], **body.given())
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{user_id}/password")
def patch_password(user_id: int, body: UpdatePasswordRequest, _admin=Depends(require_admin)):
    try:
        update_user_password(user_id, body.password)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{user_id}/sign-out")
def post_sign_out_everywhere(user_id: int, _admin=Depends(require_admin)):
    """End every session of a person: a lost phone, a shared PC, someone leaving. They can sign in again unless disabled."""
    return {"ok": True, "ended": sessions.revoke_all(user_id, sessions.REASON_ADMIN)}


@router.post("/{user_id}/password-reset")
def post_password_reset(user_id: int, _admin=Depends(require_admin)):
    try:
        email = send_user_password_reset(user_id)
        return {"ok": True, "email": email}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.patch("/{user_id}/contact")
def patch_contact(user_id: int, body: UpdateContactRequest, _admin=Depends(require_admin)):
    try:
        update_user_contact(user_id, email=body.email, phone=body.phone)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{user_id}")
def remove_user(user_id: int, admin=Depends(require_admin)):
    try:
        delete_user(user_id, admin["id"])
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
