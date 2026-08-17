"""Lightweight on-disk caches for fast repeat card generation."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

CACHE_ROOT = Path.home() / ".cache" / "player-cards"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_path(*parts: str) -> Path:
    path = CACHE_ROOT.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path, *, ttl_seconds: float | None = None) -> Any | None:
    if not path.is_file():
        return None
    if ttl_seconds is not None:
        age = time.time() - path.stat().st_mtime
        if age > ttl_seconds:
            return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, default=str), encoding="utf-8")


def pbp_files_fingerprint(files: list[Path]) -> str:
    if not files:
        return "empty"
    mtimes = [p.stat().st_mtime for p in files if p.is_file()]
    if not mtimes:
        return "empty"
    return f"{len(files)}:{max(mtimes):.0f}"


def player_cache_key(player_id: int | None, player_name: str) -> str:
    if player_id:
        return str(player_id)
    slug = hashlib.sha1(player_name.strip().lower().encode()).hexdigest()[:12]
    return f"name-{slug}"


def photo_data_url(url: str) -> str | None:
    """Return cached data URL for a remote photo, or None."""
    if not url or url.startswith("data:"):
        return url or None
    hit = load_json(_cache_path_for_url(url))
    if isinstance(hit, dict) and hit.get("data_url"):
        return str(hit["data_url"])
    return None


def photo_dimensions(url: str) -> tuple[int | None, int | None]:
    hit = load_json(_cache_path_for_url(url))
    if isinstance(hit, dict):
        w, h = hit.get("width"), hit.get("height")
        try:
            return (int(w) if w else None, int(h) if h else None)
        except (TypeError, ValueError):
            pass
    return None, None


def _cache_path_for_url(url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:24]
    return cache_path("photos", f"{digest}.json")


def store_photo_data_url(
    url: str,
    data_url: str,
    *,
    width: int | None = None,
    height: int | None = None,
) -> None:
    payload: dict[str, Any] = {"url": url, "data_url": data_url}
    if width and height:
        payload["width"] = width
        payload["height"] = height
    save_json(_cache_path_for_url(url), payload)
