"""Season-aggregate goalie stats straight from InStat's own model (SA/GA/SV/xG),
not the geometry proxies used for skater microstats.

InStat exposes goalies via the same `scout_uni_team_players_stat` endpoint used
for skaters, gated by `_is_gk: 1` and gear type 9 (vs. gear type 1 for skaters).
That response already carries a calibrated `xG` (expected goals against) figure,
so GSAx here is InStat's own model, not something we estimate.
"""

from __future__ import annotations

import logging
from typing import Any

from .instat_source import HUDL_ROOT, _match_player_name
import sys

if str(HUDL_ROOT) not in sys.path:
    sys.path.insert(0, str(HUDL_ROOT))

logger = logging.getLogger(__name__)

# Fields confirmed (empirically) to mean what their InStat label says for goalies.
# "DI" duplicates GA+SV exactly in every case we checked, so shots-against is
# derived (GA + SV) rather than trusted from that ambiguous label.
_SITUATIONS = ("", " (ES)", " (PP)", " (SH)")
_SIT_KEY = {"": "total", " (ES)": "es", " (PP)": "pp", " (SH)": "sh"}


def _pct(num: float, den: float) -> float | None:
    if den <= 0:
        return None
    return round(100.0 * num / den, 1)


def _num(row: dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


async def _fetch_team_goalie_rows(team_id: int, season_id: int, api) -> list[dict[str, Any]]:
    import instat_api as instat_mod

    instat_mod.TEAM_ID = team_id
    instat_mod.SEASON_ID = season_id
    matches = await api.get_matches_list()
    match_ids = api._extract_match_ids(matches)
    if not match_ids:
        return []
    goalies = await api.get_team_goalies(match_ids)
    col_map = await api._build_col_map(9)
    return api._parse_player_rows(goalies, col_map)


def _build_summary(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"instat_name": row.get("Player")}
    for suffix in _SITUATIONS:
        key = _SIT_KEY[suffix]
        ga = _num(row, f"GA{suffix}")
        sv = _num(row, f"SV{suffix}")
        sa = ga + sv
        sc = _num(row, f"SC{suffix}")
        scsv = _num(row, f"SCSV{suffix}")
        out[key] = {
            "shots_against": int(sa),
            "goals_against": int(ga),
            "saves": int(sv),
            "sv_pct": _pct(sv, sa),
            "scoring_chances_against": int(sc),
            "scoring_chance_saves": int(scsv),
            "scoring_chance_sv_pct": _pct(scsv, sc),
        }
    gp = _num(row, "GP")
    xg = _num(row, "xG")
    ga_total = out["total"]["goals_against"]
    sa_total = out["total"]["shots_against"]
    # NOTE: InStat's "SHO" and "xGPS" columns were checked against the NHL's own
    # official stats (Jet Greaves: 2 real shutouts vs. SHO=22; Elvis Merzlikins: 1
    # real shutout vs. SHO=9) and against the plausible per-shot xG range (~0.05-0.15)
    # — both are mislabeled/wrong for this gear type and are deliberately NOT
    # surfaced here. "xG" (season total) checks out: xg/shots_against lands at
    # ~0.07-0.08 for both goalies, a realistic league-average shot value, so GSAx
    # below is trustworthy even though those two sibling columns aren't.
    out.update({
        "games_played": int(gp),
        "xga": round(xg, 2),
        "gsax": round(xg - ga_total, 2),
        "xg_per_shot_check": round(xg / sa_total, 3) if sa_total else None,
        "height_inches": int(_num(row, "HGT") / 2.54) if row.get("HGT") else None,
        "weight_lbs": round(_num(row, "WGT") * 2.20462) if row.get("WGT") else None,
        "catches": {1: "R", 2: "L"}.get(int(_num(row, "AH")) or 0),
        "dob": row.get("DOB"),
    })
    return out


async def fetch_goalie_instat_summary(
    player_name: str,
    team_instat_id: int,
    season_id: int,
) -> dict[str, Any] | None:
    """Season-aggregate SV%/GSAx/scoring-chance splits for one goalie, straight from InStat."""
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
        try:
            rows = await _fetch_team_goalie_rows(team_instat_id, season_id, api)
        finally:
            await api.close()

    row = next((r for r in rows if _match_player_name(str(r.get("Player") or ""), player_name)), None)
    if not row:
        logger.warning("No InStat goalie row found for %s", player_name)
        return None
    return _build_summary(row)
