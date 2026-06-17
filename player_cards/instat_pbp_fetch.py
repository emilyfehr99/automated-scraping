"""Fetch full-season InStat PBP via API into a persistent team cache directory."""

from __future__ import annotations

import asyncio
import glob
import json
import os
import logging
import re
import sys
from pathlib import Path
from typing import Any

from .leagues import get_league, instat_season_id, pbp_cache_dir, resolve_instat_team_id, team_full_name

logger = logging.getLogger(__name__)

HUDL_ROOT = Path(__file__).resolve().parents[1] / "hudl-scraping"
if str(HUDL_ROOT) not in sys.path:
    sys.path.insert(0, str(HUDL_ROOT))


def _instat_api_tokens_configured() -> bool:
    return bool(
        os.getenv("INSTAT_X_AUTH_TOKEN", "").strip()
        and os.getenv("INSTAT_AUTHORIZATION", "").strip()
    )


def _instat_auth_ready() -> bool:
    if _instat_api_tokens_configured():
        return True
    return (HUDL_ROOT / "auth.json").is_file()


def team_pbp_dir(
    team_abbrev: str,
    *,
    league: str = "nhl",
    season_id: int | None = None,
    a3z_season: str | None = None,
) -> Path:
    """Persistent on-disk directory for a team's season PBP CSVs."""
    return Path(pbp_cache_dir(league, team_abbrev.upper()))


def _manifest_path(output_dir: Path, season_id: int) -> Path:
    return output_dir / f".instat_manifest_{season_id}.json"


def _pbp_path_for_match(output_dir: Path, match_id: int, date: str | None = None) -> Path:
    if date:
        return output_dir / f"game_{date}_{match_id}_pbp.csv"
    return output_dir / f"game_{match_id}_pbp.csv"


def _find_cached_pbp(output_dir: Path, match_id: int) -> Path | None:
    hits = sorted(glob.glob(str(output_dir / f"*{match_id}_pbp.csv")))
    return Path(hits[0]) if hits else None


def _match_id_from_filename(name: str) -> int | None:
    match = re.search(r"_(\d+)_pbp\.csv$", name)
    return int(match.group(1)) if match else None


def _load_manifest(output_dir: Path, season_id: int) -> dict[str, Any] | None:
    path = _manifest_path(output_dir, season_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_manifest(output_dir: Path, season_id: int, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _manifest_path(output_dir, season_id).write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _bootstrap_manifest_from_disk(output_dir: Path, season_id: int, tri: str) -> dict[str, Any] | None:
    """Build manifest from existing Desktop/API CSVs so repeat runs skip Playwright."""
    if not output_dir.is_dir():
        return None
    files = sorted(output_dir.glob("*_pbp.csv"))
    if len(files) < 20:
        return None
    match_ids: list[int] = []
    for path in files:
        mid = _match_id_from_filename(path.name)
        if mid is not None:
            match_ids.append(mid)
    if not match_ids:
        return None
    match_ids = sorted(set(match_ids))
    manifest = {
        "team": tri,
        "season_id": season_id,
        "match_ids": match_ids,
        "bootstrapped": True,
    }
    _save_manifest(output_dir, season_id, manifest)
    logger.info("Bootstrapped PBP manifest for %s (%s games on disk)", tri, len(match_ids))
    return manifest


def _complete_cache_meta(
    output_dir: Path,
    tri: str,
    season_id: int,
    manifest: dict[str, Any],
) -> dict[str, Any] | None:
    match_ids = manifest.get("match_ids") or []
    if not match_ids:
        return None
    all_paths: list[Path] = []
    for mid in match_ids:
        path = _find_cached_pbp(output_dir, mid)
        if not path:
            return None
        all_paths.append(path)
    return {
        "team": tri,
        "team_id": manifest.get("team_id"),
        "season_id": season_id,
        "a3z_season": manifest.get("a3z_season"),
        "output_dir": str(output_dir),
        "match_ids": match_ids,
        "files": sorted(all_paths, key=lambda p: p.name),
        "cached": len(all_paths),
        "complete": len(all_paths) == len(match_ids),
        "downloaded": 0,
        "failed": [],
        "source": "instat_api",
        "ephemeral": False,
        "skipped_api": True,
    }


def try_fast_pbp_cache(
    team_abbrev: str,
    output_dir: Path,
    *,
    league: str = "nhl",
    a3z_season: str | None = None,
    season_id: int | None = None,
) -> dict[str, Any] | None:
    """Return metadata when every season game CSV is already on disk (no Playwright)."""
    tri = team_abbrev.upper()
    sid = season_id if season_id is not None else instat_season_id(a3z_season, league)
    manifest = _load_manifest(output_dir, sid)
    if manifest is None:
        manifest = _bootstrap_manifest_from_disk(output_dir, sid, tri)
    if manifest is None:
        return None
    return _complete_cache_meta(output_dir, tri, sid, manifest)


async def _fetch_season_match_ids(api, team_id: int, season_id: int) -> list[int]:
    import instat_api

    instat_api.TEAM_ID = team_id
    instat_api.SEASON_ID = season_id
    matches = await api.get_matches_list()
    return api._extract_match_ids(matches)


async def _download_team_pbp_with_api(
    api,
    team_abbrev: str,
    output_dir: Path,
    *,
    league: str = "nhl",
    a3z_season: str | None = None,
    season_id: int | None = None,
    max_downloads: int | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    tri = team_abbrev.upper()
    sid = season_id if season_id is not None else instat_season_id(a3z_season, league)
    out = output_dir
    out.mkdir(parents=True, exist_ok=True)

    if not refresh and max_downloads is None:
        fast = try_fast_pbp_cache(tri, out, a3z_season=a3z_season, season_id=sid, league=league)
        if fast:
            logger.info("PBP cache hit for %s (%s games) — skipping InStat session", tri, fast["cached"])
            return fast

    team_id = await resolve_instat_team_id(api, league, tri)
    if not team_id:
        raise LookupError(f"InStat team ID not found for {tri}")

    match_ids = await _fetch_season_match_ids(api, team_id, sid)
    if not match_ids:
        raise LookupError(f"No InStat matches for {tri} season_id={sid}")

    to_fetch: list[int] = []
    for mid in match_ids:
        if _find_cached_pbp(out, mid):
            continue
        to_fetch.append(mid)

    if max_downloads is not None:
        to_fetch = to_fetch[: max(0, max_downloads)]

    downloaded = 0
    failed: list[int] = []
    for i, mid in enumerate(to_fetch, start=1):
        info = await api.get_match_info(mid)
        raw_date = (info or {}).get("match_date", "")
        date = raw_date.split("T")[0] if raw_date else ""
        path = _pbp_path_for_match(out, mid, date or None)
        ok = await api.export_pbp_csv(mid, str(path))
        if ok:
            downloaded += 1
            logger.info("[%s/%s] PBP %s", i, len(to_fetch), mid)
        else:
            failed.append(mid)
            logger.warning("PBP download failed for match %s", mid)
        if i < len(to_fetch):
            await asyncio.sleep(0.75)

    all_paths: list[Path] = []
    for mid in match_ids:
        path = _find_cached_pbp(out, mid)
        if path:
            all_paths.append(path)

    _save_manifest(
        out,
        sid,
        {
            "team": tri,
            "team_id": team_id,
            "season_id": sid,
            "a3z_season": a3z_season,
            "match_ids": match_ids,
            "league": league,
        },
    )

    return {
        "team": tri,
        "team_id": team_id,
        "season_id": sid,
        "a3z_season": a3z_season,
        "output_dir": str(out),
        "match_ids": match_ids,
        "files": sorted(all_paths, key=lambda p: p.name),
        "cached": len(all_paths),
        "complete": len(all_paths) == len(match_ids),
        "downloaded": downloaded,
        "failed": failed,
        "source": "instat_api",
        "ephemeral": False,
        "skipped_api": downloaded == 0 and not failed,
        "league": league,
    }


async def _download_team_pbp_async(
    team_abbrev: str,
    output_dir: Path,
    *,
    league: str = "nhl",
    a3z_season: str | None = None,
    season_id: int | None = None,
    max_downloads: int | None = None,
    refresh: bool = False,
    api=None,
) -> dict[str, Any]:
    if api is not None:
        return await _download_team_pbp_with_api(
            api,
            team_abbrev,
            output_dir,
            league=league,
            a3z_season=a3z_season,
            season_id=season_id,
            max_downloads=max_downloads,
            refresh=refresh,
        )

    from playwright.async_api import async_playwright
    from instat_api import InStatAPI

    if not _instat_auth_ready():
        raise RuntimeError(
            "InStat auth missing: set INSTAT_X_AUTH_TOKEN + INSTAT_AUTHORIZATION, or hudl-scraping/auth.json"
        )

    api = InStatAPI()
    if _instat_api_tokens_configured():
        if not await api.init_session(None):
            raise RuntimeError("InStat API token auth failed")
        try:
            result = await _download_team_pbp_with_api(
                api,
                team_abbrev,
                output_dir,
                league=league,
                a3z_season=a3z_season,
                season_id=season_id,
                max_downloads=max_downloads,
                refresh=refresh,
            )
        finally:
            await api.close()
        return result

    async with async_playwright() as p:
        if not await api.init_session(p):
            raise RuntimeError("InStat session init failed (check auth.json)")
        result = await _download_team_pbp_with_api(
            api,
            team_abbrev,
            output_dir,
            league=league,
            a3z_season=a3z_season,
            season_id=season_id,
            max_downloads=max_downloads,
            refresh=refresh,
        )
        await api.close()
        return result


async def batch_download_team_pbp(
    jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Download PBP for multiple teams in one InStat/Playwright session."""
    from playwright.async_api import async_playwright
    from instat_api import InStatAPI

    if not jobs:
        return []

    if not _instat_auth_ready():
        raise RuntimeError(
            "InStat auth missing: set INSTAT_X_AUTH_TOKEN + INSTAT_AUTHORIZATION, or hudl-scraping/auth.json"
        )

    results: list[dict[str, Any]] = []
    api = InStatAPI()

    async def _run_jobs() -> None:
        for job in jobs:
            tri = job["team"]
            try:
                meta = await _download_team_pbp_with_api(
                    api,
                    tri,
                    job["output_dir"],
                    league=job.get("league", "nhl"),
                    a3z_season=job.get("a3z_season"),
                    season_id=job.get("season_id"),
                    max_downloads=job.get("max_downloads"),
                    refresh=job.get("refresh", False),
                )
                results.append(meta)
            except Exception as exc:
                logger.error("%s/%s PBP download failed: %s", job.get("league"), tri, exc)
                results.append({"team": tri, "league": job.get("league"), "error": str(exc)})

    if _instat_api_tokens_configured():
        if not await api.init_session(None):
            raise RuntimeError("InStat API token auth failed")
        try:
            await _run_jobs()
        finally:
            await api.close()
        return results

    async with async_playwright() as p:
        if not await api.init_session(p):
            raise RuntimeError("InStat session init failed (check auth.json)")
        await _run_jobs()
        await api.close()
    return results


def ensure_team_pbp_files(
    team_abbrev: str,
    output_dir: Path,
    *,
    league: str = "nhl",
    a3z_season: str | None = None,
    season_id: int | None = None,
    max_downloads: int | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Ensure season PBP CSVs exist in output_dir (persistent cache)."""
    return asyncio.run(
        _download_team_pbp_async(
            team_abbrev,
            output_dir,
            league=league,
            a3z_season=a3z_season,
            season_id=season_id,
            max_downloads=max_downloads,
            refresh=refresh,
        )
    )
