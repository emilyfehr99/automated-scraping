"""PWHL actionshots API — NHL-style URLs backed by OSC game-photo index."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import httpx

from .disk_cache import cache_path
from .pwhl_action_photos import resolve_pwhl_action_photo
from .pwhl_photos import PWHL_HOCKEYTECH_TEAM_IDS, _fetch_ht_roster

# Mirror NHL assets.leaguestat / nhle.com sizing convention.
DEFAULT_SIZE = "1296x729"
SUPPORTED_SIZES = frozenset({DEFAULT_SIZE, "960x540", "640x360"})


def _api_base() -> str:
    return str(os.getenv("PWHL_ACTIONSHOTS_API_BASE") or "").rstrip("/")


def pwhl_actionshot_api_path(
    ht_player_id: str | int,
    *,
    size: str = DEFAULT_SIZE,
) -> str:
    """Relative API path for a player's action shot (NHL actionshots URL shape)."""
    if size not in SUPPORTED_SIZES:
        size = DEFAULT_SIZE
    return f"/pwhl/actionshots/{size}/{ht_player_id}.jpg"


def pwhl_actionshot_api_url(
    ht_player_id: str | int,
    *,
    size: str = DEFAULT_SIZE,
) -> str:
    """Absolute actionshot URL when PWHL_ACTIONSHOTS_API_BASE is set, else relative path."""
    path = pwhl_actionshot_api_path(ht_player_id, size=size)
    base = _api_base()
    return f"{base}{path}" if base else path


def build_roster_lookup() -> dict[str, dict[str, str]]:
    """Map HockeyTech player id -> {name, team}."""
    out: dict[str, dict[str, str]] = {}
    for tri, ht_team_id in PWHL_HOCKEYTECH_TEAM_IDS.items():
        for row in _fetch_ht_roster(ht_team_id):
            pid = str(row.get("player_id") or "")
            name = str(row.get("name") or "").strip()
            if pid and name:
                out[pid] = {"name": name, "team": tri}
    return out


def _cache_file(ht_player_id: str, source_url: str) -> Path:
    digest = hashlib.sha256(source_url.encode()).hexdigest()[:16]
    return cache_path("pwhl", "actionshots", f"{ht_player_id}_{digest}.jpg")


def fetch_actionshot_bytes(ht_player_id: str, source_url: str) -> tuple[bytes, Path]:
    """Return cached or freshly downloaded action-shot bytes."""
    path = _cache_file(ht_player_id, source_url)
    if path.is_file() and path.stat().st_size > 2_000:
        return path.read_bytes(), path
    resp = httpx.get(
        source_url,
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "PlayerCards/1.0"},
    )
    resp.raise_for_status()
    data = resp.content
    if len(data) < 500:
        raise ValueError("actionshot too small")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data, path


def resolve_actionshot(
    ht_player_id: str | int,
    *,
    player_name: str | None = None,
    team_abbrev: str | None = None,
    discover: bool = False,
    size: str = DEFAULT_SIZE,
) -> dict[str, Any] | None:
    """Resolve PWHL actionshot metadata for API responses."""
    pid = str(ht_player_id)
    roster = build_roster_lookup()
    row = roster.get(pid) or {}
    name = player_name or row.get("name") or ""
    tri = str(team_abbrev or row.get("team") or "").upper()

    photo = resolve_pwhl_action_photo(
        pid,
        name or None,
        team_abbrev=tri or None,
        discover=discover,
        allow_team_fallback=False,
    )
    if not photo or not photo.get("card_photo_url"):
        return None

    source = str(photo.get("photo_source") or "osc")
    kind = "player" if source in ("osc", "osc_photo", "osc_release", "local_action") else "team_fallback"

    return {
        "league": "pwhl",
        "ht_player_id": pid,
        "name": name,
        "team": tri,
        "size": size if size in SUPPORTED_SIZES else DEFAULT_SIZE,
        "source_url": str(photo["card_photo_url"]),
        "actionshot_url": pwhl_actionshot_api_url(pid, size=size),
        "actionshot_path": pwhl_actionshot_api_path(pid, size=size),
        "photo_width": photo.get("photo_width"),
        "photo_height": photo.get("photo_height"),
        "photo_source": source,
        "kind": kind,
        "headshot_url": f"https://assets.leaguestat.com/pwhl/240x240/{pid}.jpg",
    }


def actionshots_manifest(*, discover: bool = False) -> dict[str, Any]:
    """Roster-wide actionshot availability (NHL-style asset manifest)."""
    roster = build_roster_lookup()
    players: list[dict[str, Any]] = []
    with_shot = 0
    for pid, row in sorted(roster.items(), key=lambda kv: (kv[1]["team"], kv[1]["name"])):
        hit = resolve_actionshot(
            pid,
            player_name=row["name"],
            team_abbrev=row["team"],
            discover=discover,
        )
        has = hit is not None
        if has:
            with_shot += 1
        players.append(
            {
                "ht_player_id": pid,
                "name": row["name"],
                "team": row["team"],
                "has_actionshot": has,
                "actionshot_url": hit["actionshot_url"] if hit else None,
                "kind": hit.get("kind") if hit else None,
            }
        )
    return {
        "league": "pwhl",
        "roster_size": len(roster),
        "with_actionshot": with_shot,
        "coverage_pct": round(100.0 * with_shot / max(len(roster), 1), 1),
        "default_size": DEFAULT_SIZE,
        "players": players,
    }
