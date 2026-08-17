"""League-wide goalie season aggregates, for percentile ranking on the goalie card.

Goalie cards have far less of a comparison pool than skater cards (roughly one
starter + one backup per team vs. a full league of forwards/defensemen), so
percentiles here are computed against every NHL goalie with a meaningful game
count this season rather than against a single team's roster.
"""

from __future__ import annotations

import logging
from typing import Any

from .goalie_source import _build_summary, _fetch_team_goalie_rows
from .leagues import NHL_INSTAT_TEAM_IDS

logger = logging.getLogger(__name__)


async def fetch_league_goalie_rows(season_id: int = 36) -> list[dict[str, Any]]:
    """One InStat-derived summary dict per goalie, across every NHL team."""
    try:
        from playwright.async_api import async_playwright
        from instat_api import InStatAPI
    except ImportError:
        return []

    from .instat_source import HUDL_ROOT
    if not (HUDL_ROOT / "auth.json").exists():
        return []

    out: list[dict[str, Any]] = []
    api = InStatAPI()
    async with async_playwright() as p:
        if not await api.init_session(p):
            return []
        try:
            for team_abbrev, team_id in NHL_INSTAT_TEAM_IDS.items():
                try:
                    rows = await _fetch_team_goalie_rows(team_id, season_id, api)
                except Exception as e:
                    logger.warning("League goalie fetch failed for %s: %s", team_abbrev, e)
                    continue
                for row in rows:
                    summary = _build_summary(row)
                    summary["team"] = team_abbrev
                    out.append(summary)
        finally:
            await api.close()
    return out


def _percentile_rank(value: float, population: list[float]) -> float | None:
    if value is None or not population:
        return None
    below = sum(1 for v in population if v < value)
    tied = sum(1 for v in population if v == value)
    # Standard "mean rank" percentile: ties split the credit.
    return round((below + 0.5 * tied) / len(population), 3)


def compute_goalie_percentiles(
    target: dict[str, Any],
    league_rows: list[dict[str, Any]],
    *,
    min_gp: int = 10,
) -> dict[str, float | None]:
    """Percentile rank of `target` (a goalie_source summary dict) within
    `league_rows`, restricted to goalies with at least `min_gp` games played
    (so a 3-game call-up backup doesn't skew the population)."""
    pool = [r for r in league_rows if r.get("games_played", 0) >= min_gp]

    def pop(metric_path: tuple[str, ...]) -> list[float]:
        vals = []
        for r in pool:
            v: Any = r
            for key in metric_path:
                v = (v or {}).get(key) if isinstance(v, dict) else None
            if isinstance(v, (int, float)):
                vals.append(float(v))
        return vals

    def val(metric_path: tuple[str, ...]) -> float | None:
        v: Any = target
        for key in metric_path:
            v = (v or {}).get(key) if isinstance(v, dict) else None
        return float(v) if isinstance(v, (int, float)) else None

    metrics = {
        "sv_pct_overall": ("total", "sv_pct"),
        "es_sv_pct": ("es", "sv_pct"),
        "scoring_chance_sv_pct": ("total", "scoring_chance_sv_pct"),
        "gsax": ("gsax",),
    }
    percentiles: dict[str, float | None] = {"pool_size": len(pool)}
    for label, path in metrics.items():
        v = val(path)
        percentiles[label] = _percentile_rank(v, pop(path)) if v is not None else None
    return percentiles
