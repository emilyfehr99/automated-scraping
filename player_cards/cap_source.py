"""NHL salary cap data from CapWages (public player pages)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

from .disk_cache import cache_path, load_json, save_json
from .nhl_bio import _first_name_matches

logger = logging.getLogger(__name__)

CAP_CACHE_TTL = 86_400  # 24h

CAPWAGES_BASE = "https://capwages.com/players"
CURRENT_SEASON = "2025-26"


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower())
    return s.strip("-")


def _slug_candidates(name: str) -> list[str]:
    parts = name.split()
    if len(parts) < 2:
        return [_slugify(name)]
    first, last = parts[0], parts[-1]
    slugs = [
        _slugify(f"{first} {last}"),
        _slugify(f"{last} {first}"),
    ]
    if _first_name_matches(first, "egor"):
        slugs.insert(0, _slugify(f"yegor {last}"))
    if _first_name_matches(first, "yegor"):
        slugs.append(_slugify(f"egor {last}"))
    return list(dict.fromkeys(s for s in slugs if s))


def _parse_money(raw: str | None) -> float | None:
    if not raw:
        return None
    digits = re.sub(r"[^\d.]", "", str(raw))
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def format_usd_compact(raw: str | float | int | None) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        amount = float(raw)
    else:
        amount = _parse_money(str(raw))
        if amount is None:
            text = str(raw).strip()
            return text or None
    if amount >= 1_000_000:
        millions = amount / 1_000_000
        text = f"${millions:.2f}M"
        return text.replace(".00M", "M")
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:,.0f}"


def _expiry_season(contract: dict[str, Any]) -> str | None:
    details = contract.get("details") or []
    if not details:
        return None
    season = str(details[-1].get("season", "")).strip()
    return season or None


def _market_projection(projections: list[dict[str, Any]] | None) -> str | None:
    if not projections:
        return None
    best = max(
        projections,
        key=lambda p: _parse_money(p.get("projectedCapHit")) or 0,
    )
    return format_usd_compact(best.get("projectedCapHit"))


def _fetch_page_props(slug: str) -> dict[str, Any] | None:
    api_key = os.getenv("CAPWAGES_API_KEY", "").strip()
    if api_key:
        try:
            resp = httpx.get(
                f"https://capwages.com/api/gateway/v1/players/{slug}",
                headers={"x-api-key": api_key, "User-Agent": "PlayerCards/1.0"},
                timeout=20.0,
            )
            if resp.status_code == 200:
                payload = resp.json()
                data = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(data, dict):
                    return {"player": data, "projections": data.get("projections")}
        except Exception as exc:
            logger.warning("CapWages API failed for %s: %s", slug, exc)

    try:
        resp = httpx.get(
            f"{CAPWAGES_BASE}/{slug}",
            timeout=20.0,
            headers={"User-Agent": "PlayerCards/1.0"},
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            resp.text,
            flags=re.S,
        )
        if not match:
            return None
        page = json.loads(match.group(1))
        return page.get("props", {}).get("pageProps") or {}
    except Exception as exc:
        logger.warning("CapWages page fetch failed for %s: %s", slug, exc)
        return None


def _season_row(contract: dict[str, Any], season: str = CURRENT_SEASON) -> dict[str, Any] | None:
    for row in contract.get("details") or []:
        if str(row.get("season", "")).strip() == season:
            return row
    details = contract.get("details") or []
    return details[-1] if details else None


def _normalize_cap(page_props: dict[str, Any], *, player_id: int | None) -> dict[str, Any] | None:
    player = page_props.get("player") or {}
    if player_id and player.get("nhlId") and int(player["nhlId"]) != int(player_id):
        return None

    contracts = player.get("contracts") or []
    if not contracts:
        return None
    contract = contracts[0]
    season_row = _season_row(contract)
    aav = (season_row or {}).get("aav") or contract.get("aav")
    aav_disp = format_usd_compact(aav)
    market_disp = _market_projection(page_props.get("projections"))
    expiry_season = _expiry_season(contract)
    if not aav_disp and not market_disp and not expiry_season:
        return None

    return {
        "source": "capwages",
        "slug": player.get("slug"),
        "aav": aav_disp,
        "market_value": market_disp,
        "expiry_season": expiry_season,
    }


def fetch_cap_info(player_name: str, player_id: int | None = None) -> dict[str, Any] | None:
    """Return current contract / cap summary for a player."""
    if player_id:
        cached = load_json(cache_path("cap", f"{player_id}.json"), ttl_seconds=CAP_CACHE_TTL)
        if isinstance(cached, dict) and cached.get("aav"):
            return cached

    for slug in _slug_candidates(player_name):
        page_props = _fetch_page_props(slug)
        if not page_props:
            continue
        cap = _normalize_cap(page_props, player_id=player_id)
        if cap:
            if player_id:
                save_json(cache_path("cap", f"{player_id}.json"), cap)
            return cap
    return None
