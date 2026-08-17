"""Goalie card — same visual system as the skater card (shared_card_css: photo
panel, hero block, percentile pillars, highlight tiles, shot map). Goalies have
a far thinner comparison pool than skaters, so only metrics with a real
league-wide population (SV%, ES SV%, Scoring-Chance SV%, GSAx — computed in
goalie_league_stats.py) get percentile-colored bars/tiles. The situational
per-shot splits (High Danger/Rush/Cycle/Royal Road/side/rebound control) have
no league population behind them (that would need full-season PBP for all 32
teams), so they're shown as plain raw-rate rows, same as the skater card's
bottom Scoring/Zone Entries/Defense tables — not dressed up as percentiles."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .color_utils import theme_text_vars
from .html_renderer import (
    FLAG_MAP,
    _bar_row,
    _cap_box_html,
    _pillar_col,
    _rate_row,
    shared_card_css,
)
from .photo_layout import embed_photo, photo_frame
from .png_export import html_to_png
from .shot_map import render_shot_map_html
from .team_colors import get_team_colors


def _m(pct: float | None) -> dict[str, float | None]:
    """Wrap a 0-1 percentile into the {"percentile": ...} shape _bar_row/_pillar_col expect."""
    return {"percentile": pct}


def _stat_tile(label: str, value: str) -> str:
    return (
        f'<div class="g-stat-tile"><div class="g-stat-tile__val">{html.escape(value)}</div>'
        f'<div class="g-stat-tile__lbl">{html.escape(label)}</div></div>'
    )


def _raw_bar_row(label: str, sv_pct: float | None, *, low_sample: bool = False) -> str:
    """Same .bar-row layout as the percentile pillar above it (label | track |
    value), but filled by the raw SV% itself rather than a league percentile —
    there's no 32-team population for these situational cuts to rank against.
    Scaled over a 70-100% SV% window (not 0-100%) so real differences between
    zones are visible instead of every bar reading as ~90% full."""
    flag = " (small n)" if low_sample else ""
    if sv_pct is None:
        return (
            f'<div class="bar-row"><span class="bar-row__lbl">{html.escape(label)}{flag}</span>'
            f'<span class="bar-row__track"><span class="bar-row__fill" style="width:0%"></span></span>'
            f'<span class="bar-row__pct">—</span></div>'
        )
    width = max(4.0, min(100.0, (sv_pct - 70.0) / 30.0 * 100.0))
    return (
        f'<div class="bar-row"><span class="bar-row__lbl">{html.escape(label)}{flag}</span>'
        f'<span class="bar-row__track"><span class="bar-row__fill" style="width:{width:.0f}%;background:var(--primary)"></span></span>'
        f'<span class="bar-row__pct">{sv_pct:.1f}%</span></div>'
    )


def _simple_pillar(title: str, rows_html: str) -> str:
    """A .pillar column without a percentile-avg badge, for rate-row content
    (real per-shot splits) — reuses the same layout as the percentile pillars
    above it so both rows read as one consistent grid, not two different systems."""
    return (
        f'<div class="pillar"><div class="pillar__head">'
        f'<span class="pillar__title">{html.escape(title)}</span></div>'
        f'<div class="pillar__rows">{rows_html}</div></div>'
    )


def _pillar_avg_of(pcts: list[float | None]) -> int | None:
    vals = [p for p in pcts if p is not None]
    return int(sum(vals) / len(vals) * 100) if vals else None


_HEATMAP_GRID = [
    ["Top Left", "Top Center", "Top Right"],
    ["Mid Left", "Mid Center", "Mid Right"],
    ["Bottom Left", "Bottom Center (Five-Hole)", "Bottom Right"],
]


def _zone_color(sv_pct: float | None) -> str:
    """Red = vulnerable zone, blue = strong zone — SV% scale, not percentile.
    All four bands are dark enough for the white value text on top to stay
    readable (the two middle tiers used to be too light for that)."""
    if sv_pct is None:
        return "#6b7280"
    if sv_pct < 78:
        return "#b8433d"
    if sv_pct < 86:
        return "#bd6a35"
    if sv_pct < 92:
        return "#4f6478"
    return "#2c5a8a"


def render_net_heatmap_html(heatmap_zones: dict[str, dict[str, Any]], games_tracked: int, total_shots: int) -> str:
    if not heatmap_zones or not total_shots:
        return '<div class="shot-map-empty">No zone-charted shot data</div>'
    w, h, pad = 300, 220, 10
    cell_w, cell_h = (w - 2 * pad) / 3, (h - 2 * pad - 24) / 3
    cells = []
    for r, row in enumerate(_HEATMAP_GRID):
        for c, zone in enumerate(row):
            d = heatmap_zones.get(zone, {"shots": 0, "goals": 0, "sv_pct": None})
            x, y = pad + c * cell_w, pad + r * cell_h
            fill = _zone_color(d["sv_pct"])
            label = zone.replace(" (Five-Hole)", "")
            sv_disp = f'{d["sv_pct"]:.0f}%' if d["sv_pct"] is not None else "—"
            cells.append(
                f'<g>'
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_w-3:.1f}" height="{cell_h-3:.1f}" rx="4" fill="{fill}" stroke="#fff" stroke-width="1.5"/>'
                f'<text x="{x+cell_w/2:.1f}" y="{y+cell_h/2-4:.1f}" text-anchor="middle" font-size="15" font-weight="700" fill="#fff" font-family="Russo One, sans-serif">{sv_disp}</text>'
                f'<text x="{x+cell_w/2:.1f}" y="{y+cell_h/2+13:.1f}" text-anchor="middle" font-size="8.5" fill="#fff" opacity="0.9">{html.escape(label)}</text>'
                f'<text x="{x+cell_w/2:.1f}" y="{y+cell_h/2+24:.1f}" text-anchor="middle" font-size="7.5" fill="#fff" opacity="0.75">{d["shots"]} shots, {d["goals"]} goals</text>'
                f"</g>"
            )
    return f"""
    <div class="shot-map-panel">
      <div class="shot-map-header">
        <div><div class="shot-map-title">Save % by Net Zone</div>
        <div class="shot-map-sub">{games_tracked} InStat-charted games · {total_shots} shots</div></div>
      </div>
      <div class="shot-map-canvas">
        <svg viewBox="0 0 {w} {h}" class="shot-map-svg" xmlns="http://www.w3.org/2000/svg">
          <rect width="{w}" height="{h}" fill="#ffffff"/>
          {"".join(cells)}
        </svg>
      </div>
    </div>"""


def render_goalie_card_html(profile: dict[str, Any]) -> str:
    bio = profile["bio"]
    colors = get_team_colors(bio["team"], league="nhl")
    primary, accent = colors["primary"], colors["accent"]
    light = colors.get("light", "#f1f5f9")
    theme = theme_text_vars(primary, accent)

    official = profile.get("official") or {}
    instat = profile.get("instat") or {}
    situational = profile.get("situational") or {}
    percentiles = profile.get("percentiles") or {}
    cap = profile.get("cap")

    sv_pct_p = percentiles.get("sv_pct_overall")
    es_sv_pct_p = percentiles.get("es_sv_pct")
    sc_sv_pct_p = percentiles.get("scoring_chance_sv_pct")
    gsax_p = percentiles.get("gsax")
    pool_size = percentiles.get("pool_size")

    # ── Header / vitals ─────────────────────────────────────────────
    photo_kind = bio.get("card_photo_kind") or "mug"
    photo_raw = bio.get("card_photo_url") or bio.get("headshot_url") or ""
    photo_src, pw, ph = embed_photo(str(photo_raw)) if photo_raw else ("", None, None)
    aspect_cls, obj_pos = photo_frame(pw, ph, kind=photo_kind)
    photo = (
        f'<img class="photo {aspect_cls}" style="object-position:{obj_pos}" src="{html.escape(photo_src)}" '
        f'alt="{html.escape(bio.get("name",""))}">'
        if photo_src else f'<div class="photo-placeholder">{html.escape(bio.get("name","")[:2].upper())}</div>'
    )
    number = bio.get("sweater_number")
    jersey = f'<div class="jersey-badge">{html.escape(str(number))}</div>' if number is not None else ""

    logo_raw = bio.get("team_logo_png_url") or bio.get("team_logo_url") or ""
    logo_src = embed_photo(str(logo_raw))[0] if logo_raw else ""

    country = bio.get("birth_country") or bio.get("country")
    flag = FLAG_MAP.get(str(country or "").upper(), "")
    name = html.escape(f"{flag} {bio.get('name','')}".strip())

    catches = instat.get("catches") or bio.get("shoots") or "—"
    height = html.escape(bio.get("height") or "—")
    weight = bio.get("weight_lbs")
    weight_disp = f"{weight} lbs" if weight else "—"
    team_name = html.escape(bio.get("team", ""))
    vitals_line = f"G · {team_name} · 2025-26 · {height} · {html.escape(weight_disp)} · Catches {html.escape(str(catches))}"

    cap_html = _cap_box_html(cap) if cap else ""

    # ── Hero block: SV% is the headline stat, colored by league percentile ──
    sv_pct = official.get("save_pct")
    gs_disp = f"{sv_pct:.1f}" if isinstance(sv_pct, (int, float)) else "—"
    gs_sub = f"{int(sv_pct_p*100)}th %ile of {pool_size} NHL goalies" if sv_pct_p is not None and pool_size else ""

    from .html_renderer import _pct_class, _pct_num
    es_disp = "—" if _pct_num(es_sv_pct_p) is None else str(_pct_num(es_sv_pct_p))
    sc_disp = "—" if _pct_num(sc_sv_pct_p) is None else str(_pct_num(sc_sv_pct_p))
    es_tier = _pct_class(es_sv_pct_p)
    sc_tier = _pct_class(sc_sv_pct_p)

    gp = official.get("games_played", "—")
    w, l, otl = official.get("wins", "—"), official.get("losses", "—"), official.get("ot_losses", "—")

    # ── Pillar 1: percentile-backed metrics (real league population) ──
    pillar1_rows = "".join([
        _bar_row("SV% (Overall)", _m(sv_pct_p)),
        _bar_row("SV% (5-on-5)", _m(es_sv_pct_p)),
        _bar_row("Scoring-Chance SV%", _m(sc_sv_pct_p)),
        _bar_row("GSAx", _m(gsax_p)),
    ])
    pillar1 = _pillar_col("League Percentiles", _pillar_avg_of([sv_pct_p, es_sv_pct_p, sc_sv_pct_p, gsax_p]), pillar1_rows)

    # ── Pillars 2/3: raw situational SV% (no league population to percentile against) ──
    def raw_row(label: str, key: str) -> str:
        d = situational.get(key) or {}
        return _raw_bar_row(label, d.get("sv_pct"), low_sample=bool(d.get("low_sample")))

    pillar2_rows = "".join([
        raw_row("High Danger", "high_danger"),
        raw_row("Medium Range", "medium"),
        raw_row("Long Range", "long_range"),
        raw_row("Rush Chances", "rush"),
    ])
    pillar3_rows = "".join([
        raw_row("Forecheck / Cycle", "cycle"),
        raw_row("Royal Road", "royal_road"),
        raw_row("Shots from Left", "left_side"),
        raw_row("Shots from Right", "right_side"),
    ])

    # ── Shot map ──
    raw_shots = profile.get("shots") or []
    shots_for_map = [{"x": s["x"], "y": s["y"], "xg": s["xg"], "goal": s["is_goal"]} for s in raw_shots]
    shot_html = render_shot_map_html(shots_for_map, primary=primary, accent=accent, player_name="Shots against")

    # ── Bottom raw-stat tables: rebound control + REAL style-of-play (not a proxy) ──
    rebound_control = situational.get("rebound_control_pct")
    real_agg = profile.get("real_shot_agg") or {}
    games_tracked = real_agg.get("games_tracked", 0)
    real_shots_n = real_agg.get("shots", 0)

    def split_rows(bucket: dict[str, dict[str, Any]], order: list[str] | None = None, *, metric: str = "sv_pct") -> str:
        items = list(bucket.items())
        if order:
            items = [(k, bucket[k]) for k in order if k in bucket] + [
                (k, v) for k, v in items if k not in (order or [])
            ]
        else:
            items.sort(key=lambda kv: -(kv[1].get("shots") or 0))
        rows = []
        for k, d in items:
            val = d.get(metric)
            disp = f"{val:.1f}%" if val is not None else "—"
            flag = " (small n)" if d.get("low_sample") else ""
            rows.append(_rate_row(f"{k} ({d.get('shots',0)}){flag}", disp))
        return "".join(rows) if rows else _rate_row("No tracked data", "—")

    # ── Season Summary: big stat tiles, not small text rows — this is headline
    # data (record, GAA, shutouts) and should carry visual weight to match. ──
    gaa_val = official.get("gaa")
    gaa_disp = f"{gaa_val:.2f}" if isinstance(gaa_val, (int, float)) else "—"
    rebound_disp = f"{rebound_control:.1f}%" if rebound_control is not None else "—"
    season_tiles = "".join([
        _stat_tile("Games Played", str(gp)),
        _stat_tile("Record (W-L-OTL)", f"{w}-{l}-{otl}"),
        _stat_tile("GAA", gaa_disp),
        _stat_tile("Shutouts", str(official.get("shutouts", "—"))),
        _stat_tile("Rebound Control", rebound_disp),
        _stat_tile("Shots Faced", str(situational.get("shots", "—"))),
    ])

    # ── Real per-shot splits: handedness, style/attack/visibility, score+rebound detail ──
    # Same .pillar layout as the percentile row above (not .rate-col), so both
    # rows read as one consistent grid instead of two different systems.
    handedness_pillar = _simple_pillar(
        "Shooter Handedness / Wing",
        split_rows(real_agg.get("handedness_splits", {}), ["vs_right_shot", "vs_left_shot", "off_wing", "on_wing", "short_side", "long_side"]),
    )
    attack_pillar = _simple_pillar(
        "Style of Play / Attack Type / Visibility",
        split_rows(real_agg.get("real_style_of_play", {}), ["Butterfly", "In Motion", "Beaten"])
        + split_rows({**real_agg.get("by_attack_type", {}), **real_agg.get("by_visibility", {})}),
    )
    situation_pillar = _simple_pillar(
        "Score Sit. (SV%) / Rebound Detail (% of saves)",
        split_rows(real_agg.get("by_score_situation", {})) + split_rows(real_agg.get("save_detail_share", {}), metric="share_pct"),
    )

    heatmap_html = render_net_heatmap_html(
        real_agg.get("heatmap_zones", {}), games_tracked, real_shots_n
    )
    real_data_note = (
        f'<div class="data-context data-context--minimal">'
        f'<span>Heatmap, style of play, handedness/attack-type/visibility/score-situation splits above come from '
        f'InStat\'s real per-shot goalie tracking ({games_tracked} of {gp if isinstance(gp,(int,str)) else "—"} games this '
        f'goalie played were shot-charted at this level of detail — InStat doesn\'t run this tracking for every game, '
        f'unlike the always-on play-by-play export the rest of the card uses). Not a proxy or estimate where shown.</span>'
        f'</div>'
        if games_tracked else
        '<div class="data-context data-context--minimal"><span>No InStat per-shot goalie tracking available for this player this season.</span></div>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Russo+One&display=swap" rel="stylesheet">
<style>
{shared_card_css(primary, accent, theme, light)}
.g-tile-row {{ background: #fff; border-bottom: 1px solid var(--line); padding: 14px 20px 16px; }}
.g-tile-row .section-tag {{ padding: 0 0 8px; }}
.g-tile-grid {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }}
.g-stat-tile {{ background: #fafaf8; border: 1px solid var(--line); border-radius: 8px; padding: 12px 6px; text-align: center; }}
.g-stat-tile__val {{ font-family: 'Russo One', sans-serif; font-size: 1.7rem; color: var(--ink); line-height: 1; }}
.g-stat-tile__lbl {{ font-size: 0.52rem; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); margin-top: 5px; }}
</style>
</head>
<body>
<article class="card">
  <div class="photo-col">
    {photo}
    <div class="photo-fade"></div>
    {jersey}
  </div>
  <div class="content">
    <header class="top">
      <img class="team-logo" src="{html.escape(logo_src)}" alt="{team_name}">
      <div class="name-block">
        <h1>{name}</h1>
        <div class="vitals">{vitals_line}</div>
      </div>
      <div class="score-cluster">
      {cap_html}
      <div class="hero-block">
        <div class="gs-hero">
          <div class="gs-hero__val">{html.escape(gs_disp)}</div>
          <div class="gs-hero__lbl">SV%</div>
          {f'<div class="gs-hero__sub">{html.escape(gs_sub)}</div>' if gs_sub else ""}
        </div>
        <div class="sub-scores">
          <div><span>5v5</span><em class="{es_tier}">{es_disp}</em></div>
          <div><span>SC</span><em class="{sc_tier}">{sc_disp}</em></div>
        </div>
      </div>
      <div class="ctx-box">
        <div>GAA<b>{gaa_disp}</b></div>
        <div>SO<b>{html.escape(str(official.get("shutouts", "—")))}</b></div>
      </div>
      </div>
    </header>
    <div class="ribbon"></div>
    <div class="main-grid">
      <div class="pillars-wrap">
        <div class="section-tag">League percentiles · <span>vs. {pool_size or "—"} NHL goalies, min 10 GP</span></div>
        <div class="pillars">{pillar1}
          <div class="pillar"><div class="pillar__head"><span class="pillar__title">Shot Location (raw SV%)</span></div><div class="pillar__rows">{pillar2_rows}</div></div>
          <div class="pillar"><div class="pillar__head"><span class="pillar__title">Situation (raw SV%)</span></div><div class="pillar__rows">{pillar3_rows}</div></div>
        </div>
      </div>
      <div class="shot-wrap">{shot_html}</div>
    </div>
    <div class="g-tile-row">
      <div class="section-tag">Season summary</div>
      <div class="g-tile-grid">{season_tiles}</div>
    </div>
    <div class="main-grid">
      <div class="pillars-wrap">
        <div class="section-tag">Real per-shot tracking · <span>{games_tracked} GP charted</span></div>
        <div class="pillars">{handedness_pillar}{attack_pillar}{situation_pillar}</div>
      </div>
      <div class="shot-wrap">{heatmap_html}</div>
    </div>
    {real_data_note}
  </div>
</article>
</body>
</html>"""


def write_goalie_card_html(profile: dict[str, Any], output: Path | str) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_goalie_card_html(profile), encoding="utf-8")
    return output


def generate_goalie_card_png(profile: dict[str, Any], output_png: Path | str) -> Path:
    output_png = Path(output_png)
    html_path = output_png.with_suffix(".html")
    write_goalie_card_html(profile, html_path)
    return html_to_png(html_path, output_png)
