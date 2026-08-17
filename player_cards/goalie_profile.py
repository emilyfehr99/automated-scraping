"""Builds a full goalie card profile: NHL bio + cap + InStat season aggregate
(real SV%/GSAx) + situational SV% splits from local PBP files.

Headline numbers (GP, SV%, GAA, shutouts) come from the NHL API's own official
stats — unambiguous and not dependent on any InStat label guess. GSAx and the
ES/PP/PK/scoring-chance splits come from InStat's own goalie model
(goalie_source.py). Situational splits (HD/rush/cycle/royal-road/rebound
control/style estimate) come from the local PBP files (goalie_pbp_metrics.py).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from .cap_source import fetch_cap_info
from .goalie_pbp_metrics import (
    aggregate_goalie_situational,
    build_goalie_shots,
    fetch_goalie_game_dates,
    games_for_goalie,
)
from .goalie_league_stats import compute_goalie_percentiles
from .goalie_shot_source import aggregate_real_shot_data, fetch_real_goalie_shot_data
from .goalie_source import fetch_goalie_instat_summary
from .instat_source import discover_team_pbp_files
from .leagues import get_league
from .nhl_bio import fetch_nhl_bio
from .team_colors import get_team_colors

logger = logging.getLogger(__name__)


def _fetch_nhl_official_stats(player_id: int, season: str = "20252026") -> dict[str, Any]:
    """Official season stat line — ground truth for GP/SV%/GAA/shutouts/W-L."""
    resp = httpx.get(
        f"https://api-web.nhle.com/v1/player/{player_id}/landing",
        headers={"User-Agent": "PlayerCards/1.0"}, timeout=12.0,
    )
    resp.raise_for_status()
    data = resp.json()
    sub = (data.get("featuredStats") or {}).get("regularSeason", {}).get("subSeason", {})
    return {
        "games_played": sub.get("gamesPlayed"),
        "wins": sub.get("wins"),
        "losses": sub.get("losses"),
        "ot_losses": sub.get("otLosses"),
        "save_pct": round(sub.get("savePctg", 0) * 100, 1) if sub.get("savePctg") is not None else None,
        "gaa": sub.get("goalsAgainstAvg"),
        "shutouts": sub.get("shutouts"),
    }


def _team_full_name(team: str) -> str:
    from .instat_source import NHL_TEAM_SEARCH
    return NHL_TEAM_SEARCH.get(team.upper(), team)


def build_goalie_card_profile(
    player_name: str,
    team: str,
    *,
    league: str = "nhl",
    season: str = "20252026",
    instat_season_id: int = 36,
    other_goalie_player_id: int | None = None,
    league_goalie_rows: list[dict[str, Any]] | None = None,
    shooter_hands: dict[str, str] | None = None,
) -> dict[str, Any]:
    """other_goalie_player_id: the team's other rostered goalie's NHL player_id,
    if known — used to resolve which goalie a shared-date game belongs to when
    both appeared (approximated by whichever logged more TOI that date).

    league_goalie_rows: precomputed output of goalie_league_stats.fetch_league_goalie_rows(),
    passed in so a multi-goalie generation run fetches the whole league once and
    reuses it, instead of refetching 32 teams per goalie card.

    shooter_hands: precomputed output of shooter_hands.fetch_league_shooter_hands(),
    same reuse reasoning."""
    bio = fetch_nhl_bio(player_name, team=team)
    player_id = bio["player_id"]

    official = _fetch_nhl_official_stats(player_id, season)
    cap = fetch_cap_info(bio["name"], player_id=player_id)

    cfg = get_league(league)
    team_instat_id = cfg.instat_ids.get(team.upper())
    instat_summary = None
    if team_instat_id:
        try:
            instat_summary = asyncio.run(
                fetch_goalie_instat_summary(bio["name"], team_instat_id, instat_season_id)
            )
        except Exception as e:
            logger.warning("InStat goalie summary failed for %s: %s", player_name, e)

    # Situational splits: figure out which of the team's downloaded PBP games
    # this goalie actually played (by date), excluding games mostly played by
    # the team's other goalie.
    situational: dict[str, Any] = {}
    shots: list[dict[str, Any]] = []
    try:
        all_files = discover_team_pbp_files(team, league=league)
        goalie_dates = fetch_goalie_game_dates(player_id, season)
        other_dates = fetch_goalie_game_dates(other_goalie_player_id, season) if other_goalie_player_id else {}
        files = games_for_goalie(all_files, goalie_dates, other_dates)
        shots = build_goalie_shots(files, _team_full_name(team), bio["name"])
        situational = aggregate_goalie_situational(shots)
    except Exception as e:
        logger.warning("Situational goalie split build failed for %s: %s", player_name, e)

    percentiles: dict[str, Any] = {}
    if instat_summary and league_goalie_rows:
        try:
            percentiles = compute_goalie_percentiles(instat_summary, league_goalie_rows, min_gp=10)
        except Exception as e:
            logger.warning("Goalie percentile computation failed for %s: %s", player_name, e)

    # Real (non-proxy) per-shot data: heatmap, handedness/attack-type/visibility/
    # rebound-detail splits, real style-of-play. Only covers games InStat
    # manually shot-charted for this goalie (see 'games_tracked' in the result).
    real_shots: list[dict[str, Any]] = []
    real_shot_agg: dict[str, Any] = {}
    if team_instat_id:
        try:
            real_shots = asyncio.run(
                fetch_real_goalie_shot_data(team_instat_id, instat_season_id, bio["name"], shooter_hands)
            )
            real_shot_agg = aggregate_real_shot_data(real_shots)
        except Exception as e:
            logger.warning("Real per-shot goalie data failed for %s: %s", player_name, e)

    return {
        "league": league,
        "bio": bio,
        "colors": get_team_colors(bio["team"], league="nhl"),
        "cap": cap,
        "official": official,
        "shots": shots,
        "real_shots": real_shots,
        "real_shot_agg": real_shot_agg,
        "instat": instat_summary,
        "situational": situational,
        "percentiles": percentiles,
        "sources": {
            "league": league,
            "position": "G",
            "season": season,
            "instat_season_id": instat_season_id,
            "cap": bool(cap),
            "instat_summary": bool(instat_summary),
            "situational_shots": len(shots),
            "real_shots_tracked": len(real_shots),
            "percentiles": bool(percentiles),
        },
    }


def generate_goalie_card(
    player_name: str,
    team: str | None = None,
    *,
    output_png: Path | str | None = None,
    season: str = "20252026",
    instat_season_id: int = 36,
    other_goalie_player_id: int | None = None,
    league_goalie_rows: list[dict[str, Any]] | None = None,
    shooter_hands: dict[str, str] | None = None,
    save_json: bool = False,
) -> dict[str, Any]:
    """CLI-facing entry point for a single NHL goalie card — mirrors the shape
    of profile.generate_player_card() (png/profile/sources) so both card types
    are drivable from the same command instead of separate one-off scripts."""
    import json

    from .card_kinds import default_output_path, stamp_card_kind
    from .goalie_renderer import generate_goalie_card_png

    if not team:
        team = fetch_nhl_bio(player_name).get("team") or ""

    profile = build_goalie_card_profile(
        player_name,
        team,
        season=season,
        instat_season_id=instat_season_id,
        other_goalie_player_id=other_goalie_player_id,
        league_goalie_rows=league_goalie_rows,
        shooter_hands=shooter_hands,
    )
    stamp_card_kind(profile, "nhl_goalie")

    if output_png:
        png_path = Path(output_png)
        png_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        png_path = default_output_path("nhl_goalie", player_name, team=team)

    generate_goalie_card_png(profile, png_path)

    result: dict[str, Any] = {
        "png": str(png_path),
        "profile": profile,
        "sources": profile["sources"],
        "card_kind": "nhl_goalie",
    }
    if save_json:
        json_path = png_path.with_suffix(".json")
        json_path.write_text(json.dumps(profile, indent=2, default=str), encoding="utf-8")
        result["json"] = str(json_path)
    return result
