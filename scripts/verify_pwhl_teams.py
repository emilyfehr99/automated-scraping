#!/usr/bin/env python3
"""Report PWHL team readiness: league config, PBP cache, card store."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from player_cards.card_store import open_store
from player_cards.instat_pbp_fetch import team_pbp_dir, try_fast_pbp_cache
from player_cards.leagues import (
    PWHL_HOCKEYTECH_TEAM_IDS,
    PWHL_INSTAT_TEAM_IDS,
    PWHL_TEAM_COLORS,
    PWHL_TEAM_SEARCH,
    list_teams,
)
from player_cards.nhl_instat import instat_season_id
from player_cards.team_colors import get_team_colors


def main() -> int:
    season = "2025-26"
    sid = instat_season_id(season, "pwhl")
    teams = list_teams("pwhl")
    rows: list[dict] = []
    ok = True

    with open_store() as store:
        for tri in teams:
            missing: list[str] = []
            if tri not in PWHL_TEAM_SEARCH:
                missing.append("search")
            if tri not in PWHL_INSTAT_TEAM_IDS:
                missing.append("instat_id")
            if tri not in PWHL_HOCKEYTECH_TEAM_IDS:
                missing.append("hockeytech_id")
            colors = get_team_colors(tri, league="pwhl")
            if not colors.get("primary"):
                missing.append("colors")

            pbp_dir = team_pbp_dir(tri, league="pwhl", a3z_season=season, season_id=sid)
            fast = try_fast_pbp_cache(tri, pbp_dir, league="pwhl", a3z_season=season, season_id=sid)
            games = len(fast.get("match_ids") or []) if fast else 0
            if not fast:
                missing.append("pbp_cache")

            store_count = len(store.list_team_players(tri, league="pwhl", season=season))
            if store_count == 0:
                missing.append("store_profiles")

            ready = not missing
            if not ready:
                ok = False
            rows.append(
                {
                    "team": tri,
                    "name": PWHL_TEAM_SEARCH.get(tri, tri),
                    "games": games,
                    "store_profiles": store_count,
                    "ready": ready,
                    "missing": missing,
                }
            )

    print(json.dumps({"season": season, "teams": rows}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
