"""NHL API — player search, bio, headshot, team logo."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import httpx

NHL_API = "https://api-web.nhle.com/v1"
NHL_SEARCH = "https://search.d3.nhle.com/api/v1/search/player"
MUG_SEASON = "20252026"
GENERIC_SKATER = "https://assets.nhle.com/mgl/nhl/images/headshots/current/168x168/skater.jpg"


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFD", name)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.lower().strip())


def team_logo_url(team: str, *, dark: bool = False) -> str:
    tri = team.upper()
    variant = "dark" if dark else "light"
    return f"https://assets.nhle.com/logos/nhl/svg/{tri}_{variant}.svg?season={MUG_SEASON}"


def team_logo_png_url(team: str) -> str:
    """Raster logo for Pillow rendering (SVG needs cairo)."""
    tri = team.upper()
    espn = {
        "ARI": "ari", "UTA": "utah", "SJS": "sj", "TBL": "tb", "NJD": "nj",
        "LAK": "la", "VGK": "vgk", "WSH": "wsh",
    }
    slug = espn.get(tri, tri.lower())
    return f"https://a.espncdn.com/i/teamlogos/nhl/500/{slug}.png"


def _first_name_matches(query_first: str, hit_first: str) -> bool:
    """Treat Egor/Yegor (common NHL transliterations) as equivalent."""
    q, h = query_first.lower(), hit_first.lower()
    if q == h:
        return True
    return {q, h} <= {"egor", "yegor"}


def search_player(name: str, *, active: bool = True, team: str | None = None) -> dict[str, Any] | None:
    resp = httpx.get(
        NHL_SEARCH,
        params={"culture": "en-us", "limit": 12, "active": str(active).lower(), "q": name},
        timeout=12.0,
        headers={"User-Agent": "PlayerCards/1.0"},
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None

    target = _norm(name)
    parts = target.split()
    target_last = parts[-1] if parts else ""
    target_first = parts[0] if len(parts) > 1 else ""
    team_tri = team.upper() if team else None

    def _score(hit: dict[str, Any]) -> tuple[int, int]:
        hit_name = _norm(hit.get("name", ""))
        hit_parts = hit_name.split()
        hit_last = hit_parts[-1] if hit_parts else ""
        hit_first = hit_parts[0] if len(hit_parts) > 1 else ""
        score = 0
        if hit_name == target:
            score += 100
        if hit_last == target_last:
            score += 40
        elif target_last and len(target_last) >= 4 and hit_last.startswith(target_last[:4]):
            score += 10
        if target_first and hit_first and _first_name_matches(target_first, hit_first):
            score += 20
        if team_tri and (hit.get("teamAbbrev") or "").upper() == team_tri:
            score += 30
        return score, int(hit.get("playerId") or 0)

    ranked = sorted(results, key=_score, reverse=True)
    if _score(ranked[0])[0] >= 40:
        return ranked[0]
    return results[0]


def fetch_player_landing(player_id: int) -> dict[str, Any]:
    resp = httpx.get(
        f"{NHL_API}/player/{player_id}/landing",
        timeout=12.0,
        headers={"User-Agent": "PlayerCards/1.0"},
    )
    resp.raise_for_status()
    return resp.json()


def _text(val: Any) -> str:
    if isinstance(val, dict):
        return str(val.get("default", ""))
    return str(val or "")


def inches_to_height(inches: int | float | None) -> str:
    if not inches:
        return "—"
    ft, inch = divmod(int(inches), 12)
    return f"{ft}'{inch}\""


def _season_mug_url(team: str, player_id: int) -> str:
    return f"https://assets.nhle.com/mugs/nhl/{MUG_SEASON}/{team.upper()}/{player_id}.png"


def _hero_image_url(landing: dict[str, Any], player_id: int) -> str | None:
    hero = str(landing.get("heroImage") or "").strip()
    if hero.startswith("http"):
        return hero
    # Official NHL action-shot pattern (1296×729).
    return f"https://assets.nhle.com/mugs/actionshots/1296x729/{player_id}.jpg"


def _normalize_mug_url(headshot: str | None, team: str, player_id: int) -> str:
    url = str(headshot or "").strip()
    if not url or "/latest/" in url:
        return _season_mug_url(team, player_id)
    return url


def best_card_photo_url(landing: dict[str, Any], team: str, player_id: int) -> tuple[str, str]:
    """Return (photo_url, kind) where kind is 'hero' or 'mug'."""
    mug = _normalize_mug_url(landing.get("headshot"), team, player_id)
    hero = _hero_image_url(landing, player_id)
    if hero:
        return hero, "hero"
    return mug, "mug"


def fetch_nhl_bio(player_name: str, team: str | None = None) -> dict[str, Any]:
    hit = search_player(player_name, team=team)
    if not hit:
        raise LookupError(f"NHL player not found: {player_name}")

    landing = fetch_player_landing(int(hit["playerId"]))
    tri = (team or hit.get("teamAbbrev") or hit.get("lastTeamAbbrev") or "").upper()
    pid = int(hit["playerId"])
    landing_tri = (landing.get("currentTeamAbbrev") or tri).upper()
    display_tri = tri if team else landing_tri
    mug = _normalize_mug_url(landing.get("headshot"), display_tri, pid)
    photo_url, photo_kind = best_card_photo_url(landing, display_tri, pid)

    return {
        "player_id": pid,
        "name": hit.get("name") or f"{_text(landing.get('firstName'))} {_text(landing.get('lastName'))}".strip(),
        "team": display_tri,
        "position": landing.get("position") or hit.get("positionCode", ""),
        "sweater_number": landing.get("sweaterNumber") or hit.get("sweaterNumber"),
        "height": landing.get("height") or inches_to_height(landing.get("heightInInches")),
        "height_inches": landing.get("heightInInches") or hit.get("heightInInches"),
        "weight_lbs": landing.get("weightInPounds") or hit.get("weightInPounds"),
        "shoots": landing.get("shootsCatches", ""),
        "headshot_url": mug,
        "hero_image_url": photo_url if photo_kind == "hero" else None,
        "card_photo_url": photo_url,
        "card_photo_kind": photo_kind,
        "team_logo_url": team_logo_url(display_tri),
        "team_logo_png_url": team_logo_png_url(display_tri),
        "birth_city": _text(landing.get("birthCity")),
        "birth_country": landing.get("birthCountry", ""),
    }
