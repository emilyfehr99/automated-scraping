"""Editorial landscape player cards — Athletic / AR Index / JFresh inspired."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

FLAG_MAP = {
    "CAN": "🇨🇦",
    "USA": "🇺🇸",
    "SWE": "🇸🇪",
    "RUS": "🇷🇺",
    "FIN": "🇫🇮",
    "CZE": "🇨🇿",
    "SVK": "🇸🇰",
    "LVA": "🇱🇻",
    "CHE": "🇨🇭",
    "SUI": "🇨🇭",
    "GER": "🇩🇪",
    "BLR": "🇧🇾",
    "AUT": "🇦🇹",
    "NOR": "🇳🇴",
    "DEN": "🇩🇰",
}

from .card_config import (
    DEFENSE_GS_KEY,
    DEFENSE_GS_KEYS,
    HIGHLIGHT_TILES,
    OFFENSE_GS_KEY,
    PILLAR_BARS,
    PWHL_PILLAR_BARS,
    PBP_RATE_GROUPS,
    PWHL_HIGHLIGHT_TILES,
    format_rate_stat,
    format_stat,
)
from .color_utils import elite_tile_fill, text_on_background, theme_text_vars
from .disk_cache import photo_data_url, photo_dimensions, store_photo_data_url
from .leagues import LEAGUES, team_full_name
from .photo_layout import embed_photo, photo_frame
from .pwhl_vitals import format_shoots_label
from .shot_map import render_shot_map_html
from .team_colors import get_team_colors


def prewarm_photo(url: str) -> str:
    """Download/cache hero photo so card render skips HTTP."""
    data_url, _, _ = embed_photo(url)
    return data_url


def _embed_photo_src(url: str) -> str:
    """Inline full-resolution photo so Playwright exports native pixels."""
    data_url, _, _ = embed_photo(url)
    return data_url


def _pct_num(pct: float | None) -> int | None:
    return int(pct * 100) if pct is not None else None


def _pct_class(pct: float | None) -> str:
    if pct is None:
        return "pct-na"
    p = pct * 100
    if p >= 85:
        return "pct-elite"
    if p >= 70:
        return "pct-strong"
    if p >= 45:
        return "pct-avg"
    return "pct-weak"


from .metric_lookup import metric_lookup as _metric_lookup


def _composite_gs_metric(sections: dict, keys: tuple[str, ...]) -> dict[str, float | None]:
    parts = [_metric_lookup(sections, k) for k in keys]
    parts = [p for p in parts if p and p.get("value") is not None]
    if not parts:
        return {"value": None, "percentile": None}
    value = sum(float(p["value"]) for p in parts)
    pcts = [float(p["percentile"]) for p in parts if p.get("percentile") is not None]
    return {"value": value, "percentile": (sum(pcts) / len(pcts)) if pcts else None}


def _pillar_avg(sections: dict, keys: list[tuple[str, str]]) -> int | None:
    pcts = []
    for key, _ in keys:
        m = _metric_lookup(sections, key)
        if m and m.get("percentile") is not None:
            pcts.append(float(m["percentile"]))
    return int(sum(pcts) / len(pcts) * 100) if pcts else None


def _jfresh_style(pct: float | None, primary: str, accent: str) -> str:
    if pct is None:
        return "background:#eceff3;color:#6b7280"
    p = pct * 100
    if p >= 90:
        fill = elite_tile_fill(primary, accent)
        fg = text_on_background(fill)
        return f"background:{fill};color:{fg}"
    if p >= 78:
        return "background:#c5ddf5;color:#0f2847"
    if p >= 62:
        return "background:#e3eef9;color:#1a3a5c"
    if p >= 45:
        return "background:#f0f2f5;color:#3d4654"
    if p >= 30:
        return "background:#fae8e8;color:#6b3030"
    return "background:#f5d4d4;color:#5c2020"


def _bar_row(label: str, m: dict | None, *, prefer_value: bool = False) -> str:
    """Render a pillar bar. ``prefer_value`` shows the raw rate (e.g. 6.3 shots/gp)
    instead of the percentile — needed on PBP-only cards so 'Shots' isn't
    read as 95 shots next to a 133-shot map. Percentile displays always use a
    trailing '%' so they aren't read as raw counts on NHL/A3Z cards either.
    """
    pct = m.get("percentile") if m else None
    num = _pct_num(pct)
    val = m.get("value") if m else None
    if prefer_value and val is not None and isinstance(val, (int, float)):
        disp = f"{val:.2f}".rstrip("0").rstrip(".") if abs(val) < 100 else f"{val:.0f}"
        w = max(4, num) if num is not None else min(100, max(12, int(float(val) * 12)))
    elif num is None and val is not None and isinstance(val, (int, float)):
        disp = f"{val:.1f}" if abs(val) < 100 else f"{val:.0f}"
        w = min(100, max(12, int(val * 12)))
    else:
        disp = "—" if num is None else f"{num}%"
        w = max(4, num) if num is not None else 0
    tier = _pct_class(pct) if pct is not None else ("bar-row--star" if val and val > 5 else "bar-row--mid")
    return (
        f'<div class="bar-row {tier}">'
        f'<span class="bar-row__lbl">{html.escape(label)}</span>'
        f'<span class="bar-row__track"><span class="bar-row__fill" style="width:{w}%"></span></span>'
        f'<span class="bar-row__pct">{disp}</span>'
        f"</div>"
    )


def _pillar_col(title: str, avg: int | None, rows: str) -> str:
    avg_disp = "—" if avg is None else f"{avg}%"
    tier = _pct_class(avg / 100 if avg is not None else None)
    return (
        f'<div class="pillar">'
        f'<div class="pillar__head"><span class="pillar__title">{html.escape(title)}</span>'
        f'<span class="pillar__avg {tier}">{avg_disp}</span></div>'
        f'<div class="pillar__rows">{rows}</div></div>'
    )


def _highlight_tile(label: str, m: dict | None, primary: str, accent: str) -> str:
    pct = m.get("percentile") if m else None
    val = m.get("value") if m else None
    if pct is not None:
        # Trailing % so tiles aren't read as raw counts (e.g. Finishing 95 ≠ 95 shots).
        disp = f"{int(pct * 100)}%"
        style = _jfresh_style(pct, primary, accent)
        elite = " hi-tile--elite" if pct * 100 >= 90 else ""
    elif val is not None and isinstance(val, (int, float)):
        disp = f"{val:.1f}" if abs(val) < 100 else f"{val:.0f}"
        norm_val = min(1.0, max(0.0, val / 10.0))
        style = _jfresh_style(norm_val, primary, accent)
        elite = " hi-tile--elite" if val >= 5.0 else ""
    else:
        disp = "—"
        style = ""
        elite = ""
    return (
        f'<div class="hi-tile{elite}" style="{style}">'
        f'<div class="hi-tile__lbl">{html.escape(label)}</div>'
        f'<div class="hi-tile__val">{html.escape(disp)}</div></div>'
    )


def _rate_row(label: str, disp: str, *, negative: bool = False, extra_class: str = "") -> str:
    cls = "rate-row"
    if negative:
        cls += " rate-row--neg"
    if extra_class:
        cls += extra_class
    return (
        f'<div class="{cls}">'
        f'<span class="rate-row__lbl">{html.escape(label)}</span>'
        f'<span class="rate-row__val">{html.escape(disp)}</span>'
        f"</div>"
    )


def _cap_row(label: str, value: str | None, *, accent: bool = False) -> str:
    if not value:
        return ""
    cls = "cap-box__row cap-box__row--accent" if accent else "cap-box__row"
    return (
        f'<div class="{cls}">'
        f'<span class="cap-box__lbl">{html.escape(label)}</span>'
        f'<span class="cap-box__val">{html.escape(value)}</span>'
        f"</div>"
    )


def _cap_box_html(cap: dict[str, Any] | None) -> str:
    if not cap:
        return ""
    rows = "".join(
        [
            _cap_row("AAV", cap.get("aav")),
            _cap_row("Proj value", cap.get("market_value"), accent=True),
            _cap_row("Expires", cap.get("expiry_season")),
        ]
    )
    if not rows:
        return ""
    return (
        f'<div class="cap-box">'
        f'<div class="cap-box__head">Contract</div>'
        f'<div class="cap-box__rows">{rows}</div>'
        f"</div>"
    )


def _faceoff_win_pct(per_game: dict) -> float | None:
    won, lost = per_game.get("Faceoffs Won"), per_game.get("Faceoffs Lost")
    if won is None or lost is None:
        return None
    try:
        w, lo = float(won), float(lost)
    except (TypeError, ValueError):
        return None
    total = w + lo
    return (100 * w / total) if total > 0 else None


def _rate_metric_value(per_game: dict, metric: dict, fo_pct: float | None) -> str:
    key = metric.get("key")
    if key == "_fo_win_pct":
        return format_rate_stat(fo_pct, "percent")
    keys = metric.get("keys") or ([key] if key else [])
    raw = None
    for candidate in keys:
        if candidate in per_game and per_game[candidate] is not None:
            raw = per_game[candidate]
            break
    return format_rate_stat(raw, metric.get("format", "compact"))


def _nhle_panel_html(nhle: dict) -> str:
    """Render the NHLe projection + comparables panel for a prospect card."""
    if not nhle:
        return ""

    proj_ppg = nhle.get("proj_ppg", 0.0)
    proj_pts = nhle.get("proj_pts_82", 0)
    factor   = nhle.get("nhle_factor", 0.0)
    league   = nhle.get("most_recent_league", "—")
    probs    = nhle.get("success_probs", {})
    comps    = nhle.get("comparables", [])
    is_defence = nhle.get("is_defence", False)

    # --- Prob bars (position-aware labels) ---
    if is_defence:
        TIER_CLASS = {
            "Star (0.70+ PPG)":     "star",
            "Top 6 (0.40-0.70)":    "top6",
            "Bottom 6 (0.15-0.40)": "bottom6",
            "Fringe NHLer":          "minor",
            "Non-Pro":               "minor",
        }
        TIER_LABEL_MAP = {
            "Star (0.70+ PPG)":     "Top Pair (0.70+ PPG)",
            "Top 6 (0.40-0.70)":    "Top 4 (0.40–0.70)",
            "Bottom 6 (0.15-0.40)": "Depth D (0.15–0.40)",
            "Fringe NHLer":          "Fringe NHLer",
        }
    else:
        TIER_CLASS = {
            "Star (0.70+ PPG)":     "star",
            "Top 6 (0.40-0.70)":    "top6",
            "Bottom 6 (0.15-0.40)": "bottom6",
            "Fringe NHLer":          "minor",
            "Non-Pro":               "minor",
        }
        TIER_LABEL_MAP = {}

    prob_rows = ""
    for tier, prob in probs.items():
        if tier == "Non-Pro":
            continue
        cls   = TIER_CLASS.get(tier, "minor")
        label = TIER_LABEL_MAP.get(tier, tier) if is_defence else tier
        pct   = round(prob * 100)
        w     = max(2, round(prob * 100))
        prob_rows += (
            f'<div class="nhle-prob-row nhle-prob-row--{cls}">'
            f'<span class="nhle-prob-row__lbl">{html.escape(label)}</span>'
            f'<span class="nhle-prob-row__track"><span class="nhle-prob-row__fill" style="width:{w}%"></span></span>'
            f'<span class="nhle-prob-row__pct">{pct}%</span>'
            f'</div>'
        )


    # --- Comparable rows (position-aware role labels) ---
    if is_defence:
        ROLE_MAP = {
            "star":    ("Top Pair",  "role--star"),
            "top6":    ("Top 4",     "role--top6"),
            "bottom6": ("Depth D",   "role--bottom6"),
            "minor":   ("Minors",    "role--minor"),
            "fringe":  ("Fringe",    "role--minor"),
        }
    else:
        ROLE_MAP = {
            "star":    ("Star",    "role--star"),
            "top6":    ("Top 6",   "role--top6"),
            "bottom6": ("Bottom 6","role--bottom6"),
            "minor":   ("Minors",  "role--minor"),
            "fringe":  ("Fringe",  "role--minor"),
        }
    def _role(ppg: float, gp: int) -> tuple[str, str]:
        if gp < 40:          return ROLE_MAP["minor"]
        if ppg >= 0.70:      return ROLE_MAP["star"]
        if ppg >= 0.40:      return ROLE_MAP["top6"]
        if ppg >= 0.15:      return ROLE_MAP["bottom6"]
        return ROLE_MAP["fringe"]

    comp_rows = ""
    for c in comps[:5]:
        rlabel, rcls = _role(c["nhl_ppg"], c["nhl_gp"])
        comp_rows += (
            f'<div class="nhle-comp-row">'
            f'<span class="nhle-comp-row__name">{html.escape(c["name"])}</span>'
            f'<span class="nhle-comp-row__sim">{c["similarity"]:.0f}%</span>'
            f'<span class="nhle-comp-row__nhl">{c["nhl_ppg"]:.2f} PPG</span>'
            f'<span class="nhle-comp-row__role {rcls}">{rlabel}</span>'
            f'</div>'
        )


    return (
        f'<div class="nhle-wrap">'
        f'<div class="nhle-grid">'
        # Left: projected PPG
        f'<div class="nhle-proj">'
        f'<div class="nhle-proj__tag">NHL Projection · NHL Floor</div>'

        f'<div class="nhle-proj__ppg">{proj_ppg:.2f}</div>'
        f'<div class="nhle-proj__pts">est. {proj_pts} pts / 82 GP</div>'
        f'<div class="nhle-proj__factor">'
        f'{html.escape(league)} NHLe Factor<b>{factor:.3f}</b>'
        f'</div>'
        f'</div>'
        # Middle: outcome probabilities
        f'<div class="nhle-probs">'
        f'<div class="nhle-probs__tag">Outcome Probabilities</div>'
        f'{prob_rows}'
        f'</div>'
        # Right: comparable players
        f'<div class="nhle-comps">'
        f'<div class="nhle-comps__tag">Historical Comparables</div>'
        f'{comp_rows}'
        f'</div>'
        f'</div>'
        f'</div>'
    )


def shared_card_css(primary: str, accent: str, theme: dict[str, str], light: str) -> str:
    """CSS shared by the skater/prospect card and the goalie card, so both stay
    visually identical (fonts, pillar bars, highlight tiles, photo panel)."""
    return f""":root {{
  --primary: {primary};
  --accent: {accent};
  --primary-text: {theme["primary_text"]};
  --accent-text: {theme["accent_text"]};
  --elite-fill: {theme["elite_fill"]};
  --elite-fill-text: {theme["elite_fill_text"]};
  --elite-em: {theme["elite_em"]};
  --photo-overlay: {theme["photo_overlay"]};
  --team-light: {light};
  --paper: #f5f4f0;
  --ink: #12151c;
  --muted: #5c6573;
  --line: rgba(0,0,0,0.08);
  --bar: {primary};
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{
  font-family: 'Inter', system-ui, sans-serif;
  background: transparent;
  width: 1540px;
  margin: 0; padding: 0;
  -webkit-font-smoothing: antialiased;
}}
.card {{
  width: 1540px;
  display: flex;
  align-items: stretch;
  background: var(--paper);
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--line);
  box-shadow: 0 12px 40px rgba(0,0,0,0.12);
}}
/* Photo column */
.photo-col {{
  width: 380px;
  flex-shrink: 0;
  position: relative;
  background: var(--primary);
  overflow: hidden;
  align-self: stretch;
}}
.photo-col--pwhl-mug {{
  background: linear-gradient(168deg, var(--primary) 0%, color-mix(in srgb, var(--accent) 42%, var(--primary)) 48%, #0a0c10 100%);
}}
.photo-col--pwhl-mug .photo-col__bg {{
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 95% 70% at 50% 108%, color-mix(in srgb, var(--accent) 55%, transparent) 0%, transparent 62%),
    radial-gradient(circle at 18% 14%, color-mix(in srgb, var(--team-light) 28%, transparent) 0%, transparent 42%),
    linear-gradient(205deg, color-mix(in srgb, var(--primary) 88%, #000) 0%, transparent 72%);
  pointer-events: none;
}}
.photo-col--pwhl-mug .photo-col__pattern {{
  position: absolute;
  inset: 0;
  opacity: 0.16;
  background-image:
    repeating-linear-gradient(
      -28deg,
      transparent,
      transparent 16px,
      color-mix(in srgb, var(--team-light) 40%, transparent) 16px,
      color-mix(in srgb, var(--team-light) 40%, transparent) 18px
    );
  pointer-events: none;
}}
.photo-col--pwhl-mug .photo-col__glow {{
  position: absolute;
  left: 50%;
  bottom: 6%;
  width: 88%;
  height: 42%;
  transform: translateX(-50%);
  background: radial-gradient(ellipse at center, color-mix(in srgb, var(--accent) 70%, transparent) 0%, transparent 72%);
  filter: blur(14px);
  opacity: 0.85;
  pointer-events: none;
}}
.photo-col__logo-watermark {{
  position: absolute;
  left: 50%;
  top: 22%;
  width: 280px;
  height: 280px;
  transform: translate(-50%, -50%);
  background: linear-gradient(
    145deg,
    var(--primary) 0%,
    color-mix(in srgb, var(--accent) 60%, var(--primary)) 100%
  );
  -webkit-mask-size: contain;
  mask-size: contain;
  -webkit-mask-repeat: no-repeat;
  mask-repeat: no-repeat;
  -webkit-mask-position: center;
  mask-position: center;
  opacity: 0.75;
  pointer-events: none;
}}
.photo-col--pwhl-mug .photo-col__figure {{
  position: absolute;
  inset: 0;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  z-index: 2;
  overflow: hidden;
  pointer-events: none;
}}
.photo-col--pwhl-mug .photo.photo--mug {{
  position: relative;
  left: auto;
  bottom: auto;
  top: auto;
  right: auto;
  width: 112%;
  height: 100%;
  max-width: none;
  transform: none;
  object-fit: contain;
  object-position: center bottom;
  filter: drop-shadow(0 14px 32px rgba(0,0,0,0.48));
}}
.photo-col--pwhl-mug .photo-fade {{
  background: linear-gradient(105deg, transparent 48%, var(--paper) 94%);
}}
.photo-col--pwhl-mug .jersey-badge {{
  color: var(--team-light);
  text-shadow: 0 2px 16px rgba(0,0,0,0.65);
}}
.photo, .photo-placeholder {{
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}}
.photo--portrait {{
  object-position: center 6%;
}}
.photo--square {{
  object-position: center 10%;
}}
.photo--landscape {{
  object-position: center 32%;
}}
.photo-placeholder {{
  display: flex; align-items: center; justify-content: center;
  font-family: 'Russo One', sans-serif; font-size: 3rem; color: var(--photo-overlay);
  background: linear-gradient(160deg, var(--primary), #000);
}}
.photo-fade {{
  position: absolute; inset: 0;
  background: linear-gradient(105deg, transparent 55%, var(--paper) 92%);
  pointer-events: none;
}}
.jersey-badge {{
  position: absolute; left: 16px; bottom: 16px;
  font-family: 'Russo One', sans-serif; font-size: 2.4rem;
  color: var(--photo-overlay); text-shadow: 0 2px 12px rgba(0,0,0,0.5);
  line-height: 1;
}}
/* Content */
.content {{ flex: 1; display: flex; flex-direction: column; min-width: 0; }}
.top {{
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 14px;
  align-items: center;
  padding: 16px 20px 12px;
}}
.score-cluster {{
  display: flex;
  align-items: stretch;
  gap: 12px;
}}
.team-logo {{ width: 44px; height: 44px; object-fit: contain; }}
.name-block {{ min-width: 0; }}
h1 {{
  font-family: 'Russo One', sans-serif;
  font-size: 1.75rem; font-weight: 400;
  color: var(--ink); line-height: 1.05;
  letter-spacing: 0.02em;
}}
.vitals {{
  font-size: 0.68rem; color: var(--muted); margin-top: 4px;
  font-weight: 500; letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}}
.cap-box {{
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 12px;
  min-width: 132px;
  max-width: 210px;
  flex-shrink: 0;
}}
.cap-box__head {{
  font-size: 0.48rem; font-weight: 700; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--primary); margin-bottom: 6px;
}}
.cap-box__rows {{ display: flex; flex-direction: column; gap: 3px; }}
.cap-box__row {{
  display: flex; justify-content: space-between; align-items: baseline; gap: 10px;
}}
.cap-box__lbl {{
  font-size: 0.5rem; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--muted);
  flex-shrink: 0;
}}
.cap-box__val {{
  font-family: 'Russo One', sans-serif; font-size: 0.72rem;
  color: var(--ink); text-align: right;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}}
.cap-box__val--wrap {{
  white-space: normal;
  line-height: 1.2;
  font-size: 0.58rem;
  letter-spacing: 0;
}}
.cap-box__row--accent .cap-box__val {{ color: #1a5c8a; }}
.hero-block {{ display: flex; align-items: stretch; gap: 0; }}
.gs-hero {{
  background: var(--elite-fill); color: var(--elite-fill-text);
  padding: 8px 18px; text-align: center;
  border-radius: 8px 0 0 8px;
  min-width: 88px;
}}
.gs-hero__val {{
  font-family: 'Russo One', sans-serif; font-size: 2.4rem; line-height: 1;
}}
.gs-hero__lbl {{
  font-size: 0.5rem; font-weight: 700; letter-spacing: 0.1em;
  text-transform: uppercase; margin-top: 2px;
}}
.sub-scores {{
  display: flex; flex-direction: column; justify-content: center;
  gap: 4px; padding: 8px 14px;
  background: #fff; border: 2px solid var(--accent);
  border-left: none; border-radius: 0 8px 8px 0;
}}
.sub-scores div {{
  font-family: 'Russo One', sans-serif; font-size: 0.95rem; color: var(--ink);
  white-space: nowrap;
}}
.sub-scores em {{
  font-style: normal;
}}
.sub-scores em.pct-elite {{ color: var(--elite-em); }}
.sub-scores em.pct-strong {{ color: var(--primary); }}
.sub-scores em.pct-weak {{ color: #b44; }}
.sub-scores span {{ color: var(--muted); font-family: Inter; font-size: 0.55rem;
  font-weight: 600; letter-spacing: 0.08em; margin-right: 4px; }}
.ctx-box {{
  text-align: center; font-size: 0.62rem; color: var(--muted);
  line-height: 1.6;
  display: flex; flex-direction: column; justify-content: center; align-items: center;
  min-width: 56px;
}}

.ctx-box b {{
  font-family: 'Russo One', sans-serif; font-size: 1rem;
  color: var(--ink); margin-left: 4px;
}}
.ribbon {{
  height: 4px;
  background: linear-gradient(90deg, var(--primary), var(--accent));
}}
.main-grid {{
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 0;
  flex: 1;
  align-items: stretch;
  border-bottom: 1px solid var(--line);
}}
.pillars-wrap {{
  display: flex; flex-direction: column; min-height: 100%;
  border-right: 1px solid var(--line);
}}
.section-tag {{
  font-size: 0.52rem; font-weight: 700; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--muted);
  padding: 10px 18px 0;
}}
.section-tag span {{ color: var(--primary); font-weight: 700; }}
.pillars {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0;
  padding: 8px 18px 16px;
  flex: 1;
  align-items: stretch;
}}
.pillar {{
  padding: 0 14px; border-right: 1px solid var(--line);
  display: flex; flex-direction: column; height: 100%;
}}
.pillar:nth-child(2) {{ background: rgba(0,0,0,0.015); border-radius: 6px; }}
.pillar:last-child {{ border-right: none; }}
.pillar__head {{
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 10px; padding-bottom: 6px; flex-shrink: 0;
  border-bottom: 2px solid var(--primary);
}}
.pillar__rows {{
  flex: 1;
  display: flex; flex-direction: column; justify-content: space-between;
  padding: 6px 0 4px;
}}
.pillar__title {{
  font-size: 0.58rem; font-weight: 700; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--primary);
}}
.pillar__avg {{
  font-family: 'Russo One', sans-serif; font-size: 1.1rem; color: var(--ink);
}}
.pillar__avg.pct-elite {{ color: var(--elite-em); }}
.pillar__avg.pct-weak {{ color: #b44; }}
.bar-row {{
  display: grid;
  grid-template-columns: 88px 1fr 26px;
  gap: 8px; align-items: center;
  padding: 5px 0;
}}
.bar-row__lbl {{
  font-size: 0.52rem; font-weight: 500; color: var(--muted);
  white-space: normal; line-height: 1.1;
  display: flex; align-items: center;
}}
.bar-row__track {{
  height: 8px; background: #e2e5ea; border-radius: 3px; overflow: hidden;
}}
.bar-row__fill {{
  display: block; height: 100%; border-radius: 3px;
  background: var(--bar);
}}
.bar-row.pct-elite .bar-row__fill {{ background: var(--elite-fill); }}
.bar-row.pct-strong .bar-row__fill {{ background: var(--primary); }}
.bar-row.pct-avg .bar-row__fill {{ background: #8a939e; }}
.bar-row.pct-weak .bar-row__fill {{ background: #c44; }}
.bar-row.pct-elite .bar-row__pct {{ color: var(--elite-em); }}
.bar-row.pct-weak .bar-row__pct {{ color: #b44; }}
.bar-row__pct {{
  font-family: 'Russo One', sans-serif; font-size: 0.72rem;
  text-align: right; color: var(--ink);
}}
.shot-wrap {{
  padding: 14px 16px; background: #fff;
  display: flex; flex-direction: column;
  border-top: 3px solid var(--primary);
}}
.shot-map-panel {{ display: flex; flex-direction: column; gap: 6px; flex: 1; justify-content: space-between; }}
.shot-map-header {{ display: flex; justify-content: space-between; align-items: baseline; }}
.shot-map-title {{
  font-family: 'Russo One', sans-serif; font-size: 0.65rem; color: var(--ink);
}}
.shot-map-stats {{ display: flex; gap: 8px; }}
.shot-map-stats b {{ font-family: 'Russo One', sans-serif; font-size: 0.78rem; color: var(--primary); }}
.shot-map-stats span {{ font-size: 0.46rem; text-transform: uppercase; color: var(--muted); }}
.shot-map-sub {{ display: block; font-size: 0.48rem; color: var(--muted); max-width: 240px; line-height: 1.25; }}
.shot-map-canvas {{ border-radius: 8px; overflow: hidden; border: 1px solid var(--line); }}
.shot-map-svg {{ width: 100%; height: auto; display: block; }}
.shot-map-footer {{ font-size: 0.48rem; color: var(--muted); display: flex; gap: 10px; align-items: center; }}
.legend-dot {{
  width: 6px; height: 6px; border-radius: 50%; display: inline-block;
  margin-right: 2px;
}}
.legend-dot--shot {{
  background: var(--primary); opacity: 0.65; border: 1px solid #fff;
}}
.legend-dot--goal {{
  background: var(--elite-fill); border: 1px solid rgba(255,255,255,0.35);
}}
/* Highlights */
.hi-band {{
  background: #fff;
  border-bottom: 1px solid var(--line);
  padding: 10px 20px 14px;
}}
.hi-band .section-tag {{ padding: 0 0 8px; }}
.highlights {{
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 8px;
}}
.hi-tile {{
  text-align: center; padding: 10px 6px; border-radius: 8px;
  border: 1px solid rgba(0,0,0,0.06);
}}
.hi-tile--elite {{
  box-shadow: 0 2px 10px rgba(0,0,0,0.08);
  border-color: rgba(0,0,0,0.1);
}}
.hi-tile__lbl {{
  font-size: 0.48rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.04em; opacity: 0.85; line-height: 1.2;
}}
.hi-tile__val {{
  font-family: 'Russo One', sans-serif; font-size: 1.1rem;
  line-height: 1.15; margin-top: 4px;
}}
/* Rates */
.rates-wrap {{
  background: #fafaf8;
  border-top: 1px solid var(--line);
  padding: 10px 20px 14px;
}}
.rates-wrap .section-tag {{ padding: 0 0 8px; }}
.rates {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0;
  align-items: stretch;
}}
.rate-col {{
  padding: 0 18px; border-right: 1px solid var(--line);
  display: flex; flex-direction: column;
  min-height: 100%;
}}
.rate-col:last-child {{ border-right: none; }}
.rate-col:first-child {{ padding-left: 0; }}
.rate-col__title {{
  font-size: 0.56rem; font-weight: 700; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--primary); margin-bottom: 8px;
  flex-shrink: 0;
}}
.rate-col__rows {{
  flex: 1;
  display: grid;
  grid-template-rows: repeat(6, minmax(24px, auto));
  gap: 0;
  align-content: start;
}}
.rate-row {{
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px; align-items: center;
  padding: 3px 0;
  border-bottom: 1px solid rgba(0,0,0,0.04);
  min-height: 24px;
}}
.rate-row:last-child {{ border-bottom: none; }}
.rate-row__lbl {{ font-size: 0.58rem; font-weight: 500; color: var(--muted); }}
.rate-row__val {{
  font-family: 'Russo One', sans-serif; font-size: 0.8rem;
  color: var(--ink); white-space: nowrap; text-align: right; min-width: 44px;
}}
.rate-row--neg .rate-row__val {{ color: #b44; }}
.rate-row--na .rate-row__val {{ color: #9ca3af; font-family: inherit; font-weight: 500; }}
.data-context {{
  display: flex; justify-content: flex-end; align-items: center;
  padding: 8px 20px 10px;
  font-size: 0.58rem; color: var(--muted);
  border-top: 1px solid var(--line);
  background: #fff;
}}
.data-context--minimal {{ justify-content: flex-end; }}
.data-context__item {{ display: flex; align-items: center; gap: 8px; }}
.data-label {{
  font-size: 0.5rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--primary);
  background: rgba(0,0,0,0.04); padding: 3px 7px; border-radius: 4px;
}}
.gs-hero__sub {{
  font-size: 0.52rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--elite-fill-text);
  opacity: 0.85;
  margin-top: 2px;
}}
/* NHLe Projection Panel (prospect cards only) */
.nhle-wrap {{
  display: flex; flex-direction: column;
  height: 180px;
  border-top: 1px solid var(--line);
  background: #fafaf8;
}}
.nhle-grid {{
  display: grid;
  grid-template-columns: 280px 1fr 340px;
  gap: 0;
  height: 100%;
  align-items: stretch;
}}
.nhle-proj {{
  padding: 12px 20px;
  display: flex; flex-direction: column; justify-content: center;
  border-right: 1px solid var(--line);
  background: #fff;
}}
.nhle-proj__tag {{
  font-size: 0.48rem; font-weight: 700; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--primary); margin-bottom: 10px;
}}
.nhle-proj__ppg {{
  font-family: 'Russo One', sans-serif; font-size: 2.8rem;
  color: var(--ink); line-height: 1;
}}
.nhle-proj__pts {{
  font-size: 0.6rem; font-weight: 600; color: var(--muted);
  margin-top: 4px; letter-spacing: 0.04em;
}}
.nhle-proj__factor {{
  margin-top: 10px; padding-top: 8px;
  border-top: 1px solid var(--line);
  font-size: 0.52rem; color: var(--muted); font-weight: 500;
}}
.nhle-proj__factor b {{
  font-family: 'Russo One', sans-serif; font-size: 0.78rem; color: var(--ink);
  margin-left: 4px;
}}
.nhle-probs {{
  padding: 14px 18px;
  display: flex; flex-direction: column; justify-content: center; gap: 7px;
  border-right: 1px solid var(--line);
}}
.nhle-probs__tag {{
  font-size: 0.48rem; font-weight: 700; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--primary); margin-bottom: 6px;
}}
.nhle-prob-row {{
  display: grid; grid-template-columns: 130px 1fr 36px;
  gap: 8px; align-items: center;
}}
.nhle-prob-row__lbl {{
  font-size: 0.56rem; font-weight: 500; color: var(--muted);
  white-space: nowrap;
}}
.nhle-prob-row__track {{
  height: 7px; background: #e2e5ea; border-radius: 3px; overflow: hidden;
}}
.nhle-prob-row__fill {{
  display: block; height: 100%; border-radius: 3px;
  background: var(--primary); transition: width 0.3s;
}}
.nhle-prob-row--star .nhle-prob-row__fill {{ background: var(--elite-fill); }}
.nhle-prob-row--top6 .nhle-prob-row__fill {{ background: var(--primary); }}
.nhle-prob-row--bottom6 .nhle-prob-row__fill {{ background: #8a939e; }}
.nhle-prob-row--minor .nhle-prob-row__fill {{ background: #c0c5cc; }}
.nhle-prob-row__pct {{
  font-family: 'Russo One', sans-serif; font-size: 0.72rem;
  color: var(--ink); text-align: right;
}}
.nhle-comps {{
  padding: 14px 18px;
  display: flex; flex-direction: column; justify-content: center; gap: 0;
  background: #fafaf8;
}}
.nhle-comps__tag {{
  font-size: 0.48rem; font-weight: 700; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--primary); margin-bottom: 8px;
}}
.nhle-comp-row {{
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 5px 0;
  border-bottom: 1px solid rgba(0,0,0,0.04);
}}
.nhle-comp-row:last-child {{ border-bottom: none; }}
.nhle-comp-row__name {{
  font-size: 0.62rem; font-weight: 600; color: var(--ink);
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.nhle-comp-row__sim {{
  font-size: 0.52rem; color: var(--muted); margin-left: 6px; white-space: nowrap;
}}
.nhle-comp-row__nhl {{
  font-family: 'Russo One', sans-serif; font-size: 0.68rem; color: var(--ink);
  white-space: nowrap; margin-left: 10px; min-width: 80px; text-align: right;
}}
.nhle-comp-row__role {{
  font-size: 0.46rem; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; padding: 2px 5px; border-radius: 3px;
  margin-left: 6px; white-space: nowrap;
}}
.role--star {{ background: var(--elite-fill); color: var(--elite-fill-text); }}
.role--top6 {{ background: color-mix(in srgb, var(--primary) 18%, #fff); color: var(--primary); }}
.role--bottom6 {{ background: #f0f2f5; color: #5c6573; }}
.role--minor {{ background: #fae8e8; color: #6b3030; }}

.card--pwhl .ribbon {{
  background: linear-gradient(90deg, var(--primary) 0%, color-mix(in srgb, var(--accent) 55%, var(--primary)) 100%);
}}
.card--pwhl .section-tag span {{
  color: color-mix(in srgb, var(--primary) 72%, var(--muted));
}}
.data-context strong {{ color: var(--ink); font-weight: 600; }}
"""


def render_player_card_html(profile: dict[str, Any]) -> str:
    bio = profile["bio"]
    league = (profile.get("league") or bio.get("league") or "nhl").lower()
    colors = get_team_colors(str(bio.get("team") or ""), league=league)
    if not colors.get("primary"):
        colors = profile.get("colors") or colors
    league_cfg = LEAGUES.get(league, LEAGUES["nhl"])
    a3z = profile.get("a3z") or {}
    pbp = profile.get("pbp") or {}
    games_ctx = profile.get("games") or {}
    per_game = pbp.get("per_game") or {}
    sections = a3z.get("sections") or {}
    pbp_only = not league_cfg.uses_a3z
    has_a3z = bool((profile.get("sources") or {}).get("a3z")) and not pbp_only

    pbp_skated = games_ctx.get("pbp_skated_games", pbp.get("games_played", 0))
    pbp_team_games = games_ctx.get("pbp_team_games", pbp.get("games", 0))
    a3z_games = games_ctx.get("a3z_games", a3z.get("games", "—"))
    season = html.escape(str(a3z.get("season") or games_ctx.get("a3z_season") or league_cfg.default_season))

    primary = colors["primary"]
    accent = colors["accent"]
    light = colors.get("light", "#f1f5f9")
    theme = theme_text_vars(primary, accent)
    team_name = team_full_name(league, bio["team"])
    toi = a3z.get("toi_5v5")
    toi_disp = f"{toi:.0f} min" if isinstance(toi, (int, float)) else "—"
    if pbp_only:
        if league == "prospect":
            pillar_tag = "Team rates · <span>per game · bar width = roster %ile</span>"
        else:
            pillar_tag = "Team percentiles · <span>per game</span>"

        pct_footer = ""
        snapshot_tag = "Team snapshot · <span>percentile vs roster</span>"
        off_lbl = "OFF %"
        def_lbl = "DEF %"
    else:
        pillar_tag = "League percentiles · <span>per 60 · A3Z</span>"
        pct_footer = f"<span>{toi_disp} 5v5 Time on Ice</span>" if toi_disp != "—" else "<span>5v5 Time on Ice</span>"
        snapshot_tag = "Profile snapshot · <span>percentile rank</span>"
        off_lbl = "OFF"
        def_lbl = "DEF"

    hero = (a3z or {}).get("microstat_game_score") or _metric_lookup(sections, "microstat_game_score") or {}
    offense = _metric_lookup(sections, OFFENSE_GS_KEY) or {}
    defense = (
        _metric_lookup(sections, DEFENSE_GS_KEY)
        or _metric_lookup(sections, "defense_composite")
        or _composite_gs_metric(sections, DEFENSE_GS_KEYS)
    )
    gs_sub = ""
    if pbp_only:
        hero_val = hero.get("value")
        gs_disp = (
            f"{float(hero_val):.1f}"
            if isinstance(hero_val, (int, float))
            else "—"
        )
        gs_lbl = "Game Score"
        hero_pct = _pct_num(hero.get("percentile"))
        if hero_pct is not None:
            gs_sub = f"{hero_pct}th %ile on team"
    elif has_a3z:
        hero_val = hero.get("value")
        gs_disp = (
            f"{float(hero_val):.1f}"
            if isinstance(hero_val, (int, float))
            else "—"
        )
        gs_lbl = "Game Score"
    else:
        gs_disp = "—" if _pct_num(hero.get("percentile")) is None else str(_pct_num(hero.get("percentile")))
        gs_lbl = "Percentile"
    if offense.get("percentile") is not None:
        off_disp = f"{_pct_num(offense.get('percentile'))}%"
    elif offense.get("value") is not None and isinstance(offense["value"], (int, float)):
        off_disp = f"{offense['value']:.1f}"
    else:
        off_disp = "—"

    if defense.get("percentile") is not None:
        def_disp = f"{_pct_num(defense.get('percentile'))}%"
    elif defense.get("value") is not None and isinstance(defense["value"], (int, float)):
        def_disp = f"{defense['value']:.1f}"
    else:
        def_disp = "—"

    off_tier = _pct_class(offense.get("percentile")) if offense.get("percentile") is not None else "bar-row--star"
    def_tier = _pct_class(defense.get("percentile")) if defense.get("percentile") is not None else "bar-row--star"

    qoc = _metric_lookup(sections, "qoc")
    qot = _metric_lookup(sections, "qot")
    qoc_disp = "—" if not qoc or qoc.get("percentile") is None else f"{int(qoc['percentile'] * 100)}%"
    qot_disp = "—" if not qot or qot.get("percentile") is None else f"{int(qot['percentile'] * 100)}%"

    if league == "prospect":
        draft_str = bio.get("draft_info", "2026 Draft Prospect")
        amateur_club = bio.get("amateur_club", "—")
        undrafted = bool(bio.get("undrafted")) or (
            bio.get("draft_round") is None
            and bio.get("draft_overall") is None
            and "eligible" in str(bio.get("draft_info") or "").lower()
        )
        if undrafted:
            draft_year = bio.get("draft_year") or "—"
            chl_line = bio.get("chl_draft_line") or "—"
            clubs = [str(c) for c in (bio.get("career_clubs") or []) if c]
            season_clubs = bio.get("season_clubs") or []
            pbp_by_club = (profile.get("sources") or {}).get("pbp_by_club") or {}
            if season_clubs:
                # This-season dual roster first (Pats + Pat Canadians etc.)
                bits = []
                for row in season_clubs:
                    t = str(row.get("team") or "")
                    gp = row.get("gp")
                    if not t:
                        continue
                    short = (
                        t.replace(" Hockey Academy", " HA")
                        .replace(" U18 AAA", "")
                        .replace(" U15 AA", "")
                        .replace(" 18U", "")
                        .replace(" U15", "")
                        .replace(" U14", "")
                    )
                    # Prefer EP/season GP; annotate whenever PBP sample diverges.
                    pbp_gp = None
                    for ht, st in pbp_by_club.items():
                        tl, hl = t.lower(), ht.lower()
                        if tl == hl or tl in hl or hl in tl:
                            pbp_gp = int(st.get("gp") or 0) or None
                            break
                    if pbp_gp is None and len(season_clubs) == 1:
                        pbp_gp = int(
                            (profile.get("sources") or {}).get("pbp_sample_games")
                            or (pbp or {}).get("games_played")
                            or 0
                        ) or None
                    if gp and pbp_gp and int(gp) > pbp_gp + 1:
                        bits.append(f"{short} ({pbp_gp}/{gp}GP PBP)")
                    elif gp and pbp_gp and int(pbp_gp) > int(gp) + 1:
                        bits.append(f"{short} ({gp}GP · {pbp_gp}GP PBP)")
                    elif gp:
                        bits.append(f"{short} ({gp}GP)")
                    elif pbp_gp:
                        bits.append(f"{short} ({pbp_gp}GP PBP)")
                    else:
                        bits.append(short)
                clubs_disp = " · ".join(bits[:3])
                if len(bits) > 3:
                    clubs_disp += f" · +{len(bits) - 3}"
            elif clubs:
                current = str(amateur_club or clubs[0])
                priors = [c for c in clubs if c != current]
                clubs_disp = f"{current} · +{len(priors)} prior" if priors else current
            else:
                clubs_disp = "—"
            ep_tot = bio.get("ep_season_totals") or {}
            ep_row = ""
            if bio.get("dual_roster") and ep_tot.get("games_played"):
                eg = int(ep_tot.get("goals") or 0)
                ea = int(ep_tot.get("assists") or 0)
                ep = int(ep_tot.get("points") or (eg + ea))
                egp = int(ep_tot.get("games_played") or 0)
                ep_row = (
                    f'<div class="cap-box__row"><span class="cap-box__lbl">All clubs</span>'
                    f'<span class="cap-box__val">{egp}GP · {eg}G-{ea}A-{ep}P</span></div>'
                )
            cap_html = (
                f'<div class="cap-box">'
                f'<div class="cap-box__head">Draft Status</div>'
                f'<div class="cap-box__rows">'
                f'<div class="cap-box__row"><span class="cap-box__lbl">NHL</span><span class="cap-box__val">Undrafted · {html.escape(str(draft_year))}</span></div>'
                f'<div class="cap-box__row"><span class="cap-box__lbl">CHL</span><span class="cap-box__val cap-box__val--wrap">{html.escape(str(chl_line))}</span></div>'
                f'<div class="cap-box__row cap-box__row--accent"><span class="cap-box__lbl">\'25-26</span><span class="cap-box__val cap-box__val--wrap">{html.escape(clubs_disp)}</span></div>'
                f'{ep_row}'
                f'</div></div>'
            )
        else:
            round_val = bio.get("draft_round", "—")
            pick_val = bio.get("draft_pick", "—")
            overall_val = bio.get("draft_overall", "—")
            cap_html = (
                f'<div class="cap-box">'
                f'<div class="cap-box__head">Draft Info</div>'
                f'<div class="cap-box__rows">'
                f'<div class="cap-box__row"><span class="cap-box__lbl">Amateur Club</span><span class="cap-box__val">{html.escape(str(amateur_club))}</span></div>'
                f'<div class="cap-box__row"><span class="cap-box__lbl">Selection</span><span class="cap-box__val">Rd {round_val}, Pick {pick_val}</span></div>'
                f'<div class="cap-box__row cap-box__row--accent"><span class="cap-box__lbl">Overall</span><span class="cap-box__val">#{overall_val} Overall</span></div>'
                f'</div></div>'
            )
    else:
        cap_html = _cap_box_html(profile.get("cap")) if league_cfg.uses_cap else ""

    pillars = []
    pillar_bars = PWHL_PILLAR_BARS if pbp_only else PILLAR_BARS
    # PBP-only leagues (PWHL, junior/prospect without A3Z) show rates so pillar
    # "Shots" matches the shot-map total, not a bare percentile integer.
    show_rates = bool(pbp_only) or league == "prospect"
    for pillar in pillar_bars:
        rows = "".join(
            _bar_row(lbl, _metric_lookup(sections, key), prefer_value=show_rates)
            for key, lbl in pillar["keys"]
        )
        pillars.append(_pillar_col(pillar["title"], _pillar_avg(sections, pillar["keys"]), rows))

    highlights = []
    highlight_tiles = PWHL_HIGHLIGHT_TILES if pbp_only else HIGHLIGHT_TILES
    for key, label in highlight_tiles:
        if key == "defense_composite":
            m = defense
        else:
            m = _metric_lookup(sections, key)
        highlights.append(_highlight_tile(label, m, primary, accent))

    rate_groups = []
    fo_pct = _faceoff_win_pct(per_game)
    for group in PBP_RATE_GROUPS:
        chips = []
        for m in group["metrics"]:
            disp = _rate_metric_value(per_game, m, fo_pct)
            na = " rate-row--na" if disp == "—" else ""
            chips.append(_rate_row(m["label"], disp, negative=m.get("negative", False), extra_class=na))
        rate_groups.append(
            f'<div class="rate-col"><div class="rate-col__title">{html.escape(group["title"])}</div>'
            f'<div class="rate-col__rows">{"".join(chips)}</div></div>'
        )

    photo_kind = bio.get("card_photo_kind") or "mug"
    photo_raw = bio.get("card_photo_url") or bio.get("headshot_url") or bio.get("hero_image_url") or ""
    if league == "pwhl" and not photo_raw:
        photo_raw = str(bio.get("headshot_url") or "")
        photo_kind = "mug"
    if not photo_raw and bio.get("player_id") and str(bio.get("league") or "").lower() != "pwhl":
        from .nhl_bio import _season_mug_url

        tri = str(bio.get("team") or "NHL").upper()
        photo_raw = _season_mug_url(tri, int(bio["player_id"]))
        photo_kind = "mug"

    photo_w = bio.get("photo_width")
    photo_h = bio.get("photo_height")
    if photo_raw:
        photo_src, probed_w, probed_h = embed_photo(str(photo_raw))
        photo_w = photo_w or probed_w
        photo_h = photo_h or probed_h
        if not photo_w or not photo_h:
            photo_w, photo_h = photo_dimensions(str(photo_raw))
    else:
        photo_src = ""

    aspect_cls, obj_pos = photo_frame(
        int(photo_w) if photo_w else None,
        int(photo_h) if photo_h else None,
        kind=str(photo_kind),
    )
    pwhl_mug = league == "pwhl" and photo_kind == "mug" and photo_src
    if pwhl_mug:
        photo_style = ""
        aspect_cls = "photo--mug"
    else:
        photo_style = html.escape(f"object-position:{obj_pos}")

    logo_raw = bio.get("team_logo_png_url") or bio.get("team_logo_url") or ""
    if logo_raw:
        logo_src, _, _ = embed_photo(str(logo_raw))
    else:
        logo_src = ""
    logo = html.escape(logo_src)
    name_text = profile.get("name") or bio.get("name") or "Unknown Player"
    country = bio.get("country")
    if country and country in FLAG_MAP:
        name = html.escape(f"{FLAG_MAP[country]} {name_text}")
    else:
        name = html.escape(name_text)
    pos = html.escape(bio.get("position", ""))
    tri = html.escape(bio["team"])
    shoots = html.escape(bio.get("shoots") or "—")
    height = html.escape(bio.get("height") or "—")
    if league == "pwhl":
        vitals_line = f"{pos} · {html.escape(team_name)} · {season} · {height} · {html.escape(format_shoots_label(bio))}"
    elif league == "prospect":
        weight = bio.get("weight_lbs")
        weight_disp = f"{weight} lbs" if weight else "—"
        draft_str = bio.get("draft_info", "2026 Draft Prospect")
        
        nhle_dict = profile.get("nhle") or {}
        ep_tot = bio.get("ep_season_totals") or {}
        # Season (EP) totals in vitals when available; always surface the PBP
        # sample that drives the shot map when it diverges (thin or extra GP).
        pbp_gp = int((pbp or {}).get("games_played") or 0)
        pbp_g = int((pbp or {}).get("goals") or 0)
        pbp_a = int((pbp or {}).get("assists") or 0)
        pbp_p = int((pbp or {}).get("points") or (pbp_g + pbp_a))
        pbp_sh = int((pbp or {}).get("shot_count") or 0)
        season_tag = ""
        if ep_tot.get("games_played"):
            gp = int(ep_tot.get("games_played") or 0)
            goals = int(ep_tot.get("goals") or 0)
            assists = int(ep_tot.get("assists") or 0)
            pts = int(ep_tot.get("points") or (goals + assists))
            if pbp_gp and abs(gp - pbp_gp) > 1:
                season_tag = (
                    f" · season · PBP {pbp_gp}GP {pbp_sh}sht/{pbp_g}G"
                )
            else:
                season_tag = " · season"
        elif nhle_dict.get("recent_gp") is not None:
            gp = nhle_dict.get("recent_gp", 0)
            goals = nhle_dict.get("recent_goals", 0)
            assists = nhle_dict.get("recent_assists", 0)
            pts = nhle_dict.get("recent_pts", 0)
        else:
            goals = pbp_g
            assists = pbp_a
            pts = pbp_p
            gp = pbp_gp
        style_comps_list = nhle_dict.get("style_comparables", [])
        style_comp_html = ""
        if style_comps_list:
            style_comp = style_comps_list[0].get("name", "")
            if style_comp:
                comp_color = accent
                if comp_color.upper() in ("#FFFFFF", "#FFF", "WHITE", "#FFFFFFFF"):
                    comp_color = primary
                style_comp_html = f" · Style Comp: <span style='color: {html.escape(comp_color)}; font-weight: 700;'>{html.escape(style_comp)}</span>"

        vitals_line = (
            f"{pos} · {html.escape(team_name)} · "
            f"{height} · {html.escape(weight_disp)} · Shoots {shoots}"
            f" · {gp} GP · {goals}G-{assists}A-{pts}P{season_tag}"
            f"{style_comp_html}"
        )

    else:
        weight = bio.get("weight_lbs")
        weight_disp = f"{weight} lbs" if weight else "—"
        vitals_line = (
            f"{pos} · {html.escape(team_name)} · {season} · "
            f"{height} · {html.escape(weight_disp)} · Shoots {shoots}"
        )
    number = bio.get("sweater_number")

    if pwhl_mug:
        mug_layers = [
            '<div class="photo-col__bg" aria-hidden="true"></div>',
            '<div class="photo-col__pattern" aria-hidden="true"></div>',
            '<div class="photo-col__glow" aria-hidden="true"></div>',
        ]
        if logo_src:
            logo_mask = html.escape(logo_src).replace("'", "%27")
            mug_layers.append(
                f'<div class="photo-col__logo-watermark" style="-webkit-mask-image:url(\'{logo_mask}\');mask-image:url(\'{logo_mask}\');"></div>'
            )
        mug_layers.append(
            '<div class="photo-col__figure" aria-hidden="false">'
            f'<img class="photo {aspect_cls}" src="{html.escape(photo_src)}" '
            f'alt="{name}" decoding="sync" fetchpriority="high"></div>'
        )
        photo = "".join(mug_layers)
        photo_col_class = "photo-col photo-col--pwhl-mug"
    else:
        photo = (
            f'<img class="photo {aspect_cls}" style="{photo_style}" src="{html.escape(photo_src)}" '
            f'alt="{name}" decoding="sync" fetchpriority="high">'
            if photo_src
            else f'<div class="photo-placeholder">{html.escape(bio["name"][:2].upper())}</div>'
        )
        photo_col_class = "photo-col"
    jersey = (
        f'<div class="jersey-badge">{html.escape(str(number))}</div>'
        if number is not None else ""
    )

    # Prefer explicit shot_count only — never reconstruct from rounded rates.
    _shots_hdr = (pbp or {}).get("shot_count") if pbp else None
    _map_sub = ""
    _src = profile.get("sources") or {}
    _gbt = _src.get("games_by_team") or {}
    _pbp_gp = int(
        (pbp or {}).get("games_played")
        or sum(int(v or 0) for v in _gbt.values())
        or 0
    )
    _ep_gp = int((bio.get("ep_season_totals") or {}).get("games_played") or 0)
    if _pbp_gp:
        _map_sub = f"Card generated from {_pbp_gp} games of PBP"
        if _ep_gp and abs(_ep_gp - _pbp_gp) > 1:
            _map_sub += f" · season {_ep_gp} GP"
    shot_html = render_shot_map_html(
        pbp.get("shots") or [],
        primary=primary,
        accent=accent,
        player_name=_map_sub,
        total_shots=_shots_hdr,
        # Pass None so map goals always equal plotted goal dots (self-consistent).
        total_goals=None,
        total_xg=pbp.get("xg_total") if pbp else None,
    )

    gs_sub_html = (
        f'<div class="gs-hero__sub">{html.escape(gs_sub)}</div>' if gs_sub else ""
    )

    nhle = profile.get("nhle") or {}
    # Pass position context into nhle dict so _nhle_panel_html can use it
    if nhle and league == "prospect":
        nhle = dict(nhle)
        nhle["is_defence"] = str(bio.get("position") or "").upper() in ("D", "LD", "RD", "DEF")
    nhle_panel = _nhle_panel_html(nhle) if league == "prospect" and nhle else ""


    card_class = "card card--pwhl" if pbp_only else "card"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Russo+One&display=swap" rel="stylesheet">
<style>
{shared_card_css(primary, accent, theme, light)}
</style>
</head>
<body>
<article class="{card_class}">
  <div class="{photo_col_class}">
    {photo}
    <div class="photo-fade"></div>
    {jersey}
  </div>
  <div class="content">
    <header class="top">
      <img class="team-logo" src="{logo}" alt="{tri}">
      <div class="name-block">
        <h1>{name}</h1>
        <div class="vitals">
          {vitals_line}
        </div>
      </div>
      <div class="score-cluster">
      {cap_html}
      <div class="hero-block">
        <div class="gs-hero">
          <div class="gs-hero__val">{html.escape(gs_disp)}</div>
          <div class="gs-hero__lbl">{html.escape(gs_lbl)}</div>
          {gs_sub_html}
        </div>
        <div class="sub-scores">
          <div><span>{html.escape(off_lbl)}</span><em class="{off_tier}">{html.escape(off_disp)}</em></div>
          <div><span>{html.escape(def_lbl)}</span><em class="{def_tier}">{html.escape(def_disp)}</em></div>
        </div>
      </div>
      <div class="ctx-box">
        <div>QOC<b>{html.escape(qoc_disp)}</b></div>
        <div>QOT<b>{html.escape(qot_disp)}</b></div>
      </div>
      </div>
    </header>
    <div class="ribbon"></div>
    <div class="main-grid">
      <div class="pillars-wrap">
        <div class="section-tag">{pillar_tag}</div>
        <div class="pillars">{"".join(pillars)}</div>
      </div>
      <div class="shot-wrap">{shot_html}</div>
    </div>
    <div class="hi-band">
      <div class="section-tag">{snapshot_tag}</div>
      <div class="highlights">{"".join(highlights)}</div>
    </div>
    {nhle_panel}
    <div class="rates-wrap"><div class="rates">{"".join(rate_groups)}</div></div>
    {f'<div class="data-context data-context--minimal">{pct_footer}</div>' if pct_footer else ''}
  </div>
</article>
</body>
</html>"""


NHL_TEAM_NAME = {
    "PIT": "Pittsburgh Penguins",
    "TOR": "Toronto Maple Leafs",
    "BOS": "Boston Bruins",
    "MTL": "Montreal Canadiens",
    "EDM": "Edmonton Oilers",
    "COL": "Colorado Avalanche",
}


def write_player_card_html(profile: dict[str, Any], output: Path | str) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_player_card_html(profile), encoding="utf-8")
    return out


def render_player_card(profile: dict[str, Any], output: Path | str) -> Path:
    import tempfile

    from .png_export import html_to_png

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        html_path = Path(tmp.name)
    try:
        write_player_card_html(profile, html_path)
        return html_to_png(html_path, out)
    finally:
        html_path.unlink(missing_ok=True)


def write_player_card_json(profile: dict[str, Any], output: Path | str) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, indent=2, default=str), encoding="utf-8")
    return out
