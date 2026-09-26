"""Image file input/output.

Uses Pillow rather than ``cv2.imread``/``cv2.imwrite`` because OpenCV cannot
open paths containing non-ASCII characters on Windows and ignores EXIF
orientation for many camera files.  Pillow handles both, can decode JPEGs at
reduced size for fast thumbnails, and lets us carry the original EXIF block
through to the export.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 250_000_000  # allow very large scans, still guard bombs

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp")
EXPORT_FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".tif": "TIFF",
    ".tiff": "TIFF",
}


@dataclass
class ImageInfo:
    path: str
    name: str
    size_bytes: int
    mtime: float
    width: int = 0
    height: int = 0


def list_images(folder: str) -> List[ImageInfo]:
    """Supported images in ``folder`` sorted naturally by name."""
    items: List[ImageInfo] = []
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if not entry.is_file() or entry.name.startswith("."):
                    continue
                if not entry.name.lower().endswith(SUPPORTED_EXTENSIONS):
                    continue
                try:
                    st = entry.stat()
                except OSError:
                    continue
                items.append(ImageInfo(entry.path, entry.name, st.st_size, st.st_mtime))
    except OSError:
        return []
    items.sort(key=lambda i: _natural_key(i.name))
    return items


def _natural_key(name: str):
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _to_bgr(img: Image.Image) -> np.ndarray:
    if img.mode in ("I;16", "I;16B", "I;16L", "I"):
        arr = np.asarray(img, dtype=np.float32)
        peak = 65535.0 if arr.max() > 255 else 255.0
        arr = np.clip(arr / peak * 255.0, 0, 255).astype(np.uint8)
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
        img = Image.alpha_composite(bg, rgba)
    rgb = np.asarray(img.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def load_image(path: str) -> Tuple[np.ndarray, Optional[bytes]]:
    """Load a full-resolution BGR image, upright, plus its EXIF bytes."""
    with Image.open(path) as img:
        # Transpose first: getexif() is cached, so cleaning it beforehand
        # would erase the orientation exif_transpose needs.
        upright = ImageOps.exif_transpose(img)
        return _to_bgr(upright), _clean_exif(upright)


def load_thumbnail(path: str, max_edge: int) -> Tuple[np.ndarray, int, int]:
    """Fast upright thumbnail. Returns (bgr, full_width, full_height)."""
    with Image.open(path) as img:
        full_w, full_h = img.size
        if img.format == "JPEG":
            img.draft("RGB", (max_edge * 2, max_edge * 2))
        img = ImageOps.exif_transpose(img)
        if _orientation_swaps(img, full_w, full_h):
            full_w, full_h = full_h, full_w
        img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        return _to_bgr(img), full_w, full_h


def _orientation_swaps(img: Image.Image, w: int, h: int) -> bool:
    iw, ih = img.size
    return (w > h) != (iw > ih) and w != h


def _clean_exif(img: Image.Image) -> Optional[bytes]:
    try:
        exif = img.getexif()
        if not exif:
            return None
        exif[0x0112] = 1  # orientation: pixels are written upright
        return exif.tobytes()
    except Exception:
        return None


def save_image(path: str, bgr: np.ndarray, exif: Optional[bytes] = None, quality: int = 95) -> None:
    ext = os.path.splitext(path)[1].lower()
    fmt = EXPORT_FORMATS.get(ext)
    if fmt is None:
        raise ValueError(f"Unsupported export format: {ext or 'no extension'}")
    img = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    kwargs = {}
    if exif:
        kwargs["exif"] = exif
    if fmt == "JPEG":
        kwargs.update(quality=quality, subsampling=0, optimize=True)
    elif fmt == "PNG":
        kwargs.update(compress_level=6)
    elif fmt == "TIFF":
        kwargs.update(compression="tiff_lzw")
    tmp = path + ".part"
    try:
        img.save(tmp, format=fmt, **kwargs)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"
