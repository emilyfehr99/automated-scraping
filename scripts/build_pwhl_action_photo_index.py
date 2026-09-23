#!/usr/bin/env python3
"""Build PWHL action-photo index from OurSports Central game photo releases."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from player_cards.pwhl_action_sync import sync_pwhl_action_photos  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=None, help="(legacy) ignored — use --full")
    parser.add_argument("--end", type=int, default=None, help="(legacy) ignored — use --full")
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--full", action="store_true", help="Scan full OSC id ranges")
    args = parser.parse_args()
    result = sync_pwhl_action_photos(full=args.full, workers=args.workers)
    print(
        f"Indexed {result['indexed_players']}/{result['roster_size']} players "
        f"({result['coverage_pct']}%), +{result['added_this_run']} this run."
    )


if __name__ == "__main__":
    main()

