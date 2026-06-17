#!/usr/bin/env python3
"""CLI: generate an NHL player microstat card (persistent PBP cache + temp HTML)."""

from __future__ import annotations

import argparse
import json

from .profile import generate_player_card


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate NHL player microstat card")
    parser.add_argument("player", help='Player name, e.g. "Sidney Crosby"')
    parser.add_argument("--team", help="Team abbrev (NHL: PIT; PWHL: MVL, BPF, …)")
    parser.add_argument("--league", default="nhl", choices=["nhl", "pwhl"], help="League (default: nhl)")
    parser.add_argument("--output", "-o", help="Output PNG path (default: temp file)")
    parser.add_argument(
        "--pbp-source",
        choices=["api", "local"],
        default="api",
        help="PBP data source: InStat API (default) or local CSVs",
    )
    parser.add_argument("--a3z-season", default=None, help="A3Z season tag, e.g. 2025-26")
    parser.add_argument("--instat-season-id", type=int, default=None, help="InStat _p_season_id override")
    parser.add_argument(
        "--max-pbp-downloads",
        type=int,
        default=None,
        help="Cap new PBP downloads this run (default: all season games)",
    )
    parser.add_argument(
        "--no-store",
        action="store_true",
        help="Bypass SQLite card store and fetch live data",
    )
    parser.add_argument(
        "--no-store",
        action="store_true",
        help="Bypass SQLite card store and fetch live data",
    )
    parser.add_argument(
        "--refresh-pbp",
        action="store_true",
        help="Re-fetch InStat match list and download any missing PBP files",
    )
    parser.add_argument(
        "--save-json",
        action="store_true",
        help="Also write profile JSON beside PNG (off by default)",
    )
    args = parser.parse_args()

    result = generate_player_card(
        args.player,
        team=args.team,
        league=args.league,
        output_png=args.output,
        a3z_season=args.a3z_season,
        pbp_source=args.pbp_source,
        instat_season_id=args.instat_season_id,
        max_pbp_downloads=args.max_pbp_downloads,
        save_json=args.save_json,
        refresh_pbp=args.refresh_pbp,
        use_store=not args.no_store,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "profile"}, indent=2))


if __name__ == "__main__":
    main()
