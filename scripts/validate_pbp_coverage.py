#!/usr/bin/env python3
"""Validate InStat PBP cache completeness for player card builds."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from player_cards.a3z_source import resolve_a3z_season
from player_cards.instat_pbp_fetch import team_pbp_dir, try_fast_pbp_cache
from player_cards.leagues import LEAGUES, get_league, instat_season_id, list_teams, min_season_games

MIN_GAMES = {"nhl": min_season_games("nhl"), "pwhl": min_season_games("pwhl")}


def check_team(
    league: str,
    team: str,
    *,
    season: str,
    season_id: int,
    work_root: Path | None = None,
) -> dict:
    tri = team.upper()
    pbp_dir = team_pbp_dir(tri, league=league, a3z_season=season, season_id=season_id)
    if work_root is not None:
        full = get_league(league).teams.get(tri, tri)
        sub = f"PWHL/{full}" if league == "pwhl" else full
        pbp_dir = work_root / sub / "Instat_API_Downloads"

    cached = try_fast_pbp_cache(tri, pbp_dir, league=league, a3z_season=season, season_id=season_id)
    games = int((cached or {}).get("cached") or 0)
    complete = bool((cached or {}).get("complete"))
    min_games = MIN_GAMES.get(league, 50)
    ok = complete and games >= min_games
    return {
        "league": league,
        "team": tri,
        "games": games,
        "complete": complete,
        "min_games": min_games,
        "ok": ok,
        "pbp_dir": str(pbp_dir),
    }


def validate(
    *,
    leagues: list[str] | None = None,
    teams: list[str] | None = None,
    season: str | None = None,
    work_root: Path | None = None,
) -> dict:
    league_keys = leagues or ["nhl", "pwhl"]
    rows: list[dict] = []
    for league in league_keys:
        cfg = get_league(league)
        season_tag = resolve_a3z_season(season or cfg.default_season, None)
        sid = instat_season_id(season_tag, league)
        target = [t.upper() for t in (teams or list_teams(league))]
        for tri in target:
            if tri not in cfg.teams:
                continue
            rows.append(
                check_team(league, tri, season=season_tag, season_id=sid, work_root=work_root)
            )
    missing = [r for r in rows if not r["ok"]]
    return {
        "season": season_tag if rows else season,
        "teams_checked": len(rows),
        "teams_ok": len(rows) - len(missing),
        "teams_missing": missing,
        "ok": not missing,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate PBP cache coverage")
    parser.add_argument("--league", default="all", help="nhl, pwhl, or all")
    parser.add_argument("--teams", default="all")
    parser.add_argument("--season", default=None)
    parser.add_argument(
        "--work-root",
        type=Path,
        default=None,
        help="PLAYER_CARDS_WORK_ROOT (default: leagues.player_cards_work_root())",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.work_root is None:
        import os

        override = os.getenv("PLAYER_CARDS_WORK_ROOT", "").strip()
        work_root = Path(override) if override else None
    else:
        work_root = args.work_root

    raw = args.league.lower()
    leagues = list(LEAGUES.keys()) if raw == "all" else [x.strip() for x in raw.split(",")]
    teams = None if args.teams.lower() == "all" else [t.strip() for t in args.teams.split(",") if t.strip()]

    report = validate(leagues=leagues, teams=teams, season=args.season, work_root=work_root)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"PBP coverage: {report['teams_ok']}/{report['teams_checked']} teams complete "
            f"(season {report.get('season')})"
        )
        for row in report["teams_missing"]:
            print(
                f"  MISSING {row['league'].upper()}/{row['team']}: "
                f"{row['games']} games (need >={row['min_games']}, complete={row['complete']})"
            )

    if not report["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
