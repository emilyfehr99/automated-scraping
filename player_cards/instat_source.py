"""Hudl/InStat tracking stats for NHL players — live API + local PBP fallback."""

from __future__ import annotations

import csv
import glob
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

HUDL_ROOT = Path(__file__).resolve().parents[1] / "hudl-scraping"
if str(HUDL_ROOT) not in sys.path:
    sys.path.insert(0, str(HUDL_ROOT))

NHL_TEAM_SEARCH: dict[str, str] = {
    "ANA": "Anaheim Ducks",
    "BOS": "Boston Bruins",
    "BUF": "Buffalo Sabres",
    "CAR": "Carolina Hurricanes",
    "CBJ": "Columbus Blue Jackets",
    "CGY": "Calgary Flames",
    "CHI": "Chicago Blackhawks",
    "COL": "Colorado Avalanche",
    "DAL": "Dallas Stars",
    "DET": "Detroit Red Wings",
    "EDM": "Edmonton Oilers",
    "FLA": "Florida Panthers",
    "LAK": "Los Angeles Kings",
    "MIN": "Minnesota Wild",
    "MTL": "Montreal Canadiens",
    "NJD": "New Jersey Devils",
    "NSH": "Nashville Predators",
    "NYI": "New York Islanders",
    "NYR": "New York Rangers",
    "OTT": "Ottawa Senators",
    "PHI": "Philadelphia Flyers",
    "PIT": "Pittsburgh Penguins",
    "SEA": "Seattle Kraken",
    "SJS": "San Jose Sharks",
    "STL": "St. Louis Blues",
    "TBL": "Tampa Bay Lightning",
    "TOR": "Toronto Maple Leafs",
    "UTA": "Utah Mammoth",
    "VAN": "Vancouver Canucks",
    "VGK": "Vegas Golden Knights",
    "WPG": "Winnipeg Jets",
    "WSH": "Washington Capitals",
}

INSTAT_CARD_PARAMS = {
    84: "SOG",
    121: "Scoring Chances",
    116: "Zone Entries",
    73: "Passes",
    50: "TOI (sec)",
    240: "Goals For",
    197: "SC",
    306: "HD Scoring Chances",
}

# Map raw InStat PBP action strings -> card metric buckets
PBP_ACTION_MAP = {
    "Entries": "Zone Entries",
    "Entries via stickhandling": "Carry-ins",
    "Entries via pass": "Pass Entries",
    "Shots": "Shots",
    "Shots on goal": "SOG",
    "Scoring chances": "Scoring Chances",
    "Passes": "Passes",
    "Accurate passes": "Accurate Passes",
    "Puck recoveries in DZ": "DZ Retrievals",
    "Puck recoveries": "Puck Recoveries",
    "Breakouts": "Zone Exits",
    "Breakouts via pass": "Exits w/ Pass",
    "Breakouts via stickhandling": "Carried Exits",
    "Puck losses": "Turnovers",
    "Puck losses in DZ": "DZ Turnovers",
    "Forecheck recoveries": "Forecheck Recoveries",
    "Passes to the slot": "Slot Passes",
    "Power play shots": "PP Shots",
}

CARD_METRIC_ORDER = [
    "Zone Entries", "Carry-ins", "Shots", "SOG", "Scoring Chances",
    "Passes", "DZ Retrievals", "Zone Exits", "Turnovers", "Forecheck Recoveries",
]


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFD", name)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.lower().strip())


def _instat_name(nhl_name: str) -> str:
    parts = nhl_name.strip().split()
    if len(parts) < 2:
        return nhl_name
    return f"{parts[-1]} {' '.join(parts[:-1])}"


def _match_player_name(row_name: str, nhl_name: str) -> bool:
    a, b = _norm(row_name), _norm(nhl_name)
    if a == b:
        return True
    instat_fmt = _norm(_instat_name(nhl_name))
    if instat_fmt == a:
        return True
    row_parts = a.split()
    inst_parts = instat_fmt.split()
    if len(row_parts) >= 2 and len(inst_parts) >= 2 and row_parts[0] == inst_parts[0]:
        from .nhl_bio import _first_name_matches

        if _first_name_matches(row_parts[-1], inst_parts[-1]):
            return True
    return False


def _norm_tri(team: str) -> str:
    from .leagues import normalize_team_abbrev

    return normalize_team_abbrev("nhl", team)


def _team_search_roots(team: str) -> list[Path]:
    tri = _norm_tri(team)
    full = NHL_TEAM_SEARCH.get(tri, "")
    nickname = full.split()[-1] if full else team
    roots = [
        Path.home() / "Desktop" / "My Analytics Work" / "Playoff Profiles",
        Path.home() / "Desktop" / "My Analytics Work" / full,
        Path.home() / "Desktop" / full,
        Path.home() / "Desktop" / "Instat_API_Downloads",
        Path.home() / "Desktop" / f"My Analytics Work/{full}/Instat_API_Downloads",
    ]
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.append(root)
        for dirpath, dirnames, _ in os.walk(root):
            for d in dirnames:
                dl = d.lower()
                if nickname.lower() in dl or full.lower() in dl:
                    found.append(Path(dirpath) / d)
    return list(dict.fromkeys(found))


def _is_team_game_file(path: Path, team: str) -> bool:
    tri = _norm_tri(team)
    full = NHL_TEAM_SEARCH.get(tri, "")
    nickname = full.split()[-1] if full else team
    name = path.name.lower()
    if nickname.lower() in name or full.lower() in name:
        return True
    if path.name.startswith("game_") and path.name.endswith("_pbp.csv"):
        return True
    return False


def discover_team_pbp_files(team: str) -> list[Path]:
    """All PBP CSV files for a team (recursive)."""
    files: list[Path] = []
    seen: set[str] = set()
    for root in _team_search_roots(team):
        for pattern in ("*.csv", "**/*.csv"):
            for path in root.glob(pattern):
                if not path.is_file():
                    continue
                key = str(path.resolve())
                if key in seen:
                    continue
                if not _is_team_game_file(path, team):
                    continue
                # game_*_pbp must mention team in contents
                if path.name.startswith("game_"):
                    try:
                        with path.open(encoding="utf-8") as f:
                            sample = f.read(4096)
                        if NHL_TEAM_SEARCH.get(_norm_tri(team), "").split()[0].lower() not in sample.lower():
                            if _norm_tri(team) not in sample.upper():
                                continue
                    except Exception:
                        continue
                seen.add(key)
                files.append(path)
    return sorted(files, key=lambda p: p.name)


def _count_game_actions(path: Path, player_name: str, team: str) -> tuple[Counter[str], bool]:
    counts: Counter[str] = Counter()
    played = False
    full_team = NHL_TEAM_SEARCH.get(_norm_tri(team), "")
    try:
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pname = row.get("player") or row.get("Player", "")
                tname = row.get("team") or row.get("Team", "")
                if not _match_player_name(pname, player_name):
                    continue
                if tname and full_team and full_team.lower() not in tname.lower():
                    continue
                played = True
                action = (row.get("action") or row.get("Action", "")).strip()
                label = PBP_ACTION_MAP.get(action)
                if label:
                    counts[label] += 1
    except Exception:
        return counts, False
    return counts, played


def aggregate_from_local_pbp(player_name: str, team: str) -> dict[str, Any] | None:
    """Aggregate per-game, averaged across every team game file on disk."""
    files = discover_team_pbp_files(team)
    if not files:
        return None

    per_game: list[tuple[Counter[str], bool, str]] = []
    for path in files:
        counts, played = _count_game_actions(path, player_name, team)
        per_game.append((counts, played, path.name))

    total_games = len(per_game)
    games_played = sum(1 for _, played, _ in per_game if played)
    if games_played == 0:
        return None

    combined: Counter[str] = Counter()
    for counts, _, _ in per_game:
        combined.update(counts)

    metrics = []
    for label in CARD_METRIC_ORDER:
        total = combined.get(label, 0)
        if total > 0 or label in ("Zone Entries", "Shots", "Passes"):
            metrics.append({
                "label": f"{label}/G",
                "value": round(total / total_games, 2),
                "source": "pbp",
            })

    return {
        "games": total_games,
        "games_played": games_played,
        "game_files": [name for _, _, name in per_game],
        "metrics": metrics[:12],
        "source": "local_pbp",
        "instat_name": _instat_name(player_name),
    }


async def fetch_from_instat_api(player_name: str, team: str, season_id: int = 35) -> dict[str, Any] | None:
    try:
        from playwright.async_api import async_playwright
        from instat_api import InStatAPI
    except ImportError:
        return None

    auth = HUDL_ROOT / "auth.json"
    if not auth.exists():
        return None

    api = InStatAPI()
    async with async_playwright() as p:
        if not await api.init_session(p):
            return None

        team_query = NHL_TEAM_SEARCH.get(_norm_tri(team), team)
        team_id = await api.find_team_by_name(f"{team_query} men")
        if not team_id:
            team_id = await api.get_team_id(team_query)
        if not team_id:
            await api.close()
            return None

        match_ids: list[int] = []
        for sid in (season_id, 34, 33, 36):
            matches_resp = await api.api_call(
                "scout_uni_advanced_matches_list",
                {"_p_season_id": sid, "_p_team_id": team_id},
            )
            if matches_resp and matches_resp.get("data"):
                block = matches_resp["data"][0].get("scout_uni_advanced_matches_list", [])
                if isinstance(block, list):
                    for m in block:
                        mid = m.get("match_id") if isinstance(m, dict) else None
                        if mid and int(mid) > 100000:
                            match_ids.append(int(mid))
            if match_ids:
                break

        if not match_ids:
            await api.close()
            return None

        skaters = await api.api_call(
            "scout_uni_team_players_stat",
            {"_p_team_id": team_id, "_p_match_arr": match_ids},
        )
        if not skaters or not skaters.get("data"):
            await api.close()
            return None
        data = skaters["data"][0].get("scout_uni_team_players_stat", {})
        col_map = await api._build_col_map(1)
        rows = api._parse_player_rows(data, col_map)
        await api.close()

        player_row = next((r for r in rows if _match_player_name(r.get("Player", ""), player_name)), None)
        if not player_row:
            return None

        metrics = []
        for pid, label in INSTAT_CARD_PARAMS.items():
            k = f"p{pid}_o0"
            if k in player_row:
                try:
                    metrics.append({"label": label, "value": float(player_row[k]), "source": "instat_api"})
                except (TypeError, ValueError):
                    pass

        skip = {"Player", "Team", "Number", "Match_ID", "Date"}
        for key, val in player_row.items():
            if key in skip or key.startswith("p"):
                continue
            try:
                fv = float(val)
            except (TypeError, ValueError):
                continue
            if any(m["label"] == key for m in metrics):
                continue
            metrics.append({"label": key, "value": fv, "source": "instat_api"})
            if len(metrics) >= 12:
                break

        return {
            "games": len(match_ids),
            "games_played": len(match_ids),
            "metrics": metrics[:12],
            "source": "instat_api",
            "team_id": team_id,
            "instat_name": player_row.get("Player"),
        }


def fetch_instat_profile(player_name: str, team: str) -> dict[str, Any] | None:
    """Prefer full local PBP set; fall back to live API."""
    local = aggregate_from_local_pbp(player_name, team)
    if local:
        return local

    import asyncio
    try:
        return asyncio.run(fetch_from_instat_api(player_name, team))
    except Exception:
        return None
