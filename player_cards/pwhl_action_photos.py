"""PWHL in-game action photos (OSC press images + local overrides)."""

from __future__ import annotations

import re
import statistics
import unicodedata
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

from .disk_cache import cache_path, load_json, save_json
from .photo_layout import fetch_photo

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[misc, assignment]

OSC_PICTURE_BASE = "https://www.oursportscentral.com/graphics/pictures/"
INDEX_TTL = 86_400 * 7

_LOCAL_ACTION_ROOTS = (
    Path.home() / "CascadeProjects" / "pwhl-analytics" / "web" / "public" / "photos" / "action",
    Path.home() / "Desktop" / "pwhl-analytics" / "web" / "public" / "photos" / "action",
    Path(__file__).resolve().parent / "data" / "pwhl_action",
)

_OPTIONAL_SEED = Path(__file__).resolve().parent / "data" / "pwhl_action_index.json"
_PLAYER_SEED_PATH = Path(__file__).resolve().parent / "data" / "pwhl_player_action_seeds.json"


def _player_seed_index() -> dict[str, Any]:
    raw = load_json(_PLAYER_SEED_PATH) if _PLAYER_SEED_PATH.is_file() else {}
    if not isinstance(raw, dict):
        return {"by_ht_id": {}, "by_name": {}, "by_team": {}}
    by_id: dict[str, Any] = {}
    by_name: dict[str, str] = {}
    for pid, row in raw.items():
        if not isinstance(row, dict) or not row.get("url"):
            continue
        name_key = _norm_name(str(row.get("player_name") or ""))
        by_id[str(pid)] = {
            "url": str(row["url"]),
            "filename": str(row.get("filename") or row["url"].rsplit("/", 1)[-1]),
            "alt": str(row.get("alt") or ""),
            "source": str(row.get("source") or "seed"),
            "name_key": name_key,
            "width": row.get("width"),
            "height": row.get("height"),
        }
        if name_key:
            by_name[name_key] = str(pid)
    return {"by_ht_id": by_id, "by_name": by_name, "by_team": {}}


def _norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "").strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _is_headshot_dimensions(width: int | None, height: int | None) -> bool:
    if not width or not height:
        return False
    if width <= 280 and height <= 280:
        return True
    short, long = min(width, height), max(width, height)
    if long <= 320:
        return True
    return long > 0 and short / long >= 0.82 and long <= 450


def is_studio_portrait(data: bytes, *, width: int | None = None, height: int | None = None) -> bool:
    """Detect media-day portraits (white/grey studio backdrops), not in-game action."""
    if Image is None:
        return bool(width and height and _is_headshot_dimensions(width, height))
    if width and height and _is_headshot_dimensions(width, height):
        return True
    try:
        im = Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        return False

    w, h = im.size
    if _is_headshot_dimensions(w, h):
        return True

    bw = max(1, int(w * 0.08))
    bh = max(1, int(h * 0.08))
    border: list[tuple[int, int, int]] = []
    for x in range(0, w, max(1, w // 40)):
        for y in range(bh):
            border.append(im.getpixel((x, y)))
            border.append(im.getpixel((x, h - 1 - y)))
    for y in range(0, h, max(1, h // 40)):
        for x in range(bw):
            border.append(im.getpixel((x, y)))
            border.append(im.getpixel((w - 1 - x, y)))

    br = [sum(p) / 3 for p in border]
    white = sum(1 for p in border if min(p) > 200) / len(border)
    light = sum(1 for b in br if b > 170) / len(border)
    var = statistics.pvariance(br) if len(br) > 1 else 0.0
    ratio = w / h if h else 1.0

    if ratio > 1.12 and white < 0.25:
        return False
    if white > 0.35 and ratio < 1.05:
        return True
    if light > 0.55 and var < 12_000 and ratio < 1.2:
        return True
    return False


def _index_path() -> Path:
    return cache_path("pwhl", "action_index.json")


def _merge_index(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = {
        "by_ht_id": dict(base.get("by_ht_id") or {}),
        "by_name": dict(base.get("by_name") or {}),
        "by_team": dict(base.get("by_team") or {}),
    }
    for ht_id, row in (extra.get("by_ht_id") or {}).items():
        out["by_ht_id"][str(ht_id)] = row
        name_key = str((row or {}).get("name_key") or "")
        if name_key:
            out["by_name"][name_key] = str(ht_id)
    for name_key, ht_id in (extra.get("by_name") or {}).items():
        out["by_name"][str(name_key)] = str(ht_id)
    for tri, row in (extra.get("by_team") or {}).items():
        out["by_team"][str(tri)] = row
    return out


def load_action_index(*, refresh: bool = False) -> dict[str, Any]:
    """Load merged action-photo index. `refresh=True` bypasses TTL but still reads disk."""
    if refresh:
        cached = load_json(_index_path())
    else:
        cached = load_json(_index_path(), ttl_seconds=INDEX_TTL)
    seed = load_json(_OPTIONAL_SEED) if _OPTIONAL_SEED.is_file() else {}
    if not isinstance(seed, dict):
        seed = {}
    seed = _merge_index(seed, _player_seed_index())
    if isinstance(cached, dict):
        return _merge_index(seed, cached)
    if seed:
        return _merge_index({}, seed)
    return {"by_ht_id": {}, "by_name": {}, "by_team": {}}


def save_action_index(index: dict[str, Any]) -> None:
    save_json(_index_path(), index)


def osc_picture_url(filename: str) -> str:
    name = str(filename or "").strip().lstrip("/")
    if name.startswith("http"):
        return name
    if name.startswith("lg") or name.startswith("md") or name.startswith("th"):
        return f"{OSC_PICTURE_BASE}{name}"
    return f"{OSC_PICTURE_BASE}lg{name}"


def _local_action_file(ht_player_id: str | int) -> Path | None:
    name = f"{ht_player_id}.jpg"
    for root in _LOCAL_ACTION_ROOTS:
        path = root / name
        if path.is_file() and path.stat().st_size > 2_000:
            return path
    return None


def _photo_from_local(ht_player_id: str) -> dict[str, Any] | None:
    path = _local_action_file(ht_player_id)
    if not path:
        return None
    try:
        data = path.read_bytes()
        if is_studio_portrait(data):
            return None
    except Exception:
        return None
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
    except Exception:
        w, h = None, None
    return {
        "card_photo_url": path.as_uri(),
        "card_photo_kind": "hero",
        "photo_width": w,
        "photo_height": h,
        "photo_source": "local_action",
    }


def _photo_from_index(ht_player_id: str, player_name: str | None = None) -> dict[str, Any] | None:
    index = load_action_index()
    by_id = index.get("by_ht_id") or {}
    row = by_id.get(str(ht_player_id))
    if not row and player_name:
        row = by_id.get(str((index.get("by_name") or {}).get(_norm_name(player_name)) or ""))
    if not isinstance(row, dict):
        return None

    url = osc_picture_url(str(row.get("url") or row.get("filename") or ""))
    if not url.startswith("http"):
        return None

    width = row.get("width")
    height = row.get("height")
    try:
        data, _ = fetch_photo(url)
        if is_studio_portrait(data, width=int(width) if width else None, height=int(height) if height else None):
            return None
        if not width or not height:
            from PIL import Image

            with Image.open(BytesIO(data)) as im:
                width, height = im.size
    except Exception:
        return None

    return {
        "card_photo_url": url,
        "card_photo_kind": "hero",
        "photo_width": width,
        "photo_height": height,
        "photo_source": str(row.get("source") or "osc"),
    }


def _photo_from_team(team_abbrev: str | None) -> dict[str, Any] | None:
    tri = str(team_abbrev or "").upper()
    if not tri:
        return None
    index = load_action_index()
    row = (index.get("by_team") or {}).get(tri)
    if not isinstance(row, dict):
        return None
    url = osc_picture_url(str(row.get("url") or row.get("filename") or ""))
    if not url.startswith("http"):
        return None
    width = row.get("width")
    height = row.get("height")
    try:
        width_i = int(width) if width else 0
        height_i = int(height) if height else 0
    except (TypeError, ValueError):
        width_i, height_i = 0, 0

    if width_i > 0 and height_i > 0 and not _is_headshot_dimensions(width_i, height_i):
        return {
            "card_photo_url": url,
            "card_photo_kind": "hero",
            "photo_width": width_i,
            "photo_height": height_i,
            "photo_source": f"{row.get('source') or 'osc'}_team",
        }

    try:
        data, _ = fetch_photo(url)
        if is_studio_portrait(data):
            return None
        from PIL import Image

        with Image.open(BytesIO(data)) as im:
            width_i, height_i = im.size
    except Exception:
        return None
    return {
        "card_photo_url": url,
        "card_photo_kind": "hero",
        "photo_width": width_i,
        "photo_height": height_i,
        "photo_source": f"{row.get('source') or 'osc'}_team",
    }


def resolve_pwhl_action_photo(
    ht_player_id: str | int,
    player_name: str | None = None,
    *,
    team_abbrev: str | None = None,
    discover: bool = True,
    allow_team_fallback: bool = False,
) -> dict[str, Any] | None:
    """Return card photo fields for an in-game PWHL action still, if available."""
    pid = str(ht_player_id)
    resolvers = [
        lambda: _photo_from_local(pid),
        lambda: _photo_from_index(pid, player_name),
    ]
    if allow_team_fallback:
        resolvers.append(lambda: _photo_from_team(team_abbrev))
    for resolver in resolvers:
        hit = resolver()
        if hit:
            return hit
    if discover and player_name:
        from .pwhl_action_sync import discover_action_photo_for_player

        discover_action_photo_for_player(pid, player_name)
        post = [lambda: _photo_from_index(pid, player_name)]
        if allow_team_fallback:
            post.append(lambda: _photo_from_team(team_abbrev))
        for resolver in post:
            hit = resolver()
            if hit:
                return hit
    return None


def parse_osc_release_photos(html: str) -> list[dict[str, str]]:
    """Extract large OSC game photos + captions from a release HTML page."""
    out: list[dict[str, str]] = []
    for match in re.finditer(
        r'graphics/pictures/((?:lg|md)[^"\']+\.jpg)"[^>]*class="photo"[^>]*alt="([^"]*)"',
        html,
        flags=re.I,
    ):
        filename = match.group(1)
        if filename.startswith("md"):
            filename = "lg" + filename[2:]
        out.append({"filename": filename, "alt": match.group(2).strip()})
    if out:
        return out
    for filename in re.findall(r"graphics/pictures/(lg[^\"']+\.jpg)", html, flags=re.I):
        out.append({"filename": filename, "alt": ""})
    return out


def register_action_photo(
    ht_player_id: str | int,
    *,
    url: str | None = None,
    filename: str | None = None,
    player_name: str | None = None,
    alt: str = "",
    source: str = "osc",
    width: int | None = None,
    height: int | None = None,
) -> None:
    """Add or update a player action photo in the on-disk index."""
    index = load_action_index(refresh=True)
    by_id = dict(index.get("by_ht_id") or {})
    by_name = dict(index.get("by_name") or {})
    photo_url = url or (osc_picture_url(filename) if filename else "")
    if not photo_url:
        return
    pid = str(ht_player_id)
    name_key = _norm_name(player_name or "")
    by_id[pid] = {
        "url": photo_url,
        "filename": filename or photo_url.rsplit("/", 1)[-1],
        "alt": alt,
        "source": source,
        "name_key": name_key,
        "width": width,
        "height": height,
    }
    if name_key:
        by_name[name_key] = pid
    save_action_index(
        {
            "by_ht_id": by_id,
            "by_name": by_name,
            "by_team": dict(index.get("by_team") or {}),
        }
    )
