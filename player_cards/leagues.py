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
# Prefer detect_pwhl_hockeytech_season() — this constant is a fallback only.
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

# InStat `_p_season_id` — men's NHL and PWHL season IDs
SEASON_TO_INSTAT: dict[str, int] = {
    "2026-27p": 38,
    "2026-27": 38,
    "2025-26p": 36,
    "2025-26": 36,
    "2024-25p": 34,
    "2024-25": 34,
}

def _default_season_from_date() -> str:
    """Derive current season tag from today's date (October rollover, no API call)."""
    import datetime as _dt
    today = _dt.date.today()
    yr = today.year if today.month >= 10 else today.year - 1
    return f"{yr}-{str(yr + 1)[-2:]}"


DEFAULT_SEASON = os.getenv("PLAYER_CARDS_SEASON", _default_season_from_date()).strip()
DEFAULT_INSTAT_SEASON_ID = int(os.getenv("INSTAT_SEASON_ID", "0").strip() or "0") or SEASON_TO_INSTAT.get(DEFAULT_SEASON, 36)


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
        uses_a3z=False,  # NHL cards use InStat PBP microstats (see qoc_qot.compute_microstat_game_score)
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
    "pwhl_prospect": LeagueConfig(
        key="pwhl_prospect",
        label="PWHL Prospect",
        teams={},
        instat_ids=PROSPECT_INSTAT_TEAM_IDS,
        instat_gender=2,
        instat_search_suffix="women",
        uses_a3z=False,
        uses_nhl_api=False,
        uses_cap=False,
        default_season=DEFAULT_SEASON,
        work_dir_name="My Analytics Work/PWHL_Prospects",
    ),
}


def _bootstrap_season_fallback() -> tuple[str, int]:
    """Compute a best-guess season tag from the current date (no API call).
    NHL seasons start in October; before October we're in the previous season.
    """
    import datetime as _dt
    today = _dt.date.today()
    start_yr = today.year if today.month >= 10 else today.year - 1
    tag = f"{start_yr}-{str(start_yr + 1)[-2:]}"
    # Inline InStat ID formula (avoids forward-ref to instat_season_id)
    sid = SEASON_TO_INSTAT.get(tag, 36 + (start_yr - 2025) * 2)
    return tag, sid


_SEASON_DETECTION_CACHE: dict[str, Any] = {"time": 0.0, "result": _bootstrap_season_fallback()}
_PWHL_SEASON_CACHE: dict[str, Any] = {"time": 0.0, "result": PWHL_HOCKEYTECH_SEASON}


def season_tag_from_nhl_id(raw_sid: str | int) -> str:
    """Convert NHL API season id (20252026) to tag (2025-26)."""
    text = str(raw_sid).strip()
    if len(text) == 8 and text.isdigit():
        yr = int(text[:4])
        return f"{yr}-{str(yr + 1)[-2:]}"
    if "-" in text:
        return text
    raise ValueError(f"Unrecognized NHL season id: {raw_sid!r}")


def nhl_api_season_id(season_tag: str | None = None) -> str:
    """Convert tag (2025-26) to NHL API season id (20252026)."""
    tag = (season_tag or detect_active_season("nhl")[0]).strip()
    if len(tag) == 8 and tag.isdigit():
        return tag
    start = int(tag.split("-")[0])
    return f"{start}{start + 1}"


def prior_season_tag(season_tag: str | None = None) -> str:
    """Previous season tag (2025-26 → 2024-25)."""
    tag = (season_tag or detect_active_season("nhl")[0]).strip()
    if tag.endswith("p"):
        tag = tag[:-1]
    start = int(tag.split("-")[0])
    return f"{start - 1}-{str(start)[-2:]}"


def a3z_min_team_gp() -> int:
    """A3Z current-season data is unreliable until this many team GP."""
    raw = os.getenv("A3Z_MIN_TEAM_GP", "30").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 30


def nhl_standings_gp_for_season(season_tag: str | None = None) -> int | None:
    """Sum of gamesPlayed from standings/now when it matches the active season."""
    tag = season_tag or detect_active_season("nhl")[0]
    want = nhl_api_season_id(tag)
    data = _http_json("https://api-web.nhle.com/v1/standings/now", timeout=8.0)
    if not isinstance(data, dict):
        return None
    standings = data.get("standings") or []
    if not standings:
        return None
    got = str((standings[0] or {}).get("seasonId") or "")
    if got != want:
        return 0
    return sum(int(row.get("gamesPlayed") or 0) for row in standings)


def a3z_current_season_ready(
    season_tag: str | None = None,
    *,
    team_games: int | None = None,
) -> bool:
    """True once enough GP exist for current-season A3Z to be usable.

    Gate: team_games >= A3Z_MIN_TEAM_GP when known, else league standings
    imply at least that many GP for a typical team (sum/32).
    """
    min_gp = a3z_min_team_gp()
    if min_gp <= 0:
        return True
    if team_games is not None:
        return int(team_games) >= min_gp
    total = nhl_standings_gp_for_season(season_tag)
    if total is None:
        return False
    # Approximate per-team GP from league total.
    return (total / 32.0) >= min_gp


def _http_json(url: str, *, timeout: float = 12.0) -> Any:
    """JSON GET with httpx when available, else stdlib urllib."""
    try:
        import httpx

        r = httpx.get(url, follow_redirects=True, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    try:
        import json
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "PlayerCards/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _detect_nhl_season_from_calendar() -> tuple[str, int] | None:
    """Pick active NHL season from standings-season start/end dates."""
    from datetime import date

    data = _http_json("https://api-web.nhle.com/v1/standings-season", timeout=8.0)
    if not isinstance(data, dict):
        return None
    seasons = data.get("seasons") or []
    if not seasons:
        return None

    today_raw = str(data.get("currentDate") or "")
    try:
        today = date.fromisoformat(today_raw[:10]) if today_raw else date.today()
    except ValueError:
        today = date.today()

    parsed: list[tuple[int, date, date]] = []
    for row in seasons:
        raw_id = row.get("id")
        try:
            sid_int = int(raw_id)
            start = date.fromisoformat(str(row.get("standingsStart"))[:10])
            end = date.fromisoformat(str(row.get("standingsEnd"))[:10])
        except Exception:
            continue
        parsed.append((sid_int, start, end))
    if not parsed:
        return None

    # Exact window (regular season in progress).
    for sid_int, start, end in sorted(parsed, key=lambda x: x[0], reverse=True):
        if start <= today <= end:
            tag = season_tag_from_nhl_id(sid_int)
            return tag, instat_season_id(tag, "nhl")

    # Offseason: keep the latest season that has already started.
    started = [p for p in parsed if p[1] <= today]
    if started:
        sid_int = max(started, key=lambda x: x[0])[0]
        tag = season_tag_from_nhl_id(sid_int)
        return tag, instat_season_id(tag, "nhl")

    # Pre-history fallback: earliest upcoming season.
    sid_int = min(parsed, key=lambda x: x[0])[0]
    tag = season_tag_from_nhl_id(sid_int)
    return tag, instat_season_id(tag, "nhl")


def _detect_nhl_season_from_standings() -> tuple[str, int] | None:
    """Use standings/now when the league has rolled and games exist."""
    data = _http_json("https://api-web.nhle.com/v1/standings/now", timeout=8.0)
    if not isinstance(data, dict):
        return None
    st = data.get("standings") or []
    if not st:
        return None
    raw_sid = str(st[0].get("seasonId") or "")
    if len(raw_sid) != 8 or not raw_sid.isdigit():
        return None
    # Trust standings season id once any team has played, or always if calendar failed.
    gp = sum(int(row.get("gamesPlayed") or 0) for row in st)
    if gp <= 0:
        return None
    tag = season_tag_from_nhl_id(raw_sid)
    return tag, instat_season_id(tag, "nhl")


def detect_active_season(league: str | None = "nhl") -> tuple[str, int]:
    """Detect current active season dynamically (with 5-minute memory TTL).

    Uses the NHL standings-season calendar so rollover happens on the new
    season's start date (even at 0 GP), not only after the first game.
    Override with PLAYER_CARDS_SEASON / INSTAT_SEASON_ID when needed.
    """
    env_season = os.getenv("PLAYER_CARDS_SEASON", "").strip()
    env_instat = os.getenv("INSTAT_SEASON_ID", "").strip()
    if env_season:
        sid = int(env_instat) if env_instat.isdigit() else instat_season_id(env_season, league)
        return env_season, sid

    import time

    now = time.time()
    if now - _SEASON_DETECTION_CACHE["time"] < 300.0:
        return _SEASON_DETECTION_CACHE["result"]

    key = (league or "nhl").strip().lower()
    detected: tuple[str, int] | None = None
    if key in ("nhl", "prospect", ""):
        detected = _detect_nhl_season_from_calendar() or _detect_nhl_season_from_standings()
    elif key == "pwhl":
        # PWHL InStat season tags track the same year label as NHL.
        detected = _detect_nhl_season_from_calendar() or _detect_nhl_season_from_standings()

    if detected:
        _SEASON_DETECTION_CACHE["time"] = now
        _SEASON_DETECTION_CACHE["result"] = detected
        return detected

    _SEASON_DETECTION_CACHE["time"] = now
    return _SEASON_DETECTION_CACHE["result"]


def detect_pwhl_hockeytech_season() -> int:
    """Active PWHL HockeyTech regular-season id (auto-advances each year)."""
    import time

    now = time.time()
    if now - _PWHL_SEASON_CACHE["time"] < 300.0:
        return int(_PWHL_SEASON_CACHE["result"])

    data = _http_json(
        "https://lscluster.hockeytech.com/feed/"
        "?feed=modulekit&view=seasons&key=446521baf8c38984&client_code=pwhl&fmt=json",
        timeout=15.0,
    )
    seasons = ((data or {}).get("SiteKit") or {}).get("Seasons") or []
    nhl_tag, _ = detect_active_season("nhl")
    start_yr = nhl_tag.split("-")[0] if "-" in nhl_tag else ""

    chosen: int | None = None
    for row in seasons:
        name = str(row.get("season_name") or "")
        if "Regular Season" not in name:
            continue
        try:
            sid = int(row.get("season_id"))
        except Exception:
            continue
        if start_yr and start_yr in name:
            chosen = sid
            break
        if chosen is None:
            chosen = sid  # seasons list is newest-first

    if chosen is None and seasons:
        try:
            chosen = int(seasons[0].get("season_id"))
        except Exception:
            chosen = PWHL_HOCKEYTECH_SEASON

    result = chosen if chosen is not None else PWHL_HOCKEYTECH_SEASON
    _PWHL_SEASON_CACHE["time"] = now
    _PWHL_SEASON_CACHE["result"] = result
    return int(result)


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
    base = LEAGUES[key]
    active_season, _ = detect_active_season(key)
    if active_season != base.default_season:
        return LeagueConfig(
            key=base.key,
            label=base.label,
            teams=base.teams,
            instat_ids=base.instat_ids,
            instat_gender=base.instat_gender,
            instat_search_suffix=base.instat_search_suffix,
            uses_a3z=base.uses_a3z,
            uses_nhl_api=base.uses_nhl_api,
            uses_cap=base.uses_cap,
            default_season=active_season,
            work_dir_name=base.work_dir_name,
        )
    return base


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
    if "-" in key:
        try:
            start_yr = int(key.split("-")[0])
            offset = (start_yr - 2025) * 2
            return 36 + offset
        except Exception:
            pass
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
