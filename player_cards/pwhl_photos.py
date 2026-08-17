"""PWHL player photos via HockeyTech roster + LeagueStat CDN."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import httpx

from .disk_cache import cache_path, load_json, save_json
from .pwhl_cutout import ensure_pwhl_cutout
from .pwhl_vitals import enrich_vitals
from .leagues import PWHL_HOCKEYTECH_SEASON, PWHL_HOCKEYTECH_TEAM_IDS, team_full_name
from .photo_layout import fetch_photo

HT_KEY = "446521baf8c38984"
HT_BASE = "https://lscluster.hockeytech.com/feed/index.php"
HT_MEDIA_BASE = "https://lscluster.hockeytech.com/feed/"
PHOTO_CDN = "https://assets.leaguestat.com/pwhl"
ROSTER_TTL = 86_400
MEDIA_TTL = 86_400

# HockeyTech game/action stills: OTT_Leslie, MTL_Gosling_61, BOS_Keller_5, BOS_Müller_11
_TEAM_TAGGED_RE = re.compile(r"^[A-Z]{2,5}_")
_PWHL_EVENT_RE = re.compile(r"_PWHL_", re.I)
_STUDIO_TITLE_RE = re.compile(r"^[A-Za-z][A-Za-z'’-]+_[A-Za-z][A-Za-z'’-]+$")

_LOCAL_PHOTO_ROOTS = (
    Path.home() / "CascadeProjects" / "pwhl-analytics" / "web" / "public" / "photos" / "players",
    Path.home() / "Desktop" / "pwhl-analytics" / "web" / "public" / "photos" / "players",
)


def _norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "").strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _norm_tokens(name: str) -> list[str]:
    s = unicodedata.normalize("NFKD", str(name or "").strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [t for t in re.sub(r"[^a-zA-Z0-9'-]+", " ", s).lower().split() if t]


def _display_name(instat_name: str) -> str:
    """InStat/PBP 'Last First' -> card 'First Last'."""
    parts = instat_name.strip().split()
    if len(parts) < 2:
        return instat_name.strip()
    return f"{' '.join(parts[1:])} {parts[0]}"


def presentation_name(name: str, *, roster_name: str | None = None) -> str:
    """Card display name — always First Last. HockeyTech roster is canonical."""
    if roster_name:
        return roster_name.strip()
    parts = name.strip().split()
    if len(parts) < 2:
        return name.strip()
    # InStat uses Last First; HockeyTech roster is already First Last.
    if len(parts) == 2 and parts[0][0].isupper() and parts[1][0].isupper():
        roster_hit = search_pwhl_player(name)
        if roster_hit and str(roster_hit.get("name") or "").lower() == name.lower():
            return str(roster_hit["name"])
        swapped = _display_name(name)
        roster_hit = search_pwhl_player(swapped)
        if roster_hit:
            return str(roster_hit.get("name") or swapped)
        return swapped
    return _display_name(name)


def _first_name_compatible(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return a.startswith(b) or b.startswith(a)


def _last_name_match(a: str, b: str) -> bool:
    """Match surnames including hyphenated variants (Channell -> Channell-Watkins)."""
    al = str(a or "").lower()
    bl = str(b or "").lower()
    if not al or not bl:
        return False
    if al == bl:
        return True
    a_base = al.split("-")[0]
    b_base = bl.split("-")[0]
    return a_base == b_base or al == b_base or bl == a_base


def _instat_roster_match(instat_name: str, roster_name: str) -> bool:
    ip = instat_name.split()
    if len(ip) < 2:
        return _norm_name(instat_name) == _norm_name(roster_name)
    ilast = _norm_name(ip[0])
    ifirst = _norm_tokens(" ".join(ip[1:]))
    rtokens = _norm_tokens(roster_name)
    rfirst = rtokens[0] if rtokens else ""
    rlast = rtokens[-1] if rtokens else ""
    if not ifirst or not rtokens:
        return False
    last_ok = ilast == rlast or ilast in rtokens or _last_name_match(ilast, rlast)
    if not last_ok:
        return False
    if all(t in rtokens for t in ifirst):
        return True
    return _first_name_compatible(ifirst[0], rfirst)


def photo_cdn_url(player_id: str | int, *, size: str = "240x240") -> str:
    return f"{PHOTO_CDN}/{size}/{player_id}.jpg"


def _local_photo_file(player_id: str | int) -> Path | None:
    name = f"{player_id}.jpg"
    for root in _LOCAL_PHOTO_ROOTS:
        path = root / name
        if path.is_file() and path.stat().st_size > 500:
            return path
    return None


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


def _is_headshot_dimensions(width: int | None, height: int | None) -> bool:
    """Square or tiny images are roster mugs, not in-game action stills."""
    if not width or not height:
        return False
    if width <= 280 and height <= 280:
        return True
    short, long = min(width, height), max(width, height)
    if long <= 320:
        return True
    return long > 0 and short / long >= 0.82 and long <= 450


def _local_photo_url(player_id: str | int) -> str | None:
    """Local override only when the file is larger than a roster mug."""
    path = _local_photo_file(player_id)
    if not path:
        return None
    w, h = _image_dimensions(path) or (None, None)
    if _is_headshot_dimensions(w, h):
        return None
    return path.as_uri()


def _is_junk_media_title(title: str) -> bool:
    tl = str(title or "").lower()
    return any(x in tl for x in ("placeholder", "logo", "nophoto", "no photo"))


def _is_action_media_title(title: str) -> bool:
    """Team-tagged stills from game photography (preferred card art)."""
    t = str(title or "").strip()
    if not t or _is_junk_media_title(t):
        return False
    if _TEAM_TAGGED_RE.match(t):
        return True
    return bool(_PWHL_EVENT_RE.search(t))


def _media_action_score(title: str, width: int, height: int) -> tuple[int, int, int]:
    """Higher is better: action/game stills beat studio portraits."""
    t = str(title or "").strip()
    if _is_junk_media_title(t):
        return (-100, 0, 0)

    score = 0
    if _is_action_media_title(t):
        score += 120
        if re.search(r"_\d+$", t):
            score += 15
    elif width > 0 and height > 0 and width > height * 1.08:
        score += 80
    elif _STUDIO_TITLE_RE.match(t) and not _TEAM_TAGGED_RE.match(t):
        score += 10
    elif re.fullmatch(r"[A-Za-z][A-Za-z'’-]+", t):
        score += 20
    else:
        score += 40

    if _STUDIO_TITLE_RE.match(t) and width * height > 2_500_000:
        score -= 25

    return (score, width * height, 0)


def _is_landscape_action_dimensions(width: int | None, height: int | None) -> bool:
    """In-game card heroes need landscape stills, not portrait media-day frames."""
    if not width or not height or width <= 0 or height <= 0:
        return False
    return width > height * 1.08


def _ht_media_is_action_still(url: str, width: int, height: int, *, title: str = "") -> bool:
    """HockeyTech PWHL player-media: only landscape, non-studio in-game stills."""
    del title
    if _is_headshot_dimensions(width, height):
        return False
    if not _is_landscape_action_dimensions(width, height):
        return False
    try:
        data, _ = fetch_photo(url)
        if is_studio_portrait(data, width=width, height=height):
            return False
        try:
            from io import BytesIO

            from PIL import Image

            with Image.open(BytesIO(data)) as im:
                w, h = im.size
            if not _is_landscape_action_dimensions(w, h):
                return False
            return not is_studio_portrait(data, width=w, height=h)
        except Exception:
            return _is_landscape_action_dimensions(width, height)
    except Exception:
        return False


def _media_matches_player(title: str, player_name: str, sweater_number: str | int | None = None) -> bool:
    """Team-tagged HockeyTech still must reference this skater by last name."""
    del sweater_number  # jersey in filename often differs from current sweater number
    if not _is_action_media_title(title):
        return False
    tokens = _norm_tokens(player_name)
    if not tokens:
        return True
    last = tokens[-1]
    title_l = str(title or "").lower()
    return last.lower() in title_l or _norm_name(last) in _norm_name(title)


def _best_player_media(
    items: list[dict[str, Any]],
    *,
    player_name: str = "",
    sweater_number: str | int | None = None,
) -> dict[str, Any] | None:
    """Pick this player's non-studio action still from HockeyTech player media."""
    ranked: list[tuple[tuple[int, int, int], int, dict[str, Any]]] = []
    for it in items:
        if str(it.get("deleted") or "") == "1":
            continue
        title = str(it.get("title") or "")
        if _is_junk_media_title(title):
            continue
        if player_name and not _media_matches_player(title, player_name, sweater_number):
            continue
        url = str(it.get("url") or it.get("thumb") or "").strip()
        if not url.startswith("http"):
            continue
        try:
            w = int(it.get("width") or 0)
            h = int(it.get("height") or 0)
        except (TypeError, ValueError):
            w, h = 0, 0
        if not _ht_media_is_action_still(url, w, h, title=title):
            continue
        primary = 1 if str(it.get("is_primary") or "") == "1" else 0
        base = _media_action_score(title, w, h)
        ranked.append((base, primary, {**it, "url": url, "width": w, "height": h}))

    if not ranked:
        return None
    ranked.sort(key=lambda row: (row[0][0], row[1], row[0][1], row[0][2]), reverse=True)
    return ranked[0][2]


def _resolve_pwhl_headshot(
    ht_player_id: str,
    roster_row: dict[str, Any] | None = None,
    *,
    player_name: str | None = None,
) -> dict[str, Any]:
    """Best available PWHL portrait (largest HockeyTech media-day still > local > LeagueStat)."""
    pid = str(ht_player_id)
    display_name = player_name or str((roster_row or {}).get("name") or "")
    jersey = (roster_row or {}).get("sweater_number")
    candidates: list[dict[str, Any]] = []

    path = _local_photo_file(pid)
    if path:
        w, h = _image_dimensions(path) or (0, 0)
        candidates.append({
            "url": path.as_uri(),
            "width": w,
            "height": h,
            "source": "local",
        })

    media = _fetch_player_media(pid)
    best = _best_headshot_media(media, player_name=display_name, sweater_number=jersey)
    if best:
        candidates.append({
            "url": str(best["url"]),
            "width": int(best.get("width") or 0) or None,
            "height": int(best.get("height") or 0) or None,
            "source": "hockeytech",
        })

    roster_url = str((roster_row or {}).get("photo_url") or "").strip()
    url = roster_url if roster_url.startswith("http") else photo_cdn_url(pid)
    candidates.append({"url": url, "width": 240, "height": 240, "source": "leaguestat"})

    source_rank = {"hockeytech": 2, "local": 1, "leaguestat": 0}

    def _rank(shot: dict[str, Any]) -> tuple[int, int]:
        w = int(shot.get("width") or 0)
        h = int(shot.get("height") or 0)
        return (w * h, source_rank.get(str(shot.get("source") or ""), 0))

    return max(candidates, key=_rank)


def _is_portrait_media_title(title: str) -> bool:
    """HockeyTech PWHL portraits: team tags (MTL_Gosling_61) or studio names."""
    t = str(title or "").strip()
    if not t or _is_junk_media_title(t):
        return False
    if _is_action_media_title(t):
        return True
    if _STUDIO_TITLE_RE.match(t):
        return True
    return False


def _best_headshot_media(
    items: list[dict[str, Any]],
    *,
    player_name: str = "",
    sweater_number: str | int | None = None,
) -> dict[str, Any] | None:
    """Pick the largest player-matched portrait from HockeyTech media."""
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for it in items:
        title = str(it.get("title") or "")
        if not _is_portrait_media_title(title):
            continue
        if player_name and _is_action_media_title(title):
            if not _media_matches_player(title, player_name, sweater_number):
                continue
        url = str(it.get("url") or it.get("thumb") or "").strip()
        if not url.startswith("http"):
            continue
        try:
            w = int(it.get("width") or 0)
            h = int(it.get("height") or 0)
        except (TypeError, ValueError):
            w, h = 0, 0
        primary = 1 if str(it.get("is_primary") or "") == "1" else 0
        ranked.append((w * h, primary, {**it, "url": url, "width": w, "height": h}))

    if not ranked:
        return None
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return ranked[0][2]


def _card_photo_from_ht_player(
    ht_player_id: str,
    roster_row: dict[str, Any] | None = None,
    *,
    player_name: str | None = None,
    team_abbrev: str | None = None,
) -> dict[str, Any]:
    """Resolve PWHL card art from highest-quality team headshot."""
    del team_abbrev
    pid = str(ht_player_id)
    headshot_url = photo_cdn_url(pid)
    display_name = player_name or str((roster_row or {}).get("name") or "")
    shot = _resolve_pwhl_headshot(pid, roster_row, player_name=display_name)
    source_url = str(shot["url"])
    try:
        cutout = ensure_pwhl_cutout(source_url)
        card_url = cutout["path"].as_uri()
        card_w = cutout.get("width") or shot.get("width")
        card_h = cutout.get("height") or shot.get("height")
    except Exception:
        card_url = source_url
        card_w = shot.get("width")
        card_h = shot.get("height")

    return {
        "headshot_url": headshot_url,
        "card_photo_url": card_url,
        "card_photo_kind": "mug",
        "photo_width": card_w,
        "photo_height": card_h,
        "photo_source": shot.get("source"),
        "headshot_source_url": source_url,
    }


def refresh_pwhl_bio(bio: dict[str, Any]) -> dict[str, Any]:
    """Re-resolve PWHL bio, vitals, and card photo from HockeyTech roster."""
    name = str(bio.get("instat_name") or bio.get("name") or "").strip()
    tri = str(bio.get("team") or "").upper()
    hit: dict[str, Any] | None = None

    if name and tri:
        hit = lookup_pwhl_player(name, tri)
    if not hit and name:
        found = search_pwhl_player(name)
        if found:
            tri = str(found.get("team") or tri).upper()
            hit = lookup_pwhl_player(str(found.get("name") or name), tri) if tri else None

    if not hit:
        return bio

    out = dict(bio)
    out["team"] = tri
    out["ht_player_id"] = str(hit.get("ht_player_id") or hit.get("player_id") or out.get("ht_player_id") or "")
    out["name"] = str(hit.get("name") or out.get("name") or "")
    out["instat_name"] = str(hit.get("instat_name") or name or out.get("instat_name") or "")
    out["position"] = hit.get("position") or out.get("position") or ""
    out["sweater_number"] = hit.get("sweater_number") or out.get("sweater_number")
    out["height"] = hit.get("height") or out.get("height")
    out["shoots"] = hit.get("shoots") or out.get("shoots")
    for key in (
        "headshot_url",
        "card_photo_url",
        "card_photo_kind",
        "photo_width",
        "photo_height",
        "photo_source",
        "headshot_source_url",
    ):
        if hit.get(key) is not None:
            out[key] = hit[key]

    ht_team_id = PWHL_HOCKEYTECH_TEAM_IDS.get(tri)
    if ht_team_id:
        logo = f"https://assets.leaguestat.com/pwhl/logos/{ht_team_id}.png"
        out["team_logo_url"] = logo
        out["team_logo_png_url"] = logo
    return out


def refresh_pwhl_card_photo(bio: dict[str, Any]) -> dict[str, Any]:
    """Re-resolve PWHL card photo from the best available headshot."""
    return refresh_pwhl_bio(bio)


def _fetch_ht_roster(ht_team_id: str, season_id: int = PWHL_HOCKEYTECH_SEASON) -> list[dict[str, Any]]:
    cache_file = cache_path("pwhl", "rosters", f"{ht_team_id}_{season_id}_v2.json")
    hit = load_json(cache_file, ttl_seconds=ROSTER_TTL)
    if isinstance(hit, list):
        return hit

    url = (
        f"{HT_BASE}?feed=modulekit&view=statviewtype&type=roster"
        f"&team_id={ht_team_id}&season_id={season_id}&key={HT_KEY}&client_code=pwhl"
    )
    resp = httpx.get(url, timeout=30.0, headers={"Accept": "application/json"})
    resp.raise_for_status()
    raw = re.sub(r"^\d+:\s*", "", resp.text)
    data = json.loads(raw)
    rows = data.get("SiteKit", {}).get("Statviewtype", []) or []
    if isinstance(rows, dict):
        rows = [rows]
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("player_id"):
            continue
        pid = str(row["player_id"])
        img = str(row.get("player_image") or "").strip()
        if not img:
            img = photo_cdn_url(pid)
        out.append(
            {
                "player_id": pid,
                "name": str(row.get("name") or row.get("display_name") or ""),
                "position": str(row.get("position") or ""),
                "sweater_number": row.get("sweater_number") or row.get("tp_jersey_number") or row.get("jersey_number"),
                "photo_url": img,
                "height": row.get("height") or row.get("h"),
                "weight": row.get("weight") or row.get("w"),
                "shoots": row.get("shoots"),
            }
        )
    save_json(cache_file, out)
    return out


def _fetch_player_media(ht_player_id: str) -> list[dict[str, Any]]:
    cache_file = cache_path("pwhl", "media", f"{ht_player_id}.json")
    hit = load_json(cache_file, ttl_seconds=MEDIA_TTL)
    if isinstance(hit, list):
        return hit

    url = (
        f"{HT_MEDIA_BASE}?feed=modulekit&view=player&category=media"
        f"&player_id={ht_player_id}&key={HT_KEY}&client_code=pwhl"
    )
    resp = httpx.get(url, timeout=30.0, headers={"Accept": "application/json"})
    resp.raise_for_status()
    raw = re.sub(r"^\d+:\s*", "", resp.text)
    data = json.loads(raw)
    items = data.get("SiteKit", {}).get("Player") or []
    if isinstance(items, dict):
        items = [items]
    out = [it for it in items if isinstance(it, dict)]
    save_json(cache_file, out)
    return out


def search_pwhl_player(player_name: str) -> dict[str, Any] | None:
    """Find a PWHL skater across all HockeyTech rosters (no --team required)."""
    target = player_name.strip()
    if not target:
        return None

    query_norm = _norm_name(target)
    query_tokens = _norm_tokens(target)
    query_last = query_tokens[-1] if query_tokens else ""
    query_first = " ".join(query_tokens[:-1]) if len(query_tokens) > 1 else ""

    def _score(row: dict[str, Any], tri: str) -> tuple[int, str]:
        name = str(row.get("name") or "")
        score = 0
        if name.lower() == target.lower():
            score += 100
        elif _display_name(target).lower() == name.lower():
            score += 100
        elif _instat_roster_match(target, name):
            score += 80
        else:
            name_norm = _norm_name(name)
            if query_norm and name_norm == query_norm:
                score += 90
            else:
                rtokens = _norm_tokens(name)
                rlast = rtokens[-1] if rtokens else ""
                rfirst = rtokens[0] if rtokens else ""
                if query_last and rlast == query_last:
                    score += 40
                if query_first and rfirst and _first_name_compatible(query_first.split()[0], rfirst):
                    score += 20
        return score, tri

    best: tuple[int, str, dict[str, Any]] | None = None
    for tri, ht_team_id in PWHL_HOCKEYTECH_TEAM_IDS.items():
        for row in _fetch_ht_roster(ht_team_id):
            score, team = _score(row, tri)
            if score < 40:
                continue
            if best is None or (score, tri) > (best[0], best[1]):
                best = (score, tri, {**row, "team": tri})

    if not best:
        return None
    _, tri, row = best
    return {
        "team": tri,
        "name": str(row.get("name") or _display_name(target)),
        "player_id": row.get("player_id"),
        "position": row.get("position") or "",
        "sweater_number": row.get("sweater_number"),
    }


def _find_roster_row(target: str, roster: list[dict[str, Any]]) -> dict[str, Any] | None:
    query = target.strip()
    if not query:
        return None
    ql = query.lower()
    qnorm = _norm_name(query)
    best: tuple[int, dict[str, Any]] | None = None
    for row in roster:
        name = str(row.get("name") or "")
        score = 0
        if name.lower() == ql:
            score = 100
        elif _display_name(query).lower() == name.lower():
            score = 100
        elif _instat_roster_match(query, name):
            score = 85
        elif _norm_name(name) == qnorm:
            score = 90
        else:
            parts = _norm_tokens(query)
            rtokens = _norm_tokens(name)
            if parts and rtokens:
                qlast = parts[-1]
                rlast = rtokens[-1]
                if qlast == rlast or _last_name_match(qlast, rlast):
                    if parts[0] == rtokens[0] or _first_name_compatible(parts[0], rtokens[0]):
                        score = 70
        if score < 70:
            continue
        if best is None or score > best[0]:
            best = (score, row)
    return best[1] if best else None


def lookup_pwhl_player(
    instat_name: str,
    team_abbrev: str,
    *,
    league: str = "pwhl",
) -> dict[str, Any] | None:
    """Match an InStat-style name to HockeyTech metadata + action/card photo."""
    tri = team_abbrev.upper()
    target = instat_name.strip()
    hit: dict[str, Any] | None = None

    ht_team_id = PWHL_HOCKEYTECH_TEAM_IDS.get(tri)
    if ht_team_id:
        hit = _find_roster_row(target, _fetch_ht_roster(ht_team_id))

    if not hit:
        found = search_pwhl_player(target)
        if not found:
            return None
        tri = str(found.get("team") or tri).upper()
        ht_team_id = PWHL_HOCKEYTECH_TEAM_IDS.get(tri)
        if not ht_team_id:
            return None
        hit = _find_roster_row(str(found.get("name") or target), _fetch_ht_roster(ht_team_id))
        if not hit:
            hit = {
                "player_id": found.get("player_id"),
                "name": found.get("name"),
                "position": found.get("position"),
                "sweater_number": found.get("sweater_number"),
                "photo_url": "",
            }

    pid = str(hit["player_id"])
    vitals = enrich_vitals(
        str(hit.get("name") or presentation_name(target)),
        target,
        hit,
        ht_player_id=pid,
        position=hit.get("position"),
    )
    photos = _card_photo_from_ht_player(
        pid,
        hit,
        player_name=str(hit.get("name") or presentation_name(target)),
        team_abbrev=tri,
    )

    return {
        "player_id": int(pid) if pid.isdigit() else pid,
        "ht_player_id": pid,
        "name": str(hit.get("name") or presentation_name(target)),
        "instat_name": target,
        "position": hit.get("position") or "",
        "sweater_number": vitals.get("sweater_number") or hit.get("sweater_number"),
        "height": vitals.get("height"),
        "shoots": vitals.get("shoots"),
        **photos,
        "team_full": team_full_name(league, tri),
    }
