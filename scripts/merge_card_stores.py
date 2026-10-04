#!/usr/bin/env python3
"""Merge shard player card SQLite stores into one database."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def merge_stores(
    target: Path,
    sources: list[Path],
    *,
    base: Path | None = None,
) -> dict[str, int]:
    """Merge shard DBs into ``target``.

    When ``base`` is set (prior merged store), start from that DB and upsert
    shard rows on top — used for incremental scheduled rebuilds that only
    refresh teams with new games.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    main = sqlite3.connect(target)
    main.execute("PRAGMA busy_timeout = 30000")
    first = True
    counts = {"player_profiles": 0, "team_builds": 0}

    ordered: list[Path] = []
    if base is not None and base.is_file():
        ordered.append(base)
    ordered.extend(src for src in sources if src.is_file())

    for src in ordered:
        if first:
            backup = sqlite3.connect(src)
            backup.backup(main)
            backup.close()
            first = False
        else:
            main.execute("ATTACH DATABASE ? AS shard", (str(src.resolve()),))
            for table in ("player_profiles", "team_builds"):
                main.execute(
                    f"INSERT OR REPLACE INTO {table} SELECT * FROM shard.{table}"
                )
            main.execute("INSERT OR IGNORE INTO meta SELECT * FROM shard.meta")
            main.commit()
            main.execute("DETACH DATABASE shard")

    if first:
        main.close()
        raise SystemExit("No source databases to merge")

    for table in ("player_profiles", "team_builds"):
        row = main.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        counts[table] = int(row[0]) if row else 0

    main.commit()
    main.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge player card store shards")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--base",
        type=Path,
        default=None,
        help="Prior merged store to upsert into (incremental builds)",
    )
    parser.add_argument("shards", type=Path, nargs="+")
    args = parser.parse_args()
    counts = merge_stores(args.out, args.shards, base=args.base)
    print(f"Merged {len(args.shards)} shards -> {args.out}" + (f" (base={args.base})" if args.base else ""))
    print(counts)


if __name__ == "__main__":
    main()
