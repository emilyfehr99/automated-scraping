#!/usr/bin/env python3
"""Audit PWHL action-photo coverage across the full HockeyTech roster."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from player_cards.pwhl_action_photos import resolve_pwhl_action_photo
from player_cards.pwhl_action_sync import action_photo_coverage, ensure_pwhl_action_index
from player_cards.pwhl_photos import PWHL_HOCKEYTECH_TEAM_IDS, _fetch_ht_roster


def audit(*, sync: bool = False) -> dict:
    if sync:
        ensure_pwhl_action_index(force=True)
    cov = action_photo_coverage()
    rows = []
    hero = placeholder = 0
    for tri, team_id in PWHL_HOCKEYTECH_TEAM_IDS.items():
        for player in _fetch_ht_roster(team_id):
            pid = str(player.get("player_id") or "")
            name = str(player.get("name") or "")
            photo = resolve_pwhl_action_photo(pid, name, team_abbrev=tri, discover=False, allow_team_fallback=False)
            kind = (photo or {}).get("card_photo_kind") or "placeholder"
            if kind == "hero":
                hero += 1
            else:
                placeholder += 1
            rows.append(
                {
                    "team": tri,
                    "ht_player_id": pid,
                    "name": name,
                    "card_photo_kind": kind,
                    "card_photo_url": (photo or {}).get("card_photo_url"),
                    "photo_source": (photo or {}).get("photo_source"),
                }
            )
    return {
        "roster_size": len(rows),
        "hero": hero,
        "placeholder": placeholder,
        "coverage_pct": round(100.0 * hero / max(len(rows), 1), 1),
        "index": cov,
        "players": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sync", action="store_true", help="Run OSC sync before audit")
    parser.add_argument("--missing-only", action="store_true")
    args = parser.parse_args()
    report = audit(sync=args.sync)
    print(
        f"PWHL action photos: {report['hero']}/{report['roster_size']} hero "
        f"({report['coverage_pct']}%), {report['placeholder']} placeholder"
    )
    if args.missing_only:
        for row in report["players"]:
            if row["card_photo_kind"] != "hero":
                print(f"  {row['team']} {row['name']}")
    else:
        for row in report["players"]:
            src = row.get("photo_source") or "—"
            print(f"  {row['team']:3} {row['name']:28} {row['card_photo_kind']:11} {src}")


if __name__ == "__main__":
    main()
