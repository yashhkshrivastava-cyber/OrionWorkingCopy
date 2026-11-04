from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field

from app import letterhead, letterhead_pdf
from app.ai import features as ai_features
from app.dependencies import require_admin, require_letterhead, require_letterhead_design, require_letterhead_write

router = APIRouter(prefix="/letterhead", tags=["letterhead"])


class LetterIn(BaseModel):
    title: str
    ref_no: Optional[str] = None
    letter_date: date
    body_html: str = ""
    font: str = "sans"
    font_size: int = 11
    show_header: bool = True
    show_footer: bool = True


class LetterAiIn(BaseModel):
    mode: str = Field(max_length=10)
    brief: str = Field(default="", max_length=ai_features.MAX_BRIEF)
    text: str = Field(default="", max_length=ai_features.MAX_LETTER_TEXT + 2000)
    action: str = Field(default="", max_length=12)
    tone: str = Field(default="professional", max_length=20)
    language: str = Field(default="", max_length=40)
    allow_cloud_once: bool = False


def _bad_request(exc: letterhead.LetterheadError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _read(upload: UploadFile, limit: int, too_big: str) -> bytes:
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=too_big)
    return data


def _safe_name(name: str | None, fallback: str) -> str:
    stem = (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = "".join(ch for ch in stem if ch.isalnum() or ch in " -_().").strip()[:80]
    return stem or fallback


# --------------------------------------------------------------------------- the letterhead itself


@router.get("/design")
def get_design(_user=Depends(require_letterhead_design)):
    return letterhead.public_design()


@router.get("/design/{part}")
def get_design_image(part: str, _user=Depends(require_letterhead_design)):
    try:
        data, mime = letterhead.design_image(part)
    except letterhead.LetterheadError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    # The address carries the design's version, so a changed image has a new address.
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})


@router.put("/design")
def put_design(body: dict[str, Any], user=Depends(require_admin)):
    return letterhead.save_settings(body, user["id"])


@router.post("/design/{part}")
def post_design_image(part: str, file: UploadFile = File(...), user=Depends(require_admin)):
    data = _read(file, letterhead.MAX_IMAGE_BYTES, "The image is larger than 8 MB. Save it smaller and try again.")
    try:
        return letterhead.save_image(part, data, user["id"])
    except letterhead.LetterheadError as exc:
        raise _bad_request(exc) from exc


@router.delete("/design/{part}")
def delete_design_image(part: str, user=Depends(require_admin)):
    try:
        return letterhead.reset_image(part, user["id"])
    except letterhead.LetterheadError as exc:
        raise _bad_request(exc) from exc


# --------------------------------------------------------------------------- PDFs


@router.get("/blank.pdf")
def blank(pages: int = Query(default=1, ge=1, le=50), _user=Depends(require_letterhead)):
    data = letterhead_pdf.blank_pdf(letterhead.load_design(), pages)
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="Letterhead.pdf"'})


@router.post("/stamp")
def stamp(
    file: UploadFile = File(...),
    fit: bool = Form(default=True),
    first_page_only: bool = Form(default=False),
    header: bool = Form(default=True),
    footer: bool = Form(default=True),
    _user=Depends(require_letterhead),
):
    data = _read(file, letterhead_pdf.MAX_PDF_BYTES, "The PDF is larger than 25 MB.")
    try:
        stamped, pages = letterhead_pdf.stamp_pdf(data, letterhead.load_design(), fit=fit, first_page_only=first_page_only,
                                                  header=header, footer=footer)
    except letterhead.LetterheadError as exc:
        raise _bad_request(exc) from exc
    name = f"{_safe_name(file.filename, 'Document')} on letterhead.pdf"
    return Response(content=stamped, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"', "X-Orion-Pages": str(pages)})


# --------------------------------------------------------------------------- letters


@router.post("/ai")
def letter_ai(body: LetterAiIn, user=Depends(require_letterhead_write)):
    """Draft a letter from a few points, or improve the text of one. The answer is text for the editor; nothing is saved."""
    result = ai_features.write_letter(
        user, mode=body.mode, brief=body.brief, text=body.text, action=body.action, tone=body.tone, language=body.language,
        allow_cloud_once=body.allow_cloud_once,
    )
    if result.get("status") == "invalid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["message"])
    return result


@router.get("/letters")
def letters(q: Optional[str] = None, _user=Depends(require_letterhead)):
    return {"letters": letterhead.list_letters(q)}


@router.get("/letters/{letter_id}")
def letter(letter_id: int, _user=Depends(require_letterhead)):
    found = letterhead.get_letter(letter_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That letter does not exist.")
    return found


@router.post("/letters", status_code=status.HTTP_201_CREATED)
def create_letter(body: LetterIn, user=Depends(require_letterhead_write)):
    try:
        return letterhead.create_letter(body.model_dump(), user["id"])
    except letterhead.LetterheadError as exc:
        raise _bad_request(exc) from exc


@router.put("/letters/{letter_id}")
def update_letter(letter_id: int, body: LetterIn, user=Depends(require_letterhead_write)):
    try:
        saved = letterhead.update_letter(letter_id, body.model_dump(), user["id"])
    except letterhead.LetterheadError as exc:
        raise _bad_request(exc) from exc
    if not saved:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That letter does not exist.")
    return saved


@router.delete("/letters/{letter_id}")
def delete_letter(letter_id: int, _user=Depends(require_letterhead_write)):
    if not letterhead.delete_letter(letter_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That letter does not exist.")
    return {"ok": True}
