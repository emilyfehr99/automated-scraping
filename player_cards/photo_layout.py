"""Aspect-aware photo framing for player card renders."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

from .disk_cache import cache_path, load_json, save_json


def _image_size(data: bytes) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(BytesIO(data)) as im:
            return im.size
    except Exception:
        return None


def _cache_path(url: str) -> Any:
    import hashlib

    digest = hashlib.sha256(url.encode()).hexdigest()[:24]
    return cache_path("photos", f"{digest}.json")


def load_photo_cache(url: str) -> dict[str, Any] | None:
    if not url or url.startswith("data:"):
        return None
    hit = load_json(_cache_path(url))
    return hit if isinstance(hit, dict) else None


def photo_aspect_class(width: int | None, height: int | None) -> str:
    if not width or not height or width <= 0 or height <= 0:
        return "photo--portrait"
    ratio = width / height
    if ratio < 0.92:
        return "photo--portrait"
    if ratio <= 1.08:
        return "photo--square"
    return "photo--landscape"


def photo_object_position(width: int | None, height: int | None, *, kind: str = "mug") -> str:
    """Crop anchor tuned per aspect ratio so faces stay centered in the column."""
    if not width or not height:
        return "center 12%" if kind == "mug" else "center 30%"

    ratio = width / height
    if ratio < 0.92:
        return "center 6%"
    if ratio <= 1.08:
        return "center 10%"
    return "center 32%"


def photo_frame(width: int | None, height: int | None, *, kind: str = "mug") -> tuple[str, str]:
    return photo_aspect_class(width, height), photo_object_position(width, height, kind=kind)


def fetch_photo(url: str) -> tuple[bytes, str]:
    resp = httpx.get(url, timeout=20.0, follow_redirects=True, headers={"User-Agent": "PlayerCards/1.0"})
    resp.raise_for_status()
    mime = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
    if not mime.startswith("image/"):
        mime = "image/jpeg"
    return resp.content, mime


def embed_photo(url: str) -> tuple[str, int | None, int | None]:
    """Return (data URL or original URL, width, height)."""
    if not url:
        return "", None, None
    if url.startswith("data:"):
        return url, None, None

    local_path: Path | None = None
    if url.startswith("file://"):
        local_path = Path(url[7:])
    else:
        candidate = Path(url)
        if candidate.is_file():
            local_path = candidate

    if local_path is not None and local_path.is_file():
        try:
            data = local_path.read_bytes()
            if len(data) < 500:
                return url, None, None
            w, h = _image_size(data)
            mime = "image/png" if local_path.suffix.lower() == ".png" else "image/jpeg"
            encoded = base64.b64encode(data).decode("ascii")
            return f"data:{mime};base64,{encoded}", w, h
        except Exception:
            return url, None, None

    cached = load_photo_cache(url)
    if cached and cached.get("data_url"):
        return (
            str(cached["data_url"]),
            cached.get("width"),
            cached.get("height"),
        )

    try:
        data, mime = fetch_photo(url)
        if len(data) < 500:
            return url, None, None
        w, h = _image_size(data)
        encoded = base64.b64encode(data).decode("ascii")
        data_url = f"data:{mime};base64,{encoded}"
        save_json(
            _cache_path(url),
            {"url": url, "data_url": data_url, "width": w, "height": h},
        )
        return data_url, w, h
    except Exception:
        return url, None, None
