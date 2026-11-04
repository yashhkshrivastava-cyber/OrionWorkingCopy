from io import BytesIO
from pathlib import Path
import subprocess
import tempfile
from typing import Optional

from fastapi import HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from app.auth import clear_user_avatar, fetch_user_by_id, set_user_avatar
from app.config import avatar_dir

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

MAX_BYTES = 12 * 1024 * 1024
OUT_SIZE = 512
OUT_EXT = "jpg"
OUT_MEDIA = "image/jpeg"


def avatar_path(user_id: int, ext: str) -> Path:
    return avatar_dir() / f"{user_id}.{ext}"


def existing_avatar_path(user: dict) -> Optional[Path]:
    ext = user.get("avatar_ext")
    version = int(user.get("avatar_version") or 0)
    if not ext or version <= 0:
        return None
    path = avatar_path(user["id"], ext)
    return path if path.is_file() else None


def _looks_like_heif(data: bytes) -> bool:
    return len(data) > 12 and data[4:8] == b"ftyp" and (
        data[8:12] in {b"heic", b"heif", b"mif1", b"msf1", b"heix"}
    )


def _sips_to_jpeg(data: bytes) -> Optional[bytes]:
    try:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "in.heic"
            dest = Path(folder) / "out.jpg"
            source.write_bytes(data)
            result = subprocess.run(
                ["sips", "-s", "format", "jpeg", str(source), "--out", str(dest)],
                check=False,
                capture_output=True,
            )
            if result.returncode == 0 and dest.is_file():
                return dest.read_bytes()
    except OSError:
        return None
    return None


def _encode_jpeg(image: Image.Image, max_size: int = OUT_SIZE) -> bytes:
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGB")
    image.thumbnail((max_size, max_size))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85, optimize=True)
    return buffer.getvalue()


def encode_image(data: bytes, max_size: int = OUT_SIZE) -> bytes:
    try:
        return _encode_jpeg(Image.open(BytesIO(data)), max_size)
    except (UnidentifiedImageError, OSError, ValueError):
        converted = _sips_to_jpeg(data) if _looks_like_heif(data) else None
        if converted:
            return _encode_jpeg(Image.open(BytesIO(converted)), max_size)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Could not read that photo. Try another image, or a JPEG/PNG.",
        ) from None


def _to_jpeg(data: bytes) -> bytes:
    return encode_image(data, OUT_SIZE)


def save_avatar(user_id: int, upload: UploadFile) -> dict:
    data = upload.file.read(MAX_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a photo to upload.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Photo must be 12 MB or smaller.")

    jpeg = _to_jpeg(data)
    current = fetch_user_by_id(user_id)
    previous = existing_avatar_path(current) if current else None
    dest = avatar_path(user_id, OUT_EXT)
    dest.write_bytes(jpeg)
    if previous and previous != dest:
        previous.unlink(missing_ok=True)
    return set_user_avatar(user_id, OUT_EXT)


def remove_avatar(user_id: int) -> dict:
    current = fetch_user_by_id(user_id)
    path = existing_avatar_path(current) if current else None
    if path:
        path.unlink(missing_ok=True)
    return clear_user_avatar(user_id)


def avatar_response(user_id: int) -> FileResponse:
    user = fetch_user_by_id(user_id)
    path = existing_avatar_path(user) if user else None
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No profile photo")
    return FileResponse(
        path,
        media_type=OUT_MEDIA,
        headers={"Cache-Control": "private, max-age=60"},
    )
