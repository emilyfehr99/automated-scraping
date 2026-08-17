"""NHL API — player search, bio, headshot, team logo."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

import httpx

logger = logging.getLogger(__name__)

NHL_API = "https://api-web.nhle.com/v1"
NHL_SEARCH = "https://search.d3.nhle.com/api/v1/search/player"
MUG_SEASON = "20252026"
GENERIC_SKATER = "https://assets.nhle.com/mgl/nhl/images/headshots/current/168x168/skater.jpg"
EP_AUTOCOMPLETE = "https://autocomplete.eliteprospects.com/all"
EP_PHOTO_BASE = "https://files.eliteprospects.com/layout/players/"
EP_LOGO_BASE = "https://files.eliteprospects.com/layout/logos/"
EP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.eliteprospects.com/",
    "Accept": "application/json, text/plain, */*",
}


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


def search_eliteprospects_team_logo(team_name: str) -> str | None:
    """Find team logo URL from EliteProspects for junior/NCAA/European clubs.

    Prefers an exact full-team name match, then a case-insensitive contains match,
    so e.g. "Regina Pats" does not accidentally resolve to a juvenile farm logo.
    """
    if not team_name or team_name == "N/A":
        return None
    try:
        r = httpx.get(
            EP_AUTOCOMPLETE,
            params={"q": team_name},
            headers=EP_HEADERS,
            timeout=8.0,
        )
        if r.status_code != 200:
            return None
        teams = [item for item in (r.json() or []) if item.get("_type") == "team" and item.get("logo")]
        if not teams:
            return None
        target = _norm(team_name)
        exact = next((t for t in teams if _norm(str(t.get("fullteam") or "")) == target), None)
        if exact:
            return EP_LOGO_BASE + exact["logo"]
        soft = next(
            (
                t
                for t in teams
                if target in _norm(str(t.get("fullteam") or ""))
                or _norm(str(t.get("fullteam") or "")) in target
            ),
            None,
        )
        hit = soft or teams[0]
        return EP_LOGO_BASE + hit["logo"]
    except Exception as exc:
        logger.warning("Failed to fetch EP logo for %s: %s", team_name, exc)
    return None


def fetch_eliteprospects_player(player_name: str) -> dict[str, Any] | None:
    """Resolve an undrafted/amateur prospect from EliteProspects autocomplete."""
    if not player_name:
        return None
    try:
        r = httpx.get(
            EP_AUTOCOMPLETE,
            params={"q": player_name, "type": "player"},
            headers=EP_HEADERS,
            timeout=8.0,
        )
        if r.status_code != 200:
            return None
        results = r.json() if isinstance(r.json(), list) else []
        target = _norm(player_name)
        hit = next((h for h in results if _norm(str(h.get("fullname") or "")) == target), None)
        if not hit:
            # Fall back to first player hit whose name shares both tokens
            parts = set(target.split())
            hit = next(
                (
                    h
                    for h in results
                    if h.get("_type", "player") == "player"
                    and parts
                    and parts <= set(_norm(str(h.get("fullname") or "")).split())
                ),
                None,
            )
        return hit if isinstance(hit, dict) else None
    except Exception as exc:
        logger.warning("EP player lookup failed for %s: %s", player_name, exc)
        return None


def fetch_undrafted_prospect_bio(
    player_name: str,
    *,
    amateur_club: str | None = None,
) -> dict[str, Any]:
    """Build a prospect bio branded entirely on the amateur club (no NHL team).

    Used for players who have not been drafted yet — colours/logos come from the
    junior/NCAA club rather than an NHL franchise. Height/weight/shoots, CHL draft,
    and career clubs are enriched from the EliteProspects API module.
    """
    from .amateur_brands import resolve_team_brand
    from .ep_api import (
        current_season_by_club,
        get_player_photo,
        get_profile,
        season_scoring_totals,
    )
    from .ep_profile import format_chl_draft_line

    profile = get_profile(player_name)
    club = (
        amateur_club
        or profile.get("amateur_club")
        or ""
    ).strip() or "Amateur"

    draft_year = profile.get("nhl_draft_year")
    if isinstance(draft_year, str) and draft_year.isdigit():
        draft_year = int(draft_year)
    if isinstance(draft_year, int):
        draft_info = profile.get("nhl_draft_info") or f"{draft_year} NHL Draft Eligible"
    else:
        draft_info = profile.get("nhl_draft_info") or "NHL Draft Eligible"
        draft_year = None

    headshot = profile.get("photo_url") or get_player_photo(player_name)
    brand = resolve_team_brand(club, league="prospect")
    logo = brand.get("logo_url")

    country_code = profile.get("birth_country") or ""
    height = profile.get("height")
    height_inches = profile.get("height_inches")
    if height and not height_inches:
        from .ep_profile import _parse_height
        height, height_inches = _parse_height(str(height))
    weight_lbs = profile.get("weight_lbs")
    shoots = profile.get("shoots") or None
    position = profile.get("position") or ""
    chl_draft = profile.get("chl_draft") if isinstance(profile.get("chl_draft"), dict) else None
    career_clubs = list(profile.get("career_clubs") or [])
    pbp_clubs = list(profile.get("pbp_clubs") or [])
    if club:
        career_clubs = [club] + [c for c in career_clubs if c != club]
        pbp_clubs = [club] + [c for c in pbp_clubs if c != club]

    season_clubs = current_season_by_club(profile, season="2025-26")
    ep_totals = season_scoring_totals(profile, season="2025-26")
    dual_roster = bool(profile.get("dual_roster")) or len(season_clubs) >= 2

    ep_id = profile.get("ep_id")
    return {
        "player_id": int(ep_id) if str(ep_id or "").isdigit() else 0,
        "name": player_name,
        "team": club,
        "position": position,
        "sweater_number": None,
        "height": height,
        "height_inches": height_inches,
        "weight_lbs": weight_lbs,
        "shoots": shoots,
        "headshot_url": headshot,
        "hero_image_url": None,
        "card_photo_url": headshot,
        "card_photo_kind": "mug" if headshot else None,
        "team_logo_url": logo,
        "team_logo_png_url": logo,
        "birth_city": profile.get("birth_city") or None,
        "birth_country": country_code,
        "country": country_code,
        "draft_details": None,
        "draft_info": draft_info,
        "draft_year": draft_year,
        "draft_round": None,
        "draft_pick": None,
        "draft_overall": None,
        "chl_draft": chl_draft,
        "chl_draft_line": profile.get("chl_draft_line") or format_chl_draft_line(chl_draft),
        "career_clubs": career_clubs,
        "career_seasons": profile.get("career_seasons") or [],
        "season_clubs": season_clubs,
        "ep_season_totals": ep_totals,
        "pbp_clubs": pbp_clubs,
        "dual_roster": dual_roster,
        "amateur_club": club,
        "amateur_league": None,
        "undrafted": True,
        "league": "prospect",
        "ep_id": ep_id,
        "ep_slug": profile.get("slug"),
        "brand_source": brand.get("source"),
    }


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
    best_score, _ = _score(ranked[0])
    # Require first name match or full name match so different first names (e.g. Ashton vs Maddox) are not matched
    if best_score >= 60:
        return ranked[0]
    return None


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


def _primary_game_log_team(player_id: int) -> str | None:
    """Team with the most regular-season GP (best mug jersey context for traded players)."""
    counts = fetch_player_season_teams(player_id)
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _is_venue_hero_url(url: str | None) -> bool:
    """NHL heroImage often points at a generic arena/venue action shot, not the player."""
    u = str(url or "").lower()
    return "actionshots" in u or "getty" in u


def _espn_headshot_url(player_name: str) -> str | None:
    try:
        resp = httpx.get(
            "https://site.web.api.espn.com/apis/common/v3/search",
            params={"query": player_name, "limit": 8, "type": "player"},
            timeout=10.0,
            headers={"User-Agent": "PlayerCards/1.0"},
        )
        resp.raise_for_status()
        target = _norm(player_name)
        for item in resp.json().get("items") or []:
            if str(item.get("league") or "").lower() != "nhl":
                continue
            if _norm(str(item.get("displayName") or "")) != target:
                continue
            athlete_id = item.get("id")
            if not athlete_id:
                continue
            aresp = httpx.get(
                f"https://site.api.espn.com/apis/common/v3/sports/hockey/nhl/athletes/{athlete_id}",
                timeout=10.0,
                headers={"User-Agent": "PlayerCards/1.0"},
            )
            aresp.raise_for_status()
            payload = aresp.json().get("athlete") or aresp.json()
            href = str((payload.get("headshot") or {}).get("href") or "").strip()
            if href.startswith("http"):
                return href
    except Exception:
        pass
    return None


def best_card_photo_url(
    landing: dict[str, Any],
    team: str,
    player_id: int,
    *,
    player_name: str | None = None,
) -> tuple[str, str]:
    """Return (photo_url, kind) where kind is 'hero' or 'mug'."""
    mug = _normalize_mug_url(landing.get("headshot"), team, player_id)
    hero = _hero_image_url(landing, player_id)
    landing_hero = str(landing.get("heroImage") or "").strip()

    # Player cards need a portrait; NHL heroImage is often a venue wide shot.
    if _is_venue_hero_url(landing_hero) or _is_venue_hero_url(hero):
        espn = _espn_headshot_url(player_name) if player_name else None
        if espn:
            return espn, "mug"
        return mug, "mug"

    if mug:
        return mug, "mug"
    espn = _espn_headshot_url(player_name) if player_name else None
    if espn:
        return espn, "mug"
    if hero:
        return hero, "hero"
    return GENERIC_SKATER, "mug"


def refresh_nhl_card_photo(bio: dict[str, Any]) -> dict[str, Any]:
    """Re-resolve portrait URL (fixes stale store rows with arena hero shots)."""
    pid = bio.get("player_id")
    name = str(bio.get("name") or "")
    if not pid or not name:
        return bio
    landing = fetch_player_landing(int(pid))
    display_tri = str(bio.get("team") or landing.get("currentTeamAbbrev") or "").upper()
    photo_tri = _primary_game_log_team(int(pid)) or display_tri
    mug = _normalize_mug_url(landing.get("headshot"), photo_tri, int(pid))
    photo_url, photo_kind = best_card_photo_url(
        landing, photo_tri, int(pid), player_name=name
    )
    out = dict(bio)
    out["headshot_url"] = mug
    out["hero_image_url"] = photo_url if photo_kind == "hero" else None
    out["card_photo_url"] = photo_url
    out["card_photo_kind"] = photo_kind
    return out


def fetch_nhl_bio(player_name: str, team: str | None = None) -> dict[str, Any]:
    hit = search_player(player_name, team=team)
    if not hit:
        # Prospects who aren't on an active NHL roster yet don't show up
        # in the "active" search index — retry against the full index.
        hit = search_player(player_name, active=False, team=team)
    if not hit:
        return {"name": player_name, "team": team or "N/A", "player_id": 0, "position": "N/A", "height": "N/A", "weight": "N/A", "shoots": "N/A", "birthDate": "N/A"}

    landing = fetch_player_landing(int(hit["playerId"]))
    tri = (team or hit.get("teamAbbrev") or hit.get("lastTeamAbbrev") or "").upper()
    pid = int(hit["playerId"])
    name = hit.get("name") or f"{_text(landing.get('firstName'))} {_text(landing.get('lastName'))}".strip()
    landing_tri = (landing.get("currentTeamAbbrev") or tri).upper()
    display_tri = tri if team else landing_tri
    photo_tri = _primary_game_log_team(pid) or display_tri
    mug = _normalize_mug_url(landing.get("headshot"), photo_tri, pid)
    photo_url, photo_kind = best_card_photo_url(landing, photo_tri, pid, player_name=name)

    return {
        "player_id": pid,
        "name": name,
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
        "draft_details": landing.get("draftDetails"),
        "season_totals": landing.get("seasonTotals"),
    }


def fetch_player_season_teams(
    player_id: int,
    *,
    nhl_season: str = MUG_SEASON,
) -> dict[str, int]:
    """Regular-season games played per NHL team abbrev (handles mid-season trades)."""
    resp = httpx.get(
        f"{NHL_API}/player/{player_id}/game-log/{nhl_season}/2",
        timeout=20.0,
        headers={"User-Agent": "PlayerCards/1.0"},
    )
    resp.raise_for_status()
    counts: dict[str, int] = {}
    for game in resp.json().get("gameLog") or []:
        tri = str(game.get("teamAbbrev") or "").upper()
        if tri:
            counts[tri] = counts.get(tri, 0) + 1
    return counts
