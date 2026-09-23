"""NHL salary cap data from CapWages (team wage pages + player pages)."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .disk_cache import cache_path, load_json, save_json
from .nhl_bio import _first_name_matches

logger = logging.getLogger(__name__)

CAP_CACHE_TTL = 86_400  # 24h disk cache for bulk / CI builds
LIVE_MEMORY_TTL = 60  # seconds — throttle live API hammering

CAPWAGES_BASE = "https://capwages.com/players"
CAPWAGES_TEAMS = "https://capwages.com/teams"
CAPWAGES_GATEWAY = "https://capwages.com/api/gateway/v1/players"

# In-process live throttle: cache_key → (expires_monotonic, payload)
_live_memory: dict[str, tuple[float, dict[str, Any]]] = {}
_team_page_memory: dict[str, tuple[float, dict[str, Any]]] = {}


class CapUnavailableError(RuntimeError):
    """CapWages gateway and page scrape both failed (transport / upstream down)."""


def _current_season_tag() -> str:
    try:
        from .leagues import detect_active_season

        return detect_active_season("nhl")[0]
    except Exception:
        return "2025-26"


CURRENT_SEASON = "2025-26"  # fallback; prefer _current_season_tag()


def _slugify(name: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", name.strip().lower())
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_name)
    return s.strip("-")


def _slug_candidates(name: str) -> list[str]:
    parts = name.split()
    if not parts:
        return []
    if len(parts) < 2:
        return [_slugify(name)]
    first, last = parts[0], parts[-1]
    slugs = [
        _slugify(name),
        _slugify(f"{first} {last}"),
        _slugify(f"{last} {first}"),
    ]
    if len(parts) > 2:
        surname_compound = " ".join(parts[1:])
        slugs.insert(1, _slugify(f"{first} {surname_compound}"))
        slugs.append(_slugify(f"{surname_compound} {first}"))
        slugs.append(_slugify(f"{first} {last}"))
    if _first_name_matches(first, "egor"):
        slugs.insert(0, _slugify(f"yegor {' '.join(parts[1:])}"))
        slugs.insert(1, _slugify(f"yegor {last}"))
    if _first_name_matches(first, "yegor"):
        slugs.append(_slugify(f"egor {' '.join(parts[1:])}"))
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


def _contract_seasons(contract: dict[str, Any]) -> list[str]:
    return [str(d.get("season", "")).strip() for d in (contract.get("details") or []) if d.get("season")]


def _season_row(contract: dict[str, Any], season: str | None = None) -> dict[str, Any] | None:
    season = season or _current_season_tag()
    for row in contract.get("details") or []:
        if str(row.get("season", "")).strip() == season:
            return row
    details = contract.get("details") or []
    return details[-1] if details else None


def _pick_active_and_extension(
    contracts: list[dict[str, Any]],
    season: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Choose the deal to display.

    CapWages posts new extensions on team pages as ``unconfirmed`` first — we
    treat those as authoritative (no waiting for confirmation). Prefer:
      1. Unconfirmed / newly listed extension (longest / latest expiry)
      2. Confirmed contract covering the current season
      3. Any remaining contract
    """
    season = season or _current_season_tag()
    if not contracts:
        return None, None

    unconfirmed = [c for c in contracts if c.get("unconfirmed")]
    extensions = [
        c
        for c in contracts
        if c.get("unconfirmed") or "extension" in str(c.get("type") or "").lower()
    ]

    def _expiry_key(c: dict[str, Any]) -> str:
        return _expiry_season(c) or ""

    # Newest signed extension wins (often listed first, unconfirmed).
    primary: dict[str, Any] | None = None
    if unconfirmed:
        primary = max(unconfirmed, key=_expiry_key)
    elif extensions:
        # Prefer future-dated extension over an older "Extension" that is just the current deal
        future = []
        covering = []
        for c in extensions:
            seasons = _contract_seasons(c)
            if seasons and seasons[0] > season:
                future.append(c)
            elif season in seasons:
                covering.append(c)
            else:
                future.append(c)
        pool = future or covering or extensions
        primary = max(pool, key=_expiry_key)

    if primary is None:
        covering = [c for c in contracts if season in _contract_seasons(c)]
        primary = covering[0] if covering else contracts[0]

    # Prior deal (e.g. remaining years before extension kicks in) as secondary.
    prior = None
    for c in contracts:
        if c is primary:
            continue
        if season in _contract_seasons(c):
            prior = c
            break
    if prior is None:
        for c in contracts:
            if c is not primary:
                prior = c
                break
    return primary, prior


def _market_projection(
    projections: list[dict[str, Any]] | None,
    *,
    player_slug: str | None = None,
) -> str | None:
    if not projections:
        return None
    rows = projections
    if player_slug:
        matched = [p for p in projections if str(p.get("slug") or "") == player_slug]
        if matched:
            rows = matched
    best = max(
        rows,
        key=lambda p: _parse_money(p.get("projectedCapHit")) or 0,
    )
    return format_usd_compact(best.get("projectedCapHit"))


def _ua_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }


def _fetch_gateway(slug: str) -> tuple[dict[str, Any] | None, bool]:
    """Returns (page_props, transport_error)."""
    api_key = os.getenv("CAPWAGES_API_KEY", "").strip()
    if not api_key:
        return None, False
    try:
        resp = httpx.get(
            f"{CAPWAGES_GATEWAY}/{slug}",
            headers={"x-api-key": api_key, "User-Agent": "PlayerCards/1.0"},
            timeout=20.0,
        )
        if resp.status_code == 404:
            return None, False
        if resp.status_code != 200:
            logger.warning("CapWages API HTTP %s for %s", resp.status_code, slug)
            return None, True
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            return {"player": data, "projections": data.get("projections")}, False
        return None, False
    except Exception as exc:
        logger.warning("CapWages API failed for %s: %s", slug, exc)
        return None, True


def _fetch_page(slug: str) -> tuple[dict[str, Any] | None, bool]:
    """Returns (page_props, transport_error)."""
    try:
        resp = httpx.get(
            f"{CAPWAGES_BASE}/{slug}",
            timeout=20.0,
            headers=_ua_headers(),
            follow_redirects=True,
        )
        if resp.status_code == 404:
            return None, False
        if resp.status_code != 200:
            logger.warning("CapWages page HTTP %s for %s", resp.status_code, slug)
            return None, True
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            resp.text,
            flags=re.S,
        )
        if not match:
            return None, False
        page = json.loads(match.group(1))
        return page.get("props", {}).get("pageProps") or {}, False
    except Exception as exc:
        logger.warning("CapWages page fetch failed for %s: %s", slug, exc)
        return None, True


def _fetch_page_props(slug: str) -> tuple[dict[str, Any] | None, str | None, bool]:
    """Prefer CapWages gateway when CAPWAGES_API_KEY is set; fall back to HTML scrape."""
    props, api_err = _fetch_gateway(slug)
    if props is not None:
        return props, "capwages_api", False

    props, page_err = _fetch_page(slug)
    if props is not None:
        return props, "capwages_page", False

    return None, None, bool(api_err or page_err)


def _team_slug_candidates(team: str | None) -> list[str]:
    if not team:
        return []
    tri = team.strip().upper()
    out: list[str] = []
    try:
        from .team_source import _team_capwages_slug

        slug = _team_capwages_slug(tri)
        if slug:
            out.append(slug)
    except Exception:
        pass
    # hyphen form sometimes used
    for s in list(out):
        out.append(s.replace("_", "-"))
    if re.fullmatch(r"[A-Z]{2,3}", tri):
        pass
    else:
        out.append(re.sub(r"[^a-z0-9]+", "_", team.strip().lower()).strip("_"))
    return list(dict.fromkeys(s for s in out if s))


def _fetch_team_page_props(team_slug: str) -> tuple[dict[str, Any] | None, bool]:
    cached = _team_page_memory.get(team_slug)
    if cached and time.monotonic() <= cached[0]:
        return dict(cached[1]), False
    try:
        resp = httpx.get(
            f"{CAPWAGES_TEAMS}/{team_slug}",
            timeout=20.0,
            headers=_ua_headers(),
            follow_redirects=True,
        )
        if resp.status_code == 404:
            return None, False
        if resp.status_code != 200:
            logger.warning("CapWages team HTTP %s for %s", resp.status_code, team_slug)
            return None, True
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            resp.text,
            flags=re.S,
        )
        if not match:
            return None, False
        page = json.loads(match.group(1))
        props = page.get("props", {}).get("pageProps") or {}
        _team_page_memory[team_slug] = (time.monotonic() + LIVE_MEMORY_TTL, dict(props))
        return props, False
    except Exception as exc:
        logger.warning("CapWages team page failed for %s: %s", team_slug, exc)
        return None, True


def _iter_team_roster_players(team_props: dict[str, Any]) -> list[dict[str, Any]]:
    players: list[dict[str, Any]] = []
    data = team_props.get("data") or {}
    for bucket in data.values():
        if isinstance(bucket, dict):
            for group in bucket.values():
                if isinstance(group, list):
                    players.extend(p for p in group if isinstance(p, dict) and p.get("slug"))
        elif isinstance(bucket, list):
            players.extend(p for p in bucket if isinstance(p, dict) and p.get("slug"))
    return players


def _match_team_player(
    team_props: dict[str, Any],
    *,
    player_name: str,
    player_id: int | None,
    player_slug: str | None = None,
) -> dict[str, Any] | None:
    slugs = set(_slug_candidates(player_name))
    if player_slug:
        slugs.add(player_slug)
    name_key = re.sub(r"[^a-z]", "", player_name.lower())
    for p in _iter_team_roster_players(team_props):
        if player_id is not None:
            try:
                if int(p.get("nhlId") or 0) == int(player_id):
                    return p
            except (TypeError, ValueError):
                pass
        if str(p.get("slug") or "") in slugs:
            return p
        raw_name = str(p.get("name") or "")
        # CapWages uses "Steel, Sam"
        if "," in raw_name:
            last, first = [x.strip() for x in raw_name.split(",", 1)]
            flipped = f"{first} {last}"
        else:
            flipped = raw_name
        if re.sub(r"[^a-z]", "", flipped.lower()) == name_key:
            return p
    return None


def _normalize_cap(
    page_props: dict[str, Any],
    *,
    player_id: int | None,
    source: str,
    player_override: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    player = player_override or page_props.get("player") or {}
    nhl_id_raw = player.get("nhlId")
    nhl_id: int | None = None
    if nhl_id_raw is not None:
        try:
            nhl_id = int(nhl_id_raw)
        except (TypeError, ValueError):
            nhl_id = None
    if player_id and nhl_id is not None and nhl_id != int(player_id):
        return None

    contracts = player.get("contracts") or []
    if not contracts:
        return None

    season = _current_season_tag()
    primary, prior = _pick_active_and_extension(contracts, season)
    if not primary:
        return None

    # Use primary deal AAV — for extensions that start later, fall back to first
    # season row / contract-level aav rather than requiring current-season coverage.
    season_row = _season_row(primary, season)
    if season_row is None and (primary.get("details") or []):
        season_row = primary["details"][0]
    aav = (season_row or {}).get("aav") or (season_row or {}).get("capHit") or primary.get("aav")
    aav_disp = format_usd_compact(aav)
    expiry_season = _expiry_season(primary)

    player_slug = player.get("slug")
    market_disp = _market_projection(page_props.get("projections"), player_slug=player_slug)
    if not aav_disp and not market_disp and not expiry_season:
        return None

    out: dict[str, Any] = {
        "source": source,
        "slug": player_slug,
        "nhl_id": nhl_id if nhl_id is not None else (int(player_id) if player_id else None),
        "team": player.get("currentTeamTricode") or (page_props.get("teamMetadata") or {}).get("tricode"),
        "aav": aav_disp,
        "market_value": market_disp or aav_disp,
        "expiry_season": expiry_season,
        "contract_type": primary.get("type"),
        "unconfirmed": bool(primary.get("unconfirmed")),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    terms = (player.get("termsDetails") or player.get("terms") or "").strip()
    if terms:
        out["terms_note"] = terms

    if prior and prior is not primary:
        prior_row = _season_row(prior, season) or ((prior.get("details") or [None])[0])
        out["prior_aav"] = format_usd_compact(
            (prior_row or {}).get("aav") or (prior_row or {}).get("capHit") or prior.get("aav")
        )
        out["prior_expiry"] = _expiry_season(prior)
        out["prior_type"] = prior.get("type")

    return out


def _memory_key(player_name: str, player_id: int | None, team: str | None = None) -> str:
    bits = []
    if player_id:
        bits.append(f"id:{int(player_id)}")
    else:
        bits.append(f"name:{player_name.strip().lower()}")
    if team:
        bits.append(f"team:{team.strip().upper()}")
    return "|".join(bits)


def _memory_get(key: str) -> dict[str, Any] | None:
    row = _live_memory.get(key)
    if not row:
        return None
    expires, payload = row
    if time.monotonic() > expires:
        _live_memory.pop(key, None)
        return None
    return dict(payload)


def _memory_set(key: str, payload: dict[str, Any]) -> None:
    _live_memory[key] = (time.monotonic() + LIVE_MEMORY_TTL, dict(payload))


def _cap_from_team(
    *,
    player_name: str,
    player_id: int | None,
    team: str | None,
    player_slug: str | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    """Try CapWages team wage page (signings/extensions land here first)."""
    any_transport = False
    for team_slug in _team_slug_candidates(team):
        props, terr = _fetch_team_page_props(team_slug)
        if terr:
            any_transport = True
        if not props:
            continue
        matched = _match_team_player(
            props,
            player_name=player_name,
            player_id=player_id,
            player_slug=player_slug,
        )
        if not matched:
            continue
        cap = _normalize_cap(
            props,
            player_id=player_id,
            source="capwages_team",
            player_override=matched,
        )
        if cap:
            return cap, any_transport
    return None, any_transport


def fetch_cap_info(
    player_name: str,
    player_id: int | None = None,
    *,
    live: bool = False,
    team: str | None = None,
) -> dict[str, Any] | None:
    """Return current contract / cap summary for a player.

    New signings/extensions usually appear on CapWages **team wage pages**
    before the global signings feed. When ``live=True`` (or ``team`` is set),
    we prefer the team roster contract block, then fall back to the player page.

    ``live=True`` skips the 24h disk cache (60s in-process throttle).
    Raises ``CapUnavailableError`` when CapWages is unreachable.
    """
    mem_key = _memory_key(player_name, player_id, team)

    if live:
        cached_live = _memory_get(mem_key)
        if cached_live and cached_live.get("aav"):
            return cached_live
    elif player_id:
        cached = load_json(cache_path("cap", f"{player_id}.json"), ttl_seconds=CAP_CACHE_TTL)
        if isinstance(cached, dict) and cached.get("aav"):
            return cached

    any_transport_error = False
    saw_reachable_miss = False
    player_slug: str | None = None
    team_hint = team

    # 1) Team wage page first when we know the club (freshest for extensions).
    if team_hint:
        cap, terr = _cap_from_team(
            player_name=player_name,
            player_id=player_id,
            team=team_hint,
        )
        any_transport_error = any_transport_error or terr
        if cap:
            if player_id:
                save_json(cache_path("cap", f"{player_id}.json"), cap)
            if live:
                _memory_set(mem_key, cap)
            return cap

    # 2) Player page / gateway — also discover team slug for a team-page pass.
    for slug in _slug_candidates(player_name):
        page_props, source, transport_error = _fetch_page_props(slug)
        if transport_error:
            any_transport_error = True
        if not page_props or not source:
            if page_props is None and not transport_error:
                saw_reachable_miss = True
            continue

        player = page_props.get("player") or {}
        player_slug = player.get("slug") or slug
        if not team_hint:
            team_hint = player.get("currentTeamTricode") or player.get("currentTeamSlug")

        # Prefer team roster merge once we know the club.
        if team_hint:
            cap, terr = _cap_from_team(
                player_name=player_name,
                player_id=player_id,
                team=str(team_hint),
                player_slug=player_slug,
            )
            any_transport_error = any_transport_error or terr
            if cap:
                if player_id:
                    save_json(cache_path("cap", f"{player_id}.json"), cap)
                if live:
                    _memory_set(mem_key, cap)
                return cap

        cap = _normalize_cap(page_props, player_id=player_id, source=source)
        if cap:
            if player_id:
                save_json(cache_path("cap", f"{player_id}.json"), cap)
            if live:
                _memory_set(mem_key, cap)
            return cap
        saw_reachable_miss = True

    if live and any_transport_error and not saw_reachable_miss:
        raise CapUnavailableError(
            f"CapWages unreachable for {player_name!r} (team + player paths failed)"
        )
    return None
