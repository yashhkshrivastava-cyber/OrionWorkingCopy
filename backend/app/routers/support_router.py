import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.chat_media import prepare_upload
from app.config import support_dir
from app.dependencies import get_current_user
from app.mail import send_support_request

router = APIRouter(prefix="/support", tags=["support"])

MAX_FILES = 5
MAX_SUBJECT = 160
MAX_DETAILS = 8000


def _save_copy(user: dict, subject: str, details: str, prepared: list[dict]) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = support_dir() / f"{stamp}-{user['id']}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "request.json").write_text(
        json.dumps(
            {
                "user_id": user["id"],
                "username": user.get("username"),
                "display_name": user.get("display_name"),
                "email": user.get("email"),
                "phone": user.get("phone"),
                "role": user.get("role"),
                "subject": subject,
                "details": details,
                "attachments": [item["original_name"] for item in prepared],
                "created_at": stamp,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for index, item in enumerate(prepared, start=1):
        name = f"{index:02d}-{item['original_name']}"
        (folder / name).write_bytes(item["data"])


@router.post("/requests")
async def create_request(
    subject: str = Form(...),
    details: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    user=Depends(get_current_user),
):
    subject = (subject or "").strip()
    details = (details or "").strip()
    if not subject:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a short subject.")
    if len(subject) > MAX_SUBJECT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Subject is too long.")
    if not details:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Describe the issue.")
    if len(details) > MAX_DETAILS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Description is too long.")

    uploads = [item for item in files if item and item.filename]
    if len(uploads) > MAX_FILES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Attach up to 5 files.")

    prepared = [prepare_upload(item) for item in uploads]
    _save_copy(user, subject, details, prepared)
    attachments = [
        (item["original_name"], item["data"], item["content_type"]) for item in prepared
    ]
    try:
        send_support_request(user, subject, details, attachments)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {"ok": True}