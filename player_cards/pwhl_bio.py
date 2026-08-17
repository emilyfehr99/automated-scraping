"""PWHL player bio — derived from InStat PBP + HockeyTech headshots."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .leagues import PWHL_HOCKEYTECH_TEAM_IDS, _ascii_fold, get_league, team_full_name
from .pbp_team_cache import get_team_frames, warm_team_pbp
from .pwhl_photos import _display_name, lookup_pwhl_player, presentation_name, refresh_pwhl_bio, search_pwhl_player


def _slug_id(name: str, team: str) -> int:
    digest = hashlib.sha1(f"pwhl:{team}:{name}".encode()).hexdigest()
    return int(digest[:9], 16)


def pwhl_team_logo_png_url(team_abbrev: str) -> str | None:
    """LeagueStat CDN team mark (HockeyTech team id)."""
    ht_id = PWHL_HOCKEYTECH_TEAM_IDS.get(team_abbrev.upper())
    if not ht_id:
        return None
    return f"https://assets.leaguestat.com/pwhl/logos/{ht_id}.png"


def _is_team_match(pbp_team_name: str, query_team_name: str) -> bool:
    # Raw PBP CSVs often drop diacritics (e.g. "Brynas IF" for "Brynäs IF") -
    # fold both sides so accented team names still match.
    p_name = _ascii_fold(pbp_team_name.lower().strip())
    q_name = _ascii_fold(query_team_name.lower().strip())
    if q_name == p_name:
        return True
    if q_name.startswith("usa") or "usntdp" in q_name:
        return "usa" in p_name or "usntdp" in p_name or "u.s. national" in p_name
    q_first = q_name.split()[0]
    if len(q_first) >= 3:
        return q_first in p_name
    return q_name in p_name


def roster_from_pbp(files: list[Path], team_abbrev: str, *, league: str = "pwhl") -> list[dict[str, Any]]:
    """Unique skater names from team PBP files."""
    cfg = get_league(league)
    # Prospect clubs are full names ("Everett Silvertips"); don't force .upper()
    # into cfg.teams lookups that only exist for NHL/PWHL tris.
    tri = team_abbrev if league == "prospect" else team_abbrev.upper()
    team_full = cfg.teams.get(tri.upper() if league != "prospect" else tri, tri)
    if league == "prospect":
        team_full = team_abbrev
    warm_team_pbp(files)
    from collections import Counter
    player_games = Counter()
    for _path, df in get_team_frames(files):
        if "player" not in df.columns:
            continue
        team_mask = df["team"].astype(str).apply(lambda x: _is_team_match(x, team_full))
        sub = df.loc[team_mask, "player"].astype(str).str.strip()
        for raw in sub.unique():
            if not raw or raw.lower() == "nan":
                continue
            if "shift" in raw.lower():
                continue
            # InStat is usually Last First; _display_name → First Last for card keys.
            player_games[_display_name(raw)] += 1

    # Prospects / junior teams often have thin samples — keep modest floor.
    min_gp = 3 if league == "prospect" else 5
    names = [
        name
        for name, gp in sorted(player_games.items(), key=lambda kv: (-kv[1], kv[0]))
        if gp >= min_gp
    ]
    return [
        {
            "player_id": _slug_id(name, tri),
            "name": name,
            "team": tri,
            "league": league,
            "games": int(player_games[name]),
        }
        for name in names
    ]


def fetch_pwhl_bio(
    player_name: str,
    team: str | None = None,
    *,
    league: str = "pwhl",
    files: list[Path] | None = None,
) -> dict[str, Any]:
    cfg = get_league(league)
    tri = (team or "").upper()
    if not tri:
        raise LookupError(f"Team required for PWHL player {player_name!r}")

    team_full = team_full_name(league, tri)
    instat_name = player_name.strip()
    if files:
        roster = roster_from_pbp(files, tri, league=league)
        target = player_name.lower()
        for entry in roster:
            if entry["name"].lower() == target or target in entry["name"].lower():
                instat_name = entry["name"]
                break
            parts = target.split()
            if parts and parts[-1] in entry["name"].lower():
                instat_name = entry["name"]
                break

    meta = lookup_pwhl_player(instat_name, tri, league=league)
    if not meta:
        found = search_pwhl_player(player_name)
        if found:
            tri = str(found.get("team") or tri).upper()
            meta = lookup_pwhl_player(str(found.get("name") or player_name), tri, league=league)
    display_name = meta["name"] if meta else presentation_name(instat_name)
    player_id = meta.get("player_id") if meta else _slug_id(instat_name, tri)
    ht_player_id = (meta or {}).get("ht_player_id")
    photo_url = (meta or {}).get("card_photo_url")
    photo_kind = (meta or {}).get("card_photo_kind") or ("mug" if photo_url else "placeholder")

    logo_png = pwhl_team_logo_png_url(tri)

    bio = {
        "player_id": player_id,
        "ht_player_id": ht_player_id,
        "name": display_name,
        "instat_name": instat_name,
        "team": tri,
        "league": league,
        "position": (meta or {}).get("position") or "",
        "sweater_number": (meta or {}).get("sweater_number"),
        "height": (meta or {}).get("height"),
        "weight_lbs": None,
        "shoots": (meta or {}).get("shoots"),
        "headshot_url": (meta or {}).get("headshot_url"),
        "hero_image_url": None,
        "card_photo_url": photo_url,
        "card_photo_kind": photo_kind,
        "photo_width": (meta or {}).get("photo_width"),
        "photo_height": (meta or {}).get("photo_height"),
        "team_logo_url": logo_png,
        "team_logo_png_url": logo_png,
        "birth_city": None,
        "birth_country": None,
        "team_full": team_full,
    }
    return refresh_pwhl_bio(bio)
