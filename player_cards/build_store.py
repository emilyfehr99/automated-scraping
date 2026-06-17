#!/usr/bin/env python3
"""Batch build player card SQLite store for NHL and/or PWHL."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from .a3z_source import resolve_a3z_season
from .card_store import DEFAULT_STORE_PATH, open_store
from .disk_cache import pbp_files_fingerprint
from .html_renderer import prewarm_photo
from .instat_pbp_fetch import (
    batch_download_team_pbp,
    ensure_team_pbp_files,
    team_pbp_dir,
    try_fast_pbp_cache,
)
from .leagues import LEAGUES, get_league, instat_season_id, list_teams, team_full_name
from .pbp_display import _pbp_values, compute_team_metric_percentiles
from .pbp_metrics import aggregate_player_pbp
from .pbp_team_cache import warm_team_pbp
from .profile import build_player_card_profile
from .pwhl_bio import roster_from_pbp
from .qoc_qot import compute_league_context

logger = logging.getLogger(__name__)

NHL_API = "https://api-web.nhle.com/v1"
ROSTER_SEASON = "20252026"


def fetch_nhl_roster(team: str) -> list[dict[str, Any]]:
    tri = team.upper()
    resp = httpx.get(
        f"{NHL_API}/roster/{tri}/{ROSTER_SEASON}",
        timeout=20.0,
        headers={"User-Agent": "PlayerCards/1.0"},
    )
    resp.raise_for_status()
    data = resp.json()
    players: list[dict[str, Any]] = []
    for group in ("forwards", "defensemen", "goalies"):
        for p in data.get(group) or []:
            first = (p.get("firstName") or {}).get("default") or ""
            last = (p.get("lastName") or {}).get("default") or ""
            name = f"{first} {last}".strip()
            if not name or not p.get("id"):
                continue
            players.append(
                {
                    "player_id": int(p["id"]),
                    "name": name,
                    "team": tri,
                    "league": "nhl",
                }
            )
    return players


def fetch_roster(league: str, team: str, pbp_files: list[Path]) -> list[dict[str, Any]]:
    cfg = get_league(league)
    if cfg.uses_nhl_api:
        return fetch_nhl_roster(team)
    return roster_from_pbp(pbp_files, team, league=league)


def _team_pbp_percentiles(
    roster: list[dict[str, Any]],
    pbp_files: list[Path],
    team: str,
    *,
    league: str,
    team_games: int | None,
) -> dict[str, dict[str, float | None]]:
    metrics: dict[str, dict[str, float]] = {}
    for entry in roster:
        name = entry["name"]
        pbp = aggregate_player_pbp(name, team, files=pbp_files, team_games=team_games)
        if not pbp:
            continue
        vals = _pbp_values(pbp.get("per_game") or {})
        metrics[name] = {k: v for k, v in vals.items() if not k.startswith("_")}
    return compute_team_metric_percentiles(metrics)


def build_team(
    store,
    league: str,
    team: str,
    *,
    season: str,
    instat_sid: int,
    skip_pbp_download: bool = False,
    refresh_pbp: bool = False,
    players_only: bool = False,
) -> dict[str, Any]:
    cfg = get_league(league)
    tri = team.upper()
    pbp_dir = team_pbp_dir(tri, league=league, a3z_season=season, season_id=instat_sid)
    t0 = time.perf_counter()

    pbp_meta: dict[str, Any] = {}
    pbp_files: list[Path] = []

    if players_only or skip_pbp_download:
        fast = try_fast_pbp_cache(tri, pbp_dir, league=league, a3z_season=season, season_id=instat_sid)
        if not fast:
            raise RuntimeError(
                f"No cached PBP for {league}/{tri} — run without --skip-pbp-download first"
            )
        pbp_meta = fast
        pbp_files = [Path(p) for p in fast.get("files", [])]
    else:
        pbp_meta = ensure_team_pbp_files(
            tri,
            pbp_dir,
            league=league,
            a3z_season=season,
            season_id=instat_sid,
            refresh=refresh_pbp,
        )
        pbp_files = [Path(p) for p in pbp_meta.get("files", [])]

    if pbp_files:
        warm_team_pbp(pbp_files)
        team_full = team_full_name(league, tri)
        logger.info("Precomputing league QOC/QOT for %s/%s (%s games)", league, tri, len(pbp_files))
        compute_league_context(pbp_files, team_full)

    fingerprint = pbp_files_fingerprint(pbp_files) if pbp_files else None
    match_ids = pbp_meta.get("match_ids") or []
    team_game_count = len(match_ids) if pbp_meta.get("complete") and match_ids else None
    roster = fetch_roster(league, tri, pbp_files)
    logger.info("Building %s %s — %s players", league, tri, len(roster))

    pct_by_player: dict[str, dict[str, float | None]] = {}
    if not cfg.uses_a3z and pbp_files:
        pct_by_player = _team_pbp_percentiles(roster, pbp_files, tri, league=league, team_games=team_game_count)

    built = 0
    skipped = 0
    for entry in roster:
        name = entry["name"]
        try:
            profile = build_player_card_profile(
                name,
                team=tri,
                league=league,
                a3z_season=season,
                instat_season_id=instat_sid,
                pbp_dir=pbp_dir,
                refresh_pbp=False,
                use_store=False,
                pbp_percentiles=pct_by_player.get(name),
            )
            url = (profile.get("bio") or {}).get("card_photo_url")
            if url:
                prewarm_photo(url)
            store.upsert_profile(profile, season=season, pbp_fingerprint=fingerprint)
            built += 1
            logger.info("  [%s/%s] %s", built, len(roster), name)
        except Exception as exc:
            skipped += 1
            logger.warning("  skip %s: %s", name, exc)

    store.upsert_team(
        tri,
        season,
        league=league,
        pbp_fingerprint=fingerprint,
        pbp_dir=str(pbp_dir),
        match_count=team_game_count or len(pbp_files),
        player_count=built,
    )

    return {
        "league": league,
        "team": tri,
        "season": season,
        "built": built,
        "skipped": skipped,
        "roster": len(roster),
        "pbp_games": len(pbp_files),
        "seconds": round(time.perf_counter() - t0, 1),
    }


def build_store(
    *,
    leagues: list[str] | None = None,
    teams: list[str] | None = None,
    season: str | None = None,
    instat_season_id_override: int | None = None,
    store_path: Path | str | None = None,
    skip_pbp_download: bool = False,
    refresh_pbp: bool = False,
    players_only: bool = False,
) -> dict[str, Any]:
    league_keys = [lk.lower() for lk in (leagues or ["nhl"])]
    results: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    total_players = 0

    team_plan: list[tuple[str, str, str, int]] = []
    download_jobs: list[dict[str, Any]] = []

    for league_key in league_keys:
        cfg = get_league(league_key)
        season_tag = resolve_a3z_season(season or cfg.default_season, instat_season_id_override)
        sid = (
            instat_season_id_override
            if instat_season_id_override is not None
            else instat_season_id(season_tag, league_key)
        )
        target = [t.upper() for t in (teams or list_teams(league_key))]
        for tri in target:
            if tri not in cfg.teams:
                continue
            team_plan.append((league_key, tri, season_tag, sid))
            if skip_pbp_download or players_only:
                continue
            pbp_dir = team_pbp_dir(tri, league=league_key, a3z_season=season_tag, season_id=sid)
            cached = try_fast_pbp_cache(
                tri, pbp_dir, league=league_key, a3z_season=season_tag, season_id=sid
            )
            if cached and not refresh_pbp:
                logger.info("PBP already cached for %s/%s (%s games)", league_key, tri, cached["cached"])
                continue
            download_jobs.append(
                {
                    "league": league_key,
                    "team": tri,
                    "output_dir": pbp_dir,
                    "a3z_season": season_tag,
                    "season_id": sid,
                    "refresh": refresh_pbp,
                }
            )

    if download_jobs:
        logger.info("Batch downloading PBP for %s teams (one InStat session)", len(download_jobs))
        asyncio.run(batch_download_team_pbp(download_jobs))

    with open_store(store_path) as store:
        for league_key, tri, season_tag, sid in team_plan:
            cfg = get_league(league_key)
            if tri not in cfg.teams:
                logger.warning("Unknown %s team: %s", league_key, tri)
                continue
            store.set_meta(f"season:{league_key}", season_tag)
            store.set_meta(f"instat_season_id:{league_key}", str(sid))
            logger.info("=== Index %s / %s ===", league_key.upper(), tri)
            try:
                use_skip = skip_pbp_download or players_only or bool(
                    try_fast_pbp_cache(
                        tri,
                        team_pbp_dir(tri, league=league_key, a3z_season=season_tag, season_id=sid),
                        league=league_key,
                        a3z_season=season_tag,
                        season_id=sid,
                    )
                )
                summary = build_team(
                    store,
                    league_key,
                    tri,
                    season=season_tag,
                    instat_sid=sid,
                    skip_pbp_download=use_skip,
                    refresh_pbp=False,
                    players_only=players_only,
                )
                results.append(summary)
            except Exception as exc:
                logger.error("%s/%s failed: %s", league_key, tri, exc)
                results.append({"league": league_key, "team": tri, "error": str(exc)})

        for league_key in league_keys:
            season_tag = resolve_a3z_season(season or get_league(league_key).default_season, instat_season_id_override)
            total_players += store.count_players(season_tag, league=league_key)

    return {
        "store": str(store_path or DEFAULT_STORE_PATH),
        "leagues": league_keys,
        "players_indexed": total_players,
        "seconds": round(time.perf_counter() - t0, 1),
        "results": results,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Prebuild player card store (NHL + PWHL)")
    parser.add_argument(
        "--league",
        default="nhl",
        help="nhl, pwhl, or all (comma-separated)",
    )
    parser.add_argument(
        "--teams",
        default="all",
        help="Team abbrevs or 'all' for the selected league(s)",
    )
    parser.add_argument("--season", default=None)
    parser.add_argument("--instat-season-id", type=int, default=None)
    parser.add_argument("--store", default=str(DEFAULT_STORE_PATH))
    parser.add_argument("--skip-pbp-download", action="store_true")
    parser.add_argument("--refresh-pbp", action="store_true")
    parser.add_argument("--players-only", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    raw = args.league.lower()
    if raw == "all":
        league_list = list(LEAGUES.keys())
    else:
        league_list = [x.strip() for x in raw.split(",") if x.strip()]

    teams = None if args.teams.lower() == "all" else [t.strip() for t in args.teams.split(",") if t.strip()]
    summary = build_store(
        leagues=league_list,
        teams=teams,
        season=args.season,
        instat_season_id_override=args.instat_season_id,
        store_path=Path(args.store),
        skip_pbp_download=args.skip_pbp_download,
        refresh_pbp=args.refresh_pbp,
        players_only=args.players_only,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
