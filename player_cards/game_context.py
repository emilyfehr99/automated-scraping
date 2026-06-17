"""Align InStat PBP file sets with A3Z season context."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

REGULAR_SEASON = "2025-26"
PLAYOFF_SEASON = "2025-26p"


def infer_a3z_season(pbp_files: list[Path]) -> str:
    """Pick A3Z season tag from where local PBP files live."""
    if not pbp_files:
        return REGULAR_SEASON
    joined = " ".join(str(p).lower() for p in pbp_files)
    if "playoff" in joined:
        return PLAYOFF_SEASON
    if re.search(r"2025-26p", joined):
        return PLAYOFF_SEASON
    if re.search(r"2024-25p", joined):
        return "2024-25p"
    if re.search(r"2025-26", joined):
        return REGULAR_SEASON
    return PLAYOFF_SEASON


def build_game_context(
    pbp_files: list[Path],
    pbp: dict[str, Any] | None,
    a3z: dict[str, Any] | None,
    *,
    a3z_season: str | None = None,
    pbp_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = pbp_meta or {}
    season = a3z_season or (a3z or {}).get("season") or infer_a3z_season(pbp_files)
    pbp_games = int((pbp or {}).get("games") or len(pbp_files) or 0)
    pbp_skated = int((pbp or {}).get("games_played") or 0)
    a3z_games = int((a3z or {}).get("games") or 0)
    return {
        "a3z_season": season,
        "pbp_source": meta.get("source", "local_pbp"),
        "instat_season_id": meta.get("season_id"),
        "instat_team_id": meta.get("team_id"),
        "pbp_files": [p.name for p in pbp_files],
        "pbp_team_games": pbp_games,
        "pbp_skated_games": pbp_skated,
        "a3z_games": a3z_games,
        "rates_denominator": pbp_games,
        "aligned": pbp_games > 0 and a3z_games > 0 and pbp_games == a3z_games,
        "pbp_cache_dir": meta.get("output_dir"),
        "pbp_downloaded": meta.get("downloaded"),
    }
