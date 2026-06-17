"""League registry: NHL (NHL API + A3Z + InStat) and PWHL (InStat only)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .instat_source import NHL_TEAM_SEARCH

# PWHL abbrevs are distinct from NHL to avoid MIN/MTL/TOR collisions.
PWHL_TEAM_SEARCH: dict[str, str] = {
    "BPF": "Boston Fleet",
    "MNF": "Minnesota Frost",
    "MVL": "Montreal Victoire",
    "NYS": "New York Sirens",
    "OTC": "Ottawa Charge",
    "TSR": "Toronto Sceptres",
}

PWHL_INSTAT_TEAM_IDS: dict[str, int] = {
    "BPF": 148641,
    "MNF": 148638,
    "MVL": 148640,
    "NYS": 148642,
    "OTC": 148637,
    "TSR": 148639,
}

PWHL_TEAM_COLORS: dict[str, dict[str, str]] = {
    "BPF": {"primary": "#111111", "accent": "#C8102E", "light": "#F5E8EB"},
    "MNF": {"primary": "#512698", "accent": "#78D5E8", "light": "#F0EBFA"},
    "MVL": {"primary": "#862633", "accent": "#C0A990", "light": "#F5EBED"},
    "NYS": {"primary": "#041E42", "accent": "#A2AAAD", "light": "#E8EDF5"},
    "OTC": {"primary": "#C52032", "accent": "#B9975B", "light": "#F5E8EB"},
    "TSR": {"primary": "#00205B", "accent": "#6CACE4", "light": "#E8EEFA"},
}

# Arizona (ARI) relocated to Utah; InStat lists the franchise as Utah Mammoth.
NHL_TEAM_ALIASES: dict[str, str] = {"ARI": "UTA"}

NHL_INSTAT_TEAM_IDS: dict[str, int] = {
    "ANA": 98,
    "BOS": 104,
    "BUF": 79,
    "CAR": 94,
    "CBJ": 81,
    "CGY": 105,
    "CHI": 86,
    "COL": 106,
    "DAL": 95,
    "DET": 91,
    "EDM": 102,
    "FLA": 87,
    "LAK": 84,
    "MIN": 92,
    "MTL": 78,
    "NJD": 93,
    "NSH": 85,
    "NYI": 83,
    "NYR": 88,
    "OTT": 99,
    "PHI": 67,
    "PIT": 89,
    "SEA": 108270,
    "SJS": 96,
    "STL": 103,
    "TBL": 80,
    "TOR": 90,
    "UTA": 148987,
    "VAN": 100,
    "VGK": 25174,
    "WPG": 101,
    "WSH": 68,
}

# InStat `_p_season_id` — men's NHL and PWHL 2025-26 both use 36 in our probe.
SEASON_TO_INSTAT: dict[str, int] = {
    "2025-26p": 36,
    "2025-26": 36,
    "2024-25p": 34,
    "2024-25": 34,
}

DEFAULT_SEASON = "2025-26"
DEFAULT_INSTAT_SEASON_ID = 36


@dataclass(frozen=True)
class LeagueConfig:
    key: str
    label: str
    teams: dict[str, str]
    instat_ids: dict[str, int]
    instat_gender: int  # 1 men, 2 women
    instat_search_suffix: str
    uses_a3z: bool
    uses_nhl_api: bool
    uses_cap: bool
    default_season: str
    work_dir_name: str


LEAGUES: dict[str, LeagueConfig] = {
    "nhl": LeagueConfig(
        key="nhl",
        label="NHL",
        teams=NHL_TEAM_SEARCH,
        instat_ids=NHL_INSTAT_TEAM_IDS,
        instat_gender=1,
        instat_search_suffix="men",
        uses_a3z=True,
        uses_nhl_api=True,
        uses_cap=True,
        default_season=DEFAULT_SEASON,
        work_dir_name="My Analytics Work",
    ),
    "pwhl": LeagueConfig(
        key="pwhl",
        label="PWHL",
        teams=PWHL_TEAM_SEARCH,
        instat_ids=PWHL_INSTAT_TEAM_IDS,
        instat_gender=2,
        instat_search_suffix="",
        uses_a3z=False,
        uses_nhl_api=False,
        uses_cap=False,
        default_season=DEFAULT_SEASON,
        work_dir_name="My Analytics Work/PWHL",
    ),
}


def normalize_team_abbrev(league: str | None, team_abbrev: str) -> str:
    tri = team_abbrev.upper()
    if (league or "nhl").strip().lower() == "nhl":
        return NHL_TEAM_ALIASES.get(tri, tri)
    return tri


def get_league(league: str | None) -> LeagueConfig:
    key = (league or "nhl").strip().lower()
    if key not in LEAGUES:
        raise ValueError(f"Unknown league: {league!r} (use nhl or pwhl)")
    return LEAGUES[key]


def team_full_name(league: str | None, team_abbrev: str) -> str:
    cfg = get_league(league)
    tri = normalize_team_abbrev(league, team_abbrev)
    return cfg.teams.get(tri, tri)


def instat_season_id(season: str | None, league: str | None = None) -> int:
    _ = league
    if not season:
        return DEFAULT_INSTAT_SEASON_ID
    key = season.strip()
    if key in SEASON_TO_INSTAT:
        return SEASON_TO_INSTAT[key]
    if key.endswith("p"):
        base = key[:-1]
        if base in SEASON_TO_INSTAT:
            return SEASON_TO_INSTAT[base]
    return DEFAULT_INSTAT_SEASON_ID


def player_cards_work_root() -> Path:
    """Root for team PBP caches (Desktop locally, repo path in CI)."""
    override = os.getenv("PLAYER_CARDS_WORK_ROOT", "").strip()
    if override:
        return Path(override)
    return Path.home() / "Desktop" / "My Analytics Work"


def pbp_cache_dir(league: str | None, team_abbrev: str) -> str:
    cfg = get_league(league)
    tri = normalize_team_abbrev(league, team_abbrev)
    full = cfg.teams.get(tri, tri)
    root = player_cards_work_root()
    if league == "pwhl":
        return str(root / "PWHL" / full / "Instat_API_Downloads")
    return str(root / full / "Instat_API_Downloads")


def list_teams(league: str | None = None) -> list[str]:
    cfg = get_league(league)
    return sorted(cfg.teams.keys())


async def resolve_instat_team_id(api, league: str | None, team_abbrev: str) -> int | None:
    cfg = get_league(league)
    tri = normalize_team_abbrev(league, team_abbrev)
    if tri in cfg.instat_ids:
        return cfg.instat_ids[tri]

    full = cfg.teams.get(tri)
    if not full:
        return None

    import json

    queries: list[str] = []
    if cfg.instat_search_suffix:
        queries.append(f"{full} {cfg.instat_search_suffix}")
    queries.append(full)
    if league == "nhl":
        queries.append(f"{full.split()[-1]} men")
        if tri == "UTA":
            queries.extend(["Utah Mammoth men", "Utah Hockey Club men"])

    for query in queries:
        try:
            resp = await api.api_call("scout_uni_search", {"_ps_any_text": query})
        except Exception:
            continue
        teams = (resp or {}).get("data", [{}])[0].get("scout_uni_search", {}).get("teams") or []
        parsed = []
        for res in teams:
            if isinstance(res, str):
                try:
                    res = json.loads(res)
                except Exception:
                    continue
            if isinstance(res, dict):
                parsed.append(res)
        for t in parsed:
            name = (t.get("name_eng") or "").strip()
            if name.lower() == full.lower() and t.get("gender") == cfg.instat_gender:
                cfg.instat_ids[tri] = int(t["id"])
                return int(t["id"])
        for t in parsed:
            if t.get("gender") != cfg.instat_gender:
                continue
            name = (t.get("name_eng") or "").lower()
            if full.lower() in name or name.startswith(full.split()[0].lower()):
                cfg.instat_ids[tri] = int(t["id"])
                return int(t["id"])

    team_id = await api.find_team_by_name(queries[0] if queries else full)
    if team_id:
        cfg.instat_ids[tri] = int(team_id)
        return int(team_id)
    return None
