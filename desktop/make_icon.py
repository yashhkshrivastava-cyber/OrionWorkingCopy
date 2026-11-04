"""Build Prakash Securities shield icons for Mac (.icns) and Windows (.ico)."""

from __future__ import annotations

import math
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ICONSET = Path(tempfile.mkdtemp(prefix="orion-iconset-")) / "AppIcon.iconset"
DEST = ROOT / "desktop" / "Orion.app" / "Contents" / "Resources" / "AppIcon.icns"
ICO_DEST = ROOT / "desktop" / "Orion.ico"
PROD_ICO_DEST = ROOT / "desktop" / "OrionProd.ico"


def shield_points(size: int, pad: float) -> list[tuple[float, float]]:
    return [
        (size * 0.5, pad),
        (size - pad, size * 0.24),
        (size - pad, size * 0.52),
        (size * 0.5, size - pad),
        (pad, size * 0.52),
        (pad, size * 0.24),
    ]


def star_points(cx: float, cy: float, outer: float, inner: float, n: int = 5) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(n * 2):
        radius = outer if i % 2 == 0 else inner
        angle = math.radians(-90 + i * 180 / n)
        pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return pts


def make_png(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = size * 0.07
    draw.polygon(shield_points(size, pad), fill=(15, 118, 110, 255))
    draw.polygon(
        star_points(size * 0.5, size * 0.48, size * 0.22, size * 0.09),
        fill=(255, 255, 255, 255),
    )
    return img


def write_ico() -> Path:
    ICO_DEST.parent.mkdir(parents=True, exist_ok=True)
    make_png(256).save(
        ICO_DEST,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    return ICO_DEST


def write_prod_ico() -> Path:
    """The same shield with a red PROD badge, so the two shortcuts cannot be confused."""
    img = make_png(256)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (6, 156, 250, 250),
        radius=26,
        fill=(200, 30, 45, 255),
        outline=(255, 255, 255, 255),
        width=7,
    )
    try:
        font = ImageFont.truetype("arialbd.ttf", 74)
    except OSError:
        font = ImageFont.load_default()
    width = draw.textlength("PROD", font=font)
    draw.text(((256 - width) / 2, 164), "PROD", font=font, fill=(255, 255, 255, 255))
    img.save(
        PROD_ICO_DEST,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    return PROD_ICO_DEST


def write_icns() -> Path:
    ICONSET.mkdir(parents=True, exist_ok=True)
    sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for name, size in sizes.items():
        make_png(size).save(ICONSET / name)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["iconutil", "-c", "icns", str(ICONSET), "-o", str(DEST)], check=True)
    return DEST


def main() -> None:
    print(write_ico())
    print(write_prod_ico())
    if sys.platform == "darwin":
        print(write_icns())


if __name__ == "__main__":
    main()
