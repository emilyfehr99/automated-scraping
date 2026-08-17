"""Merge NHL bio + A3Z microstats + full PBP microstats into one card profile."""

from __future__ import annotations

import json
import logging
import os
import re
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
from .instat_source import _match_player_name, discover_team_pbp_files
from .leagues import get_league, team_full_name
from .nhl_bio import MUG_SEASON, fetch_nhl_bio, fetch_player_season_teams, fetch_undrafted_prospect_bio
from .nhl_instat import instat_season_id as resolve_instat_season_id
from .pbp_display import _pbp_values, build_pbp_display_profile, compute_team_metric_percentiles
from .pbp_metrics import aggregate_player_pbp, aggregate_player_pbp_multi
from .pbp_team_cache import get_team_frames, warm_team_pbp
from .png_export import html_to_png
from .pwhl_bio import fetch_pwhl_bio, roster_from_pbp
from .qoc_qot import compute_player_qoc_qot
from .team_colors import get_team_colors

logger = logging.getLogger(__name__)

DEFAULT_A3Z_SEASON = "2025-26"
AGG_CACHE_TTL = 7 * 86_400  # 7 days — invalidated by file fingerprint


def _lookup_player_pcts(
    pct_by_name: dict[str, dict[str, float | None]],
    player_name: str,
) -> dict[str, float | None] | None:
    """Exact then soft name match (First Last ↔ Last First roster keys)."""
    if not pct_by_name or not player_name:
        return None
    hit = pct_by_name.get(player_name)
    if hit is not None:
        return hit
    for name, vals in pct_by_name.items():
        if _match_player_name(name, player_name):
            return vals
    return None


def _team_percentiles_from_pbp(
    team: str,
    pbp_files: list[Path],
    *,
    league: str,
    team_games: int | None,
    file_groups: list[tuple[str, list[Path], int | None]] | None = None,
    focus_player: str | None = None,
) -> dict[str, dict[str, float | None]]:
    """Compute roster PBP percentiles so OFF/DEF/Transition pillar scores show.

    One GS pass per game (not per teammate) so junior seasons finish quickly.
    """
    from collections import defaultdict

    from .pbp_metrics import COUNT_MAP, _resolve_team_name
    from .pwhl_bio import _is_team_match
    from .qoc_qot import compute_microstat_game_score

    if not pbp_files:
        return {}
    # Use the same PBP file set as the card aggregate. Expanding to a larger
    # team cache dilutes focus-player rates (DNP games in denominator).
    files_for_roster = list(pbp_files)
    try:
        roster = roster_from_pbp(files_for_roster, team, league=league)
    except Exception as e:
        logger.warning("Roster scan for percentiles failed: %s", e)
        return {}
    if not roster:
        return {}

    max_peers = 12 if league == "prospect" else 28
    max_files = 40 if league == "prospect" and len(files_for_roster) > 40 else len(files_for_roster)
    files_for_roster = sorted(files_for_roster, key=lambda p: p.name)[-max_files:]
    roster = sorted(roster, key=lambda e: -int(e.get("games") or 0))
    if focus_player:
        focus = next(
            (e for e in roster if _match_player_name(e["name"], focus_player)),
            None,
        )
        rest = [e for e in roster if focus is None or e["name"] != focus["name"]]
        roster = ([focus] if focus else []) + rest
    roster = roster[:max_peers]
    names = [e["name"] for e in roster]
    team_full = team_full_name(league, team)
    tg = team_games if team_games is not None else len(files_for_roster)

    totals: dict[str, dict[str, float]] = {n: defaultdict(float) for n in names}
    played: dict[str, int] = {n: 0 for n in names}

    warm_team_pbp(files_for_roster)
    for _path, df in get_team_frames(files_for_roster):
        tm = _resolve_team_name(df, team_full)
        if not tm:
            continue
        # Full-roster GS once per game (was N× redundant).
        try:
            gs_df = compute_microstat_game_score(df, tm)
        except Exception:
            gs_df = None
        gs_map: dict[str, tuple[float, float, float]] = {}
        if gs_df is not None and not gs_df.empty:
            for _, row in gs_df.iterrows():
                raw = str(row.get("player") or "")
                for n in names:
                    if n in gs_map:
                        continue
                    if _match_player_name(raw, n):
                        gs_map[n] = (
                            float(row.get("game_score") or 0),
                            float(row.get("offense_gs") or 0),
                            float(row.get("defense_gs") or 0),
                        )
                        break

        # Vectorized COUNT_MAP tallies for roster (skip per-player sequence scans).
        if "player" not in df.columns or "action" not in df.columns:
            continue
        team_mask = df["team"].astype(str).apply(lambda x, _tm=tm: _is_team_match(x, _tm))
        sub = df.loc[team_mask]
        if sub.empty:
            continue
        # Resolve each row's player → roster display name
        raw_players = sub["player"].astype(str)
        mapped = {}
        for raw in raw_players.unique():
            for n in names:
                if _match_player_name(raw, n):
                    mapped[raw] = n
                    break
        if not mapped:
            continue
        sub = sub[raw_players.isin(mapped.keys())].copy()
        sub["_roster"] = sub["player"].astype(str).map(mapped)
        played_tonight = set(sub["_roster"].unique())
        for n in played_tonight:
            played[n] += 1
            if n in gs_map:
                gs, off_gs, def_gs = gs_map[n]
                totals[n]["Microstat Game Score"] += gs
                totals[n]["Microstat Offense"] += off_gs
                totals[n]["Microstat Defense"] += def_gs

        acts = sub["action"].astype(str).str.strip()
        for act, label in COUNT_MAP.items():
            hit = sub.loc[acts == act]
            if hit.empty:
                continue
            for n, cnt in hit.groupby("_roster").size().items():
                totals[n][label] += float(cnt)

    metrics: dict[str, dict[str, float]] = {}
    for n in names:
        if played[n] == 0 or tg <= 0:
            continue
        per_game = {k: round(v / tg, 2) for k, v in totals[n].items()}
        vals = _pbp_values(per_game)
        metrics[n] = {k: v for k, v in vals.items() if not str(k).startswith("_")}
    if len(metrics) < 2:
        return {}
    logger.info("Team percentiles from PBP: %s players on %s", len(metrics), team)
    return compute_team_metric_percentiles(metrics)


def _cached_pbp_aggregate(
    player_id: int | None,
    player_name: str,
    team: str,
    files: list[Path],
    team_games: int | None,
    *,
    file_groups: list[tuple[str, list[Path], int | None]] | None = None,
    league: str | None = "nhl",
) -> dict[str, Any] | None:
    fp = pbp_files_fingerprint(files)
    key = player_cache_key(player_id, player_name)
    cache_team = (
        "+".join(sorted({tri for tri, _, _ in file_groups}))
        if file_groups and len(file_groups) > 1
        else team.upper()
    )
    league_key = (league or "nhl").lower()
    # v11: plottable-aligned count_totals.Shots/Goals on single-club aggregates
    path = cache_path("aggregates", f"{league_key}-v11-{cache_team}", fp, f"{key}.json")
    hit = load_json(path, ttl_seconds=AGG_CACHE_TTL)
    # Never rebuild shot_count from rounded rates — that reintroduces integer drift.
    if (
        isinstance(hit, dict)
        and hit.get("per_game")
        and int(hit.get("schema_version") or 0) >= 11
        and hit.get("shot_count") is not None
        and isinstance(hit.get("shots"), list)
    ):
        logger.debug("PBP aggregate cache hit for %s", player_name)
        return hit
    if file_groups and len(file_groups) > 1:
        result = aggregate_player_pbp_multi(player_name, file_groups, league=league)
    else:
        result = aggregate_player_pbp(
            player_name, team, files=files, team_games=team_games, league=league
        )
    if result:
        result["schema_version"] = 11
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


def _season_pbp_clubs(bio: dict[str, Any] | None, team: str | None = None) -> list[str]:
    """Current-season clubs for dual-roster PBP (not full career history)."""
    bio = bio or {}
    out: list[str] = []
    seen: set[str] = set()

    def _add(name: str | None) -> None:
        n = str(name or "").strip()
        if not n:
            return
        key = n.upper()
        if key in seen:
            return
        seen.add(key)
        out.append(n)

    _add(team)
    season_rows = [r for r in (bio.get("season_clubs") or []) if isinstance(r, dict)]
    for row in season_rows:
        _add(row.get("team"))
    # Only fall back to career pbp_clubs when we have no this-season roster.
    if not season_rows:
        for club in bio.get("pbp_clubs") or bio.get("career_clubs") or []:
            _add(club)
    return out


def _club_key_match(a: str, b: str) -> bool:
    x, y = a.lower().strip(), b.lower().strip()
    return x == y or x in y or y in x


def _player_pbp_teams(player_id: int | None, team: str, *, league: str, bio: dict[str, Any] | None = None) -> list[str]:
    cfg = get_league(league)
    tri = team
    # Undrafted / multi-club prospects: current-season clubs first.
    if league == "prospect" and bio:
        clubs = _season_pbp_clubs(bio, tri)
        if clubs:
            return clubs
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
    bio: dict[str, Any] | None = None,
    player_name: str | None = None,
) -> tuple[list[Path], dict[str, Any], list[str], list[tuple[str, list[Path], int | None]]]:
    source = (pbp_source or os.getenv("PLAYER_CARDS_PBP_SOURCE", "api")).lower()
    teams = _player_pbp_teams(player_id, team, league=league, bio=bio)
    harvest_baseline: dict[str, Any] | None = None

    # Prospect fast path: harvest every on-disk game the player appears in
    # (covers dual-roster + opponent-folder copies) in seconds.
    if league == "prospect" and player_name and source in {"api", "local", "harvest"}:
        try:
            from .pbp_harvest import harvest_player_pbp

            prefer = _season_pbp_clubs(bio, team) if bio else teams
            harvested = harvest_player_pbp(
                player_name,
                prefer_clubs=prefer,
                league=league,
                materialize=True,
            )
            file_groups = list(harvested.get("file_groups") or [])
            all_files = list(harvested.get("all_files") or [])
            games_by_team = dict(harvested.get("games_by_team") or {})

            # Fill any current-season club harvest missed via team-folder discover.
            present = list(games_by_team.keys())
            for club in prefer:
                if any(_club_key_match(club, p) for p in present):
                    continue
                discovered = discover_team_pbp_files(club, league=league)
                if not discovered:
                    continue
                from .pbp_harvest import _match_id_from_path
                import csv as _csv

                club_files: dict[str, Path] = {}
                for path in discovered:
                    mid = _match_id_from_path(path) or path.name
                    try:
                        with path.open(encoding="utf-8", errors="ignore") as fh:
                            for row in _csv.DictReader(fh):
                                if not _match_player_name(str(row.get("player") or ""), player_name):
                                    continue
                                row_team = str(row.get("team") or "").strip()
                                if row_team and not _club_key_match(club, row_team):
                                    continue
                                club_files[mid] = path
                                break
                    except Exception:
                        continue
                if club_files:
                    paths = sorted(club_files.values(), key=lambda p: p.name)
                    file_groups.append((club, paths, len(paths)))
                    all_files.extend(paths)
                    games_by_team[club] = len(paths)
                    present.append(club)
                    logger.info(
                        "Filled season club PBP via discover: %s → %s games for %s",
                        club,
                        len(paths),
                        player_name,
                    )

            missing_clubs = [
                c for c in prefer if not any(_club_key_match(c, p) for p in games_by_team)
            ]

            if file_groups:
                meta = {
                    "source": "local_harvest",
                    "output_dir": str(pbp_dir),
                    "files": [str(f) for f in all_files],
                    "cached": len(all_files),
                    "match_ids": [],
                    "complete": not missing_clubs,
                    "ephemeral": False,
                    "pbp_teams": list(games_by_team.keys()),
                    "games_by_team": games_by_team,
                    "expected_pbp_clubs": prefer,
                    "missing_pbp_clubs": missing_clubs,
                }
                ep_tot = (bio or {}).get("ep_season_totals") or {}
                ep_gp = int(ep_tot.get("games_played") or 0)
                harvested_gp = sum(games_by_team.values())
                thin = bool(missing_clubs) or (
                    ep_gp > 0 and harvested_gp < max(8, int(ep_gp * 0.35))
                )
                # local = disk only. harvest/api with gaps → fall through to InStat
                # for missing season clubs (e.g. Pat Canadians U18).
                if source == "local" or not thin:
                    return (
                        all_files,
                        meta,
                        list(games_by_team.keys()) or teams,
                        file_groups,
                    )
                logger.info(
                    "Harvest incomplete for %s (%s GP on disk; missing %s) — trying InStat download",
                    player_name,
                    harvested_gp,
                    missing_clubs or "thin sample",
                )
                harvest_baseline = {
                    "file_groups": file_groups,
                    "all_files": all_files,
                    "games_by_team": games_by_team,
                    "meta": meta,
                    "prefer": prefer,
                    "missing_clubs": missing_clubs,
                }
                teams = list(dict.fromkeys([*(missing_clubs or []), *teams]))
        except Exception as exc:
            logger.warning("PBP harvest failed for %s: %s", player_name, exc)

    if source == "local":
        file_groups = []
        all_files = []
        for tri in teams:
            files = discover_team_pbp_files(tri, league=league)
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
            "pbp_teams": [t for t, _, _ in file_groups] or teams,
        }
        return all_files, meta, teams, file_groups

    # harvest with gaps (or api): download missing clubs via InStat, then merge.
    file_groups = []
    all_files = []
    primary_meta: dict[str, Any] = {}
    games_by_team: dict[str, int] = {}
    # Prefer downloading only clubs harvest lacked.
    download_teams = (
        list(harvest_baseline.get("missing_clubs") or [])
        if harvest_baseline
        else teams
    ) or teams
    download_errors: list[str] = []
    for tri in download_teams:
        dir_path = (
            pbp_dir
            if str(tri).upper() == str(team).upper()
            else team_pbp_dir(tri, league=league, a3z_season=a3z_season, season_id=instat_season_id)
        )
        try:
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
        except Exception as exc:
            logger.warning("InStat PBP download failed for %s: %s", tri, exc)
            download_errors.append(f"{tri}: {exc}")
            continue
        if not files:
            continue
        match_ids = meta.get("match_ids") or []
        tg = len(match_ids) if meta.get("complete") and match_ids else len(files)
        file_groups.append((tri, files, tg))
        all_files.extend(files)
        games_by_team[tri] = tg
        if str(tri).upper() == str(team).upper():
            primary_meta = meta

    if harvest_baseline:
        # Merge downloaded clubs onto harvest baseline (player-level WHL + U18…).
        base_groups = list(harvest_baseline["file_groups"])
        base_files = list(harvest_baseline["all_files"])
        base_games = dict(harvest_baseline["games_by_team"])
        for tri, files, tg in file_groups:
            if any(_club_key_match(tri, existing) for existing, _, _ in base_groups):
                continue
            base_groups.append((tri, files, tg))
            base_files.extend(files)
            base_games[tri] = int(tg or len(files))
        prefer = list(harvest_baseline.get("prefer") or [])
        missing = [
            c for c in prefer if not any(_club_key_match(c, p) for p in base_games)
        ]
        merged = dict(harvest_baseline.get("meta") or {})
        merged.update(
            {
                "source": "harvest+api" if file_groups else "local_harvest",
                "files": [str(f) for f in base_files],
                "cached": len(base_files),
                "pbp_teams": list(base_games.keys()),
                "games_by_team": base_games,
                "expected_pbp_clubs": prefer,
                "missing_pbp_clubs": missing,
                "complete": not missing,
                "api_download_errors": download_errors or None,
            }
        )
        return base_files, merged, list(base_games.keys()) or teams, base_groups

    if not all_files:
        detail = "; ".join(download_errors[:3]) if download_errors else "no files"
        raise RuntimeError(f"InStat API returned no PBP files for {team} ({detail})")

    merged = dict(primary_meta)
    merged["files"] = [str(f) for f in all_files]
    merged["cached"] = len(all_files)
    merged["pbp_teams"] = list(games_by_team.keys()) or teams
    merged["games_by_team"] = games_by_team
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


def _display_usable(profile: dict[str, Any] | None) -> bool:
    """Return True if profile has enough data for display."""
    if not profile or not isinstance(profile, dict):
        return False
    bio = profile.get("bio") or {}
    return bool(bio.get("name"))


def _store_profile_stale(profile: dict[str, Any] | None) -> bool:
    """Return True if stored profile needs rebuild."""
    if not profile or not isinstance(profile, dict):
        return True
    return False


def _enrich_stored_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Backfill PBP percentile display for NHL profiles stored without A3Z tiles."""
    a3z = profile.get("a3z")
    sources = dict(profile.get("sources") or {})
    if sources.get("a3z"):
        return profile

    pbp = profile.get("pbp")
    if not pbp:
        return profile

    # Recompute when sections missing OR pillar percentiles never wired
    need = True
    if isinstance(a3z, dict) and a3z.get("sections"):
        offense = a3z["sections"].get("Offense") or []
        if isinstance(offense, list) and any(
            isinstance(m, dict) and m.get("percentile") is not None for m in offense
        ):
            need = False
    if not need:
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
        percentiles=_lookup_player_pcts(pct_by_name, name),
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
    sid = instat_sid if instat_sid is not None else resolve_instat_season_id(season, league)
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

    # Use the explicitly passed team (which may be the instat_team/amateur_club) for PBP lookups,
    # but keep bio["team"] intact for branding purposes.
    tri = team or bio["team"]

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
            bio=bio,
            player_name=bio.get("name") or player_name,
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
        league=league,
    )
    if pbp:
        pbp["source"] = pbp_meta.get("source", "instat_api")

    # Per-club box scores for dual-roster season lines (never use combined PBP).
    pbp_by_club: dict[str, dict[str, int]] = {}
    if file_groups and len(file_groups) > 1:
        for club, files, tg in file_groups:
            club_agg = aggregate_player_pbp(
                bio["name"], club, files=files, team_games=tg, league=league
            )
            if not club_agg:
                continue
            pbp_by_club[club] = {
                "gp": int(club_agg.get("games_played") or 0),
                "g": int(club_agg.get("goals") or 0),
                "a": int(club_agg.get("assists") or 0),
                "tp": int(club_agg.get("points") or 0),
            }
    if pbp_by_club:
        pbp_meta = dict(pbp_meta)
        pbp_meta["pbp_by_club"] = pbp_by_club

    team_full = team_full_name(league, tri)
    deployment = _cached_qoc_qot(bio.get("player_id"), bio["name"], team_full, pbp_files) if pbp_files else None

    a3z_from_api = False
    # Caller may pass per-player metric→pct (build_store) OR leave None for live compute.
    player_pcts: dict[str, float | None] | None = pbp_percentiles
    if player_pcts is None and pbp_files:
        pct_by_name = _team_percentiles_from_pbp(
            tri,
            pbp_files,
            league=league,
            team_games=team_game_count,
            file_groups=file_groups,
            focus_player=bio["name"],
        )
        player_pcts = _lookup_player_pcts(pct_by_name, bio["name"])
        if player_pcts is None and pct_by_name:
            logger.warning(
                "No percentile row for %r among %s roster keys",
                bio["name"],
                len(pct_by_name),
            )

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
                percentiles=player_pcts,
            )
    else:
        a3z = build_pbp_display_profile(
            pbp,
            deployment,
            season=season,
            percentiles=player_pcts,
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
            "games_by_team": pbp_meta.get("games_by_team"),
            "expected_pbp_clubs": pbp_meta.get("expected_pbp_clubs"),
            "missing_pbp_clubs": pbp_meta.get("missing_pbp_clubs"),
            "api_download_errors": pbp_meta.get("api_download_errors"),
            "expected_pbp_clubs": pbp_meta.get("expected_pbp_clubs"),
            "games_by_team": pbp_meta.get("games_by_team"),
            "pbp_teams": pbp_meta.get("pbp_teams"),
            "pbp_by_club": pbp_meta.get("pbp_by_club"),
            "pbp_ephemeral": pbp_meta.get("ephemeral", False),
            "pbp_downloaded": pbp_meta.get("downloaded"),
            "pbp_skipped_api": pbp_meta.get("skipped_api"),
        },
    }


def _merge_dual_roster_season(
    bio: dict[str, Any],
    pbp: dict[str, Any] | None,
    sources: dict[str, Any],
) -> None:
    """Fill empty EP season-club GP/G/A from per-club PBP and recompute totals.

    Dual-roster kids (Pats + Pat Canadians) often have EP U18 rows + thin WHL EP.
    Stamp missing WHL lines from that club's PBP only — never combined multi-club totals.
    """
    games_by_team = sources.get("games_by_team") or {}
    pbp_by_club = sources.get("pbp_by_club") or {}
    season_clubs = list(bio.get("season_clubs") or [])
    if not season_clubs and not games_by_team:
        return

    def _match_club(row_team: str, harvest_team: str) -> bool:
        a, b = row_team.lower(), harvest_team.lower()
        return a == b or a in b or b in a

    def _club_stats(row_team: str) -> dict[str, int] | None:
        for ht, stats in pbp_by_club.items():
            if _match_club(row_team, ht):
                return stats
        return None

    # Attach harvest GP / scoring onto season club rows when EP is empty
    for row in season_clubs:
        team = str(row.get("team") or "")
        stats = _club_stats(team)
        if not row.get("gp"):
            if stats and stats.get("gp"):
                row["gp"] = int(stats["gp"])
            else:
                for ht, n in games_by_team.items():
                    if _match_club(team, ht):
                        row["gp"] = int(n)
                        break
        if stats and row.get("g") is None and row.get("a") is None:
            row["g"] = int(stats.get("g") or 0)
            row["a"] = int(stats.get("a") or 0)
            row["tp"] = int(stats.get("tp") or (row["g"] + row["a"]))

    # If WHL harvest exists but no season row, append one
    for ht, n in games_by_team.items():
        if any(_match_club(str(r.get("team") or ""), ht) for r in season_clubs):
            continue
        stats = pbp_by_club.get(ht) or {}
        season_clubs.append(
            {
                "season": "2025-26",
                "team": ht,
                "league": "WHL",
                "gp": int(stats.get("gp") or n),
                "g": stats.get("g"),
                "a": stats.get("a"),
                "tp": stats.get("tp"),
            }
        )

    gp = g = a = tp = 0
    for row in season_clubs:
        gp += int(row.get("gp") or 0)
        g += int(row.get("g") or 0)
        a += int(row.get("a") or 0)
        tp += int(row.get("tp") or 0)
    bio["season_clubs"] = season_clubs
    if gp:
        bio["ep_season_totals"] = {
            "games_played": gp,
            "goals": g,
            "assists": a,
            "points": tp or (g + a),
        }
        bio["dual_roster"] = len(season_clubs) >= 2


def generate_player_card(
    player_name: str,
    team: str | None = None,
    *,
    league: str | None = None,
    kind: str | None = None,
    output_png: Path | str | None = None,
    a3z_season: str | None = None,
    pbp_source: str | None = None,
    instat_season_id: int | None = None,
    max_pbp_downloads: int | None = None,
    save_json: bool = False,
    refresh_pbp: bool = False,
    use_store: bool | None = None,
    amateur_club: str | None = None,
    undrafted: bool | None = None,
) -> dict[str, Any]:
    """Build card using persistent PBP cache or SQLite store; writes PNG only unless save_json=True.

    For undrafted NHL draft-eligible prospects (no NHL club yet), pass
    ``league="prospect"`` and ``amateur_club`` (e.g. "Everett Silvertips").
    Colours/logos resolve from the amateur club via EliteProspects.

    Card kinds stay separate on disk (see ``card_kinds``):
    nhl_player / nhl_goalie / nhl_prospect / nhl_team / pwhl_player / junior_player.

    Goalie and team kinds are dispatched to their own generators so this
    function never renders a skater card for a goalie.
    """
    from .card_kinds import (
        default_output_path,
        detect_card_kind,
        kind_to_league,
        stamp_card_kind,
    )

    explicit_kind = kind
    card_kind = detect_card_kind(
        player_name,
        kind=kind,
        league=league,
        team=team,
        amateur_club=amateur_club,
        undrafted=undrafted,
    )
    if card_kind in {"nhl_goalie", "nhl_team"}:
        from .generators import generate_card

        return generate_card(
            player_name,
            team=team,
            kind=card_kind,
            league=league,
            output_png=output_png,
            a3z_season=a3z_season,
            pbp_source=pbp_source,
            instat_season_id=instat_season_id,
            max_pbp_downloads=max_pbp_downloads,
            save_json=save_json,
            refresh_pbp=refresh_pbp,
            use_store=use_store,
            amateur_club=amateur_club,
            undrafted=undrafted,
        )
    league = (league or kind_to_league(card_kind) or "nhl").lower()
    cfg = get_league(league)
    season = resolve_a3z_season(a3z_season or cfg.default_season, instat_season_id)

    # Undrafted = prospect with no NHL drafting team. Explicit flag wins;
    # otherwise infer when an amateur club is supplied without a 3-letter NHL team.
    nhl_tri = bool(team and re.fullmatch(r"[A-Za-z]{3}", team.strip()))
    is_undrafted = (
        bool(undrafted)
        if undrafted is not None
        else card_kind == "junior_player"
        or (league == "prospect" and bool(amateur_club) and not nhl_tri)
    )

    # Junior / undrafted: harvest on-disk clubs then InStat-fill gaps by default.
    if pbp_source is None and card_kind == "junior_player":
        pbp_source = "harvest"

    profile: dict[str, Any] | None = None
    store_team = team if nhl_tri else (amateur_club or team)
    if (use_store if use_store is not None else _use_card_store()) and not refresh_pbp:
        profile = load_stored_profile(player_name, team=store_team, season=season, league=league)
        if profile and not _store_pbp_incomplete(profile):
            profile = _enrich_stored_profile(profile)
            logger.info("Card store hit for %s — skipping live data fetch", player_name)

    if profile is None:
        bio = None
        if is_undrafted or card_kind == "junior_player":
            bio = fetch_undrafted_prospect_bio(player_name, amateur_club=amateur_club or team)
        elif cfg.uses_nhl_api:
            try:
                bio = fetch_nhl_bio(player_name, team=team)
                # NHL search often misses pre-draft amateurs — fall back to EP.
                if league == "prospect" and (not bio.get("player_id") or bio.get("team") in (None, "", "N/A")):
                    bio = fetch_undrafted_prospect_bio(player_name, amateur_club=amateur_club or team)
                    is_undrafted = True
                    card_kind = "junior_player"
            except Exception:
                bio = fetch_undrafted_prospect_bio(player_name, amateur_club=amateur_club or team)
                is_undrafted = True
                card_kind = "junior_player"

        tri = (bio or {}).get("team") or team
        if explicit_kind is None:
            pos = str((bio or {}).get("position") or "").upper()
            reroute = detect_card_kind(
                player_name,
                league=league,
                team=tri if card_kind != "junior_player" else team,
                amateur_club=amateur_club,
                undrafted=undrafted,
                position=pos,
            )
            if reroute in {"nhl_goalie", "nhl_team"}:
                from .generators import generate_card

                return generate_card(
                    player_name,
                    team=tri,
                    kind=reroute,
                    league=league,
                    output_png=output_png,
                    a3z_season=a3z_season,
                    pbp_source=pbp_source,
                    instat_season_id=instat_season_id,
                    max_pbp_downloads=max_pbp_downloads,
                    save_json=save_json,
                    refresh_pbp=refresh_pbp,
                    use_store=use_store,
                    amateur_club=amateur_club,
                    undrafted=undrafted,
                    position=pos,
                )
        instat_team = amateur_club if amateur_club else tri

        if amateur_club and bio:
            bio["amateur_club"] = amateur_club
            # Undrafted cards brand on the amateur club; drafted prospects keep NHL tri.
            bio["team"] = amateur_club if is_undrafted or not nhl_tri else (team or amateur_club)
            bio["undrafted"] = bool(is_undrafted)

        pbp_dir = team_pbp_dir(instat_team, league=league, a3z_season=season, season_id=instat_season_id)
        profile = build_player_card_profile(
            player_name,
            team=instat_team,
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

    if profile:
        bio = profile.get("bio") or {}
        if is_undrafted or league == "prospect" or card_kind in {"junior_player", "nhl_prospect"}:
            _merge_dual_roster_season(bio, profile.get("pbp"), (profile.get("sources") or {}))
            bio["undrafted"] = True if is_undrafted else bio.get("undrafted")
            bio.setdefault("amateur_club", amateur_club or bio.get("team"))
            if not bio.get("draft_info"):
                bio["draft_info"] = "NHL Draft Eligible"
            profile["bio"] = bio

        stamp_card_kind(profile, card_kind)
        # Record PBP sample size vs season GP for readers / downstream.
        sources = profile.setdefault("sources", {})
        pbp = profile.get("pbp") or {}
        sources["pbp_sample_games"] = int(pbp.get("games_played") or 0)
        ep_tot = (profile.get("bio") or {}).get("ep_season_totals") or {}
        if ep_tot.get("games_played"):
            sources["season_gp"] = int(ep_tot["games_played"])
            sources["pbp_incomplete_vs_season"] = bool(
                sources["pbp_sample_games"]
                and int(ep_tot["games_played"]) > sources["pbp_sample_games"] + 1
            )

        amateur_card = card_kind == "junior_player" or bool(is_undrafted)
        if amateur_card:
            # 1. Resolve headshot URL if missing or placeholder
            if not bio.get("headshot_url") or "silhouette" in str(bio.get("headshot_url")) or "default-" in str(bio.get("headshot_url")):
                from .headshots import resolve_prospect_headshot
                photo = resolve_prospect_headshot(player_name, amateur_club=amateur_club or team or bio.get("amateur_club"))
                if photo:
                    bio["headshot_url"] = photo
                    bio["card_photo_url"] = photo
                    bio["card_photo_kind"] = "mug"

            # 2. Resolve amateur / junior team logo (never keep NHL CDN logos on undrafted cards)
            logo_raw = bio.get("team_logo_png_url") or bio.get("team_logo_url") or ""
            need_logo = (
                not logo_raw
                or "espncdn" in logo_raw
                or "assets.nhle.com" in logo_raw
                or is_undrafted
            )
            if need_logo:
                from .nhl_bio import search_eliteprospects_team_logo
                found_logo = search_eliteprospects_team_logo(
                    amateur_club or bio.get("amateur_club") or team or bio.get("team") or ""
                )
                if found_logo:
                    bio["team_logo_url"] = found_logo
                    bio["team_logo_png_url"] = found_logo

            target_team = amateur_club or bio.get("amateur_club") or team
            if target_team:
                try:
                    from .amateur_brands import get_amateur_colors
                    profile["colors"] = get_amateur_colors(target_team, league=league)
                except Exception:
                    from .team_colors import get_team_colors
                    profile["colors"] = get_team_colors(target_team, league=league)

    with tempfile.TemporaryDirectory(prefix="player-card-out-") as out_raw:
        out_dir = Path(out_raw)
        html_path = out_dir / "card.html"
        write_player_card_html(profile, html_path)

        # Shared consistency checks for every skater card kind (NHL/PWHL/junior).
        try:
            from .validate_card import _issues_for_profile

            for msg in _issues_for_profile(profile, name=player_name):
                logger.warning("card consistency: %s", msg)
        except Exception:
            logger.debug("card consistency check skipped", exc_info=True)

        if output_png:
            png_path = Path(output_png)
            png_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            png_path = default_output_path(
                card_kind,
                player_name,
                team=team,
                amateur_club=amateur_club or (profile or {}).get("bio", {}).get("amateur_club"),
            )

        html_to_png(html_path, png_path)

        result: dict[str, Any] = {
            "png": str(png_path),
            "profile": profile,
            "sources": profile["sources"],
            "card_kind": card_kind,
        }
        if save_json:
            import json

            json_path = png_path.with_suffix(".json")
            json_path.write_text(json.dumps(profile, indent=2, default=str), encoding="utf-8")
            result["json"] = str(json_path)
        return result
