"""EliteProspects API — durable prospect profile client.

Public surface:
  resolve_player(name)           → autocomplete hit
  get_profile(name, *, refresh)  → full vitals / CHL draft / career seasons
  get_team_logo(team_name)       → EP CDN logo URL
  refresh_profile(name)          → Playwright scrape → disk seed + cache

Autocomplete works over plain HTTP. Full player pages are Cloudflare-gated;
we keep seeds under ``data/ep/``, a TTL disk cache, and an optional Playwright
refresh (``EP_PLAYWRIGHT=1`` or ``refresh_profile()``).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

from .disk_cache import cache_path, load_json, save_json
from .ep_profile import (
    EP_DATA_DIR,
    _career_clubs,
    _parse_chl_draft,
    _parse_height,
    _parse_weight_lbs,
    _pbp_club_names,
    format_chl_draft_line,
    load_ep_profile,
    scrape_ep_player_page,
)

logger = logging.getLogger(__name__)

EP_AUTOCOMPLETE = "https://autocomplete.eliteprospects.com/all"
EP_PHOTO_BASE = "https://files.eliteprospects.com/layout/players/"
EP_LOGO_BASE = "https://files.eliteprospects.com/layout/logos/"
EP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.eliteprospects.com/",
    "Accept": "application/json, text/plain, */*",
}
PROFILE_TTL = 7 * 86_400


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def resolve_player(player_name: str) -> dict[str, Any] | None:
    """Resolve a player via EP autocomplete. Always HTTP — no Cloudflare page."""
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
        if hit:
            return hit
        parts = set(target.split())
        return next(
            (
                h
                for h in results
                if parts and parts <= set(_norm(str(h.get("fullname") or "")).split())
            ),
            None,
        )
    except Exception as exc:
        logger.warning("EP resolve_player failed for %s: %s", player_name, exc)
        return None


def get_team_logo(team_name: str) -> str | None:
    """Resolve an amateur/junior/NCAA team logo URL from EP autocomplete."""
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
        teams = [i for i in (r.json() or []) if i.get("_type") == "team" and i.get("logo")]
        if not teams:
            return None
        target = _norm(team_name)
        exact = next((t for t in teams if _norm(str(t.get("fullteam") or "")) == target), None)
        soft = next(
            (
                t
                for t in teams
                if target in _norm(str(t.get("fullteam") or ""))
                or _norm(str(t.get("fullteam") or "")) in target
            ),
            None,
        )
        hit = exact or soft or teams[0]
        return EP_LOGO_BASE + hit["logo"]
    except Exception as exc:
        logger.warning("EP get_team_logo failed for %s: %s", team_name, exc)
        return None


def get_player_photo(player_name: str) -> str | None:
    hit = resolve_player(player_name) or {}
    photo = (hit.get("photo") or "").strip()
    return f"{EP_PHOTO_BASE}{photo}" if photo else None


def get_profile(player_name: str, *, refresh: bool = False) -> dict[str, Any]:
    """Full prospect profile: vitals, CHL draft, career seasons, pbp_clubs.

    Guarantees a dict even when EP pages are blocked — falls back to
    autocomplete + any on-disk seed.
    """
    hit = resolve_player(player_name) or {}
    slug = hit.get("slug")
    if refresh and slug:
        scraped = refresh_profile(player_name, slug=slug, ep_id=hit.get("id"))
        if scraped:
            return scraped

    profile = load_ep_profile(player_name, slug=slug) or {}
    if not profile:
        profile = {
            "name": player_name,
            "slug": slug,
            "ep_id": hit.get("id"),
            "amateur_club": hit.get("team"),
            "position": hit.get("position"),
            "career_seasons": [],
            "career_clubs": [hit["team"]] if hit.get("team") else [],
            "pbp_clubs": [hit["team"]] if hit.get("team") else [],
            "nhl_draft_year": int(hit["season"]) if str(hit.get("season") or "").isdigit() else None,
        }
    profile.setdefault("name", player_name)
    profile.setdefault("slug", slug)
    profile.setdefault("ep_id", hit.get("id"))
    if hit.get("photo") and not profile.get("photo_url"):
        profile["photo_url"] = EP_PHOTO_BASE + hit["photo"]
    seasons = list(profile.get("career_seasons") or [])
    profile["career_clubs"] = profile.get("career_clubs") or _career_clubs(seasons)
    profile["pbp_clubs"] = profile.get("pbp_clubs") or _pbp_club_names(
        seasons, profile.get("amateur_club") or hit.get("team")
    )
    if profile.get("chl_draft") and not profile.get("chl_draft_line"):
        profile["chl_draft_line"] = format_chl_draft_line(profile["chl_draft"])
    return profile


def current_season_by_club(
    profile: dict[str, Any],
    *,
    season: str = "2025-26",
) -> list[dict[str, Any]]:
    """League-season rows for ``season`` (excludes pure tournaments when GP present)."""
    rows = []
    for row in profile.get("career_seasons") or []:
        if str(row.get("season") or "") != season:
            continue
        league = str(row.get("league") or "")
        # Keep SMAAAHL / WHL / CSSHL / JPHL / NCAA; drop Hlinka etc.
        if any(x in league.upper() for x in ("HLINKA", "WSI", "CIRCLE K", "BRICK", "TELUS")):
            continue
        rows.append(row)
    return rows


def season_scoring_totals(
    profile: dict[str, Any],
    *,
    season: str = "2025-26",
) -> dict[str, int]:
    """Sum EP GP/G/A/P across all non-tournament clubs for a season."""
    gp = g = a = tp = 0
    for row in current_season_by_club(profile, season=season):
        gp += int(row.get("gp") or 0)
        g += int(row.get("g") or 0)
        a += int(row.get("a") or 0)
        tp += int(row.get("tp") or 0)
    return {"games_played": gp, "goals": g, "assists": a, "points": tp or (g + a)}


def refresh_profile(
    player_name: str,
    *,
    slug: str | None = None,
    ep_id: str | int | None = None,
) -> dict[str, Any] | None:
    """Force a Playwright scrape and persist to ``data/ep/<slug>.json`` + disk cache."""
    hit = resolve_player(player_name) or {}
    slug = slug or hit.get("slug")
    ep_id = ep_id or hit.get("id")
    if not slug:
        logger.warning("Cannot refresh EP profile — no slug for %s", player_name)
        return None

    path_slug = f"{ep_id}/{slug}" if ep_id else slug
    scraped = scrape_ep_player_page(path_slug)
    if not scraped:
        # Retry with slug-only seed path scraper
        scraped = scrape_ep_player_page(slug)
    if not scraped:
        return None

    scraped["name"] = player_name
    scraped["slug"] = slug
    scraped["ep_id"] = str(ep_id) if ep_id else scraped.get("ep_id")
    if hit.get("team"):
        scraped.setdefault("amateur_club", hit["team"])
    if hit.get("photo"):
        scraped["photo_url"] = EP_PHOTO_BASE + hit["photo"]
    seasons = list(scraped.get("career_seasons") or [])
    scraped["career_clubs"] = _career_clubs(seasons)
    scraped["pbp_clubs"] = _pbp_club_names(seasons, scraped.get("amateur_club"))
    if scraped.get("chl_draft"):
        scraped["chl_draft_line"] = format_chl_draft_line(scraped["chl_draft"])

    EP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    seed_path = EP_DATA_DIR / f"{slug}.json"
    seed_path.write_text(json.dumps(scraped, indent=2), encoding="utf-8")
    save_json(cache_path("ep_profile", f"{slug}.json"), scraped)
    logger.info("EP profile refreshed for %s → %s", player_name, seed_path)
    return scraped


def ensure_profile(player_name: str) -> dict[str, Any]:
    """Get profile; auto-refresh via Playwright once if vitals are missing."""
    profile = get_profile(player_name)
    if profile.get("height") and profile.get("shoots") and profile.get("career_seasons"):
        return profile
    if os.getenv("EP_PLAYWRIGHT", "1").strip() in {"0", "false", "no"}:
        return profile
    refreshed = refresh_profile(player_name)
    return refreshed or profile


# --- CLI: python -m player_cards.ep_api "Liam Pue" [--refresh] ---
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EliteProspects prospect profile API")
    parser.add_argument("player", help="Player name")
    parser.add_argument("--refresh", action="store_true", help="Force Playwright scrape")
    parser.add_argument("--json", action="store_true", help="Print full JSON")
    args = parser.parse_args()
    profile = get_profile(args.player, refresh=args.refresh)
    if args.json:
        print(json.dumps(profile, indent=2, default=str))
        return
    print(f"{profile.get('name')}  slug={profile.get('slug')}  ep_id={profile.get('ep_id')}")
    print(f"  {profile.get('height')} / {profile.get('weight_lbs')} lbs / shoots {profile.get('shoots')}")
    print(f"  NHL: {profile.get('nhl_draft_info')}  CHL: {profile.get('chl_draft_line')}")
    print(f"  clubs: {profile.get('career_clubs')}")
    print(f"  pbp_clubs: {profile.get('pbp_clubs')}")
    print(f"  2025-26 EP totals: {season_scoring_totals(profile)}")


if __name__ == "__main__":
    main()
