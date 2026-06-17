"""Merge NHL bio + A3Z microstats + full PBP microstats into one card profile."""

from __future__ import annotations

import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .a3z_source import fetch_a3z_profile, merge_deployment_context, resolve_a3z_season
from .cap_source import fetch_cap_info
from .card_store import load_stored_profile, open_store
from .disk_cache import cache_path, load_json, pbp_files_fingerprint, player_cache_key, save_json
from .game_context import build_game_context
from .html_renderer import write_player_card_html
from .instat_pbp_fetch import ensure_team_pbp_files, team_pbp_dir, try_fast_pbp_cache
from .instat_source import discover_team_pbp_files
from .leagues import get_league, team_full_name
from .nhl_bio import fetch_nhl_bio
from .nhl_instat import instat_season_id
from .pbp_display import build_pbp_display_profile
from .pbp_metrics import aggregate_player_pbp
from .pbp_team_cache import warm_team_pbp
from .png_export import html_to_png
from .pwhl_bio import fetch_pwhl_bio
from .qoc_qot import compute_player_qoc_qot
from .team_colors import get_team_colors

logger = logging.getLogger(__name__)

DEFAULT_A3Z_SEASON = "2025-26"
AGG_CACHE_TTL = 7 * 86_400  # 7 days — invalidated by file fingerprint


def _cached_pbp_aggregate(
    player_id: int | None,
    player_name: str,
    team: str,
    files: list[Path],
    team_games: int | None,
) -> dict[str, Any] | None:
    fp = pbp_files_fingerprint(files)
    key = player_cache_key(player_id, player_name)
    path = cache_path("aggregates", team.upper(), fp, f"{key}.json")
    hit = load_json(path, ttl_seconds=AGG_CACHE_TTL)
    if isinstance(hit, dict) and hit.get("per_game"):
        logger.debug("PBP aggregate cache hit for %s", player_name)
        return hit
    result = aggregate_player_pbp(player_name, team, files=files, team_games=team_games)
    if result:
        save_json(path, result)
    return result


def _cached_qoc_qot(
    player_id: int | None,
    player_name: str,
    team_full: str,
    files: list[Path],
) -> dict[str, Any] | None:
    fp = pbp_files_fingerprint(files)
    key = player_cache_key(player_id, player_name)
    path = cache_path("qoc", fp, f"{key}.json")
    hit = load_json(path, ttl_seconds=AGG_CACHE_TTL)
    if isinstance(hit, dict):
        return hit
    result = compute_player_qoc_qot(files, player_name, team_full)
    if result:
        save_json(path, result)
    return result


def _resolve_pbp_files(
    team: str,
    pbp_dir: Path,
    *,
    league: str = "nhl",
    a3z_season: str | None,
    pbp_source: str,
    instat_season_id: int | None,
    max_pbp_downloads: int | None,
    refresh_pbp: bool = False,
) -> tuple[list[Path], dict[str, Any]]:
    source = (pbp_source or os.getenv("PLAYER_CARDS_PBP_SOURCE", "api")).lower()

    if source == "local":
        files = discover_team_pbp_files(team)
        meta = {
            "source": "local_pbp",
            "output_dir": str(pbp_dir),
            "files": [str(f) for f in files],
            "cached": len(files),
            "match_ids": [],
            "complete": bool(files),
            "ephemeral": False,
        }
        return files, meta

    meta = ensure_team_pbp_files(
        team,
        pbp_dir,
        league=league,
        a3z_season=a3z_season,
        season_id=instat_season_id,
        max_downloads=max_pbp_downloads,
        refresh=refresh_pbp,
    )
    files = [Path(p) for p in meta.get("files", [])]
    if not files:
        raise RuntimeError(f"InStat API returned no PBP files for {team}")
    return files, meta


def _use_card_store() -> bool:
    return os.getenv("PLAYER_CARDS_USE_STORE", "1").strip().lower() not in ("0", "false", "no")


def _persist_to_store(profile: dict[str, Any], season: str, instat_sid: int | None, *, league: str = "nhl") -> None:
    bio = profile.get("bio") or {}
    tri = str(bio.get("team") or "").upper()
    if not tri:
        return
    sid = instat_sid if instat_sid is not None else instat_season_id(season, league)
    pbp_dir = team_pbp_dir(tri, league=league, a3z_season=season, season_id=sid)
    fast = try_fast_pbp_cache(tri, pbp_dir, league=league, a3z_season=season, season_id=sid)
    files = [Path(p) for p in (fast or {}).get("files", [])]
    fp = pbp_files_fingerprint(files) if files else None
    try:
        with open_store() as store:
            store.upsert_profile(profile, season=season, pbp_fingerprint=fp)
            if fp and files:
                store.upsert_team(
                    tri,
                    season,
                    league=league,
                    pbp_fingerprint=fp,
                    pbp_dir=str(pbp_dir),
                    match_count=len(files),
                    player_count=store.count_players(season, league=league),
                )
    except Exception as exc:
        logger.warning("Could not persist profile to card store: %s", exc)


def build_player_card_profile(
    player_name: str,
    team: str | None = None,
    *,
    league: str = "nhl",
    a3z_season: str | None = None,
    pbp_source: str | None = None,
    instat_season_id: int | None = None,
    max_pbp_downloads: int | None = None,
    pbp_dir: Path | None = None,
    refresh_pbp: bool = False,
    bio: dict[str, Any] | None = None,
    use_store: bool | None = None,
    pbp_percentiles: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    league = (league or "nhl").lower()
    cfg = get_league(league)
    season = resolve_a3z_season(a3z_season or cfg.default_season, instat_season_id)
    if (use_store if use_store is not None else _use_card_store()) and not refresh_pbp:
        stored = load_stored_profile(player_name, team=team, season=season, league=league)
        if stored:
            logger.info("Card store hit for %s", player_name)
            return stored

    if cfg.uses_nhl_api:
        bio = bio or fetch_nhl_bio(player_name, team=team)
    else:
        if not team:
            raise ValueError(f"{cfg.label} cards require --team ({', '.join(cfg.teams.keys())})")
        bio = bio or fetch_pwhl_bio(player_name, team, league=league)

    tri = bio["team"]

    if pbp_dir is None:
        pbp_dir = team_pbp_dir(tri, league=league, a3z_season=season, season_id=instat_season_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        cap_future = (
            pool.submit(fetch_cap_info, bio["name"], player_id=bio.get("player_id"))
            if cfg.uses_cap
            else None
        )
        pbp_future = pool.submit(
            _resolve_pbp_files,
            tri,
            pbp_dir,
            league=league,
            a3z_season=season,
            pbp_source=pbp_source or "api",
            instat_season_id=instat_season_id,
            max_pbp_downloads=max_pbp_downloads,
            refresh_pbp=refresh_pbp,
        )
        cap = cap_future.result() if cap_future else None
        pbp_files, pbp_meta = pbp_future.result()

    if not cfg.uses_nhl_api:
        bio = fetch_pwhl_bio(player_name, tri, league=league, files=pbp_files)

    warm_team_pbp(pbp_files)
    match_ids = pbp_meta.get("match_ids") or []
    team_game_count = len(match_ids) if pbp_meta.get("complete") and match_ids else None
    pbp = _cached_pbp_aggregate(
        bio.get("player_id"),
        bio["name"],
        tri,
        pbp_files,
        team_game_count,
    )
    if pbp:
        pbp["source"] = pbp_meta.get("source", "instat_api")

    team_full = team_full_name(league, tri)
    deployment = _cached_qoc_qot(bio.get("player_id"), bio["name"], team_full, pbp_files) if pbp_files else None

    if cfg.uses_a3z:
        a3z = fetch_a3z_profile(bio["name"], tri, season=season, pbp_team_games=(pbp or {}).get("games"))
        a3z = merge_deployment_context(a3z, deployment)
    else:
        a3z = build_pbp_display_profile(
            pbp,
            deployment,
            season=season,
            percentiles=pbp_percentiles,
        )

    games = build_game_context(pbp_files, pbp, a3z, a3z_season=season, pbp_meta=pbp_meta)

    return {
        "league": league,
        "bio": bio,
        "colors": get_team_colors(tri, league=league),
        "cap": cap,
        "a3z": a3z,
        "pbp": pbp,
        "instat": pbp,
        "games": games,
        "sources": {
            "league": league,
            "nhl": cfg.uses_nhl_api,
            "a3z": a3z is not None and cfg.uses_a3z,
            "pbp": pbp is not None,
            "cap": cap is not None,
            "a3z_season": season,
            "pbp_source": games.get("pbp_source"),
            "instat_season_id": games.get("instat_season_id"),
            "pbp_team_games": games["pbp_team_games"],
            "pbp_skated_games": games["pbp_skated_games"],
            "a3z_games": games["a3z_games"],
            "pbp_ephemeral": pbp_meta.get("ephemeral", False),
            "pbp_downloaded": pbp_meta.get("downloaded"),
            "pbp_skipped_api": pbp_meta.get("skipped_api"),
        },
    }


def generate_player_card(
    player_name: str,
    team: str | None = None,
    *,
    league: str = "nhl",
    output_png: Path | str | None = None,
    a3z_season: str | None = None,
    pbp_source: str | None = None,
    instat_season_id: int | None = None,
    max_pbp_downloads: int | None = None,
    save_json: bool = False,
    refresh_pbp: bool = False,
    use_store: bool | None = None,
) -> dict[str, Any]:
    """Build card using persistent PBP cache or SQLite store; writes PNG only unless save_json=True."""
    league = (league or "nhl").lower()
    cfg = get_league(league)
    season = resolve_a3z_season(a3z_season or cfg.default_season, instat_season_id)

    profile: dict[str, Any] | None = None
    if (use_store if use_store is not None else _use_card_store()) and not refresh_pbp:
        profile = load_stored_profile(player_name, team=team, season=season, league=league)
        if profile:
            logger.info("Card store hit for %s — skipping live data fetch", player_name)

    if profile is None:
        bio = fetch_nhl_bio(player_name, team=team) if cfg.uses_nhl_api else None
        tri = (bio or {}).get("team") or team
        if not tri and not cfg.uses_nhl_api:
            raise ValueError(f"{cfg.label} cards require --team")
        pbp_dir = team_pbp_dir(tri, league=league, a3z_season=season, season_id=instat_season_id)
        profile = build_player_card_profile(
            player_name,
            team=tri,
            league=league,
            a3z_season=a3z_season,
            pbp_source=pbp_source or "api",
            instat_season_id=instat_season_id,
            max_pbp_downloads=max_pbp_downloads,
            pbp_dir=pbp_dir,
            refresh_pbp=refresh_pbp,
            bio=bio,
            use_store=False,
        )
        _persist_to_store(profile, season, instat_season_id, league=league)

    with tempfile.TemporaryDirectory(prefix="player-card-out-") as out_raw:
        out_dir = Path(out_raw)
        html_path = out_dir / "card.html"
        write_player_card_html(profile, html_path)

        if output_png:
            png_path = Path(output_png)
            png_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".png", prefix="microstat-card-", delete=False
            )
            png_path = Path(tmp.name)
            tmp.close()

        html_to_png(html_path, png_path)

        result: dict[str, Any] = {
            "png": str(png_path),
            "profile": profile,
            "sources": profile["sources"],
        }
        if save_json:
            import json

            json_path = png_path.with_suffix(".json")
            json_path.write_text(json.dumps(profile, indent=2, default=str), encoding="utf-8")
            result["json"] = str(json_path)
        return result
