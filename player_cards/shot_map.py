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


def _parse_shot(s: dict) -> tuple[float, float, float, bool] | None:
    try:
        x_m, y_m = float(s["x"]), float(s["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if x_m < NZ_LIMIT:
        return None
    return x_m, y_m, float(s.get("xg", 0)), bool(s.get("goal"))


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


def render_shot_map_html(
    shots: list[dict],
    *,
    primary: str,
    accent: str,
    player_name: str = "",
) -> str:
    if not shots:
        return '<div class="shot-map-empty">No shot data</div>'

    cal = _load_calibration()
    vb_w, vb_h = int(cal["vb_w"]), int(cal["vb_h"])

    non_goals, goals = _split_shots(shots)
    plotted = len(non_goals) + len(goals)
    total_xg = sum(float(s.get("xg", 0)) for s in shots if _parse_shot(s))

    rink_uri = rink_image_uri()
    bg = (
        f'<image href="{html.escape(rink_uri)}" x="0" y="0" width="{vb_w}" height="{vb_h}" '
        f'preserveAspectRatio="xMidYMid meet" opacity="0.98"/>'
        if rink_uri
        else f'<rect width="{vb_w}" height="{vb_h}" fill="#1a2d4a"/>'
    )

    subtitle = html.escape(player_name) if player_name else "Offensive zone"

    return f"""
    <div class="shot-map-panel">
      <div class="shot-map-header">
        <div>
          <div class="shot-map-title">Shot Map</div>
          <div class="shot-map-sub">{subtitle}</div>
        </div>
        <div class="shot-map-stats">
          <div><b>{plotted}</b><span>shots</span></div>
          <div><b>{total_xg:.1f}</b><span>xG</span></div>
          <div><b>{len(goals)}</b><span>goals</span></div>
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
        <span class="legend-dot legend-dot--shot"></span> Shot ({len(non_goals)})
        <span class="legend-dot legend-dot--goal"></span> Goal ({len(goals)})
      </div>
    </div>"""
