"""Background warming so the API is fast without a manual build step."""

from __future__ import annotations

import logging
from pathlib import Path

from .instat_pbp_fetch import team_pbp_dir, try_fast_pbp_cache
from .leagues import LEAGUES, instat_season_id, team_full_name
from .pbp_team_cache import warm_team_pbp
from .qoc_qot import compute_league_context

logger = logging.getLogger(__name__)


def warm_team(team: str, *, league: str = "nhl", season: str | None = None) -> bool:
    """Load PBP + league QOC context for one team if CSVs exist on disk."""
    league = (league or "nhl").lower()
    cfg = LEAGUES[league]
    tri = team.upper()
    if tri not in cfg.teams:
        return False
    season = season or cfg.default_season
    sid = instat_season_id(season, league)
    pbp_dir = team_pbp_dir(tri, league=league, a3z_season=season, season_id=sid)
    fast = try_fast_pbp_cache(tri, pbp_dir, league=league, a3z_season=season, season_id=sid)
    if not fast:
        return False
    files = [Path(p) for p in fast.get("files", [])]
    if not files:
        return False
    warm_team_pbp(files)
    compute_league_context(files, team_full_name(league, tri))
    logger.info("API warm complete for %s/%s (%s games)", league, tri, len(files))
    return True


def warm_all_cached_teams(*, season: str | None = None) -> int:
    """Warm every team that already has Desktop PBP cache (NHL + PWHL)."""
    warmed = 0
    for league_key, cfg in LEAGUES.items():
        for tri in cfg.teams:
            try:
                if warm_team(tri, league=league_key, season=season or cfg.default_season):
                    warmed += 1
            except Exception as exc:
                logger.warning("Warm failed for %s/%s: %s", league_key, tri, exc)
    logger.info("API warmed %s teams with cached PBP", warmed)
    return warmed
