"""Build A3Z-shaped card display from InStat PBP only (PWHL / no-A3Z path)."""

from __future__ import annotations

from typing import Any

from .card_config import DEFENSE_GS_KEYS, OFFENSE_GS_KEY, PILLAR_BARS

# Map A3Z pillar keys → PBP per_game keys (event counts per team GP).
PBP_METRIC_MAP: dict[str, str] = {
    "shots_per_60": "Shots",
    "chances_per_60": "Chances",
    "passes_per_60": "Passes",
    "chance_assists_per_60": "Passes",
    "shots_on_goal_per_60": "SOG",
    "one_timer_per_60": "Shots",
    "zone_entries_per_60": "Zone Entries",
    "carries_per_60": "Carry-ins",
    "exits_w_possession_per_60": "Exits w/ Possession",
    "failed_entries_per_60": "Failed Entries",
    "forechecking": "Forecheck Recoveries",
    "recoveries_per_60": "DZ Retrievals",
    "dz_retrievals_per_60": "DZ Retrievals",
    "exits": "Zone Exits",
    "entry_defense": "Denials",
    "botched_retrievals_per_60": "Botched Retrievals",
    "failed_exit_per_60": "Failed Exits",
    "denials_per_60": "Denials",
    "microstat_game_score": "_game_score",
    "offense": "_offense",
    OFFENSE_GS_KEY: "_offense",
}


def _pct_rank(value: float, population: list[float]) -> float | None:
    vals = sorted(v for v in population if v is not None)
    if not vals or value is None:
        return None
    below = sum(1 for v in vals if v < value)
    equal = sum(1 for v in vals if v == value)
    return round((below + 0.5 * equal) / len(vals), 3)


def compute_team_metric_percentiles(
    player_metrics: dict[str, dict[str, float]],
) -> dict[str, dict[str, float | None]]:
    """player_name → metric_key → percentile (0-1)."""
    keys: set[str] = set()
    for metrics in player_metrics.values():
        keys.update(metrics.keys())
    out: dict[str, dict[str, float | None]] = {p: {} for p in player_metrics}
    for key in keys:
        pop = [m.get(key) for m in player_metrics.values() if m.get(key) is not None]
        for player, metrics in player_metrics.items():
            val = metrics.get(key)
            out[player][key] = _pct_rank(float(val), [float(x) for x in pop if x is not None]) if val is not None else None
    return out


def _pbp_values(per_game: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for a3z_key, pbp_key in PBP_METRIC_MAP.items():
        if pbp_key.startswith("_"):
            continue
        raw = per_game.get(pbp_key)
        if raw is not None:
            out[a3z_key] = float(raw)
    shots = float(per_game.get("Shots") or 0)
    chances = float(per_game.get("Chances") or 0)
    out["_offense"] = shots + chances * 0.5
    exits = float(per_game.get("Zone Exits") or 0)
    denials = float(per_game.get("Denials") or 0)
    out["_defense"] = exits + denials
    goals = float(per_game.get("Goals") or 0)
    out["_game_score"] = goals * 2 + chances + shots * 0.1
    return out


def build_pbp_display_profile(
    pbp: dict[str, Any] | None,
    deployment: dict[str, Any] | None,
    *,
    season: str,
    percentiles: dict[str, float | None] | None = None,
    gs_percentile: float | None = None,
) -> dict[str, Any] | None:
    if not pbp:
        return None
    per_game = pbp.get("per_game") or {}
    values = _pbp_values(per_game)
    pct = percentiles or {}

    def _metric(key: str, label: str | None = None) -> dict[str, Any]:
        val = values.get(key)
        return {
            "label": label or key,
            "key": key,
            "value": round(val, 2) if val is not None else None,
            "percentile": pct.get(key) if pct.get(key) is not None else gs_percentile if key == "microstat_game_score" else None,
        }

    sections: dict[str, list[dict[str, Any]]] = {}
    for pillar in PILLAR_BARS:
        rows = []
        for key, lbl in pillar["keys"]:
            rows.append(_metric(key, lbl))
        sections[pillar["title"]] = rows

    context = []
    if deployment:
        for k in ("qoc", "qot"):
            m = deployment.get(k) or {}
            context.append(
                {
                    "label": m.get("label", k.upper()),
                    "key": k,
                    "value": m.get("value"),
                    "percentile": m.get("percentile"),
                }
            )
    sections["Context"] = context
    sections["Game Score"] = [_metric("microstat_game_score", "Game Score")]
    sections["Offense"] = [_metric(OFFENSE_GS_KEY, "Offence")]
    sections["Defense"] = [_metric("entry_defense", "Entry Defense"), _metric("exits", "Exits")]

    games = pbp.get("games_played") or pbp.get("games")
    return {
        "season": season,
        "games": games,
        "toi_5v5": None,
        "microstat_game_score": sections["Game Score"][0],
        "metrics": sections["Game Score"][:1],
        "sections": sections,
        "source": "pbp_only",
    }
