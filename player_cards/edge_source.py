"""Fetch and cache NHL EDGE tracking data (skating speed, shot speed, distance)."""

from __future__ import annotations

import logging
from typing import Any
import requests

from .disk_cache import cache_path, load_json, save_json

logger = logging.getLogger(__name__)

EDGE_BASE = "https://api-web.nhle.com/v1/edge"
CACHE_TTL = 86400  # 24 hours


def _fetch_skater_edge_payload(player_id: int, season: str = "now") -> dict[str, Any] | None:
    """Fetch raw skater detail payload from NHL Edge API."""
    url = f"{EDGE_BASE}/skater-detail/{player_id}/{season}"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code != 404:
            logger.debug("Edge API returned status %s for player %s", resp.status_code, player_id)
    except Exception as exc:
        logger.debug("Edge API request failed for player %s: %s", player_id, exc)
    return None


def fetch_edge_info(
    player_id: int | None,
    season: str = "now",
    *,
    use_cache: bool = True,
) -> dict[str, Any] | None:
    """Return normalized NHL Edge metrics with league percentiles.

    Returns dict with keys:
      - top_speed_mph (float), top_speed_pct (int)
      - bursts_over_20 (int), bursts_pct (int)
      - top_shot_mph (float), top_shot_pct (int)
      - distance_miles (float), distance_pct (int)
    """
    if not player_id:
        return None

    path = cache_path("edge", f"player_{player_id}_{season}.json")
    if use_cache:
        cached = load_json(path, ttl_seconds=CACHE_TTL)
        if isinstance(cached, dict):
            return cached

    raw = _fetch_skater_edge_payload(player_id, season)
    if not raw:
        return None

    # 1. Skating speed (max & bursts)
    skating = raw.get("skatingSpeed") or {}
    speed_max = skating.get("speedMax") or {}
    top_spd = speed_max.get("imperial")
    top_spd_pct = speed_max.get("percentile")

    bursts = skating.get("burstsOver20") or {}
    bursts_val = bursts.get("value")
    bursts_pct = bursts.get("percentile")

    # 2. Shot speed (max)
    shot_max = raw.get("topShotSpeed") or {}
    top_shot = shot_max.get("imperial")
    top_shot_pct = shot_max.get("percentile")

    # 3. Distance skated (total)
    dist = raw.get("totalDistanceSkated") or {}
    dist_val = dist.get("imperial")
    dist_pct = dist.get("percentile")

    # If all metrics are missing, return None
    if top_spd is None and bursts_val is None and top_shot is None and dist_val is None:
        return None

    norm: dict[str, Any] = {
        "source": "nhl_edge",
        "top_speed_mph": round(float(top_spd), 1) if top_spd is not None else None,
        "top_speed_pct": round(float(top_spd_pct) * 100) if top_spd_pct is not None else None,
        "bursts_over_20": int(bursts_val) if bursts_val is not None else None,
        "bursts_pct": round(float(bursts_pct) * 100) if bursts_pct is not None else None,
        "top_shot_mph": round(float(top_shot), 1) if top_shot is not None else None,
        "top_shot_pct": round(float(top_shot_pct) * 100) if top_shot_pct is not None else None,
        "distance_miles": round(float(dist_val), 1) if dist_val is not None else None,
        "distance_pct": round(float(dist_pct) * 100) if dist_pct is not None else None,
    }

    save_json(path, norm)
    return norm
