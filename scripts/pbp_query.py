#!/usr/bin/env python3
"""Query local InStat PBP caches for research.

Examples:
  # What's on disk?
  python scripts/pbp_query.py summary

  # List Tampa games in April 2026
  python scripts/pbp_query.py list --team TBL --from 2026-04-01 --to 2026-04-30

  # All PWHL Montreal games
  python scripts/pbp_query.py list --league pwhl --team MVL

  # Specific match ids
  python scripts/pbp_query.py list --match-ids 2170425,2170686

  # Load everything into parquet
  python scripts/pbp_query.py export --team TBL --out data/tbl_2025_26.parquet

  # One night's slate (deduped across teams)
  python scripts/pbp_query.py export --date 2026-04-26 --out data/slate_2026-04-26.parquet
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from player_cards.pbp_catalog import (  # noqa: E402
    catalog_games,
    dedupe_by_match_id,
    filter_games,
    load_dataframe,
    resolve_files,
    summary,
)


def _split_ids(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [x.strip() for x in raw.split(",") if x.strip()]


def cmd_summary(_: argparse.Namespace) -> None:
    print(json.dumps(summary(), indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    games = catalog_games()
    hits = filter_games(
        games,
        league=args.league,
        team=args.team,
        game_date=args.date,
        date_from=args.date_from,
        date_to=args.date_to,
        match_ids=_split_ids(args.match_ids),
    )
    if args.dedupe:
        hits = dedupe_by_match_id(hits)
    print(json.dumps([g.to_dict() for g in hits], indent=2))
    print(f"\n{len(hits)} games", file=sys.stderr)


def cmd_export(args: argparse.Namespace) -> None:
    paths = resolve_files(
        league=args.league,
        team=args.team,
        game_date=args.date,
        date_from=args.date_from,
        date_to=args.date_to,
        match_ids=_split_ids(args.match_ids),
        dedupe=not args.no_dedupe,
    )
    if not paths:
        print("No PBP files matched filters", file=sys.stderr)
        sys.exit(1)

    df = load_dataframe(paths)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    suffix = out.suffix.lower()
    if suffix == ".parquet":
        df.to_parquet(out, index=False)
    elif suffix == ".csv":
        df.to_csv(out, index=False)
    else:
        out = out.with_suffix(".parquet")
        df.to_parquet(out, index=False)
    print(f"Wrote {len(df):,} rows from {len(paths)} files -> {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Query local InStat PBP caches")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("summary", help="Counts and date range on disk").set_defaults(func=cmd_summary)

    list_p = sub.add_parser("list", help="List matching game files (JSON)")
    list_p.add_argument("--league", choices=["nhl", "pwhl"])
    list_p.add_argument("--team", help="Team abbrev, e.g. TBL or MVL")
    list_p.add_argument("--date", help="Single game date YYYY-MM-DD")
    list_p.add_argument("--from", dest="date_from", help="Start date (inclusive)")
    list_p.add_argument("--to", dest="date_to", help="End date (inclusive)")
    list_p.add_argument("--match-ids", help="Comma-separated InStat match ids")
    list_p.add_argument("--dedupe", action="store_true", default=True)
    list_p.set_defaults(func=cmd_list)

    exp = sub.add_parser("export", help="Load matching games to parquet/csv")
    exp.add_argument("--league", choices=["nhl", "pwhl"])
    exp.add_argument("--team")
    exp.add_argument("--date")
    exp.add_argument("--from", dest="date_from")
    exp.add_argument("--to", dest="date_to")
    exp.add_argument("--match-ids")
    exp.add_argument("--no-dedupe", action="store_true")
    exp.add_argument("--out", required=True, help="Output .parquet or .csv")
    exp.set_defaults(func=cmd_export)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
