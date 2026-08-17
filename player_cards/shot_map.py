"""Half-rink shot map — goals and shots plotted as markers."""

from __future__ import annotations

import html
from pathlib import Path

from PIL import Image

# InStat PBP coords (metres)
RINK_LENGTH = 60.96
CENTER_X = RINK_LENGTH / 2
GOAL_X = RINK_LENGTH
RINK_Y = 25.91
NZ_LIMIT = 38.10

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
HALF_RINK_PATH = ASSETS_DIR / "half_rink.png"

_CALIBRATION: dict[str, float] | None = None


def _load_calibration() -> dict[str, float]:
    global _CALIBRATION
    if _CALIBRATION is not None:
        return _CALIBRATION
    if HALF_RINK_PATH.is_file():
        with Image.open(HALF_RINK_PATH) as img:
            w, h = img.size
    else:
        w, h = 375, 328
    _CALIBRATION = {"vb_w": float(w), "vb_h": float(h)}
    return _CALIBRATION


def rink_image_uri() -> str:
    if HALF_RINK_PATH.is_file():
        return HALF_RINK_PATH.resolve().as_uri()
    return ""


def instat_to_svg(x_m: float, y_m: float) -> tuple[float, float]:
    cal = _load_calibration()
    w, h = cal["vb_w"], cal["vb_h"]
    x, y = float(x_m), float(y_m)
    frac_x = max(0.0, min(1.0, (x - CENTER_X) / (GOAL_X - CENTER_X)))
    frac_y = max(0.0, min(1.0, y / RINK_Y))
    return frac_x * w, frac_y * h


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "goal"}


def _parse_shot(s: dict) -> tuple[float, float, float, bool] | None:
    try:
        x_m, y_m = float(s["x"]), float(s["y"])
    except (KeyError, TypeError, ValueError):
        return None
    is_goal = _as_bool(s.get("goal"))
    # Keep goals even if tagged slightly outside OZ so map counts match PBP totals.
    if x_m < NZ_LIMIT and not is_goal:
        return None
    if x_m < NZ_LIMIT:
        x_m = NZ_LIMIT
    return x_m, y_m, float(s.get("xg", 0)), is_goal


def _split_shots(shots: list[dict]) -> tuple[list[dict], list[dict]]:
    non_goals: list[dict] = []
    goals: list[dict] = []
    for s in shots:
        parsed = _parse_shot(s)
        if not parsed:
            continue
        x_m, y_m, xg, is_goal = parsed
        sx, sy = instat_to_svg(x_m, y_m)
        point = {"sx": sx, "sy": sy, "xg": xg}
        if is_goal:
            goals.append(point)
        else:
            non_goals.append(point)
    return non_goals, goals


def _shots_svg(shots: list[dict], primary: str) -> str:
    parts: list[str] = []
    for s in shots:
        sx, sy = s["sx"], s["sy"]
        r = 3.2 + min(2.0, s["xg"] * 4.0)
        parts.append(
            f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{r:.1f}" fill="{primary}" '
            f'stroke="#fff" stroke-width="0.8" opacity="0.55"/>'
        )
    return "".join(parts)


def _goals_svg(goals: list[dict], accent: str) -> str:
    parts: list[str] = []
    for g in goals:
        sx, sy = g["sx"], g["sy"]
        parts.append(
            f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="7.5" fill="{accent}" '
            f'stroke="#111" stroke-width="1.8" opacity="0.95"/>'
        )
        parts.append(
            f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="3" fill="#fff" stroke="none"/>'
        )
    return "".join(parts)


def render_team_shot_heatmap_html(
    shots: list[dict],
    *,
    primary: str,
    title: str,
    subtitle: str = "",
    nx: int = 12,
    ny: int = 8,
) -> str:
    """Binned density heatmap (sequential single-hue, light->dark by shot
    count per cell) for season/team-volume shot data - thousands of individual
    dots overlap into an unreadable blob at that density, so this bins them
    into a grid instead (same idea as the sibling pwhl-analytics ShotHeatmap
    component). Goals are annotated as a count label per cell rather than
    plotted as separate markers, since a raw goal-dot overlay gets just as
    cluttered at ~250 goals/season."""
    if not shots:
        return '<div class="shot-map-empty">No shot data</div>'

    cal = _load_calibration()
    vb_w, vb_h = cal["vb_w"], cal["vb_h"]
    x_lo, x_hi = NZ_LIMIT, GOAL_X
    y_lo, y_hi = 0.0, RINK_Y
    cell_x_m, cell_y_m = (x_hi - x_lo) / nx, (y_hi - y_lo) / ny

    grid_shots = [[0] * nx for _ in range(ny)]
    grid_goals = [[0] * nx for _ in range(ny)]
    total_xg = 0.0
    total_goals = 0
    plotted = 0
    for s in shots:
        parsed = _parse_shot(s)
        if not parsed:
            continue
        x_m, y_m, xg, is_goal = parsed
        cx = min(nx - 1, max(0, int((x_m - x_lo) / cell_x_m)))
        cy = min(ny - 1, max(0, int((y_m - y_lo) / cell_y_m)))
        grid_shots[cy][cx] += 1
        total_xg += xg
        plotted += 1
        if is_goal:
            grid_goals[cy][cx] += 1
            total_goals += 1

    max_count = max((max(row) for row in grid_shots), default=0) or 1
    peak_cy, peak_cx = max(
        ((cy, cx) for cy in range(ny) for cx in range(nx)),
        key=lambda t: grid_shots[t[0]][t[1]],
    )
    rink_uri = rink_image_uri()
    bg = (
        f'<image href="{html.escape(rink_uri)}" x="0" y="0" width="{vb_w:.0f}" height="{vb_h:.0f}" '
        f'preserveAspectRatio="xMidYMid meet" opacity="0.98"/>'
        if rink_uri else f'<rect width="{vb_w:.0f}" height="{vb_h:.0f}" fill="#1a2d4a"/>'
    )

    cells = []
    for cy in range(ny):
        for cx in range(nx):
            n = grid_shots[cy][cx]
            if n == 0:
                continue
            x0_m, y0_m = x_lo + cx * cell_x_m, y_lo + cy * cell_y_m
            x1_m, y1_m = x0_m + cell_x_m, y0_m + cell_y_m
            sx0, sy0 = instat_to_svg(x0_m, y0_m)
            sx1, sy1 = instat_to_svg(x1_m, y1_m)
            x, y = min(sx0, sx1), min(sy0, sy1)
            w, h = abs(sx1 - sx0), abs(sy1 - sy0)
            t = n / max_count
            opacity = 0.14 + 0.78 * t
            cells.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                f'fill="{primary}" opacity="{opacity:.2f}" stroke="#fff" stroke-width="1"/>'
            )
            # Only the single hottest cell gets a number label - the season-total
            # goal count is already in the header stat line above, and labeling
            # every nonzero cell (dozens of them) is exactly the visual noise
            # this heatmap replaced the raw-scatter shot map to avoid.
            if (cy, cx) == (peak_cy, peak_cx):
                cells.append(
                    f'<text x="{x+w/2:.1f}" y="{y+h/2+5:.1f}" text-anchor="middle" '
                    f'font-size="13" font-weight="700" fill="#fff" '
                    f'font-family="Russo One, sans-serif">{n}</text>'
                )

    return f"""
    <div class="shot-map-panel">
      <div class="shot-map-header">
        <div>
          <div class="shot-map-title">{html.escape(title)}</div>
          <div class="shot-map-sub">{html.escape(subtitle)}</div>
        </div>
        <div class="shot-map-stats">
          <div><b>{plotted}</b><span>shots</span></div>
          <div><b>{total_xg:.0f}</b><span>xG</span></div>
          <div><b>{total_goals}</b><span>goals</span></div>
        </div>
      </div>
      <div class="shot-map-canvas">
        <svg viewBox="0 0 {vb_w:.0f} {vb_h:.0f}" class="shot-map-svg" xmlns="http://www.w3.org/2000/svg">
          {bg}
          <g class="heat-cells">{"".join(cells)}</g>
        </svg>
      </div>
      <div class="shot-map-footer">
        <span class="legend-dot" style="background:{primary};opacity:0.3"></span> Fewer shots
        <span class="legend-dot" style="background:{primary};opacity:0.9"></span> More shots
        <span style="margin-left:8px">· number = goals in that cell</span>
      </div>
    </div>"""


def render_shot_map_html(
    shots: list[dict],
    *,
    primary: str,
    accent: str,
    player_name: str = "",
    total_shots: int | float | None = None,
    total_goals: int | float | None = None,
    total_xg: float | None = None,
) -> str:
    if not shots:
        return '<div class="shot-map-empty">No shot data</div>'

    cal = _load_calibration()
    vb_w, vb_h = int(cal["vb_w"]), int(cal["vb_h"])

    non_goals, goals = _split_shots(shots)
    plotted = len(non_goals) + len(goals)
    xg_plotted = sum(float(s.get("xg", 0)) for s in shots if _parse_shot(s))
    # Shot map numbers MUST equal what is drawn — never a separate box-score
    # total that double-counted InStat Shots+SOG+Goals rows.
    if total_shots is not None and int(total_shots) != plotted:
        import logging

        logging.getLogger(__name__).warning(
            "shot_map total_shots=%s != plotted=%s — using plotted",
            total_shots,
            plotted,
        )
    if total_goals is not None and int(total_goals) != len(goals):
        import logging

        logging.getLogger(__name__).warning(
            "shot_map total_goals=%s != plotted goals=%s — using plotted",
            total_goals,
            len(goals),
        )
    disp_shots = plotted
    disp_goals = len(goals)
    disp_xg = float(total_xg) if total_xg is not None else xg_plotted

    rink_uri = rink_image_uri()
    bg = (
        f'<image href="{html.escape(rink_uri)}" x="0" y="0" width="{vb_w}" height="{vb_h}" '
        f'preserveAspectRatio="xMidYMid meet" opacity="0.98"/>'
        if rink_uri
        else f'<rect width="{vb_w}" height="{vb_h}" fill="#1a2d4a"/>'
    )

    subtitle = html.escape(player_name) if player_name else "Offensive zone"
    n_shot = len(non_goals)
    n_goal = len(goals)

    return f"""
    <div class="shot-map-panel">
      <div class="shot-map-header">
        <div>
          <div class="shot-map-title">Shot Map</div>
          <div class="shot-map-sub">{subtitle}</div>
        </div>
        <div class="shot-map-stats">
          <div><b>{disp_shots}</b><span>shots</span></div>
          <div><b>{disp_xg:.1f}</b><span>xG</span></div>
          <div><b>{disp_goals}</b><span>goals</span></div>
        </div>
      </div>
      <div class="shot-map-canvas">
        <svg viewBox="0 0 {vb_w} {vb_h}" class="shot-map-svg" xmlns="http://www.w3.org/2000/svg">
          {bg}
          <g class="shot-dots">{_shots_svg(non_goals, primary)}</g>
          <g class="shot-goals">{_goals_svg(goals, accent)}</g>
        </svg>
      </div>
      <div class="shot-map-footer">
        <span class="legend-dot legend-dot--shot"></span> No goal ({n_shot})
        <span class="legend-dot legend-dot--goal"></span> Goal ({n_goal})
        <span style="margin-left:8px">· {n_shot}+{n_goal}={disp_shots}</span>
      </div>
    </div>"""
