"""Player card service — store + on-disk PBP only (no InStat downloads)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .a3z_source import resolve_a3z_season
from .card_store import DEFAULT_STORE_PATH, open_store
from .html_renderer import write_player_card_html
from .leagues import LEAGUES, get_league, player_cards_work_root
from .png_export import html_to_png
from .profile import _display_usable, _enrich_stored_profile, _store_profile_stale, load_stored_profile


class PlayerNotFoundError(LookupError):
    pass


class DataNotReadyError(RuntimeError):
    """Store or PBP cache missing — run sync_player_cards_ci.py first."""


def _store_path() -> Path:
    return Path(os.getenv("PLAYER_CARDS_STORE", str(DEFAULT_STORE_PATH)))


def _season(league: str, season: str | None) -> str:
    cfg = get_league(league)
    return resolve_a3z_season(season or cfg.default_season, None)


def store_status(*, season: str | None = None) -> dict[str, Any]:
    """Summary of indexed teams/players and on-disk PBP layout."""
    store_path = _store_path()
    work_root = player_cards_work_root()
    out: dict[str, Any] = {
        "store_path": str(store_path),
        "store_exists": store_path.is_file(),
        "work_root": str(work_root),
        "leagues": {},
    }
    if not store_path.is_file():
        return out

    with open_store(store_path) as store:
        for league_key, cfg in LEAGUES.items():
            season_tag = _season(league_key, season)
            teams = store.list_teams(season_tag)
            league_teams = [dict(r) for r in teams if str(r["league"]) == league_key]
            out["leagues"][league_key] = {
                "season": season_tag,
                "teams_indexed": len(league_teams),
                "players_indexed": store.count_players(season_tag, league=league_key),
                "teams": [
                    {
                        "team": row["team"],
                        "match_count": row["match_count"],
                        "player_count": row["player_count"],
                    }
                    for row in league_teams
                ],
            }
    return out


def pbp_coverage(*, season: str | None = None) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "validate_pbp_coverage.py"
    if not script.is_file():
        return {"ok": False, "error": "validate_pbp_coverage.py missing"}
    env = {**os.environ, "PYTHONPATH": str(root)}
    proc = subprocess.run(
        [sys.executable, str(script), "--league", "all", "--json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(root),
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        return {"ok": False, "stderr": proc.stderr}
    import json

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "raw": proc.stdout, "stderr": proc.stderr}


def search_players(
    query: str,
    *,
    league: str | None = None,
    season: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    q = query.strip()
    if not q:
        return []
    store_path = _store_path()
    if not store_path.is_file():
        return []

    leagues = [league.lower()] if league else list(LEAGUES.keys())
    hits: list[dict[str, Any]] = []
    with open_store(store_path) as store:
        for league_key in leagues:
            season_tag = _season(league_key, season)
            hits.extend(store.search_players(q, league=league_key, season=season_tag, limit=limit))
    hits.sort(key=lambda r: (-int(r.get("score") or 0), r.get("name") or ""))
    return hits[:limit]


def list_team_roster(
    team: str,
    *,
    league: str = "nhl",
    season: str | None = None,
) -> list[dict[str, Any]]:
    store_path = _store_path()
    if not store_path.is_file():
        return []
    with open_store(store_path) as store:
        return store.list_team_players(team, league=league, season=_season(league, season))


def load_profile(
    player_name: str,
    *,
    team: str | None = None,
    league: str = "nhl",
    season: str | None = None,
) -> dict[str, Any]:
    """Load + enrich a player profile from the card store (no InStat API)."""
    store_path = _store_path()
    if not store_path.is_file():
        raise DataNotReadyError(
            f"Card store not found at {store_path}. "
            "Run: python scripts/sync_player_cards_ci.py"
        )

    season_tag = _season(league, season)
    profile = load_stored_profile(
        player_name,
        team=team,
        season=season_tag,
        league=league,
        store_path=store_path,
    )
    if profile is None:
        raise PlayerNotFoundError(f"Player not in store: {player_name!r} ({league})")

    profile = _enrich_stored_profile(profile)
    if _store_profile_stale(profile) or not _display_usable(profile):
        raise DataNotReadyError(
            f"Stale/incomplete data for {player_name!r}. "
            "Sync CI artifacts: python scripts/sync_player_cards_ci.py"
        )
    return profile


def render_card_png(
    player_name: str,
    *,
    team: str | None = None,
    league: str = "nhl",
    season: str | None = None,
    output: Path | str | None = None,
) -> Path:
    profile = load_profile(player_name, team=team, league=league, season=season)
    if output:
        png_path = Path(output)
        png_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", prefix="player-card-", delete=False)
        png_path = Path(tmp.name)
        tmp.close()

    with tempfile.TemporaryDirectory(prefix="player-card-html-") as out_raw:
        html_path = Path(out_raw) / "card.html"
        write_player_card_html(profile, html_path)
        html_to_png(html_path, png_path)
    return png_path
