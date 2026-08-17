"""PWHL studio headshot background removal (cached transparent PNG cutouts)."""

from __future__ import annotations

import hashlib
import sys
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from .disk_cache import cache_path
from .photo_layout import fetch_photo

_CUTOUT_VERSION = "v3-bottom2"
_CUTOUT_DIR = cache_path("pwhl", "cutouts")
_REMBG_MODEL = "u2net_human_seg"


def _vendor_rembg_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".vendor" / "rembg"


def _bootstrap_rembg() -> None:
    vendor = _vendor_rembg_path()
    if vendor.is_dir() and str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))


@lru_cache(maxsize=1)
def _rembg_session() -> Any:
    _bootstrap_rembg()
    from rembg import new_session

    return new_session(_REMBG_MODEL)


def _rembg_remove_bytes(image_bytes: bytes) -> bytes:
    """Run rembg portrait segmentation with edge matting."""
    _bootstrap_rembg()
    from rembg import remove

    return remove(
        image_bytes,
        session=_rembg_session(),
        alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10,
        alpha_matting_erode_size=10,
    )


def _defringe_rgba(rgba: Any) -> Any:
    """Reduce light studio halos on semi-transparent edge pixels."""
    import numpy as np

    arr = np.asarray(rgba, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 4:
        return rgba

    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    fringe = (alpha > 12) & (alpha < 245) & (lum > 185)
    if fringe.any():
        bleed = np.clip((lum - 185) / 70.0, 0.0, 1.0)
        scale = 1.0 - (0.55 * bleed * (1.0 - alpha / 255.0))
        rgb[fringe] *= scale[fringe, None]
        alpha[fringe] *= 1.0 - 0.35 * bleed[fringe]

    out = np.empty_like(arr)
    out[:, :, :3] = np.clip(rgb, 0, 255)
    out[:, :, 3] = np.clip(alpha, 0, 255)
    return out.astype(np.uint8)


def _trim_alpha_bounds(rgba: Any, *, alpha_min: int = 20, bottom_alpha_min: int = 180) -> Any:
    """Crop transparent margins; use a stricter alpha floor on the bottom edge."""
    import numpy as np

    arr = np.asarray(rgba, dtype=np.uint8)
    if arr.ndim != 3 or arr.shape[2] != 4:
        return rgba

    alpha = arr[:, :, 3]
    rows = np.where((alpha > alpha_min).any(axis=1))[0]
    cols = np.where((alpha > alpha_min).any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return arr

    solid_rows = np.where((alpha > bottom_alpha_min).any(axis=1))[0]
    y1 = int(solid_rows[-1]) if solid_rows.size else int(rows[-1])
    return arr[int(rows[0]) : y1 + 1, int(cols[0]) : int(cols[-1]) + 1]


def _cutout_path(source_url: str) -> Path:
    digest = hashlib.sha256(f"{_CUTOUT_VERSION}:{source_url}".encode()).hexdigest()[:24]
    return _CUTOUT_DIR / f"{digest}.png"


def _remove_studio_background(image_bytes: bytes) -> tuple[bytes, int, int]:
    """Return PNG bytes with transparent studio backdrop."""
    import numpy as np
    from PIL import Image

    try:
        raw = _rembg_remove_bytes(image_bytes)
    except ImportError as exc:
        raise RuntimeError(
            "PWHL headshot cutouts require rembg. Install with: "
            "pip install rembg onnxruntime"
        ) from exc

    with Image.open(BytesIO(raw)) as im:
        rgba = _trim_alpha_bounds(_defringe_rgba(np.array(im.convert("RGBA"))))
        out = Image.fromarray(rgba, mode="RGBA")
        buf = BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), out.width, out.height


def ensure_pwhl_cutout(source_url: str) -> dict[str, Any]:
    """Download (if needed), cut out studio background, cache PNG; return path + size."""
    url = str(source_url or "").strip()
    if not url:
        raise ValueError("source_url required")

    out_path = _cutout_path(url)
    if out_path.is_file() and out_path.stat().st_size > 80:
        from PIL import Image

        with Image.open(out_path) as im:
            w, h = im.size
        return {"path": out_path, "width": w, "height": h, "cached": True}

    if url.startswith("file://"):
        data = Path(url[7:]).read_bytes()
    elif Path(url).is_file():
        data = Path(url).read_bytes()
    else:
        data, _ = fetch_photo(url)

    png_bytes, w, h = _remove_studio_background(data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png_bytes)
    return {"path": out_path, "width": w, "height": h, "cached": False}
