import logging
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel

from app.auth import (
    ROLE_LABELS,
    ROLE_PAGES,
    ROLES,
    authenticate,
    can_access_bank,
    can_access_billing,
    can_access_etl,
    can_access_ai,
    can_access_documents,
    can_access_letterhead,
    can_access_ods,
    can_access_dw,
    can_access_page,
    can_access_tally,
    can_access_tally_dw,
    can_access_attendance,
    can_access_tenders,
    can_write_bank,
    can_write_billing,
    can_write_dw,
    can_write_etl,
    can_write_documents,
    can_write_letterhead,
    can_write_ods,
    can_write_tally,
    can_write_attendance,
    can_write_tenders,
    can_access_orion_dashboard,
    can_access_tally_dashboard,
    can_write_tally_dw,
    public_user,
    complete_password_reset,
    password_reset_token_valid,
    request_password_reset,
    update_own_profile,
)
from app import sessions, throttle
from app.security_headers import cookie_secure
from app.avatars import avatar_response, remove_avatar, save_avatar
from app.config import SESSION_COOKIE_NAME, session_ttl_seconds
from app.dependencies import get_current_user, get_optional_user
from app.signup import count_pending_signups, request_signup

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    username: str
    password: str


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = None
    preferred_theme: Optional[str] = None
    appearance: Optional[dict] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    username: str
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    display_name: str
    password: str
    email: str
    phone: Optional[str] = None


def _serialize_user(user: dict) -> dict:
    pages = [p for p in ("home", "dashboard", "data", "utility", "letterhead", "documents", "bank", "tenders", "attendance", "etl", "sql", "admin") if can_access_page(user, p)]
    payload = {
        **public_user(user),
        "pages": pages,
        "can_ods": can_access_ods(user),
        "can_ods_write": can_write_ods(user),
        "can_dw": can_access_dw(user),
        "can_dw_write": can_write_dw(user),
        "can_tally": can_access_tally(user),
        "can_tally_write": can_write_tally(user),
        "can_tally_dw": can_access_tally_dw(user),
        "can_tally_dw_write": can_write_tally_dw(user),
        "can_billing": can_access_billing(user),
        "can_billing_write": can_write_billing(user),
        "can_etl": can_access_etl(user),
        "can_etl_write": can_write_etl(user),
        "can_letterhead": can_access_letterhead(user),
        "can_letterhead_write": can_write_letterhead(user),
        "can_documents": can_access_documents(user),
        "can_documents_write": can_write_documents(user),
        "can_bank": can_access_bank(user),
        "can_bank_write": can_write_bank(user),
        "can_tenders": can_access_tenders(user),
        "can_tenders_write": can_write_tenders(user),
        "can_attendance": can_access_attendance(user),
        "can_attendance_write": can_write_attendance(user),
        "can_ai": can_access_ai(user),
        "can_orion_dashboard": can_access_orion_dashboard(user),
        "can_tally_dashboard": can_access_tally_dashboard(user),
    }
    if user.get("role") == "admin":
        payload["pending_signups"] = count_pending_signups()
    return payload


def _limited(kind: str, username: Optional[str], request: Request) -> str:
    """Refuse (429, with how long to wait) when this kind of attempt is going too often. Returns the caller's address."""
    ip = throttle.client_address(request)
    try:
        throttle.check(kind, username, ip)
    except throttle.TooManyAttempts as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=exc.message, headers={"Retry-After": str(exc.retry_after)}
        ) from exc
    return ip


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response):
    ip = _limited("login", body.username, request)  # before the password is looked at, so a block cannot be used to test one
    user = authenticate(body.username, body.password)
    throttle.record("login", body.username, ip, succeeded=user is not None)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = sessions.create_session(user["id"], ip=ip, user_agent=request.headers.get("user-agent"))
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),  # not sent over plain HTTP, so it cannot be read off the network (security_headers.py)
        path="/",
        max_age=session_ttl_seconds(),
    )
    return _serialize_user(user)


@router.post("/logout")
def logout(request: Request, response: Response, orion_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME)):
    # Ends the session on the server, not just the browser's copy of the cookie. Open to anyone: a cookie that is not ours
    # or is already over simply has nothing to end.
    sessions.revoke_token(orion_session)
    # The same attributes it was set with, or some browsers keep the cookie they were told to delete.
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=cookie_secure(request))
    return {"ok": True}


@router.get("/sessions")
def my_sessions(user=Depends(get_current_user), orion_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME)):
    """The places this person is signed in, newest activity first, with this one marked."""
    return {"sessions": sessions.list_for_user(user["id"], sessions.current_ref(orion_session))}


@router.post("/sessions/revoke-others")
def sign_out_other_devices(user=Depends(get_current_user), orion_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME)):
    ended = sessions.revoke_all(user["id"], sessions.REASON_OTHERS, keep_ref=sessions.current_ref(orion_session))
    return {"ok": True, "ended": ended}


@router.delete("/sessions/{session_id}")
def end_session(session_id: int, user=Depends(get_current_user)):
    if not sessions.revoke_one(user["id"], session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That session is not signed in any more.")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(get_current_user)):
    return _serialize_user(user)


@router.post("/register")
def register(body: RegisterRequest, request: Request):
    ip = _limited("register", None, request)
    throttle.record("register", None, ip, succeeded=True)  # every request counts: asking is the abuse, not being refused
    try:
        request_signup(
            body.username,
            body.display_name,
            body.password,
            body.email,
            phone=body.phone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest, request: Request):
    ip = _limited("forgot", body.username, request)
    throttle.record("forgot", body.username, ip, succeeded=True)  # each request sends an email, so each one counts
    try:
        request_password_reset(body.username, body.email)
    except Exception:
        log.exception("Password reset email could not be sent")
    return {"ok": True}


@router.get("/reset-password")
def reset_password_status(request: Request, token: str = ""):
    ip = _limited("reset", None, request)
    valid = password_reset_token_valid(token)
    if not valid:
        throttle.record("reset", None, ip, succeeded=False)  # a wrong token is a guess at the secret
    return {"valid": valid}


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, request: Request):
    ip = _limited("reset", None, request)
    try:
        complete_password_reset(body.token, body.password)
    except ValueError as exc:
        throttle.record("reset", None, ip, succeeded=False)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    throttle.record("reset", None, ip, succeeded=True)
    return {"ok": True}


@router.patch("/me")
def patch_me(body: UpdateProfileRequest, user=Depends(get_current_user)):
    try:
        updated = update_own_profile(
            user["id"],
            display_name=body.display_name,
            preferred_theme=body.preferred_theme,
            appearance=body.appearance,
            email=body.email,
            phone=body.phone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _serialize_user(updated)


@router.post("/me/avatar")
def post_avatar(user=Depends(get_current_user), file: UploadFile = File(...)):
    updated = save_avatar(user["id"], file)
    return _serialize_user(updated)


@router.delete("/me/avatar")
def delete_avatar(user=Depends(get_current_user)):
    updated = remove_avatar(user["id"])
    return _serialize_user(updated)


@router.get("/avatar/{user_id}")
def get_avatar(user_id: int, _user=Depends(get_current_user)):
    return avatar_response(user_id)


@router.get("/config")
def auth_config(user=Depends(get_optional_user)):
    return {
        "roles": [{"id": r, "label": ROLE_LABELS[r]} for r in ROLES],
        "role_pages": {k: list(v) for k, v in ROLE_PAGES.items()},
        "authenticated": user is not None,
        "user": _serialize_user(user) if user else None,
    }
