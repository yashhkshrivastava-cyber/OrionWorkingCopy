from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status

from app.auth import (
    can_access_ai,
    can_access_attendance,
    can_access_billing,
    can_access_bank,
    can_access_documents,
    can_access_dw,
    can_access_etl,
    can_access_letterhead,
    can_access_ods,
    can_access_orion_dashboard,
    can_access_tally_dashboard,
    can_access_tally,
    can_access_tally_dw,
    can_access_tenders,
    can_write_attendance,
    can_write_billing,
    can_write_bank,
    can_write_documents,
    can_write_dw,
    can_write_etl,
    can_write_letterhead,
    can_write_ods,
    can_write_tally,
    can_write_tally_dw,
    can_write_tenders,
    is_admin,
)
from app import sessions
from app.observability import bind_user
from app.config import SESSION_COOKIE_NAME


def get_current_user(
    orion_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    if not orion_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    # The cookie must be ours AND the session must still be live on the server AND the person still active: signing out,
    # a password change and disabling the account all end a session even though the browser still holds its cookie.
    user = sessions.user_for_token(orion_session)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    bind_user(user["id"])  # so the log line for this request says who it was
    return user


def get_optional_user(
    orion_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    if not orion_session:
        return None
    return sessions.user_for_token(orion_session)


def require_admin(user=Depends(get_current_user)):
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def require_ods(user=Depends(get_current_user)):
    if not can_access_ods(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ODS access required")
    return user


def require_ods_write(user=Depends(get_current_user)):
    if not can_write_ods(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can review operational data, but you do not have permission to change it.",
        )
    return user


def require_dw(user=Depends(get_current_user)):
    if not can_access_dw(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="DW access required")
    return user


def require_dw_write(user=Depends(get_current_user)):
    if not can_write_dw(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can browse the warehouse, but you do not have permission to run loads.",
        )
    return user


def require_tally(user=Depends(get_current_user)):
    if not can_access_tally(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tally ODS access required")
    return user


def require_tally_write(user=Depends(get_current_user)):
    if not can_write_tally(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can browse Tally ODS, but you do not have permission to run loads.",
        )
    return user


def require_tally_dw(user=Depends(get_current_user)):
    if not can_access_tally_dw(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tally warehouse access required")
    return user


def require_tally_dw_write(user=Depends(get_current_user)):
    if not can_write_tally_dw(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can browse the Tally warehouse, but you do not have permission to run loads.",
        )
    return user


def require_billing(user=Depends(get_current_user)):
    if not can_access_billing(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Billing access required")
    return user


def require_billing_write(user=Depends(get_current_user)):
    if not can_write_billing(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can view bills, but you do not have permission to change them.",
        )
    return user


def require_etl(user=Depends(get_current_user)):
    if not can_access_etl(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ETL access required")
    return user


def require_etl_write(user=Depends(get_current_user)):
    if not can_write_etl(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can see the pipelines, but you do not have permission to run them.",
        )
    return user


def require_letterhead(user=Depends(get_current_user)):
    if not can_access_letterhead(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Letterhead access required")
    return user


def require_letterhead_write(user=Depends(get_current_user)):
    if not can_write_letterhead(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can read and print letters, but you do not have permission to change them.",
        )
    return user


def require_ai(user=Depends(get_current_user)):
    if not can_access_ai(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The AI assistant is not turned on for your account.")
    return user


def require_documents(user=Depends(get_current_user)):
    if not can_access_documents(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Documents access required")
    return user


def require_bank(user=Depends(get_current_user)):
    if not can_access_bank(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bank access required")
    return user


def require_bank_write(user=Depends(get_current_user)):
    if not can_write_bank(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can see the bank, but you do not have permission to change it.",
        )
    return user


def require_tenders(user=Depends(get_current_user)):
    if not can_access_tenders(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenders access required")
    return user


def require_attendance(user=Depends(get_current_user)):
    if not can_access_attendance(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Attendance access required")
    return user


def require_attendance_write(user=Depends(get_current_user)):
    if not can_write_attendance(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can see the attendance registers, but you do not have permission to change them.",
        )
    return user


def require_tenders_write(user=Depends(get_current_user)):
    if not can_write_tenders(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can see the tenders found, but you do not have permission to change the searches.",
        )
    return user


def require_documents_write(user=Depends(get_current_user)):
    if not can_write_documents(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can read documents, but you do not have permission to change them.",
        )
    return user


def require_letterhead_design(user=Depends(get_current_user)):
    """Seeing the letterhead itself: needed to write a letter, and to print a bill on it."""
    if not (can_access_letterhead(user) or can_access_billing(user)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Letterhead or Billing access required")
    return user


def require_orion_dashboard(user=Depends(get_current_user)):
    if not can_access_orion_dashboard(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Orion dashboard access required",
        )
    return user


def require_tally_dashboard(user=Depends(get_current_user)):
    if not can_access_tally_dashboard(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tally dashboard access required",
        )
    return user
