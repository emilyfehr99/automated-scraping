"""Editorial landscape player cards — Athletic / AR Index / JFresh inspired."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import httpx

from .card_config import (
    DEFENSE_GS_KEYS,
    HIGHLIGHT_TILES,
    OFFENSE_GS_KEY,
    PILLAR_BARS,
    PBP_RATE_GROUPS,
    format_stat,
)
from .disk_cache import photo_data_url, store_photo_data_url
from .leagues import LEAGUES, team_full_name
from .shot_map import render_shot_map_html


def prewarm_photo(url: str) -> str:
    """Download/cache hero photo so card render skips HTTP."""
    return _embed_photo_src(url)


def _embed_photo_src(url: str) -> str:
    """Inline full-resolution photo so Playwright exports native pixels."""
    if not url or url.startswith("data:"):
        return url
    cached = photo_data_url(url)
    if cached:
        return cached
    try:
        import base64

        resp = httpx.get(url, timeout=20.0, follow_redirects=True, headers={"User-Agent": "PlayerCards/1.0"})
        resp.raise_for_status()
        if len(resp.content) < 8_000:
            return url
        mime = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        encoded = base64.b64encode(resp.content).decode("ascii")
        data_url = f"data:{mime};base64,{encoded}"
        store_photo_data_url(url, data_url)
        return data_url
    except Exception:
        return url


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


def _metric_lookup(sections: dict, key: str) -> dict | None:
    for items in sections.values():
        for m in items:
            if m.get("key") == key:
                return m
    return None


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


def _jfresh_style(pct: float | None, accent: str) -> str:
    if pct is None:
        return "background:#eceff3;color:#6b7280"
    p = pct * 100
    if p >= 90:
        return f"background:{accent};color:#111"
    if p >= 78:
        return "background:#c5ddf5;color:#0f2847"
    if p >= 62:
        return "background:#e3eef9;color:#1a3a5c"
    if p >= 45:
        return "background:#f0f2f5;color:#3d4654"
    if p >= 30:
        return "background:#fae8e8;color:#6b3030"
    return "background:#f5d4d4;color:#5c2020"


def _bar_row(label: str, m: dict | None) -> str:
    pct = m.get("percentile") if m else None
    num = _pct_num(pct)
    disp = "—" if num is None else str(num)
    w = max(4, num) if num is not None else 0
    tier = _pct_class(pct)
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


def _highlight_tile(label: str, m: dict | None, accent: str) -> str:
    pct = m.get("percentile") if m else None
    disp = "—" if pct is None else str(int(pct * 100))
    style = _jfresh_style(pct, accent)
    elite = " hi-tile--elite" if pct is not None and pct * 100 >= 90 else ""
    return (
        f'<div class="hi-tile{elite}" style="{style}">'
        f'<div class="hi-tile__lbl">{html.escape(label)}</div>'
        f'<div class="hi-tile__val">{html.escape(disp)}</div></div>'
    )


def _rate_row(label: str, disp: str, *, negative: bool = False) -> str:
    cls = "rate-row"
    if negative:
        cls += " rate-row--neg"
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


def render_player_card_html(profile: dict[str, Any]) -> str:
    bio = profile["bio"]
    colors = profile["colors"]
    league = (profile.get("league") or bio.get("league") or "nhl").lower()
    league_cfg = LEAGUES.get(league, LEAGUES["nhl"])
    a3z = profile.get("a3z") or {}
    pbp = profile.get("pbp") or {}
    games_ctx = profile.get("games") or {}
    per_game = pbp.get("per_game") or {}
    sections = a3z.get("sections") or {}
    has_a3z = bool((profile.get("sources") or {}).get("a3z"))

    pbp_skated = games_ctx.get("pbp_skated_games", pbp.get("games_played", 0))
    pbp_team_games = games_ctx.get("pbp_team_games", pbp.get("games", 0))
    a3z_games = games_ctx.get("a3z_games", a3z.get("games", "—"))
    season = html.escape(str(a3z.get("season", "")))

    primary = colors["primary"]
    accent = colors["accent"]
    team_name = team_full_name(league, bio["team"])
    toi = a3z.get("toi_5v5")
    toi_disp = f"{toi:.0f} min" if isinstance(toi, (int, float)) else "—"
    pillar_tag = (
        "League percentiles · <span>per 60 · A3Z</span>"
        if has_a3z
        else "Team percentiles · <span>InStat PBP</span>"
    )
    pct_footer = (
        f'<span>A3Z · <strong>{a3z_games} GP</strong> · {toi_disp} 5v5 TOI</span>'
        if has_a3z
        else f'<span>InStat · <strong>{pbp_skated}</strong> GP skated</span>'
    )

    hero = (a3z or {}).get("microstat_game_score") or _metric_lookup(sections, "microstat_game_score") or {}
    offense = _metric_lookup(sections, OFFENSE_GS_KEY) or {}
    defense = _composite_gs_metric(sections, DEFENSE_GS_KEYS)
    gs_disp = "—" if _pct_num(hero.get("percentile")) is None else str(_pct_num(hero.get("percentile")))
    off_disp = "—" if _pct_num(offense.get("percentile")) is None else str(_pct_num(offense.get("percentile")))
    def_disp = "—" if _pct_num(defense.get("percentile")) is None else str(_pct_num(defense.get("percentile")))
    off_tier = _pct_class(offense.get("percentile"))
    def_tier = _pct_class(defense.get("percentile"))

    qoc = _metric_lookup(sections, "qoc")
    qot = _metric_lookup(sections, "qot")
    qoc_disp = "—" if not qoc or qoc.get("percentile") is None else str(int(qoc["percentile"] * 100))
    qot_disp = "—" if not qot or qot.get("percentile") is None else str(int(qot["percentile"] * 100))

    cap_html = _cap_box_html(profile.get("cap")) if league_cfg.uses_cap else ""

    pillars = []
    for pillar in PILLAR_BARS:
        rows = "".join(_bar_row(lbl, _metric_lookup(sections, key)) for key, lbl in pillar["keys"])
        pillars.append(_pillar_col(pillar["title"], _pillar_avg(sections, pillar["keys"]), rows))

    highlights = []
    for key, label in HIGHLIGHT_TILES:
        if key == "defense_composite":
            m = defense
        else:
            m = _metric_lookup(sections, key)
        highlights.append(_highlight_tile(label, m, accent))

    rate_groups = []
    fo_pct = _faceoff_win_pct(per_game)
    for group in PBP_RATE_GROUPS:
        chips = []
        for m in group["metrics"]:
            key = m["key"]
            if key == "_fo_win_pct":
                if fo_pct is None:
                    continue
                disp = f"{fo_pct:.0f}%"
            else:
                disp = format_stat(per_game.get(key), m.get("format", "compact"))
            if disp == "—":
                continue
            chips.append(_rate_row(m["label"], disp, negative=m.get("negative", False)))
        if chips:
            rate_groups.append(
                f'<div class="rate-col"><div class="rate-col__title">{html.escape(group["title"])}</div>'
                f'<div class="rate-col__rows">{"".join(chips)}</div></div>'
            )

    photo_kind = bio.get("card_photo_kind") or "mug"
    photo_raw = bio.get("card_photo_url") or bio.get("hero_image_url") or bio.get("headshot_url") or ""
    if not photo_raw and bio.get("player_id"):
        photo_raw = f"https://assets.nhle.com/mugs/actionshots/1296x729/{bio['player_id']}.jpg"
        photo_kind = "hero"
    photo_src = html.escape(_embed_photo_src(photo_raw))
    logo = html.escape(bio.get("team_logo_png_url") or bio.get("team_logo_url") or "")
    name = html.escape(bio["name"])
    pos = html.escape(bio.get("position", ""))
    tri = html.escape(bio["team"])
    shoots = html.escape(bio.get("shoots") or "—")
    height = html.escape(bio.get("height") or "—")
    weight = bio.get("weight_lbs")
    weight_disp = f"{weight} lbs" if weight else "—"
    number = bio.get("sweater_number")

    photo = (
        f'<img class="photo photo--{photo_kind}" src="{photo_src}" alt="{name}" decoding="sync" fetchpriority="high">'
        if photo_src
        else f'<div class="photo-placeholder">{html.escape(bio["name"][:2].upper())}</div>'
    )
    jersey = (
        f'<div class="jersey-badge">{html.escape(str(number))}</div>'
        if number is not None else ""
    )

    shot_html = render_shot_map_html(
        pbp.get("shots") or [],
        primary=primary,
        accent=accent,
        player_name="",
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Russo+One&display=swap" rel="stylesheet">
<style>
:root {{
  --primary: {primary};
  --accent: {accent};
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
  min-height: 100%;
}}
.photo, .photo-placeholder {{
  width: 100%;
  height: 100%;
  min-height: 560px;
  object-fit: cover;
  display: block;
}}
.photo--hero {{
  object-position: center 18%;
}}
.photo--mug {{
  object-position: center top;
}}
.photo-placeholder {{
  display: flex; align-items: center; justify-content: center;
  font-family: 'Russo One', sans-serif; font-size: 3rem; color: var(--accent);
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
  color: var(--accent); text-shadow: 0 2px 12px rgba(0,0,0,0.5);
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
}}
.cap-box {{
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 12px;
  min-width: 132px;
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
}}
.cap-box__val {{
  font-family: 'Russo One', sans-serif; font-size: 0.78rem;
  color: var(--ink); white-space: nowrap;
}}
.cap-box__row--accent .cap-box__val {{ color: #1a5c8a; }}
.hero-block {{ display: flex; align-items: stretch; gap: 0; }}
.gs-hero {{
  background: var(--accent); color: #111;
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
.sub-scores em.pct-elite {{ color: #9a7200; }}
.sub-scores em.pct-strong {{ color: var(--primary); }}
.sub-scores em.pct-weak {{ color: #b44; }}
.sub-scores span {{ color: var(--muted); font-family: Inter; font-size: 0.55rem;
  font-weight: 600; letter-spacing: 0.08em; margin-right: 4px; }}
.ctx-box {{
  text-align: right; font-size: 0.62rem; color: var(--muted);
  line-height: 1.6;
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
.pillar__avg.pct-elite {{ color: #9a7200; }}
.pillar__avg.pct-weak {{ color: #b44; }}
.bar-row {{
  display: grid;
  grid-template-columns: 76px 1fr 26px;
  gap: 8px; align-items: center;
  padding: 5px 0;
}}
.bar-row__lbl {{
  font-size: 0.58rem; font-weight: 500; color: var(--muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.bar-row__track {{
  height: 8px; background: #e2e5ea; border-radius: 3px; overflow: hidden;
}}
.bar-row__fill {{
  display: block; height: 100%; border-radius: 3px;
  background: var(--bar);
}}
.bar-row.pct-elite .bar-row__fill {{ background: var(--accent); }}
.bar-row.pct-strong .bar-row__fill {{ background: var(--primary); }}
.bar-row.pct-avg .bar-row__fill {{ background: #8a939e; }}
.bar-row.pct-weak .bar-row__fill {{ background: #c44; }}
.bar-row.pct-elite .bar-row__pct {{ color: #9a7200; }}
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
.shot-map-sub {{ display: none; }}
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
  background: var(--accent); border: 1px solid #333;
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
}}
.rate-col {{
  padding: 0 18px; border-right: 1px solid var(--line);
  display: flex; flex-direction: column;
}}
.rate-col:last-child {{ border-right: none; }}
.rate-col:first-child {{ padding-left: 0; }}
.rate-col__title {{
  font-size: 0.56rem; font-weight: 700; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--primary); margin-bottom: 8px;
}}
.rate-col__rows {{
  flex: 1;
  display: flex; flex-direction: column; justify-content: space-between;
}}
.rate-row {{
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px; align-items: baseline;
  padding: 4px 0;
  border-bottom: 1px solid rgba(0,0,0,0.04);
}}
.rate-row:last-child {{ border-bottom: none; }}
.rate-row__lbl {{ font-size: 0.58rem; font-weight: 500; color: var(--muted); }}
.rate-row__val {{
  font-family: 'Russo One', sans-serif; font-size: 0.8rem;
  color: var(--ink); white-space: nowrap; text-align: right; min-width: 44px;
}}
.rate-row--neg .rate-row__val {{ color: #b44; }}
.data-context {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 20px 12px;
  font-size: 0.58rem; color: var(--muted);
  border-top: 1px solid var(--line);
  background: #fff;
}}
.data-context__item {{ display: flex; align-items: center; gap: 8px; }}
.data-label {{
  font-size: 0.5rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--primary);
  background: rgba(0,0,0,0.04); padding: 3px 7px; border-radius: 4px;
}}
.data-context strong {{ color: var(--ink); font-weight: 600; }}
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
      <img class="team-logo" src="{logo}" alt="{tri}">
      <div class="name-block">
        <h1>{name}</h1>
        <div class="vitals">
          {pos} · {html.escape(team_name)} · {season} ·
          {height} · {html.escape(weight_disp)} · Shoots {shoots}
        </div>
      </div>
      <div class="score-cluster">
      {cap_html}
      <div class="hero-block">
        <div class="gs-hero">
          <div class="gs-hero__val">{html.escape(gs_disp)}</div>
          <div class="gs-hero__lbl">Game Score</div>
        </div>
        <div class="sub-scores">
          <div><span>OFF</span><em class="{off_tier}">{html.escape(off_disp)}</em></div>
          <div><span>DEF</span><em class="{def_tier}">{html.escape(def_disp)}</em></div>
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
      <div class="section-tag">Profile snapshot · <span>percentile rank</span></div>
      <div class="highlights">{"".join(highlights)}</div>
    </div>
    <div class="rates-wrap">
      <div class="section-tag">Event rates · <span>per GP · {pbp_skated} games skated</span></div>
      <div class="rates">{"".join(rate_groups)}</div>
    </div>
    <div class="data-context">
      <div class="data-context__item">
        <span class="data-label">Percentiles</span>
        {pct_footer}
      </div>
      <div class="data-context__item">
        <span class="data-label">Event rates</span>
        <span>PBP · <strong>{pbp_team_games}</strong> team GP · <strong>{pbp_skated}</strong> skated</span>
      </div>
    </div>
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
