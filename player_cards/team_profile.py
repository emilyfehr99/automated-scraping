"""Builds a full team card profile: roster-averaged skater microstats (same
metrics/keys as an individual skater card, averaged across the lineup),
goalie tandem summary, and league standing. Optionally ranked against the
other 31 NHL teams when a precomputed league pool is supplied."""

from __future__ import annotations

from typing import Any

from .nhl_bio import team_logo_png_url, team_logo_url
from .team_colors import get_team_colors
from .team_source import (
    aggregate_team_skater_averages,
    aggregate_team_zone_events,
    compute_official_stat_percentiles,
    compute_team_percentiles,
    compute_team_totals,
    fetch_league_team_official_stats,
    fetch_team_front_office,
    fetch_team_game_log,
    fetch_team_goalie_summary,
    fetch_team_scoring_leaders,
    fetch_team_standing,
)

# Official-stat metrics shown in the (always-real, 32-team) League Percentiles
# pillar - cheap NHL API data, no InStat download required.
OFFICIAL_STAT_KEYS = [
    "pointPct", "goalsForPerGame", "goalsAgainstPerGame",
    "powerPlayPct", "penaltyKillPct", "faceoffWinPct",
    "shotsForPerGame", "shotsAgainstPerGame",
]


def _team_full_name(team: str) -> str:
    from .instat_source import NHL_TEAM_SEARCH
    return NHL_TEAM_SEARCH.get(team.upper(), team.upper())


def fetch_top_prospects(team: str, current_year: int = 2026, years: int = 3, limit: int = 3) -> str:
    """Fetch the highest recent draft picks for a team."""
    from .draft_source import fetch_draft_picks
    all_picks = []
    for y in range(current_year - years + 1, current_year + 1):
        picks = fetch_draft_picks(y)
        for p in picks:
            if p.get("teamAbbrev", "").upper() == team.upper():
                all_picks.append(p)
    if not all_picks:
        return "None"
    
    # Sort by overall pick ascending
    all_picks.sort(key=lambda x: x.get("overallPick", 999))
    top = all_picks[:limit]
    
    disp = []
    for p in top:
        first = p.get("firstName", {}).get("default", "")
        last = p.get("lastName", {}).get("default", "")
        overall = p.get("overallPick", "?")
        disp.append(f"{first} {last} ({overall})")
    
    return ", ".join(disp)

def build_team_card_profile(
    team: str,
    *,
    league: str = "nhl",
    season: str = "2025-26",
    instat_season_id: int = 36,
    league_team_averages: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tri = team.upper()

    skater_data = aggregate_team_skater_averages(
        tri, league=league, season=season, instat_season_id=instat_season_id,
    )
    goalie_summary = fetch_team_goalie_summary(tri)
    standing = fetch_team_standing(tri)
    leaders = fetch_team_scoring_leaders(tri)
    team_totals = compute_team_totals(skater_data.get("per_player") or {}, skater_data.get("games"))
    zone_events = aggregate_team_zone_events(tri, league=league, files=skater_data.get("files"))
    game_log = fetch_team_game_log(tri)
    front_office = fetch_team_front_office(tri)
    top_prospects_str = fetch_top_prospects(tri)

    percentiles: dict[str, float | None] = {}
    if league_team_averages:
        percentiles = compute_team_percentiles(skater_data.get("averages") or {}, league_team_averages)

    season_id = int(f"{season.split('-')[0]}{int(season.split('-')[0]) + 1}") if "-" in season else 20252026
    league_official = fetch_league_team_official_stats(season_id)
    official_row = league_official.get(tri, {})
    official_percentiles = (
        compute_official_stat_percentiles(official_row, league_official, OFFICIAL_STAT_KEYS)
        if official_row else {}
    )

    return {
        "league": league,
        "team": tri,
        "team_name": _team_full_name(tri),
        "colors": get_team_colors(tri, league="nhl"),
        "logo_url": team_logo_url(tri),
        "logo_png_url": team_logo_png_url(tri),
        "standing": standing,
        "official": official_row,
        "official_percentiles": official_percentiles,
        "leaders": leaders,
        "skater_averages": skater_data.get("averages") or {},
        "skater_percentiles": percentiles,
        "team_totals": team_totals,
        "zone_events": zone_events,
        "game_log": game_log,
        "front_office": front_office,
        "player_count": skater_data.get("player_count", 0),
        "roster_size": skater_data.get("roster_size", 0),
        "games": skater_data.get("games"),
        "goalies": goalie_summary,
        "top_prospects": top_prospects_str,
        "sources": {
            "league": league,
            "season": season,
            "instat_season_id": instat_season_id,
            "skaters_with_data": skater_data.get("player_count", 0),
            "roster_size": skater_data.get("roster_size", 0),
            "league_pool_size": len(league_team_averages) if league_team_averages else 0,
            "official_league_pool_size": len(league_official),
            "standing_found": standing is not None,
            "shots_for": len(zone_events.get("shots_for", [])),
            "shots_against": len(zone_events.get("shots_against", [])),
            "nz_turnovers": zone_events.get("nz_turnovers", 0),
        },
    }
