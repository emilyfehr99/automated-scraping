"""Fetch and search NHL Entry Draft picks via API with local caching."""

from __future__ import annotations

import logging
from typing import Any
import httpx

from .disk_cache import cache_path, load_json, save_json
from .nhl_bio import _norm, _first_name_matches

logger = logging.getLogger(__name__)


def fetch_draft_picks(year: int = 2026) -> list[dict[str, Any]]:
    """Fetch all draft picks for a given year from the NHL API with a 24h disk cache."""
    path = cache_path("draft", f"picks_{year}.json")
    # Cache for 24 hours (86400 seconds)
    hit = load_json(path, ttl_seconds=86400)
    if isinstance(hit, list):
        return hit

    url = f"https://api-web.nhle.com/v1/draft/picks/{year}/all"
    logger.info("Fetching NHL draft picks for %s from API...", year)
    try:
        resp = httpx.get(
            url,
            timeout=15.0,
            headers={"User-Agent": "PlayerCards/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        picks = data.get("picks") or []
        if isinstance(picks, list) and picks:
            save_json(path, picks)
            return picks
    except Exception as e:
        logger.warning("Failed to fetch draft picks from NHL API for %s: %s", year, e)
    return []


def find_draft_pick(player_name: str, year: int = 2026) -> dict[str, Any] | None:
    """Find a prospect's draft selection details by name."""
    picks = fetch_draft_picks(year)
    if not picks:
        return None

    target = _norm(player_name)
    
    # 1. Exact full-name match
    for pick in picks:
        first = pick.get("firstName", {}).get("default", "")
        last = pick.get("lastName", {}).get("default", "")
        fullname = f"{first} {last}"
        if _norm(fullname) == target:
            return pick

    # 2. Relaxed match matching parts and transliterations (e.g. Yegor vs Egor)
    parts = target.split()
    if len(parts) >= 2:
        target_first, target_last = parts[0], parts[-1]
        for pick in picks:
            first = _norm(pick.get("firstName", {}).get("default", ""))
            last = _norm(pick.get("lastName", {}).get("default", ""))
            if last == target_last and _first_name_matches(target_first, first):
                return pick

    return None
