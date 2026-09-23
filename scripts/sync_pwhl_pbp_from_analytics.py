#!/usr/bin/env python3
"""Copy league-wide PWHL PBP from pwhl-analytics into per-team Instat_API_Downloads caches."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from player_cards.instat_pbp_fetch import _pbp_path_for_match, _save_manifest, team_pbp_dir
from player_cards.leagues import PWHL_TEAM_SEARCH, instat_season_id, team_full_name
from player_cards.nhl_instat import instat_season_id as resolve_sid

_ANALYTICS_PBP_ROOTS = (
    Path.home() / "CascadeProjects" / "pwhl-analytics" / "data" / "pbp",
    Path.home() / "Desktop" / "pwhl-analytics" / "data" / "pbp",
)


def _analytics_pbp_dir() -> Path | None:
    for path in _ANALYTICS_PBP_ROOTS:
        if path.is_dir() and any(path.glob("game_*_pbp.csv")):
            return path
    return None


def _team_abbrev(full_name: str) -> str | None:
    for tri, full in PWHL_TEAM_SEARCH.items():
        if full.lower() == full_name.strip().lower():
            return tri
    return None


def sync_team(
    tri: str,
    *,
    season: str,
    season_id: int,
    source_dir: Path,
    dry_run: bool = False,
) -> dict:
    full = team_full_name("pwhl", tri)
    out_dir = team_pbp_dir(tri, league="pwhl", a3z_season=season, season_id=season_id)
    match_ids: list[int] = []
    copied = 0

    for meta_path in sorted(source_dir.glob("game_*_meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        mid = int(meta["match_id"])
        teams = {meta.get("team1"), meta.get("team2")}
        if full not in {t for t in teams if t}:
            continue
        src = source_dir / f"game_{mid}_pbp.csv"
        if not src.is_file():
            src = source_dir / meta_path.name.replace("_meta.json", "_pbp.csv")
        if not src.is_file():
            continue
        date = str(meta.get("match_date") or "").split("T")[0] or None
        dest = _pbp_path_for_match(out_dir, mid, date)
        match_ids.append(mid)
        if dry_run:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        if not dest.is_file() or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)
            copied += 1

    if not dry_run and match_ids:
        from player_cards.leagues import PWHL_INSTAT_TEAM_IDS

        _save_manifest(
            out_dir,
            season_id,
            {
                "team": tri,
                "team_id": PWHL_INSTAT_TEAM_IDS.get(tri),
                "season_id": season_id,
                "a3z_season": season,
                "match_ids": sorted(set(match_ids)),
                "league": "pwhl",
                "source": "pwhl_analytics_sync",
            },
        )

    return {
        "team": tri,
        "games": len(set(match_ids)),
        "copied": copied,
        "output_dir": str(out_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync PWHL PBP from pwhl-analytics to team caches")
    parser.add_argument("--teams", default="", help="Comma-separated abbrevs or all")
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = _analytics_pbp_dir()
    if not source:
        print("pwhl-analytics data/pbp not found", file=sys.stderr)
        return 1

    season_id = resolve_sid(args.season, "pwhl")
    teams = (
        [t.strip().upper() for t in args.teams.split(",") if t.strip()]
        if args.teams and args.teams.lower() != "all"
        else list(PWHL_TEAM_SEARCH)
    )

    results = [
        sync_team(tri, season=args.season, season_id=season_id, source_dir=source, dry_run=args.dry_run)
        for tri in teams
    ]
    print(json.dumps({"source": str(source), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
