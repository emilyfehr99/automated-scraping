"""Align InStat PBP file sets with A3Z season context."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from .leagues import DEFAULT_SEASON

REGULAR_SEASON = DEFAULT_SEASON
PLAYOFF_SEASON = f"{DEFAULT_SEASON}p"


def infer_a3z_season(pbp_files: list[Path]) -> str:
    """Pick A3Z season tag from where local PBP files live."""
    if not pbp_files:
        return REGULAR_SEASON
    joined = " ".join(str(p).lower() for p in pbp_files)
    
    # Check for explicit playoff indicator
    is_playoff = "playoff" in joined
    
    # Regex match any season tag like 2025-26, 2026-27, 2024-25p, etc.
    m = re.search(r"\b(20\d\d-\d\d(p)?)\b", joined)
    if m:
        tag = m.group(1)
        if is_playoff and not tag.endswith("p"):
            return f"{tag}p"
        return tag
        
    if is_playoff:
        return PLAYOFF_SEASON
    return REGULAR_SEASON


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
