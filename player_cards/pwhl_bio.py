"""PWHL player bio — derived from InStat PBP (no NHL API)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .leagues import get_league, team_full_name
from .pbp_team_cache import get_team_frames, warm_team_pbp


def _slug_id(name: str, team: str) -> int:
    digest = hashlib.sha1(f"pwhl:{team}:{name}".encode()).hexdigest()
    return int(digest[:9], 16)


def _flip_name(name: str) -> str:
    parts = name.strip().split()
    if len(parts) >= 2 and parts[0][0].isupper() and parts[-1][0].isupper():
        return name
    if len(parts) >= 2:
        return f"{parts[-1]} {' '.join(parts[:-1])}"
    return name


def roster_from_pbp(files: list[Path], team_abbrev: str, *, league: str = "pwhl") -> list[dict[str, Any]]:
    """Unique skater names from team PBP files."""
    cfg = get_league(league)
    tri = team_abbrev.upper()
    team_full = cfg.teams.get(tri, tri)
    nick = team_full.split()[-1]
    warm_team_pbp(files)
    names: set[str] = set()
    for _path, df in get_team_frames(files):
        if "player" not in df.columns:
            continue
        team_mask = df["team"].astype(str).str.contains(nick, case=False, na=False)
        sub = df.loc[team_mask, "player"].astype(str).str.strip()
        for raw in sub.unique():
            if not raw or raw.lower() == "nan":
                continue
            if "shift" in raw.lower():
                continue
            names.add(_flip_name(raw))
    return [
        {
            "player_id": _slug_id(name, tri),
            "name": name,
            "team": tri,
            "league": league,
        }
        for name in sorted(names)
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
    resolved_name = player_name
    if files:
        roster = roster_from_pbp(files, tri, league=league)
        target = player_name.lower()
        for entry in roster:
            if entry["name"].lower() == target or target in entry["name"].lower():
                resolved_name = entry["name"]
                break
            parts = target.split()
            if parts and parts[-1] in entry["name"].lower():
                resolved_name = entry["name"]
                break

    return {
        "player_id": _slug_id(resolved_name, tri),
        "name": resolved_name,
        "team": tri,
        "league": league,
        "position": "",
        "sweater_number": None,
        "height": None,
        "weight_lbs": None,
        "shoots": None,
        "headshot_url": None,
        "hero_image_url": None,
        "card_photo_url": None,
        "card_photo_kind": "placeholder",
        "team_logo_url": None,
        "team_logo_png_url": None,
        "birth_city": None,
        "birth_country": None,
        "team_full": team_full,
    }
