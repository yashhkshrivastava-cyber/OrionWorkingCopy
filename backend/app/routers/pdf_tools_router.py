"""The PDF tools: merge, split, rotate, compress, lock and the rest (``app/pdf_tools.py``).

Every call carries its files and returns its result in the same answer. Nothing is stored. The people who may use the tools are the
people who may use the letterhead (``require_letterhead``): the tools sit beside "Put a PDF on the letterhead" and are for the same
work. The work is done in memory, so only a few jobs run at once; a call that cannot get a place within a few seconds is told to try
again rather than left waiting (and rather than slowing everyone else down).
"""

import json
import logging
import threading
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

from app import pdf_tools
from app.dependencies import require_letterhead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pdf-tools", tags=["pdf-tools"])

_JOBS = threading.BoundedSemaphore(3)
_WAIT_SECONDS = 20


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


@contextmanager
def _place() -> Iterator[None]:
    """One of the few places for a job, or a plain 'busy' answer."""
    if not _JOBS.acquire(timeout=_WAIT_SECONDS):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The PDF tools are busy with other people's files. Try again in a minute.",
            headers={"Retry-After": "20"},
        )
    try:
        yield
    finally:
        _JOBS.release()


def _read(uploads: list[UploadFile]) -> list[pdf_tools.Upload]:
    """The uploads as (name, bytes), refused as soon as one is too large or there are too many."""
    if len(uploads) > pdf_tools.MAX_FILES:
        raise _bad_request(f"At most {pdf_tools.MAX_FILES} files at once.")
    files: list[pdf_tools.Upload] = []
    total = 0
    for upload in uploads:
        name = (upload.filename or "file").rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:200] or "file"
        data = upload.file.read(pdf_tools.MAX_FILE_BYTES + 1)
        if len(data) > pdf_tools.MAX_FILE_BYTES:
            raise _bad_request(f"{name} is larger than {pdf_tools.MAX_FILE_BYTES // (1024 * 1024)} MB.")
        total += len(data)
        if total > pdf_tools.MAX_TOTAL_BYTES:
            raise _bad_request(f"The files together are larger than {pdf_tools.MAX_TOTAL_BYTES // (1024 * 1024)} MB.")
        files.append((name, data))
    return files


def _options(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        raise _bad_request("The options were not understood.") from None
    if not isinstance(value, dict):
        raise _bad_request("The options were not understood.")
    return value


def _download_name(name: str) -> str:
    ascii_name = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in name)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


@router.get("/limits")
def limits(_user=Depends(require_letterhead)):
    """What a job may be, so the screen can say so before a file is sent."""
    return {
        "max_file_mb": pdf_tools.MAX_FILE_BYTES // (1024 * 1024),
        "max_total_mb": pdf_tools.MAX_TOTAL_BYTES // (1024 * 1024),
        "max_files": pdf_tools.MAX_FILES,
        "max_pages": pdf_tools.MAX_PAGES,
        "min_password": pdf_tools.MIN_PASSWORD,
        "tools": {tool_id: {"label": tool.label, "kind": tool.kind} for tool_id, tool in pdf_tools.TOOLS.items()},
    }


@router.post("/inspect")
def inspect(files: list[UploadFile] = File(...), options: str = Form(default=""), _user=Depends(require_letterhead)):
    """Pages, size, whether it is locked and its details, for each file: so the screen can show them before anything is done."""
    uploads = _read(files)
    with _place():
        try:
            return {"files": pdf_tools.inspect(uploads, _options(options))}
        except pdf_tools.PdfToolError as exc:
            raise _bad_request(str(exc)) from exc


@router.post("/{tool_id}")
def run_tool(tool_id: str, files: list[UploadFile] = File(...), options: str = Form(default=""), user=Depends(require_letterhead)):
    """Does one tool to the files sent and returns the result as a download (a PDF, a ZIP or a text file)."""
    if tool_id not in pdf_tools.TOOLS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="There is no such tool.")
    uploads = _read(files)
    chosen = _options(options)
    with _place():
        try:
            result = pdf_tools.run(tool_id, uploads, chosen)
        except pdf_tools.PdfToolError as exc:
            raise _bad_request(str(exc)) from exc
    bytes_in = sum(len(data) for _name, data in uploads)
    # Who, which tool and how big: never a file name, a password or what was in the file.
    logger.info("PDF tool %s for user %s: %d file(s), %d bytes in, %d bytes out", tool_id, user["id"], len(uploads), bytes_in, len(result.data))
    summary = {
        "name": result.filename, "pages": result.pages, "files": result.files, "note": result.note,
        "bytes_in": bytes_in, "bytes_out": len(result.data),
    }
    return Response(
        content=result.data,
        media_type=result.media_type,
        headers={
            "Content-Disposition": _download_name(result.filename),
            "X-Orion-Result": json.dumps(summary),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
