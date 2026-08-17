"""Team-card-specific chart components that are NOT percentile bars: a season
game-log waffle grid, circular gauge meters for single ratios, a 2D team-
identity scatter (offense vs defense), and a goals-vs-assists leaders scatter.
Each picks its form the way the dataviz skill recommends by data job, not by
default-to-a-bar: a single ratio against a limit is a meter, a season's shape
is a waffle grid (not 82 rows of bars), and a two-variable relationship is a
scatter, not a leaderboard."""

from __future__ import annotations

import html
import math
from typing import Any

_GOOD = "#0ca30c"
_CRITICAL = "#d03b3b"
_WARNING = "#c98500"


def render_season_form_waffle(game_log: list[dict[str, Any]], *, cols: int = 14) -> str:
    """One small square per game played this season, in order, colored by
    result - shows the actual shape of a season (hot streaks, slumps) that a
    single 'W-L-OTL' text stat can't. A well-established sports-viz form
    (GitHub-contributions-style), deliberately not a bar chart."""
    if not game_log:
        return '<div class="shot-map-empty">No game log available</div>'
    cell = 17
    gap = 4
    rows = math.ceil(len(game_log) / cols)
    w = cols * (cell + gap) - gap
    h = rows * (cell + gap) - gap
    color = {"W": _GOOD, "L": _CRITICAL, "OTL": _WARNING}
    squares = []
    for i, g in enumerate(game_log):
        r, c = divmod(i, cols)
        x, y = c * (cell + gap), r * (cell + gap)
        fill = color.get(g["result"], "#c7cdd6")
        title = f"{g.get('date','')} vs {g.get('opponent','')}: {g['result']} {g.get('score_for')}-{g.get('score_against')}"
        squares.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3" fill="{fill}">'
            f"<title>{html.escape(title)}</title></rect>"
        )
    counts = {k: sum(1 for g in game_log if g["result"] == k) for k in ("W", "L", "OTL")}
    legend = "".join(
        f'<span class="waffle-legend__item"><i style="background:{color[k]}"></i>{k} ({counts[k]})</span>'
        for k in ("W", "L", "OTL")
    )
    return f"""
    <div class="waffle-panel">
      <svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" class="waffle-svg">{"".join(squares)}</svg>
      <div class="waffle-legend">{legend}</div>
    </div>"""


def render_gauge(label: str, pct: float | None, *, color: str, sub: str = "") -> str:
    """Circular progress-ring meter for a single ratio (0-1) against its
    natural 0-100% limit - PP%/PK%/Faceoff% are literally percentages, the
    textbook case for a meter rather than a magnitude bar."""
    r, stroke = 42, 9
    circ = 2 * math.pi * r
    p = max(0.0, min(1.0, pct or 0.0))
    dash = circ * p
    disp = f"{p*100:.0f}%" if pct is not None else "—"
    size = (r + stroke) * 2
    return f"""
    <div class="gauge">
      <svg viewBox="0 0 {size} {size}" width="112" height="112">
        <circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="#e2e5ea" stroke-width="{stroke}"/>
        <circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}"
          stroke-linecap="round" stroke-dasharray="{dash:.1f} {circ:.1f}"
          transform="rotate(-90 {size/2} {size/2})"/>
        <text x="{size/2}" y="{size/2 - 3}" text-anchor="middle" font-size="20" font-weight="700"
          font-family="Russo One, sans-serif" fill="#1a1a1a">{disp}</text>
        <text x="{size/2}" y="{size/2 + 15}" text-anchor="middle" font-size="8" fill="#6b7280"
          font-family="Inter, sans-serif">{html.escape(sub)}</text>
      </svg>
      <div class="gauge__lbl">{html.escape(label)}</div>
    </div>"""


def render_identity_quadrant(
    off_pct: float | None, def_pct: float | None, *, team_abbrev: str, primary: str,
) -> str:
    """Where this team sits on offense (shot/goal generation) vs defense (shot/
    goal suppression) vs league average - a two-variable relationship, which
    is a scatter/position job, not something a bar can show in one shot."""
    size = 220
    pad = 28
    plot = size - 2 * pad
    ox = off_pct if off_pct is not None else 0.5
    oy = def_pct if def_pct is not None else 0.5
    px = pad + ox * plot
    py = pad + (1 - oy) * plot
    mid = pad + plot / 2
    return f"""
    <div class="quadrant">
      <svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">
        <rect x="{pad}" y="{pad}" width="{plot}" height="{plot}" fill="#fafaf8" stroke="#e2e5ea"/>
        <line x1="{mid}" y1="{pad}" x2="{mid}" y2="{pad+plot}" stroke="#d8dce2" stroke-width="1.5"/>
        <line x1="{pad}" y1="{mid}" x2="{pad+plot}" y2="{mid}" stroke="#d8dce2" stroke-width="1.5"/>
        <text x="{pad+4}" y="{pad+14}" font-size="8" fill="#9aa1ab" font-family="Inter, sans-serif">SHUTDOWN D</text>
        <text x="{pad+plot-4}" y="{pad+14}" text-anchor="end" font-size="8" fill="#9aa1ab" font-family="Inter, sans-serif">ELITE</text>
        <text x="{pad+4}" y="{pad+plot-6}" font-size="8" fill="#9aa1ab" font-family="Inter, sans-serif">REBUILDING</text>
        <text x="{pad+plot-4}" y="{pad+plot-6}" text-anchor="end" font-size="8" fill="#9aa1ab" font-family="Inter, sans-serif">HIGH EVENT</text>
        <circle cx="{px:.1f}" cy="{py:.1f}" r="10" fill="{primary}" stroke="#fff" stroke-width="2.5"/>
        <text x="{px:.1f}" y="{py+3.5:.1f}" text-anchor="middle" font-size="7.5" font-weight="700" fill="#fff" font-family="Inter, sans-serif">{html.escape(team_abbrev)}</text>
        <text x="{pad+plot/2:.1f}" y="{size-6}" text-anchor="middle" font-size="8" fill="#9aa1ab" font-family="Inter, sans-serif">Offense percentile →</text>
        <text x="10" y="{pad+plot/2:.1f}" text-anchor="middle" font-size="8" fill="#9aa1ab" font-family="Inter, sans-serif" transform="rotate(-90 10 {pad+plot/2:.1f})">Defense percentile →</text>
      </svg>
    </div>"""


def render_leaders_scatter(leaders: list[dict[str, Any]], *, primary: str) -> str:
    """Goals vs assists for the team's top scorers - a shooter/playmaker split
    is a relationship between two variables, which a single leaderboard bar
    (sorted only by total points) collapses away."""
    if not leaders:
        return '<div class="shot-map-empty">No scoring data</div>'
    size_w, size_h, pad = 340, 220, 32
    max_g = max((ld.get("goals") or 0) for ld in leaders) or 1
    max_a = max((ld.get("assists") or 0) for ld in leaders) or 1
    plot_w, plot_h = size_w - 2 * pad, size_h - 2 * pad

    def sx(a: float) -> float:
        return pad + (a / max_a) * plot_w

    def sy(g: float) -> float:
        return pad + plot_h - (g / max_g) * plot_h

    pts = []
    for ld in leaders:
        g, a, p = ld.get("goals") or 0, ld.get("assists") or 0, ld.get("points") or 0
        x, y = sx(a), sy(g)
        r = 5 + min(6, p / 12)
        last = (ld.get("name") or "").split()[-1]
        pts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{primary}" fill-opacity="0.82" stroke="#fff" stroke-width="1.5"/>'
            f'<text x="{x:.1f}" y="{y - r - 4:.1f}" text-anchor="middle" font-size="8.5" font-weight="600" '
            f'fill="#1a1a1a" font-family="Inter, sans-serif">{html.escape(last)}</text>'
        )
    return f"""
    <div class="leaders-scatter">
      <svg viewBox="0 0 {size_w} {size_h}" width="{size_w}" height="{size_h}">
        <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{size_h-pad}" stroke="#d8dce2" stroke-width="1.5"/>
        <line x1="{pad}" y1="{size_h-pad}" x2="{size_w-pad}" y2="{size_h-pad}" stroke="#d8dce2" stroke-width="1.5"/>
        <text x="{pad}" y="{size_h-8}" font-size="8" fill="#9aa1ab" font-family="Inter, sans-serif">Assists →</text>
        <text x="10" y="{pad-8}" font-size="8" fill="#9aa1ab" font-family="Inter, sans-serif">↑ Goals</text>
        {"".join(pts)}
      </svg>
    </div>"""
