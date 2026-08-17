#!/usr/bin/env python3
"""Player Cards REST API — profiles and PNGs from prebuilt store (no InStat downloads)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from . import service
from .pwhl_action_sync import action_photo_coverage, ensure_pwhl_action_index, sync_pwhl_action_photos
from .pwhl_action_photos import resolve_pwhl_action_photo
from .pwhl_actionshots import (
    DEFAULT_SIZE,
    actionshots_manifest,
    fetch_actionshot_bytes,
    pwhl_actionshot_api_path,
    resolve_actionshot,
)
from .pwhl_photos import lookup_pwhl_player

app = FastAPI(
    title="Player Cards API",
    version="1.0.0",
    description=(
        "Serve NHL/PWHL microstat player cards from the prebuilt SQLite store "
        "and on-disk InStat PBP cache. No live InStat downloads.\n\n"
        "**Setup once:** `python scripts/sync_player_cards_ci.py`"
    ),
)


class CardRequest(BaseModel):
    player: str = Field(..., description="Player display name")
    team: str | None = Field(None, description="Team abbrev (optional)")
    league: str = Field("nhl", description="nhl or pwhl")
    season: str | None = Field(None, description="e.g. 2025-26")


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, service.PlayerNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, service.DataNotReadyError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "player-cards",
        "docs": "/docs",
        "health": "/health",
        "coverage": "/coverage",
        "pwhl_actionshots": {
            "manifest": "/pwhl/actionshots",
            "image": f"/pwhl/actionshots/{DEFAULT_SIZE}/{{ht_player_id}}.jpg",
            "metadata": "/pwhl/actionshots/{ht_player_id}",
            "sync": "POST /pwhl/action-photos/sync",
        },
    }


@app.get("/health")
def health() -> dict[str, Any]:
    status = service.store_status()
    ready = bool(status.get("store_exists"))
    players = sum(
        lg.get("players_indexed", 0) for lg in (status.get("leagues") or {}).values()
    )
    pwhl_photos = action_photo_coverage()
    return {
        "status": "ok" if ready and players > 0 else "degraded",
        "store_ready": ready,
        "players_indexed": players,
        "store_path": status.get("store_path"),
        "work_root": status.get("work_root"),
        "pwhl_action_photos": {
            "indexed": pwhl_photos.get("indexed_players"),
            "roster_size": pwhl_photos.get("roster_size"),
            "coverage_pct": pwhl_photos.get("coverage_pct"),
        },
    }


@app.get("/status")
def status(season: str | None = None) -> dict[str, Any]:
    return service.store_status(season=season)


@app.get("/coverage")
def coverage(season: str | None = None) -> dict[str, Any]:
    return service.pbp_coverage(season=season)


@app.get("/players/search")
def players_search(
    q: str = Query(..., min_length=2),
    league: str | None = None,
    season: str | None = None,
    limit: int = Query(25, ge=1, le=100),
) -> dict[str, Any]:
    return {
        "query": q,
        "results": service.search_players(q, league=league, season=season, limit=limit),
    }


@app.get("/teams/{team}/roster")
def team_roster(
    team: str,
    league: str = "nhl",
    season: str | None = None,
) -> dict[str, Any]:
    roster = service.list_team_roster(team, league=league, season=season)
    if not roster:
        raise HTTPException(status_code=404, detail=f"No roster in store for {league}/{team}")
    return {"team": team.upper(), "league": league, "players": roster}


@app.get("/players/{player_name}/profile")
def player_profile(
    player_name: str,
    team: str | None = None,
    league: str = "nhl",
    season: str | None = None,
) -> dict[str, Any]:
    try:
        try:
            return service.load_profile(player_name, team=team, league=league, season=season)
        except Exception:
            import logging
            logging.info("Dynamic profile generation fallback for %s...", player_name)
            from .profile import generate_player_card
            res = generate_player_card(
                player_name,
                team=team,
                league=league,
                use_store=False,
                pbp_source="cache"
            )
            return res.get("profile") or {}
    except Exception as exc:
        raise _err(exc) from exc


@app.get("/players/{player_name}/card.png")
def player_card_png(
    player_name: str,
    team: str | None = None,
    league: str = "nhl",
    season: str | None = None,
    force: bool = False,
) -> FileResponse:
    try:
        t0 = time.perf_counter()
        
        # Check local PNG cache directory
        cache_dir = Path.home() / ".cache" / "player-cards" / "rendered_cards"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_png = cache_dir / f"{player_name.replace(' ', '_').lower()}.png"
        
        if cached_png.exists() and not force:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            return FileResponse(
                cached_png,
                media_type="image/png",
                filename=f"{player_name.replace(' ', '-').lower()}.png",
                headers={"X-Elapsed-Ms": str(elapsed_ms), "X-Cache": "HIT"},
            )

        if league.lower() == "pwhl":
            ensure_pwhl_action_index(min_coverage_pct=0.0)

        try:
            png_path = service.render_card_png(
                player_name, team=team, league=league, season=season
            )
        except Exception as exc:
            import logging
            logging.info("Dynamic card generation fallback for %s...", player_name)
            from .profile import generate_player_card
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".png", prefix="player-card-live-", delete=False)
            png_path = Path(tmp.name)
            tmp.close()
            
            # Generate the card dynamically
            generate_player_card(
                player_name,
                team=team,
                league=league,
                output_png=png_path,
                use_store=False,
                pbp_source="cache"
            )
            
        # Copy to cache directory for future hits
        import shutil
        try:
            shutil.copy2(png_path, cached_png)
        except Exception as cache_err:
            import logging
            logging.warning("Failed to save card to PNG cache: %s", cache_err)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return FileResponse(
            png_path,
            media_type="image/png",
            filename=f"{player_name.replace(' ', '-').lower()}.png",
            headers={"X-Elapsed-Ms": str(elapsed_ms), "X-Cache": "MISS"},
        )
    except Exception as exc:
        raise _err(exc) from exc


@app.get("/pwhl/action-photos/coverage")
def pwhl_action_photo_coverage() -> dict[str, Any]:
    return action_photo_coverage()


@app.get("/pwhl/actionshots")
def pwhl_actionshots_manifest(
    team: str | None = None,
    discover: bool = Query(False, description="Run on-demand OSC lookup for missing players"),
) -> dict[str, Any]:
    """NHL actionshots-style manifest for the full PWHL roster."""
    if discover:
        ensure_pwhl_action_index(min_coverage_pct=0.0)
    manifest = actionshots_manifest(discover=discover)
    if team:
        tri = team.upper()
        manifest["players"] = [p for p in manifest["players"] if p.get("team") == tri]
        manifest["roster_size"] = len(manifest["players"])
        manifest["with_actionshot"] = sum(1 for p in manifest["players"] if p.get("has_actionshot"))
        manifest["coverage_pct"] = round(
            100.0 * manifest["with_actionshot"] / max(manifest["roster_size"], 1),
            1,
        )
    return manifest


@app.get("/pwhl/actionshots/{ht_player_id}")
def pwhl_actionshot_metadata(
    ht_player_id: str,
    team: str | None = None,
    discover: bool = Query(True),
) -> dict[str, Any]:
    """JSON metadata for one player's PWHL action shot."""
    hit = resolve_actionshot(
        ht_player_id,
        team_abbrev=team,
        discover=discover,
    )
    if not hit:
        raise HTTPException(status_code=404, detail=f"No PWHL actionshot for player {ht_player_id!r}")
    return hit


@app.get("/pwhl/actionshots/{size}/{ht_player_id}.jpg")
def pwhl_actionshot_image(
    size: str,
    ht_player_id: str,
    team: str | None = None,
    redirect: bool = Query(False, description="302 redirect to source URL instead of proxying"),
) -> Response:
    """Serve in-game PWHL action shot (NHL /mugs/actionshots/{size}/{id}.jpg equivalent)."""
    hit = resolve_actionshot(
        ht_player_id,
        team_abbrev=team,
        discover=True,
        size=size,
    )
    if not hit:
        raise HTTPException(status_code=404, detail=f"No PWHL actionshot for player {ht_player_id!r}")

    source_url = str(hit["source_url"])
    if redirect:
        return RedirectResponse(source_url, status_code=302)

    try:
        data, path = fetch_actionshot_bytes(str(hit["ht_player_id"]), source_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch actionshot: {exc}") from exc

    return FileResponse(
        path,
        media_type="image/jpeg",
        filename=f"pwhl-{ht_player_id}.jpg",
        headers={
            "X-PWHL-Photo-Source": str(hit.get("photo_source") or ""),
            "X-PWHL-Photo-Kind": str(hit.get("kind") or ""),
            "Cache-Control": "public, max-age=86400",
        },
    )


@app.post("/pwhl/action-photos/sync")
def pwhl_action_photo_sync(
    full: bool = Query(False, description="Scan full OSC id ranges (slower)"),
    workers: int = Query(20, ge=1, le=40),
) -> dict[str, Any]:
    if full:
        return sync_pwhl_action_photos(full=True, workers=workers)
    return ensure_pwhl_action_index(force=True)


@app.get("/pwhl/players/{player_name}/action-photo")
def pwhl_player_action_photo(
    player_name: str,
    team: str | None = None,
) -> dict[str, Any]:
    meta = lookup_pwhl_player(player_name, team or "")
    if not meta and team:
        raise HTTPException(status_code=404, detail=f"PWHL player not found: {player_name!r}")
    if not meta:
        from .pwhl_photos import search_pwhl_player

        found = search_pwhl_player(player_name)
        if not found:
            raise HTTPException(status_code=404, detail=f"PWHL player not found: {player_name!r}")
        meta = lookup_pwhl_player(str(found.get("name") or player_name), str(found.get("team") or ""))
    if not meta:
        raise HTTPException(status_code=404, detail=f"PWHL player not found: {player_name!r}")

    ht_id = str(meta.get("ht_player_id") or meta.get("player_id") or "")
    display = str(meta.get("name") or player_name)
    tri = str(meta.get("team") or team or "").upper()
    photo = resolve_pwhl_action_photo(ht_id, display, team_abbrev=tri, discover=True)
    if not photo:
        return {
            "player": display,
            "ht_player_id": ht_id,
            "card_photo_kind": "placeholder",
            "card_photo_url": None,
            "actionshot_url": None,
        }
    actionshot = resolve_actionshot(ht_id, player_name=display, team_abbrev=tri, discover=False)
    return {
        "player": display,
        "ht_player_id": ht_id,
        **photo,
        "actionshot_url": (actionshot or {}).get("actionshot_url"),
        "actionshot_path": pwhl_actionshot_api_path(ht_id),
    }


@app.post("/cards")
def card_from_body(body: CardRequest) -> JSONResponse:
    try:
        if body.league.lower() == "pwhl":
            ensure_pwhl_action_index(min_coverage_pct=0.0)
        t0 = time.perf_counter()
        png_path = service.render_card_png(
            body.player,
            team=body.team,
            league=body.league,
            season=body.season,
        )
        profile = service.load_profile(
            body.player, team=body.team, league=body.league, season=body.season
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return JSONResponse(
            {
                "player": profile["bio"]["name"],
                "team": profile["bio"]["team"],
                "league": profile.get("league", body.league),
                "png_url": f"/players/{body.player}/card.png",
                "profile_url": f"/players/{body.player}/profile",
                "elapsed_ms": elapsed_ms,
                "sources": profile.get("sources"),
            }
        )
    except Exception as exc:
        raise _err(exc) from exc


def main() -> None:
    import uvicorn

    host = os.getenv("PLAYER_CARDS_API_HOST", "127.0.0.1")
    port = int(os.getenv("PLAYER_CARDS_API_PORT", "8250"))
    uvicorn.run("player_cards.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
