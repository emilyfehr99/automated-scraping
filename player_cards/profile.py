"""Merge NHL bio + A3Z microstats + full PBP microstats into one card profile."""

from __future__ import annotations

import json
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
from .nhl_bio import MUG_SEASON, fetch_nhl_bio, fetch_player_season_teams
from .nhl_instat import instat_season_id as resolve_instat_season_id
from .pbp_display import _pbp_values, build_pbp_display_profile, compute_team_metric_percentiles
from .pbp_metrics import aggregate_player_pbp, aggregate_player_pbp_multi
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
    *,
    file_groups: list[tuple[str, list[Path], int | None]] | None = None,
) -> dict[str, Any] | None:
    fp = pbp_files_fingerprint(files)
    key = player_cache_key(player_id, player_name)
    cache_team = (
        "+".join(sorted({tri for tri, _, _ in file_groups}))
        if file_groups and len(file_groups) > 1
        else team.upper()
    )
    path = cache_path("aggregates", cache_team, fp, f"{key}.json")
    hit = load_json(path, ttl_seconds=AGG_CACHE_TTL)
    if isinstance(hit, dict) and hit.get("per_game"):
        logger.debug("PBP aggregate cache hit for %s", player_name)
        return hit
    if file_groups and len(file_groups) > 1:
        result = aggregate_player_pbp_multi(player_name, file_groups)
    else:
        result = aggregate_player_pbp(player_name, team, files=files, team_games=team_games)
    if result:
        save_json(path, result)
    return result


def _store_pbp_incomplete(profile: dict[str, Any]) -> bool:
    """True when a traded player's store row only has one team's PBP."""
    sources = profile.get("sources") or {}
    pbp_teams = sources.get("pbp_teams")
    if isinstance(pbp_teams, list) and len(pbp_teams) > 1:
        return False
    bio = profile.get("bio") or {}
    player_id = bio.get("player_id")
    if not player_id or not sources.get("nhl"):
        return False
    log_teams = fetch_player_season_teams(int(player_id), nhl_season=MUG_SEASON)
    if not log_teams:
        return False
    expected_gp = sum(log_teams.values())
    actual_gp = int((profile.get("pbp") or {}).get("games_played") or 0)
    return actual_gp < expected_gp - 1


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


def _player_pbp_teams(player_id: int | None, team: str, *, league: str) -> list[str]:
    cfg = get_league(league)
    tri = team.upper()
    if cfg.uses_nhl_api and player_id:
        log_teams = fetch_player_season_teams(player_id, nhl_season=MUG_SEASON)
        if log_teams:
            return sorted(log_teams.keys())
    return [tri]


def _files_for_team(
    team: str,
    pbp_dir: Path,
    *,
    league: str,
    a3z_season: str | None,
    instat_sid: int | None,
    max_pbp_downloads: int | None,
    refresh_pbp: bool,
    allow_download: bool,
) -> tuple[list[Path], dict[str, Any]]:
    sid = instat_sid if instat_sid is not None else resolve_instat_season_id(a3z_season, league)
    cached = try_fast_pbp_cache(
        team,
        pbp_dir,
        league=league,
        a3z_season=a3z_season,
        season_id=sid,
    )
    if cached and not refresh_pbp:
        files = [Path(p) for p in cached.get("files", [])]
        return files, cached
    if not allow_download:
        return [], {}
    meta = ensure_team_pbp_files(
        team,
        pbp_dir,
        league=league,
        a3z_season=a3z_season,
        season_id=sid,
        max_downloads=max_pbp_downloads,
        refresh=refresh_pbp,
    )
    files = [Path(p) for p in meta.get("files", [])]
    return files, meta


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
    player_id: int | None = None,
) -> tuple[list[Path], dict[str, Any], list[str], list[tuple[str, list[Path], int | None]]]:
    source = (pbp_source or os.getenv("PLAYER_CARDS_PBP_SOURCE", "api")).lower()
    teams = _player_pbp_teams(player_id, team, league=league)

    if source == "local":
        file_groups: list[tuple[str, list[Path], int | None]] = []
        all_files: list[Path] = []
        for tri in teams:
            files = discover_team_pbp_files(tri)
            if files:
                file_groups.append((tri, files, len(files)))
                all_files.extend(files)
        meta = {
            "source": "local_pbp",
            "output_dir": str(pbp_dir),
            "files": [str(f) for f in all_files],
            "cached": len(all_files),
            "match_ids": [],
            "complete": bool(all_files),
            "ephemeral": False,
            "pbp_teams": teams,
        }
        return all_files, meta, teams, file_groups

    file_groups: list[tuple[str, list[Path], int | None]] = []
    all_files: list[Path] = []
    primary_meta: dict[str, Any] = {}
    for tri in teams:
        dir_path = (
            pbp_dir
            if tri == team.upper()
            else team_pbp_dir(tri, league=league, a3z_season=a3z_season, season_id=instat_season_id)
        )
        files, meta = _files_for_team(
            tri,
            dir_path,
            league=league,
            a3z_season=a3z_season,
            instat_sid=instat_season_id,
            max_pbp_downloads=max_pbp_downloads,
            refresh_pbp=refresh_pbp,
            allow_download=True,
        )
        if not files:
            continue
        match_ids = meta.get("match_ids") or []
        tg = len(match_ids) if meta.get("complete") and match_ids else len(files)
        file_groups.append((tri, files, tg))
        all_files.extend(files)
        if tri == team.upper():
            primary_meta = meta

    if not all_files:
        raise RuntimeError(f"InStat API returned no PBP files for {team}")

    merged = dict(primary_meta)
    merged["files"] = [str(f) for f in all_files]
    merged["cached"] = len(all_files)
    merged["pbp_teams"] = teams
    return all_files, merged, teams, file_groups


def _use_card_store() -> bool:
    return os.getenv("PLAYER_CARDS_USE_STORE", "1").strip().lower() not in ("0", "false", "no")


def _team_percentiles_from_store(
    team: str,
    season: str,
    *,
    league: str = "nhl",
    store_path: Path | str | None = None,
) -> dict[str, dict[str, float | None]]:
    """Recompute team PBP metric percentiles from profiles already in the card store."""
    metrics: dict[str, dict[str, float]] = {}
    with open_store(store_path) as store:
        rows = store._conn.execute(
            "SELECT profile_json FROM player_profiles WHERE league = ? AND team = ? AND season = ?",
            (league, team.upper(), season),
        )
        for row in rows:
            profile = json.loads(str(row["profile_json"]))
            bio = profile.get("bio") or {}
            name = bio.get("name")
            per_game = (profile.get("pbp") or {}).get("per_game") or {}
            if not name or not per_game:
                continue
            vals = _pbp_values(per_game)
            metrics[str(name)] = {k: v for k, v in vals.items() if not k.startswith("_")}
    return compute_team_metric_percentiles(metrics)


def _enrich_stored_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Backfill PBP percentile display for NHL profiles stored without A3Z tiles."""
    a3z = profile.get("a3z")
    if isinstance(a3z, dict) and a3z.get("sections"):
        return profile
    sources = dict(profile.get("sources") or {})
    if sources.get("a3z"):
        return profile

    pbp = profile.get("pbp")
    if not pbp:
        return profile

    league = str(profile.get("league") or "nhl").lower()
    cfg = get_league(league)
    bio = profile.get("bio") or {}
    tri = bio.get("team")
    if not tri:
        return profile

    season = str(sources.get("a3z_season") or cfg.default_season)
    store_path = sources.get("store_path")
    pct_by_name = _team_percentiles_from_store(
        tri, season, league=league, store_path=store_path
    )
    name = str(bio.get("name") or "")
    display = build_pbp_display_profile(
        pbp,
        None,
        season=season,
        percentiles=pct_by_name.get(name),
    )
    if not display:
        return profile

    out = dict(profile)
    out["a3z"] = display
    out["sources"] = {**sources, "a3z": False, "pbp_percentiles": True}
    return out


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
        if stored and not _store_pbp_incomplete(stored):
            logger.info("Card store hit for %s", player_name)
            return _enrich_stored_profile(stored)

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
            player_id=bio.get("player_id"),
        )
        cap = cap_future.result() if cap_future else None
        pbp_files, pbp_meta, pbp_teams, file_groups = pbp_future.result()

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
        file_groups=file_groups,
    )
    if pbp:
        pbp["source"] = pbp_meta.get("source", "instat_api")

    team_full = team_full_name(league, tri)
    deployment = _cached_qoc_qot(bio.get("player_id"), bio["name"], team_full, pbp_files) if pbp_files else None

    a3z_from_api = False
    if cfg.uses_a3z:
        a3z = fetch_a3z_profile(bio["name"], tri, season=season, pbp_team_games=(pbp or {}).get("games"))
        if a3z:
            a3z = merge_deployment_context(a3z, deployment)
            a3z_from_api = True
        else:
            a3z = build_pbp_display_profile(
                pbp,
                deployment,
                season=season,
                percentiles=(pbp_percentiles or {}).get(bio["name"]),
            )
    else:
        a3z = build_pbp_display_profile(
            pbp,
            deployment,
            season=season,
            percentiles=(pbp_percentiles or {}).get(bio["name"]),
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
            "a3z": a3z_from_api,
            "pbp_percentiles": bool(a3z) and not a3z_from_api,
            "pbp": pbp is not None,
            "cap": cap is not None,
            "a3z_season": season,
            "pbp_source": games.get("pbp_source"),
            "instat_season_id": games.get("instat_season_id"),
            "pbp_team_games": games["pbp_team_games"],
            "pbp_skated_games": games["pbp_skated_games"],
            "a3z_games": games["a3z_games"],
            "pbp_teams": pbp_meta.get("pbp_teams") or [tri],
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
        if profile and not _store_pbp_incomplete(profile):
            profile = _enrich_stored_profile(profile)
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
