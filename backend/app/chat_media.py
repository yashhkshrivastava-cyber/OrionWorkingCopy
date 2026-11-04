from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.avatars import encode_image
from app.config import chat_media_dir

MAX_BYTES = 12 * 1024 * 1024
IMAGE_MAX = 1600
IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp"}
VIDEO_EXTS = {"mp4", "mov", "webm", "m4v"}
# A voice note, as the browser records it (Chrome and Firefox: webm or ogg with Opus; Safari: mp4 audio).
AUDIO_EXTS = {"webm", "ogg", "m4a", "mp4", "mp3", "wav", "aac"}
AUDIO_TYPES = {"webm": "audio/webm", "ogg": "audio/ogg", "m4a": "audio/mp4", "mp4": "audio/mp4", "mp3": "audio/mpeg", "wav": "audio/wav", "aac": "audio/aac"}
FILE_EXTS = {"pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "zip", "ppt", "pptx"}
CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "png": "image/png",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "m4v": "video/mp4",
    "pdf": "application/pdf",
}


def _safe_name(name: str) -> str:
    # No folder parts, no control characters (a newline in a name must never reach a header), no quote marks.
    kept = "".join(ch for ch in Path(name or "file").name if ch.isprintable()).replace('"', "").replace("\\", "")
    return (kept.strip() or "file")[:180]


def _ext(name: str) -> str:
    return Path(name).suffix.lower().lstrip(".")


def _is_gif(data: bytes) -> bool:
    return data[:6] in {b"GIF87a", b"GIF89a"}


def prepare_upload(upload: UploadFile) -> dict:
    data = upload.file.read(MAX_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a file to attach.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Attachment must be 12 MB or smaller.")

    original = _safe_name(upload.filename or "file")
    ext = _ext(original)
    guessed = (upload.content_type or "").split(";")[0].strip().lower()

    if _is_gif(data):
        return {
            "kind": "image",
            "ext": "gif",
            "original_name": original if original.lower().endswith(".gif") else f"{Path(original).stem}.gif",
            "content_type": "image/gif",
            "data": data,
        }

    looks_image = ext in IMAGE_EXTS or guessed.startswith("image/")
    if looks_image:
        jpeg = encode_image(data, IMAGE_MAX)
        stem = Path(original).stem or "photo"
        return {
            "kind": "image",
            "ext": "jpg",
            "original_name": f"{stem}.jpg",
            "content_type": "image/jpeg",
            "data": jpeg,
        }

    # Audio is recognised by what the browser says it is (a voice note is a webm or mp4 like a video, but "audio/..."), never by the name alone.
    if guessed.startswith("audio/"):
        if ext not in AUDIO_EXTS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That audio type is not supported.")
        return {
            "kind": "audio",
            "ext": ext,
            "original_name": original,
            "content_type": AUDIO_TYPES[ext],
            "data": data,
        }

    if ext in VIDEO_EXTS or guessed.startswith("video/"):
        if ext not in VIDEO_EXTS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That video type is not supported.")
        return {
            "kind": "video",
            "ext": ext,
            "original_name": original,
            "content_type": CONTENT_TYPES.get(ext, guessed or "video/mp4"),
            "data": data,
        }

    if ext in FILE_EXTS:
        return {
            "kind": "file",
            "ext": ext,
            "original_name": original,
            "content_type": CONTENT_TYPES.get(ext, guessed or "application/octet-stream"),
            "data": data,
        }

    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "Attach a photo, video, PDF, Office file, text, or zip.",
    )


def media_path(message_id: int, ext: str) -> Path:
    return chat_media_dir() / f"{int(message_id)}.{ext}"


def write_prepared(message_id: int, prepared: dict) -> Path:
    dest = media_path(message_id, prepared["ext"])
    dest.write_bytes(prepared["data"])
    return dest


def unlink_media(message_id: int, ext: str):
    media_path(message_id, ext).unlink(missing_ok=True)


def media_response(path: Path, content_type: str, filename: str, inline: bool) -> FileResponse:
    disposition = "inline" if inline else "attachment"
    safe = filename.replace('"', "")
    return FileResponse(
        path,
        media_type=content_type or "application/octet-stream",
        headers={
            "Cache-Control": "private, max-age=3600",
            # A file is shown as the type it was checked to be and never guessed at, so a text file cannot be run as a page.
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'{disposition}; filename="{safe}"',
        },
    )
