#!/usr/bin/env python3
"""CLI: one entry point for every card kind.

Kinds stay separate on disk (see player_cards/generators/):
  nhl_player, nhl_goalie, nhl_prospect, nhl_team, pwhl_player, junior_player
"""

from __future__ import annotations

import argparse
import json

from .card_kinds import CARD_KINDS
from .generators import generate_card


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an NHL/PWHL/junior player, goalie, or team card. "
        "Kind is auto-detected, or pass --kind to keep pipelines separate."
    )
    parser.add_argument(
        "player",
        nargs="?",
        default=None,
        help='Player name (e.g. "Sidney Crosby") or, with --team-card, a team abbrev (e.g. "CBJ")',
    )
    parser.add_argument(
        "--team-card",
        action="store_true",
        help="Generate an NHL team card. The 'player' arg is read as a team abbrev.",
    )
    parser.add_argument("--team", help="Team abbrev (optional — resolved when omitted)")
    parser.add_argument(
        "--league",
        default=None,
        choices=["nhl", "pwhl", "prospect"],
        help="Force league (optional — auto-detected from name/team/store)",
    )
    parser.add_argument(
        "--kind",
        default=None,
        choices=list(CARD_KINDS),
        help="Card kind (keeps output trees separate). Auto-detected when omitted.",
    )
    parser.add_argument(
        "--amateur-club",
        default=None,
        help='Amateur / junior club for undrafted prospects (e.g. "Everett Silvertips").',
    )
    parser.add_argument(
        "--undrafted",
        action="store_true",
        help="Force undrafted / junior branding.",
    )
    parser.add_argument("--output", "-o", help="Output PNG path (default: kind output tree)")
    parser.add_argument(
        "--pbp-source",
        choices=["api", "local", "harvest"],
        default=None,
        help="PBP source: InStat API, local CSVs only, or harvest (default depends on card kind)",
    )
    parser.add_argument("--a3z-season", default=None, help="A3Z season tag, e.g. 2025-26")
    parser.add_argument("--instat-season-id", type=int, default=None)
    parser.add_argument("--max-pbp-downloads", type=int, default=None)
    parser.add_argument("--no-store", action="store_true")
    parser.add_argument("--refresh-pbp", action="store_true")
    parser.add_argument("--save-json", action="store_true")
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Run the built-in batch for --kind junior_player or nhl_prospect",
    )
    args = parser.parse_args()

    if args.batch:
        if args.kind == "nhl_prospect":
            from .generators.nhl_prospect import generate_batch
        else:
            from .generators.junior_player import generate_batch
        generate_batch()
        return

    if not args.player:
        parser.error("player name is required unless --batch is set")

    result = generate_card(
        args.player,
        team=args.team,
        league=args.league,
        kind=args.kind,
        output_png=args.output,
        a3z_season=args.a3z_season,
        pbp_source=args.pbp_source,
        instat_season_id=args.instat_season_id,
        max_pbp_downloads=args.max_pbp_downloads,
        save_json=args.save_json,
        refresh_pbp=args.refresh_pbp,
        use_store=False if args.no_store else None,
        amateur_club=args.amateur_club,
        undrafted=True if args.undrafted else None,
        team_card=args.team_card,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "profile"}, indent=2))


if __name__ == "__main__":
    main()
