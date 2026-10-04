#!/usr/bin/env python3
"""Decide whether a player-cards CI rebuild is needed — and for whom.

Compares live NHL per-team GP + PWHL finals against the previous successful
run. Skips PWHL entirely when its regular season has not started (or has ended).
Only NHL teams with new games since the last fingerprint are marked dirty.

Exit 0 always; writes GitHub Actions outputs + plan JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UA = "PlayerCardsFreshness/1.0"
PWHL_KEY = "446521baf8c38984"

NHL_SHARDS: list[dict[str, Any]] = [
    {"shard_id": 1, "teams": "ANA,BOS,BUF,CGY", "league": "nhl"},
    {"shard_id": 2, "teams": "CAR,CBJ,CHI,COL", "league": "nhl"},
    {"shard_id": 3, "teams": "DAL,DET,EDM,FLA", "league": "nhl"},
    {"shard_id": 4, "teams": "LAK,MIN,MTL,NJD", "league": "nhl"},
    {"shard_id": 5, "teams": "NSH,NYI,NYR,OTT", "league": "nhl"},
    {"shard_id": 6, "teams": "PHI,PIT,SEA,SJS", "league": "nhl"},
    {"shard_id": 7, "teams": "STL,TBL,TOR,UTA", "league": "nhl"},
    {"shard_id": 8, "teams": "VAN,VGK,WPG,WSH", "league": "nhl"},
]
PWHL_SHARD = {"shard_id": 9, "teams": "BPF,MNF,MVL,NYS,OTC,TSR", "league": "pwhl"}


def _get_json(url: str, timeout: float = 20.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def nhl_fingerprint() -> dict[str, Any]:
    """Calendar-based active season + per-team standings GP."""
    from player_cards.leagues import detect_active_season, nhl_api_season_id

    tag, instat_sid = detect_active_season("nhl")
    api_sid = nhl_api_season_id(tag)

    data = _get_json("https://api-web.nhle.com/v1/standings/now")
    standings = data.get("standings") or []
    standing_sid = str((standings[0] or {}).get("seasonId") or "") if standings else ""
    team_gp: dict[str, int] = {}
    gp_sum = 0
    if standing_sid == api_sid:
        for row in standings:
            abbrev = (row.get("teamAbbrev") or {}).get("default") or row.get("teamAbbrev")
            if not abbrev:
                continue
            tri = str(abbrev).upper()
            gp = int(row.get("gamesPlayed") or 0)
            team_gp[tri] = gp
            gp_sum += gp

    return {
        "league": "nhl",
        "season_tag": tag,
        "season_id": api_sid,
        "instat_season_id": instat_sid,
        "games_played_sum": gp_sum,
        "standings_season_id": standing_sid,
        "team_count": len(team_gp),
        "team_gp": team_gp,
    }


def pwhl_fingerprint() -> dict[str, Any]:
    """PWHL HT regular-season window + completed-game count.

    ``season_active`` is True only while today falls inside the HockeyTech
    regular-season start/end dates — not during NHL October or PWHL preseason.
    """
    from player_cards.leagues import (
        _pwhl_regular_seasons_from_hockeytech,
        detect_active_season,
        detect_pwhl_hockeytech_season,
    )

    season_tag, instat_sid = detect_active_season("pwhl")
    season_id = str(detect_pwhl_hockeytech_season())
    today = date.today()
    season_active = False
    for row in _pwhl_regular_seasons_from_hockeytech():
        if row["tag"] == season_tag and row["start"] <= today <= row["end"]:
            season_active = True
            break

    final = 0
    scheduled = 0
    team_final: dict[str, int] = {}
    if season_active:
        url = (
            f"https://lscluster.hockeytech.com/feed/"
            f"?feed=modulekit&view=schedule&key={PWHL_KEY}"
            f"&client_code=pwhl&season_id={season_id}&fmt=json"
        )
        data = _get_json(url, timeout=45.0)
        games = (data.get("SiteKit") or {}).get("Schedule") or []
        scheduled = len(games)
        for g in games:
            if str(g.get("final") or "") != "1":
                continue
            final += 1
            for key in ("home_team_code", "visiting_team_code", "home_code", "away_code"):
                code = str(g.get(key) or "").upper()
                if code:
                    team_final[code] = team_final.get(code, 0) + 1

    return {
        "league": "pwhl",
        "season_tag": season_tag,
        "season_id": season_id,
        "instat_season_id": instat_sid,
        "season_active": season_active,
        "final_games": final,
        "scheduled_games": scheduled,
        "team_final": team_final,
    }


def live_fingerprint() -> dict[str, Any]:
    nhl = nhl_fingerprint()
    pwhl = pwhl_fingerprint()
    return {
        "version": 3,
        "nhl_season_tag": nhl["season_tag"],
        "nhl_season_id": nhl["season_id"],
        "nhl_instat_season_id": nhl["instat_season_id"],
        "nhl_games_played_sum": nhl["games_played_sum"],
        "nhl_team_count": nhl["team_count"],
        "nhl_team_gp": nhl["team_gp"],
        "pwhl_season_tag": pwhl["season_tag"],
        "pwhl_season_id": pwhl["season_id"],
        "pwhl_instat_season_id": pwhl["instat_season_id"],
        "pwhl_season_active": pwhl["season_active"],
        "pwhl_final_games": pwhl["final_games"],
        "pwhl_scheduled_games": pwhl["scheduled_games"],
        "pwhl_team_final": pwhl["team_final"],
    }


def load_previous(path: Path | None) -> dict[str, Any] | None:
    if not path or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def dirty_nhl_teams(prev: dict[str, Any] | None, live: dict[str, Any], *, force: bool) -> list[str]:
    live_gp = {str(k).upper(): int(v) for k, v in (live.get("nhl_team_gp") or {}).items()}
    all_teams = sorted(live_gp) or sorted(
        {t for s in NHL_SHARDS for t in s["teams"].split(",")}
    )
    if force or prev is None:
        return all_teams
    if prev.get("nhl_season_id") != live.get("nhl_season_id"):
        return all_teams
    prev_gp = {str(k).upper(): int(v) for k, v in (prev.get("nhl_team_gp") or {}).items()}
    # Legacy v2 fingerprints only had the sum — rebuild all NHL once to seed per-team.
    if not prev_gp and prev.get("nhl_games_played_sum") is not None:
        if int(prev.get("nhl_games_played_sum") or 0) != int(live.get("nhl_games_played_sum") or 0):
            return all_teams
        return []
    dirty = [t for t, gp in live_gp.items() if gp > prev_gp.get(t, -1)]
    # New franchise abbrev appearing in standings
    dirty.extend(t for t in live_gp if t not in prev_gp)
    return sorted(set(dirty))


def pwhl_should_build(prev: dict[str, Any] | None, live: dict[str, Any], *, force: bool) -> bool:
    if not live.get("pwhl_season_active"):
        return False
    if force or prev is None:
        return True
    if prev.get("pwhl_season_id") != live.get("pwhl_season_id"):
        return True
    if int(live.get("pwhl_final_games") or 0) > int(prev.get("pwhl_final_games") or 0):
        return True
    return False


def build_matrix(dirty_nhl: list[str], include_pwhl: bool) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    dirty_set = {t.upper() for t in dirty_nhl}
    for shard in NHL_SHARDS:
        teams = [t for t in shard["teams"].split(",") if t in dirty_set]
        if teams:
            selected.append(
                {
                    "shard_id": shard["shard_id"],
                    "teams": ",".join(teams),
                    "league": "nhl",
                }
            )
    if include_pwhl:
        selected.append(dict(PWHL_SHARD))
    return selected


def change_reason(
    prev: dict[str, Any] | None,
    live: dict[str, Any],
    dirty_nhl: list[str],
    include_pwhl: bool,
    *,
    force: bool,
) -> str:
    if force:
        return "force=true"
    if prev is None:
        return "no previous fingerprint"
    reasons: list[str] = []
    if prev.get("nhl_season_id") != live.get("nhl_season_id"):
        reasons.append(
            f"NHL season {prev.get('nhl_season_id')} → {live.get('nhl_season_id')}"
        )
    if dirty_nhl:
        reasons.append(f"{len(dirty_nhl)} NHL team(s) with new games")
    if include_pwhl:
        if not prev.get("pwhl_season_active") and live.get("pwhl_season_active"):
            reasons.append("PWHL regular season started")
        elif prev.get("pwhl_season_id") != live.get("pwhl_season_id"):
            reasons.append(
                f"PWHL season {prev.get('pwhl_season_id')} → {live.get('pwhl_season_id')}"
            )
        elif int(live.get("pwhl_final_games") or 0) > int(prev.get("pwhl_final_games") or 0):
            reasons.append("new PWHL games")
        else:
            reasons.append("PWHL rebuild")
    if not reasons:
        if not live.get("pwhl_season_active"):
            return "no new NHL games; PWHL regular season not active"
        return "no new NHL/PWHL completed games since last build"
    return ", ".join(reasons)


def _write_output(key: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        print(f"OUTPUT {key}={value}")
        return
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(f"{key}={value}\n")


def _write_output_multiline(key: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        print(f"OUTPUT {key}={value[:200]}...")
        return
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(f"{key}<<EOF\n{value}\nEOF\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--previous", type=Path, default=Path(".ci/data-fingerprint.json"))
    ap.add_argument("--write-live", type=Path, default=Path(".ci/live-fingerprint.json"))
    ap.add_argument("--write-plan", type=Path, default=Path(".ci/build-plan.json"))
    ap.add_argument(
        "--force",
        action="store_true",
        help="Rebuild all active-league teams (still skips inactive PWHL)",
    )
    args = ap.parse_args()

    live = live_fingerprint()
    args.write_live.parent.mkdir(parents=True, exist_ok=True)
    args.write_live.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    prev = load_previous(args.previous)
    force = bool(args.force)

    dirty_nhl = dirty_nhl_teams(prev, live, force=force)
    include_pwhl = pwhl_should_build(prev, live, force=force)
    matrix_include = build_matrix(dirty_nhl, include_pwhl)
    should_build = bool(matrix_include)
    reason = change_reason(prev, live, dirty_nhl, include_pwhl, force=force)
    full_build = bool(
        force
        or prev is None
        or (
            len(dirty_nhl) >= 32
            and include_pwhl
            and live.get("pwhl_season_active")
        )
        or (
            len(dirty_nhl) >= 32
            and not live.get("pwhl_season_active")
            and not include_pwhl
        )
    )
    # "Full" for merge coverage = rebuilt every NHL team this run (PWHL optional).
    full_nhl = len(dirty_nhl) >= 32 or (
        force and bool(live.get("nhl_team_gp"))
    )

    plan = {
        "should_build": should_build,
        "reason": reason,
        "full_build": full_nhl and (include_pwhl or not live.get("pwhl_season_active")),
        "full_nhl": full_nhl,
        "include_pwhl": include_pwhl,
        "dirty_nhl_teams": dirty_nhl,
        "matrix": {"include": matrix_include},
        "pwhl_season_active": bool(live.get("pwhl_season_active")),
    }
    args.write_plan.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("Live fingerprint:")
    print(json.dumps(live, indent=2, sort_keys=True))
    print("Previous fingerprint:")
    print(json.dumps(prev, indent=2, sort_keys=True) if prev else "  <none>")
    print("Build plan:")
    print(json.dumps(plan, indent=2, sort_keys=True))
    print(f"should_build={should_build} reason={reason}")

    _write_output("should_build", "true" if should_build else "false")
    _write_output("reason", reason)
    _write_output("include_pwhl", "true" if include_pwhl else "false")
    _write_output("full_nhl", "true" if full_nhl else "false")
    _write_output("full_build", "true" if plan["full_build"] else "false")
    _write_output("dirty_nhl_count", str(len(dirty_nhl)))
    _write_output("dirty_nhl_teams", ",".join(dirty_nhl))
    _write_output_multiline("matrix", json.dumps(plan["matrix"], separators=(",", ":")))
    _write_output(
        "summary",
        (
            f"nhl={live.get('nhl_season_tag')} dirty={len(dirty_nhl)} "
            f"pwhl_active={live.get('pwhl_season_active')} "
            f"pwhl_build={include_pwhl} ({reason})"
        ),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
