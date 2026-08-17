"""Resolve player name → team/league using built-in APIs only (no external search)."""

from __future__ import annotations

from typing import Any

from .a3z_source import resolve_a3z_season
from .card_store import open_store
from .leagues import get_league
from .nhl_bio import _norm, search_player
from .pwhl_photos import search_pwhl_player


def _confident_nhl_hit(player_name: str, *, team: str | None = None) -> dict[str, Any] | None:
    hit = search_player(player_name, team=team)
    if not hit:
        return None
    target = _norm(player_name)
    hit_name = _norm(str(hit.get("name") or ""))
    if target == hit_name:
        return hit
    t_parts = target.split()
    h_parts = hit_name.split()
    if t_parts and h_parts and t_parts[-1] == h_parts[-1]:
        if len(t_parts) == 1:
            return hit
        if t_parts[0] == h_parts[0] or t_parts[0][:1] == h_parts[0][:1]:
            return hit
    return None


def detect_league(player_name: str, *, team: str | None = None) -> str:
    """Infer nhl vs pwhl from optional team abbrev, card store, or API lookup."""
    name = player_name.strip()
    if not name:
        raise ValueError("Player name is required")

    tri = (team or "").upper()
    if tri:
        pwhl_teams = get_league("pwhl").teams
        nhl_teams = get_league("nhl").teams
        if tri in pwhl_teams and tri not in nhl_teams:
            return "pwhl"
        if tri in nhl_teams and tri not in pwhl_teams:
            return "nhl"

    season = resolve_a3z_season(None, None)
    try:
        with open_store() as store:
            hit = store.find_profile_league(name, team=team, season=season)
            if hit:
                return hit[0]
    except Exception:
        pass

    nhl_hit = _confident_nhl_hit(name, team=team)
    pwhl_hit = search_pwhl_player(name)
    if nhl_hit and not pwhl_hit:
        return "nhl"
    if pwhl_hit and not nhl_hit:
        return "pwhl"
    if nhl_hit and pwhl_hit:
        target = _norm(name)
        if _norm(str(pwhl_hit.get("name") or "")) == target:
            return "pwhl"
        return "nhl"
    raise LookupError(f"Player not found in NHL or PWHL: {name!r}")


def resolve_player(
    player_name: str,
    *,
    league: str | None = None,
    team: str | None = None,
) -> dict[str, Any]:
    """Resolve display name, team abbrev, and player id from league data sources."""
    if league is None:
        league = detect_league(player_name, team=team)
    league = league.lower()
    cfg = get_league(league)
    name = player_name.strip()
    if not name:
        raise ValueError("Player name is required")

    if cfg.uses_nhl_api:
        from .nhl_bio import fetch_nhl_bio

        if team:
            bio = fetch_nhl_bio(name, team=team)
        else:
            hit = _confident_nhl_hit(name) or search_player(name) or search_player(name, active=False)
            if not hit:
                bio = {"name": name, "team": team or "N/A", "player_id": 0, "position": "N/A", "height": "N/A", "weight": "N/A", "shoots": "N/A", "birthDate": "N/A"}
            else:
                bio = fetch_nhl_bio(name, team=hit.get("teamAbbrev") or hit.get("lastTeamAbbrev"))
        return {
            "league": league,
            "name": bio["name"],
            "team": bio["team"],
            "player_id": bio.get("player_id"),
            "position": bio.get("position"),
            "bio": bio,
        }

    tri = (team or "").upper()
    if not tri:
        hit = search_pwhl_player(name)
        if not hit:
            teams = ", ".join(sorted(cfg.teams.keys()))
            raise LookupError(
                f"PWHL player not found: {name!r}. "
                f"Not on any {cfg.label} roster ({teams})."
            )
        tri = str(hit["team"]).upper()
        return {
            "league": league,
            "name": hit["name"],
            "team": tri,
            "player_id": hit.get("player_id"),
            "position": hit.get("position"),
            "bio": None,
        }

    return {
        "league": league,
        "name": name,
        "team": tri,
        "player_id": None,
        "position": None,
        "bio": None,
    }
