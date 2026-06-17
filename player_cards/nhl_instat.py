"""InStat team IDs and season mapping (delegates to leagues.py)."""

from __future__ import annotations

from .leagues import (
    DEFAULT_INSTAT_SEASON_ID,
    NHL_INSTAT_TEAM_IDS,
    SEASON_TO_INSTAT,
    instat_season_id,
    pbp_cache_dir,
    resolve_instat_team_id,
)

A3Z_SEASON_TO_INSTAT = SEASON_TO_INSTAT


async def resolve_nhl_team_id(api, team_abbrev: str) -> int | None:
    return await resolve_instat_team_id(api, "nhl", team_abbrev)
