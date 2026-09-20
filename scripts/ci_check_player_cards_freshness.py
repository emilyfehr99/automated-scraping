#!/usr/bin/env python3
"""Decide whether a player-cards CI rebuild is needed.

Compares live NHL + PWHL completed-game fingerprints against the previous
successful run's fingerprint. Exit 0 always; writes GitHub Actions outputs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

UA = "PlayerCardsNewDataCheck/1.0"
PWHL_KEY = "446521baf8c38984"
NHL_STANDINGS = "https://api-web.nhle.com/v1/standings/now"
PWHL_SEASONS = (
    f"https://lscluster.hockeytech.com/feed/"
    f"?feed=modulekit&view=seasons&key={PWHL_KEY}&client_code=pwhl&fmt=json"
)


def _get_json(url: str, timeout: float = 20.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def nhl_fingerprint() -> dict[str, Any]:
    data = _get_json(NHL_STANDINGS)
    standings = data.get("standings") or []
    season_id = str((standings[0] or {}).get("seasonId") or "") if standings else ""
    gp_sum = sum(int(row.get("gamesPlayed") or 0) for row in standings)
    return {
        "league": "nhl",
        "season_id": season_id,
        "games_played_sum": gp_sum,
        "team_count": len(standings),
    }


def _pwhl_regular_season_id() -> str:
    data = _get_json(PWHL_SEASONS)
    seasons = (data.get("SiteKit") or {}).get("Seasons") or []
    for row in seasons:
        name = str(row.get("season_name") or "")
        if "Regular Season" in name:
            return str(row.get("season_id"))
    if seasons:
        return str(seasons[0].get("season_id"))
    return "8"


def pwhl_fingerprint() -> dict[str, Any]:
    season_id = _pwhl_regular_season_id()
    url = (
        f"https://lscluster.hockeytech.com/feed/"
        f"?feed=modulekit&view=schedule&key={PWHL_KEY}"
        f"&client_code=pwhl&season_id={season_id}&fmt=json"
    )
    data = _get_json(url, timeout=45.0)
    games = (data.get("SiteKit") or {}).get("Schedule") or []
    final = sum(1 for g in games if str(g.get("final") or "") == "1")
    return {
        "league": "pwhl",
        "season_id": season_id,
        "final_games": final,
        "scheduled_games": len(games),
    }


def live_fingerprint() -> dict[str, Any]:
    nhl = nhl_fingerprint()
    pwhl = pwhl_fingerprint()
    return {
        "version": 1,
        "nhl_season_id": nhl["season_id"],
        "nhl_games_played_sum": nhl["games_played_sum"],
        "nhl_team_count": nhl["team_count"],
        "pwhl_season_id": pwhl["season_id"],
        "pwhl_final_games": pwhl["final_games"],
        "pwhl_scheduled_games": pwhl["scheduled_games"],
    }


def load_previous(path: Path | None) -> dict[str, Any] | None:
    if not path or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def comparable(fp: dict[str, Any]) -> dict[str, Any]:
    """Fields that gate rebuilds (ignore timestamps / metadata)."""
    keys = (
        "version",
        "nhl_season_id",
        "nhl_games_played_sum",
        "pwhl_season_id",
        "pwhl_final_games",
    )
    return {k: fp.get(k) for k in keys}


def _write_output(key: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        print(f"OUTPUT {key}={value}")
        return
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(f"{key}={value}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--previous", type=Path, default=Path(".ci/data-fingerprint.json"))
    ap.add_argument("--write-live", type=Path, default=Path(".ci/live-fingerprint.json"))
    ap.add_argument(
        "--force",
        action="store_true",
        help="Always rebuild (ignore previous fingerprint)",
    )
    args = ap.parse_args()

    live = live_fingerprint()
    args.write_live.parent.mkdir(parents=True, exist_ok=True)
    args.write_live.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    prev = load_previous(args.previous)
    force = bool(args.force)

    if force:
        reason = "force=true"
        should_build = True
    elif prev is None:
        reason = "no previous fingerprint"
        should_build = True
    elif comparable(prev) != comparable(live):
        reason = "new games or season change"
        should_build = True
    else:
        reason = "no new NHL/PWHL completed games since last build"
        should_build = False

    print("Live fingerprint:")
    print(json.dumps(live, indent=2, sort_keys=True))
    print("Previous fingerprint:")
    print(json.dumps(prev, indent=2, sort_keys=True) if prev else "  <none>")
    print(f"should_build={should_build} reason={reason}")

    _write_output("should_build", "true" if should_build else "false")
    _write_output("reason", reason)
    _write_output(
        "summary",
        (
            f"nhl_gp={live.get('nhl_games_played_sum')} "
            f"pwhl_final={live.get('pwhl_final_games')} "
            f"({reason})"
        ),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
