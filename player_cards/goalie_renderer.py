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


def render_net_heatmap_html(
    heatmap_zones: dict[str, dict[str, Any]],
    games_tracked: int,
    total_shots: int,
    *,
    title: str = "Save % by Net Zone",
    subtitle: str | None = None,
) -> str:
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
    sub = subtitle or f"{games_tracked} InStat-charted games · {total_shots} shots"
    return f"""
    <div class="shot-map-panel">
      <div class="shot-map-header">
        <div><div class="shot-map-title">{html.escape(title)}</div>
        <div class="shot-map-sub">{html.escape(sub)}</div></div>
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
    # Use colors already resolved in the profile (respects amateur club / prospect league)
    colors = profile.get("colors") or get_team_colors(bio["team"], league=profile.get("league", "nhl"))
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
    team_name = html.escape(bio.get("team", "") or bio.get("amateur_club", ""))

    # Prospect/junior: show amateur club, league, height/weight, draft info
    is_prospect = profile.get("league") == "prospect" or bio.get("undrafted") or profile.get("card_kind") == "junior_goalie"
    if is_prospect:
        draft_line = html.escape(bio.get("draft_info") or "Undrafted")
        amateur_league = html.escape(bio.get("amateur_league") or ("NCAA" if "university" in (bio.get("amateur_club") or "").lower() else ""))
        league_tag = f" · {amateur_league}" if amateur_league else ""
        hw_bits = []
        if height and height != "—":
            hw_bits.append(height)
        if weight_disp and weight_disp != "—":
            hw_bits.append(html.escape(weight_disp))
        hw_tag = f" · {' · '.join(hw_bits)}" if hw_bits else ""
        vitals_line = f"G · {team_name}{league_tag}{hw_tag} · {draft_line} · Catches {html.escape(str(catches))}"
    else:
        season_tag = profile.get("season") if isinstance(profile, dict) else getattr(profile, "season", None)
        if not season_tag:
            try:
                from .leagues import DEFAULT_SEASON
                season_tag = DEFAULT_SEASON
            except Exception:
                season_tag = "2026-27"
        vitals_line = f"G · {team_name} · {season_tag} · {height} · {html.escape(weight_disp)} · Catches {html.escape(str(catches))}"


    if is_prospect:
        dd = bio.get("draft_details") or {}
        undrafted = bool(bio.get("undrafted")) or (
            bio.get("draft_round") is None
            and bio.get("draft_overall") is None
            and not dd.get("year")
            and "eligible" in str(bio.get("draft_info") or "").lower()
        )
        if undrafted or (not bio.get("draft_overall") and not dd.get("overallPick")):
            now = datetime.now()
            draft_year = bio.get("draft_year") or str(now.year if now.month >= 7 else now.year)
            chl_line = bio.get("chl_draft_line") or bio.get("amateur_league") or ("NCAA" if "university" in (bio.get("amateur_club") or "").lower() else "CHL")
            cap_html = (
                f'<div class="cap-box">'
                f'<div class="cap-box__head">Draft Status</div>'
                f'<div class="cap-box__rows">'
                f'<div class="cap-box__row"><span class="cap-box__lbl">NHL</span><span class="cap-box__val">Undrafted · {html.escape(str(draft_year))}</span></div>'
                f'<div class="cap-box__row"><span class="cap-box__lbl">Club</span><span class="cap-box__val cap-box__val--wrap">{html.escape(str(team_name))}</span></div>'
                f'<div class="cap-box__row cap-box__row--accent"><span class="cap-box__lbl">League</span><span class="cap-box__val cap-box__val--wrap">{html.escape(str(chl_line))}</span></div>'
                f'</div></div>'
            )
        else:
            round_val = bio.get("draft_round") or dd.get("round", "—")
            pick_val = bio.get("draft_pick") or dd.get("pickInRound", "—")
            overall_val = bio.get("draft_overall") or dd.get("overallPick", "—")
            draft_team = bio.get("draft_team") or dd.get("teamAbbrev", "")
            team_str = f" ({draft_team})" if draft_team else ""
            cap_html = (
                f'<div class="cap-box">'
                f'<div class="cap-box__head">Draft Info</div>'
                f'<div class="cap-box__rows">'
                f'<div class="cap-box__row"><span class="cap-box__lbl">Amateur Club</span><span class="cap-box__val">{html.escape(str(team_name))}</span></div>'
                f'<div class="cap-box__row"><span class="cap-box__lbl">Selection</span><span class="cap-box__val">Rd {round_val}, Pick {pick_val}</span></div>'
                f'<div class="cap-box__row cap-box__row--accent"><span class="cap-box__lbl">Overall</span><span class="cap-box__val">#{overall_val} Overall{team_str}</span></div>'
                f'</div></div>'
            )
    else:
        cap_html = _cap_box_html(cap) if cap else ""


    # ── Hero block: SV% is the headline stat ──
    sv_pct = official.get("save_pct")
    gs_disp = f"{sv_pct:.1f}" if isinstance(sv_pct, (int, float)) else "—"
    # For prospect cards no league percentile population exists
    if sv_pct_p is not None and pool_size:
        gs_sub = f"{int(sv_pct_p*100)}th %ile of {pool_size} NHL goalies"
    elif is_prospect:
        gaa_v = official.get("gaa")
        gs_sub = f"GAA {gaa_v:.2f} · {official.get('shots_against', 0)} shots faced" if gaa_v is not None else ""
    else:
        gs_sub = ""

    from .html_renderer import _pct_class, _pct_num
    es_disp = "—" if _pct_num(es_sv_pct_p) is None else str(_pct_num(es_sv_pct_p))
    sc_disp = "—" if _pct_num(sc_sv_pct_p) is None else str(_pct_num(sc_sv_pct_p))
    es_tier = _pct_class(es_sv_pct_p)
    sc_tier = _pct_class(sc_sv_pct_p)

    gp = official.get("games_played", "—")
    w, l, otl = official.get("wins", "—"), official.get("losses", "—"), official.get("ot_losses", "—")


    # ── Pillar 1, 2, 3 ──
    ov_sv = situational.get("sv_pct_overall")
    ev_d = situational.get("even_strength", {})
    pk_d = situational.get("penalty_kill", {})
    pp_d = situational.get("power_play", {})
    hd_d = situational.get("high_danger", {})
    med_d = situational.get("medium", {})
    lng_d = situational.get("long_range", {})
    slot_d = situational.get("slot", {})
    rush_d = situational.get("rush", {})
    royal_d = situational.get("royal_road", {})
    cycle_d = situational.get("cycle", {})
    flank_d = situational.get("flank", {})

    if sv_pct_p is not None and not is_prospect:
        pillar1_rows = "".join([
            _bar_row("SV% (Overall)", _m(sv_pct_p)),
            _bar_row("SV% (5-on-5)", _m(es_sv_pct_p)),
            _bar_row("Scoring-Chance SV%", _m(sc_sv_pct_p)),
            _bar_row("GSAx", _m(gsax_p)),
        ])
        pillar1 = _pillar_col("League Percentiles", _pillar_avg_of([sv_pct_p, es_sv_pct_p, sc_sv_pct_p, gsax_p]), pillar1_rows)
    else:
        pillar1_rows = "".join([
            _raw_bar_row("Overall SV%", ov_sv),
            _raw_bar_row("5v5 Even Strength", ev_d.get("sv_pct"), low_sample=bool(ev_d.get("low_sample"))),
            _raw_bar_row("Penalty Kill (SH)", pk_d.get("sv_pct"), low_sample=bool(pk_d.get("low_sample"))),
            _raw_bar_row("Power Play", pp_d.get("sv_pct"), low_sample=bool(pp_d.get("low_sample"))),
        ])
        pillar1 = _simple_pillar("Strength Splits (SV%)", pillar1_rows)

    pillar2_rows = "".join([
        _raw_bar_row("High Danger (<15m)", hd_d.get("sv_pct"), low_sample=bool(hd_d.get("low_sample"))),
        _raw_bar_row("Medium Range (15-25m)", med_d.get("sv_pct"), low_sample=bool(med_d.get("low_sample"))),
        _raw_bar_row("Long Range (>25m)", lng_d.get("sv_pct"), low_sample=bool(lng_d.get("low_sample"))),
        _raw_bar_row("Inner Slot Area", slot_d.get("sv_pct"), low_sample=bool(slot_d.get("low_sample"))),
    ])
    pillar2 = _simple_pillar("Shot Danger (SV%)", pillar2_rows)

    pillar3_rows = "".join([
        _raw_bar_row("Rush Chances", rush_d.get("sv_pct"), low_sample=bool(rush_d.get("low_sample"))),
        _raw_bar_row("Royal Road (Cross-Slot)", royal_d.get("sv_pct"), low_sample=bool(royal_d.get("low_sample"))),
        _raw_bar_row("Forecheck / Cycle", cycle_d.get("sv_pct"), low_sample=bool(cycle_d.get("low_sample"))),
        _raw_bar_row("Perimeter / Flanks", flank_d.get("sv_pct"), low_sample=bool(flank_d.get("low_sample"))),
    ])
    pillar3 = _simple_pillar("Tactical Sequences (SV%)", pillar3_rows)

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

    # ── Season Summary: big stat tiles ──
    gaa_val = official.get("gaa")
    gaa_disp = f"{gaa_val:.2f}" if isinstance(gaa_val, (int, float)) else "—"
    rebound_disp = f"{rebound_control:.1f}%" if rebound_control is not None else "—"
    qs_v = official.get("quality_starts")
    qs_pct_val = official.get("quality_start_pct")
    qs_pct_str = f"{qs_pct_val:.0f}%" if isinstance(qs_pct_val, (int, float)) else "—"
    qs_disp = f"{qs_v} ({qs_pct_str})" if qs_v is not None else "—"

    if is_prospect:
        saves_v = official.get("saves", "—")
        season_tiles = "".join([
            _stat_tile("Games Played", str(gp)),
            _stat_tile("Saves", str(saves_v)),
            _stat_tile("GAA", gaa_disp),
            _stat_tile("Shutouts", str(official.get("shutouts", "—"))),
            _stat_tile("Quality Starts", qs_disp),
            _stat_tile("Shots Faced", str(situational.get("shots", official.get("shots_against", "—")))),
        ])
    else:
        season_tiles = "".join([
            _stat_tile("Games Played", str(gp)),
            _stat_tile("Record (W-L-OTL)", f"{w}-{l}-{otl}"),
            _stat_tile("GAA", gaa_disp),
            _stat_tile("Shutouts", str(official.get("shutouts", "—"))),
            _stat_tile("Quality Starts", qs_disp if qs_v is not None else rebound_disp),
            _stat_tile("Shots Faced", str(situational.get("shots", official.get("shots_against", "—")))),
        ])

    # ── Bottom pillars & heatmap ──
    if "handedness_splits" in real_agg and "Left Flank (Outside)" in real_agg["handedness_splits"]:
        handedness_pillar = _simple_pillar(
            "Lateral & Angle Splits (SV%)",
            split_rows(real_agg.get("handedness_splits", {}), [
                "Shots from Left", "Shots from Right", "Left Flank (Outside)", "Right Flank (Outside)", "Inner Slot Area"
            ]),
        )
        attack_pillar = _simple_pillar(
            "Save Posture & Technique (SV%)",
            split_rows(real_agg.get("real_style_of_play", {}), [
                "Butterfly Posture", "In Motion / Recovery", "Scramble / Beaten"
            ]) + split_rows(real_agg.get("by_attack_type", {}), [
                "High Danger (<15m)", "Medium Range (15-25m)", "Long Range (>25m)"
            ]),
        )
        situation_pillar = _simple_pillar(
            "Rebound & Workload Analytics",
            split_rows(real_agg.get("save_detail_share", {}), metric="share_pct"),
        )
        heatmap_html = render_net_heatmap_html(
            real_agg.get("heatmap_zones", {}),
            games_tracked,
            real_shots_n,
            title="Save % by Ice Zone (Location & Range)",
            subtitle=f"{games_tracked} games · {real_shots_n} shots against",
        )
        real_data_note = (
            f'<div class="data-context data-context--minimal">'
            f'<span>Heatmap, save posture, strength situations (5v5/PK/PP), tactical sequences (Rush/Cycle/Royal Road), and ice location splits '
            f'derived from {real_shots_n} shots across {games_tracked} games in local InStat play-by-play tracking.</span>'
            f'</div>'
        )
    else:
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

    pillars_section_tag = (
        f"Situational Save % · <span>{official.get('shots_against', situational.get('shots', 0))} shots across {gp} games</span>"
        if (is_prospect or sv_pct_p is None) else
        f"League percentiles · <span>vs. {pool_size or '—'} NHL goalies, min 10 GP</span>"
    )

    ev_sv = (situational.get("even_strength") or {}).get("sv_pct")
    rush_sv = (situational.get("rush") or {}).get("sv_pct")
    reb_ctrl = situational.get("rebound_control_pct")
    ctx_qs = official.get("quality_start_pct")
    ctx_qs_str = f"{ctx_qs:.0f}%" if isinstance(ctx_qs, (int, float)) else "—"

    if sv_pct_p is not None and not is_prospect:
        sub_scores_html = (
            f'<div><span>5v5</span><em class="{es_tier}">{es_disp}</em></div>'
            f'<div><span>SC</span><em class="{sc_tier}">{sc_disp}</em></div>'
        )
        ctx_box_html = (
            f'<div class="ctx-box">'
            f'<div>GAA<b>{gaa_disp}</b></div>'
            f'<div>SO<b>{html.escape(str(official.get("shutouts", "—")))}</b></div>'
            f'</div>'
        )
    else:
        sub_scores_html = (
            f'<div><span>5v5 EV</span><em>{f"{ev_sv:.1f}%" if ev_sv is not None else "—"}</em></div>'
            f'<div><span>Rush</span><em>{f"{rush_sv:.1f}%" if rush_sv is not None else "—"}</em></div>'
            f'<div><span>Reb. Ctrl</span><em>{f"{reb_ctrl:.1f}%" if reb_ctrl is not None else "—"}</em></div>'
        )
        ctx_box_html = (
            f'<div class="ctx-box">'
            f'<div>GAA<b>{gaa_disp}</b></div>'
            f'<div>SO<b>{html.escape(str(official.get("shutouts", "—")))}</b></div>'
            f'<div>QS%<b>{ctx_qs_str}</b></div>'
            f'</div>'
        )




    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Russo+One&display=swap" rel="stylesheet">
<style>
{shared_card_css(primary, accent, theme, light)}
.hero-block {{ display: flex; align-items: stretch; gap: 0; }}
.hero-block .gs-hero {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
.sub-scores {{
  display: flex;
  flex-direction: column;
  justify-content: space-around;
  background: #fff;
  border: 1px solid var(--line);
  border-left: none;
  border-top-right-radius: 8px;
  border-bottom-right-radius: 8px;
  padding: 6px 12px;
  min-width: 105px;
}}
.sub-scores > div {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}}
.sub-scores span {{
  font-size: 0.52rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--muted);
  letter-spacing: 0.04em;
}}
.sub-scores em {{
  font-family: 'Russo One', sans-serif;
  font-style: normal;
  font-size: 0.72rem;
  color: var(--ink);
}}
.ctx-box {{
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  justify-content: space-around;
  min-width: 90px;
  gap: 3px;
}}
.ctx-box > div {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.52rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--muted);
  letter-spacing: 0.04em;
}}
.ctx-box b {{
  font-family: 'Russo One', sans-serif;
  font-size: 0.75rem;
  color: var(--ink);
}}
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
          {sub_scores_html}
        </div>
      </div>
      {ctx_box_html}
      </div>
    </header>
    <div class="ribbon"></div>
    <div class="main-grid">
      <div class="pillars-wrap">
        <div class="section-tag">{pillars_section_tag}</div>
        <div class="pillars">{pillar1}{pillar2}{pillar3}</div>
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
