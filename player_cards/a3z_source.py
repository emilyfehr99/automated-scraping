"""Load All Three Zones microstats from the local a3z-api database."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_A3Z_SEASON = "2025-26"

CONTEXT_ALIASES: dict[str, list[str]] = {
    "qoc": ["qoc", "quality_of_competition", "competition", "qoc_pct"],
    "qot": ["qot", "quality_of_teammates", "teammates", "qot_pct"],
}


def _a3z_root() -> Path | None:
    """Locate a3z-api (sibling repo locally, or A3Z_API_ROOT in CI)."""
    env = os.getenv("A3Z_API_ROOT", "").strip()
    candidates = [
        Path(env) if env else None,
        Path(__file__).resolve().parents[2] / "a3z-api",
        Path(__file__).resolve().parents[1] / "all-three-zones-api",
    ]
    for root in candidates:
        if root and (root / "src" / "db.py").is_file():
            return root
    return None


def _a3z_available() -> bool:
    return _a3z_root() is not None


def _load_a3z_modules():
    root = _a3z_root()
    if root is None:
        return None, None, None
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    from src.db import connect, init_db
    from src.player_reports import build_player_profile

    return connect, init_db, build_player_profile


def resolve_a3z_season(a3z_season: str | None, instat_season_id: int | None = None) -> str:
    """Pick the A3Z season tag aligned with InStat season when possible."""
    if a3z_season:
        return a3z_season.strip()
    if instat_season_id == 36:
        return "2025-26"
    if instat_season_id == 34:
        return "2024-25"
    return DEFAULT_A3Z_SEASON


def _slug(name: str, team: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return f"{base}-{team.lower()}"


def _context_metric(stats: dict[str, Any], key: str, label: str, aliases: list[str]) -> dict[str, Any] | None:
    for alias in aliases:
        if alias.endswith("_pct"):
            continue
        if alias not in stats or stats[alias] is None:
            continue
        val = stats[alias]
        if isinstance(val, float) and val != val:
            continue
        pct = stats.get(f"{alias}_pct")
        if pct is None and alias.endswith("_pct") is False:
            pct = stats.get(f"{key}_pct")
        return {"label": label, "key": key, "value": val, "percentile": pct}
    return None


def merge_deployment_context(a3z: dict[str, Any] | None, deployment: dict[str, Any] | None) -> dict[str, Any] | None:
    """Overlay PBP-derived QOC/QOT onto A3Z Context section (Clarkson deployment logic)."""
    if not a3z:
        return a3z
    if not deployment:
        return a3z
    sections = dict(a3z.get("sections") or {})
    context = []
    for key, label in (("qoc", "QOC"), ("qot", "QOT")):
        m = deployment.get(key)
        if m and m.get("value") is not None:
            context.append({**m, "label": label, "key": key})
        else:
            existing = next((x for x in sections.get("Context", []) if x.get("key") == key), None)
            context.append(existing or {"label": label, "key": key, "value": None, "percentile": None})
    sections["Context"] = context
    return {**a3z, "sections": sections, "deployment": deployment}


def _inject_context_metrics(profile: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    sections = dict(profile.get("sections") or {})
    context = []
    for key, label in (("qoc", "QOC"), ("qot", "QOT")):
        m = _context_metric(stats, key, label, CONTEXT_ALIASES[key])
        if m:
            context.append(m)
        else:
            context.append({"label": label, "key": key, "value": None, "percentile": None})
    sections["Context"] = context
    profile = {**profile, "sections": sections}
    return profile


def _pick_metrics(profile: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    priority = [
        ("Game Score", "microstat_game_score"),
        ("Game Score", "5v5_game_score"),
        ("Shooting", "shots_per_60"),
        ("Shooting", "chances_per_60"),
        ("Playmaking", "chance_assists_per_60"),
        ("Transition", "zone_entries_per_60"),
        ("Defense", "dz_retrievals_per_60"),
        ("Defense", "zone_exits_per_60"),
    ]
    out: list[dict[str, Any]] = []
    sections = profile.get("sections", {})
    for section, key in priority:
        for m in sections.get(section, []):
            if m.get("key") == key:
                out.append(m)
                break
        if len(out) >= limit:
            break
    return out


def fetch_a3z_profile(
    player_name: str,
    team: str,
    season: str | None = None,
    *,
    pbp_team_games: int | None = None,
) -> dict[str, Any] | None:
    connect, init_db, build_player_profile = _load_a3z_modules()
    if connect is None:
        return None

    conn = connect()
    init_db(conn)
    slug = _slug(player_name, team)
    if season:
        row = conn.execute(
            "SELECT slug, season, stats_json FROM players WHERE slug = ? AND season = ?",
            (slug, season),
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT slug, season, stats_json FROM players WHERE name LIKE ? AND team = ? AND season = ? LIMIT 1",
                (f"%{player_name}%", team.upper(), season),
            ).fetchone()
    else:
        row = conn.execute(
            "SELECT slug, season, stats_json FROM players WHERE slug = ? OR (name LIKE ? AND team = ?) "
            "ORDER BY last_synced DESC LIMIT 1",
            (slug, f"%{player_name}%", team.upper()),
        ).fetchone()
    if not row:
        conn.close()
        return None
    resolved_season = season or row["season"]
    profile = build_player_profile(conn, row["slug"], season=resolved_season)
    stats = json.loads(row["stats_json"])
    conn.close()
    profile = _inject_context_metrics(profile, stats)
    hero = next((m for m in profile.get("sections", {}).get("Game Score", []) if m["key"] == "microstat_game_score"), None)
    a3z_games = profile.get("games")
    return {
        "season": profile.get("season"),
        "games": a3z_games,
        "toi_5v5": profile.get("toi_5v5"),
        "microstat_game_score": hero,
        "metrics": _pick_metrics(profile),
        "sections": profile.get("sections"),
        "pbp_team_games": pbp_team_games,
        "aligned_with_pbp": (
            pbp_team_games is not None and a3z_games is not None and int(pbp_team_games) == int(a3z_games)
        ),
    }
