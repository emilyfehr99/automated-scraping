#!/usr/bin/env python3
"""Refresh PWHL card-store profiles (PBP + display) without photo/cutout work."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from player_cards.build_store import _team_pbp_percentiles, fetch_roster
from player_cards.card_store import load_stored_profile, open_store
from player_cards.disk_cache import pbp_files_fingerprint
from player_cards.instat_pbp_fetch import team_pbp_dir, try_fast_pbp_cache
from player_cards.leagues import list_teams
from player_cards.nhl_instat import instat_season_id
from player_cards.pbp_display import build_pbp_display_profile
from player_cards.pbp_metrics import aggregate_player_pbp
from player_cards.card_config import PWHL_PILLAR_BARS
from player_cards.profile import (
    _cached_pbp_aggregate,
    _cached_qoc_qot,
    _player_pbp_percentiles,
)
from player_cards.pwhl_vitals import resolve_ht_vitals
from player_cards.leagues import team_full_name
from player_cards.team_colors import get_team_colors
from player_cards.a3z_source import resolve_a3z_season

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def refresh_team(store, tri: str, *, season: str = "2025-26") -> dict:
    sid = instat_season_id(season, "pwhl")
    pbp_dir = team_pbp_dir(tri, league="pwhl", a3z_season=season, season_id=sid)
    fast = try_fast_pbp_cache(tri, pbp_dir, league="pwhl", a3z_season=season, season_id=sid)
    if not fast:
        return {"team": tri, "error": "no_pbp"}
    files = [Path(p) for p in fast["files"]]
    match_ids = fast.get("match_ids") or []
    team_games = len(match_ids) if fast.get("complete") and match_ids else len(files)
    roster = fetch_roster("pwhl", tri, files)
    pct_by_player = _team_pbp_percentiles(roster, files, tri, league="pwhl", team_games=team_games)
    fp = pbp_files_fingerprint(files)
    team_full = team_full_name("pwhl", tri)
    deployment_cache: dict[str, dict] = {}
    built = 0

    store._conn.execute(
        "DELETE FROM player_profiles WHERE league='pwhl' AND team=? AND season=?",
        (tri, season),
    )
    store._conn.commit()

    for entry in roster:
        name = entry["name"]
        player_id = entry["player_id"]
        pbp = aggregate_player_pbp(name, tri, files=files, team_games=team_games, league="pwhl")
        if not pbp:
            continue
        existing = load_stored_profile(name, team=tri, season=season, league="pwhl")
        bio = (existing or {}).get("bio") or {
            "player_id": player_id,
            "name": name,
            "team": tri,
            "league": "pwhl",
            "instat_name": name,
        }
        patch = resolve_ht_vitals(name, tri, bio)
        new_bio = {**bio}
        for key, val in patch.items():
            if val is not None and val != "":
                new_bio[key] = val
        bio = new_bio
        if name not in deployment_cache:
            deployment_cache[name] = _cached_qoc_qot(player_id, name, team_full, files) or {}
        deployment = deployment_cache[name]
        player_pct = pct_by_player.get(name) or _player_pbp_percentiles(
            name, pbp, [tri], season=season, league="pwhl",
            file_groups=[(tri, files, team_games)],
            instat_name=bio.get("instat_name"),
        )
        a3z = build_pbp_display_profile(
            pbp, deployment, season=season, percentiles=player_pct, pillar_bars=PWHL_PILLAR_BARS,
        )
        profile = {
            "league": "pwhl",
            "bio": bio,
            "colors": get_team_colors(tri, league="pwhl"),
            "cap": None,
            "a3z": a3z,
            "pbp": pbp,
            "deployment": deployment,
            "sources": {
                **((existing or {}).get("sources") or {}),
                "league": "pwhl",
                "a3z": False,
                "pbp": True,
                "pbp_percentiles": True,
                "a3z_season": season,
                "pbp_team_games": team_games,
                "pbp_skated_games": pbp.get("games_played"),
            },
        }
        store.upsert_profile(profile, season=season, pbp_fingerprint=fp)
        built += 1

    store.upsert_team(
        tri, season, league="pwhl", pbp_fingerprint=fp, pbp_dir=str(pbp_dir),
        match_count=team_games, player_count=built,
    )
    return {"team": tri, "built": built, "games": team_games}


def main() -> int:
    teams = [t.strip().upper() for t in sys.argv[1:]] if len(sys.argv) > 1 else [
        t for t in list_teams("pwhl")
        if try_fast_pbp_cache(
            t,
            team_pbp_dir(t, league="pwhl", a3z_season="2025-26", season_id=instat_season_id("2025-26", "pwhl")),
            league="pwhl",
            a3z_season="2025-26",
            season_id=instat_season_id("2025-26", "pwhl"),
        )
    ]
    results = []
    with open_store() as store:
        for tri in teams:
            logger.info("Refreshing %s...", tri)
            results.append(refresh_team(store, tri))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
