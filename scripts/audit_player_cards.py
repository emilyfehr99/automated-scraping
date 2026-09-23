#!/usr/bin/env python3
"""Audit player card data accuracy (store + live profile checks)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from player_cards.card_store import open_store
from player_cards.leagues import LEAGUES, list_teams
from player_cards.profile import (
    _display_missing_percentiles,
    _display_usable,
    _stale_pbp_display,
    _store_pbp_stale,
    _store_profile_stale,
    build_player_card_profile,
)
from player_cards.pbp_display import _pbp_values


def _audit_profile(prof: dict[str, Any], *, league: str) -> list[str]:
    issues: list[str] = []
    bio = prof.get("bio") or {}
    pbp = prof.get("pbp") or {}
    a3z = prof.get("a3z") or {}
    pg = pbp.get("per_game") or {}

    if _store_profile_stale(prof):
        issues.append("stale_profile")
    if not _display_usable(prof):
        issues.append("display_unusable")
    if _store_pbp_stale(pbp):
        issues.append("stale_pbp_aggregate")
    if pg.get("Chance Assists") is None and league == "pwhl":
        issues.append("missing_chance_assists")
    if _display_missing_percentiles(a3z):
        issues.append("missing_percentiles")
    if _stale_pbp_display(a3z):
        issues.append("stale_display_layout")

    for vital in ("height", "shoots", "position"):
        val = bio.get(vital)
        if not val or val in ("—", ""):
            if vital == "position" and not bio.get("ht_player_id"):
                issues.append(f"missing_bio_{vital}")
            elif vital != "position":
                issues.append(f"missing_bio_{vital}")
            break

    offense = (a3z.get("sections") or {}).get("Offense") or []
    if league == "pwhl":
        if any(m.get("key") == "one_timer_per_60" for m in offense):
            issues.append("pwhl_has_one_timer_metric")
        play = next((m for m in offense if m.get("key") == "chance_assists_per_60"), None)
        if play and play.get("value") is None:
            issues.append("playmaking_dash")

    gp_skated = int(pbp.get("games_played") or 0)
    gp_team = int(pbp.get("games") or 0)
    if gp_skated and gp_team and gp_skated > gp_team:
        issues.append(f"gp_skated_exceeds_team:{gp_skated}>{gp_team}")

    shots = pbp.get("shots") or []
    goals_map = sum(1 for s in shots if s.get("goal"))
    goals_pbp = int(pbp.get("goals") or 0)
    if shots and goals_map != goals_pbp:
        issues.append(f"shot_map_goals_mismatch:{goals_map}!={goals_pbp}")

    vals = _pbp_values(pg)
    if pg.get("Shots") and vals.get("shots_per_60") is None:
        issues.append("shots_metric_unmapped")

    hero = (a3z.get("microstat_game_score") or {})
    if league == "pwhl" and hero.get("value") is not None:
        ms = float(pg.get("Microstat Game Score") or 0)
        hv = float(hero["value"])
        if abs(ms - hv) > 0.05:
            issues.append(f"hero_gs_mismatch:{hv}!={ms}")

    return issues


def audit_store(*, league: str | None, season: str) -> dict[str, Any]:
    from player_cards.instat_pbp_fetch import team_pbp_dir, try_fast_pbp_cache
    from player_cards.nhl_instat import instat_season_id

    rows: list[dict[str, Any]] = []
    summary: dict[str, int] = {"profiles": 0, "with_issues": 0, "skipped_no_pbp": 0}

    pbp_ready: set[tuple[str, str]] = set()
    if league in (None, "pwhl"):
        sid = instat_season_id(season, "pwhl")
        for tri in list_teams("pwhl"):
            pbp_dir = team_pbp_dir(tri, league="pwhl", a3z_season=season, season_id=sid)
            if try_fast_pbp_cache(tri, pbp_dir, league="pwhl", a3z_season=season, season_id=sid):
                pbp_ready.add(("pwhl", tri))

    with open_store() as store:
        conn = store._conn
        q = "SELECT league, name, team, profile_json FROM player_profiles WHERE season=?"
        params: list[Any] = [season]
        if league:
            q += " AND league=?"
            params.append(league.lower())
        for lg, name, team, pj in conn.execute(q, params).fetchall():
            if lg == "pwhl" and (lg, team) not in pbp_ready:
                summary["skipped_no_pbp"] += 1
                continue
            prof = json.loads(pj)
            summary["profiles"] += 1
            issues = _audit_profile(prof, league=lg)
            if issues:
                summary["with_issues"] += 1
                rows.append({"league": lg, "name": name, "team": team, "issues": issues})

    return {"summary": summary, "issues": rows}


def audit_live(
    *,
    league: str,
    teams: list[str],
    season: str,
    sample: int,
) -> dict[str, Any]:
    from player_cards.build_store import fetch_roster
    from player_cards.instat_pbp_fetch import team_pbp_dir, try_fast_pbp_cache
    from player_cards.nhl_instat import instat_season_id

    sid = instat_season_id(season, league)
    checked: list[dict[str, Any]] = []
    for tri in teams:
        pbp_dir = team_pbp_dir(tri, league=league, a3z_season=season, season_id=sid)
        fast = try_fast_pbp_cache(tri, pbp_dir, league=league, a3z_season=season, season_id=sid)
        if not fast:
            checked.append({"team": tri, "error": "no_pbp_cache"})
            continue
        files = [Path(p) for p in fast.get("files", [])]
        roster = fetch_roster(league, tri, files)
        names = [e["name"] for e in roster[:sample]] if sample else [e["name"] for e in roster]
        for name in names:
            try:
                prof = build_player_card_profile(
                    name,
                    team=tri,
                    league=league,
                    refresh_pbp=True,
                    use_store=False,
                )
                issues = _audit_profile(prof, league=league)
                checked.append({"team": tri, "name": name, "issues": issues})
            except Exception as exc:
                checked.append({"team": tri, "name": name, "error": str(exc)})

    bad = [c for c in checked if c.get("issues") or c.get("error")]
    return {"checked": len(checked), "with_issues": len(bad), "results": checked}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit player card data accuracy")
    parser.add_argument("--league", default="pwhl", help="nhl, pwhl, or all")
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--live", action="store_true", help="Rebuild sample profiles live (slow)")
    parser.add_argument("--teams", default="", help="Comma-separated team abbrevs for live audit")
    parser.add_argument("--sample", type=int, default=3, help="Players per team for live audit")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    out: dict[str, Any] = {"season": args.season}
    lg = None if args.league.lower() == "all" else args.league.lower()
    out["store"] = audit_store(league=lg, season=args.season)

    if args.live:
        leagues = list(LEAGUES) if args.league.lower() == "all" else [args.league.lower()]
        out["live"] = {}
        for league_key in leagues:
            teams = (
                [t.strip().upper() for t in args.teams.split(",") if t.strip()]
                if args.teams
                else list_teams(league_key)
            )
            out["live"][league_key] = audit_live(
                league=league_key,
                teams=teams,
                season=args.season,
                sample=args.sample,
            )

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        s = out["store"]["summary"]
        print(f"Store audit: {s['profiles']} profiles, {s['with_issues']} with issues")
        for row in out["store"]["issues"][:30]:
            print(f"  {row['league']}/{row['team']} {row['name']}: {', '.join(row['issues'])}")
        if len(out["store"]["issues"]) > 30:
            print(f"  ... and {len(out['store']['issues']) - 30} more")
        if args.live and out.get("live"):
            for lg_key, live in out["live"].items():
                print(f"Live {lg_key}: {live['checked']} checked, {live['with_issues']} with issues")

    return 1 if out["store"]["summary"]["with_issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
