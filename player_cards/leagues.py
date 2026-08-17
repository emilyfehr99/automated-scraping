"""League registry: NHL (NHL API + A3Z + InStat) and PWHL (InStat only)."""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .instat_source import NHL_TEAM_SEARCH


def _ascii_fold(s: str) -> str:
    """Strip diacritics — InStat's search index doesn't match accented text
    (e.g. querying "Genève-Servette" returns nothing, but "Geneve-Servette" hits)."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")

# PWHL abbrevs are distinct from NHL to avoid MIN/MTL/TOR collisions.
PWHL_TEAM_SEARCH: dict[str, str] = {
    "BPF": "Boston Fleet",
    "MNF": "Minnesota Frost",
    "MVL": "Montreal Victoire",
    "NYS": "New York Sirens",
    "OTC": "Ottawa Charge",
    "STT": "Seattle Torrent",
    "TSR": "Toronto Sceptres",
    "VGE": "Vancouver Goldeneyes",
}

PWHL_INSTAT_TEAM_IDS: dict[str, int] = {
    "BPF": 148641,
    "MNF": 148638,
    "MVL": 148640,
    "NYS": 148642,
    "OTC": 148637,
    "STT": 1165880,
    "TSR": 148639,
    "VGE": 1165881,
}

PROSPECT_INSTAT_TEAM_IDS: dict[str, int] = {
    "ERIE": 105,
    "SAGINAW": 128,
    "MEDICINE HAT": 156,
    "FROLUNDA": 18340,
    "HV71 JR.": 24654,
    "SPOKANE": 165,
    "PENTICTON": 178,
    "BRAMPTON": 121, # Mississauga/Brampton Steelheads
    "SUDBURY": 130,
    "KITCHENER": 114,
    "OSHAWA": 120,
    "OWEN SOUND": 124,
    "CALGARY": 147,
    "KELOWNA": 153,
    "KAMLOOPS": 152,
    "PETERBOROUGH": 123,
    "LEKSAND JR.": 24651,
    "LONDON": 116,
    "DJURGARDEN JR.": 24653,
    "TAPPARA": 18338,
    "YOUNGSTOWN": 279,
    "MONCTON": 139,
    "FROLUNDA JR.": 24652,
    "PRINCE GEORGE": 157,
    "BRANTFORD": 104,
    "VANCOUVER": 169,
    "BARRIE": 102,
    "PENN STATE": 295,
    "NORTH DAKOTA": 326,
    "USA U-18": 277,
    "OREBRO JR.": 24662,
    "EVERETT SILVERTIPS": 151,
    "EVERETT": 151,
    "REGINA PATS": 167,
    "REGINA": 167,
    # SMAAAHL U18 AAA — resolved via scout_uni_search (gender=1)
    "REGINA PAT CANADIANS U18 AAA": 104849,
    "REGINA PAT CANADIANS": 104849,
    "PAT CANADIANS": 104849,
}

# HockeyTech / LeagueStat (assets.leaguestat.com/pwhl/{size}/{player_id}.jpg)
PWHL_HOCKEYTECH_SEASON = 8
PWHL_HOCKEYTECH_TEAM_IDS: dict[str, str] = {
    "BPF": "1",
    "MNF": "2",
    "MVL": "3",
    "NYS": "4",
    "OTC": "5",
    "TSR": "6",
    "STT": "8",
    "VGE": "9",
}

PWHL_TEAM_COLORS: dict[str, dict[str, str]] = {
    # Canonical PWHL brand primaries (aligned with pwhl-analytics teamColors.ts)
    "BPF": {"primary": "#173F35", "accent": "#4A8F87", "light": "#E8F2F0"},
    "MNF": {"primary": "#250E62", "accent": "#9880B8", "light": "#EDE8F8"},
    "MVL": {"primary": "#862633", "accent": "#C0A990", "light": "#F5EBED"},
    "NYS": {"primary": "#00BAB3", "accent": "#041E42", "light": "#E6FAF9"},
    "OTC": {"primary": "#A6192E", "accent": "#FDB827", "light": "#F5E8EB"},
    "TSR": {"primary": "#0067B9", "accent": "#FDB827", "light": "#E8F2FA"},
    "STT": {"primary": "#00A3AD", "accent": "#041E42", "light": "#E6FAFA"},
    "VGE": {"primary": "#FDB827", "accent": "#041E42", "light": "#FFF8E6"},
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
    "prospect": LeagueConfig(
        key="prospect",
        label="Prospect",
        teams={},
        instat_ids=PROSPECT_INSTAT_TEAM_IDS,
        instat_gender=1,
        instat_search_suffix="men",
        uses_a3z=False,
        uses_nhl_api=True,
        uses_cap=False,
        default_season=DEFAULT_SEASON,
        work_dir_name="My Analytics Work/Prospects",
    ),
}


def normalize_team_abbrev(league: str | None, team_abbrev: str) -> str:
    if (league or "nhl").strip().lower() == "prospect":
        return team_abbrev  # Preserve amateur club name casing and spaces
    tri = team_abbrev.upper()
    if (league or "nhl").strip().lower() == "nhl":
        return NHL_TEAM_ALIASES.get(tri, tri)
    return tri


def get_league(league: str | None) -> LeagueConfig:
    key = (league or "nhl").strip().lower()
    if key not in LEAGUES:
        raise ValueError(f"Unknown league: {league!r} (use nhl, pwhl, or prospect)")
    return LEAGUES[key]


def team_full_name(league: str | None, team_abbrev: str) -> str:
    cfg = get_league(league)
    if league == "prospect":
        return team_abbrev
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


def min_season_games(league: str | None) -> int:
    """Minimum team-game CSV count for a complete season PBP cache."""
    key = (league or "nhl").lower()
    if key == "pwhl":
        return 25
    # WHL dual-roster / U18 prospects often play ~20-40 games; don't require 70.
    if key == "prospect":
        return 20
    return 70


def pbp_cache_dir(league: str | None, team_abbrev: str) -> str:
    cfg = get_league(league)
    tri = normalize_team_abbrev(league, team_abbrev)
    full = cfg.teams.get(tri, tri)
    root = player_cards_work_root()
    if league == "pwhl":
        return str(root / "PWHL" / full / "Instat_API_Downloads")
    if league == "prospect":
        # Match existing Desktop caches (REGINA PATS, EVERETT SILVERTIPS, …).
        return str(root / "Prospects" / str(full).upper() / "Instat_API_Downloads")
    return str(root / full / "Instat_API_Downloads")


def list_teams(league: str | None = None) -> list[str]:
    cfg = get_league(league)
    return sorted(cfg.teams.keys())


def _prospect_instat_id_lookup(cfg: LeagueConfig, tri: str) -> int | None:
    """Case-insensitive lookup for prospect InStat team IDs (exact / compact only)."""
    if tri in cfg.instat_ids:
        return int(cfg.instat_ids[tri])
    up = tri.upper().strip()
    if up in cfg.instat_ids:
        return int(cfg.instat_ids[up])
    # "Regina Pat Canadians U18 AAA" → "REGINA PAT CANADIANS"
    compact = " ".join(up.replace(" U18 AAA", "").replace(" U18", "").replace(" AAA", "").split())
    if compact in cfg.instat_ids:
        return int(cfg.instat_ids[compact])
    return None


def _prospect_search_queries(full: str) -> list[str]:
    """Build InStat scout search queries for junior / U18 club names.

    Note: appending \"men\" often returns null for U18 AAA clubs — try bare names first.
    """
    import re

    base = _ascii_fold(full).strip()
    stripped = re.sub(r"\s+U-?\d+\s*AAA\b", "", base, flags=re.I)
    stripped = re.sub(r"\s+AAA\b", "", stripped, flags=re.I).strip()
    stripped = re.sub(r"\s+", " ", stripped)
    queries: list[str] = []
    for q in (
        base,
        stripped if stripped and stripped.lower() != base.lower() else "",
        "Regina Pat Canadians" if "canadians" in base.lower() else "",
        "Pat Canadians" if "canadians" in base.lower() else "",
        f"{stripped} men" if stripped else "",
        f"{base} men",
    ):
        q = (q or "").strip()
        if q and q not in queries:
            queries.append(q)
    return queries


async def resolve_instat_team_id(api, league: str | None, team_abbrev: str) -> int | None:
    cfg = get_league(league)
    tri = normalize_team_abbrev(league, team_abbrev)
    if league == "prospect":
        hit = _prospect_instat_id_lookup(cfg, tri)
        if hit is not None:
            return hit
    elif tri in cfg.instat_ids:
        return cfg.instat_ids[tri]

    if league == "prospect":
        full = tri
    else:
        full = cfg.teams.get(tri)
        if not full:
            return None
    full = _ascii_fold(full)

    import json

    if league == "prospect":
        queries = _prospect_search_queries(full)
    else:
        queries = []
        if cfg.instat_search_suffix:
            queries.append(f"{full} {cfg.instat_search_suffix}")
        queries.append(full)
        if league == "nhl":
            queries.append(f"{full.split()[-1]} men")
            if tri == "UTA":
                queries.extend(["Utah Mammoth men", "Utah Hockey Club men"])

    def _remember(tid: int) -> int:
        cfg.instat_ids[tri] = tid
        cfg.instat_ids[str(tri).upper()] = tid
        return tid

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
        needles = {full.lower(), *(q.lower() for q in queries)}
        for t in parsed:
            name = (t.get("name_eng") or "").strip()
            if name.lower() in needles and t.get("gender") == cfg.instat_gender:
                return _remember(int(t["id"]))
        for t in parsed:
            if t.get("gender") != cfg.instat_gender:
                continue
            name = (t.get("name_eng") or "").lower()
            if any(n in name or name in n for n in needles if len(n) >= 8):
                return _remember(int(t["id"]))
            if full.lower() in name or name.startswith(full.split()[0].lower()):
                return _remember(int(t["id"]))

    # find_team_by_name defaults to women's gender — only use for non-prospect,
    # or force a men-suffixed query for prospects.
    search_q = queries[0] if queries else full
    if league == "prospect" and "men" not in search_q.lower():
        search_q = f"{search_q} men"
    team_id = await api.find_team_by_name(search_q)
    if team_id:
        return _remember(int(team_id))
    return None
