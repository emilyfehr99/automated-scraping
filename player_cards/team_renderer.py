"""Team card — single-view horizontal layout, same footprint as the skater/
goalie cards. Simple colored logo sidebar (matches the skater card's
photo-col slot), header with hero record, a Team Averages bar section
(Offense/Transition/Defense - self-normalized, no 32-team InStat pool exists
yet to percentile these against), a Transition funnel row (entries/exits as
a chain, not a flat bar list), and a footer strip: season summary tiles,
goalie SV%, and the season-form win/loss waffle grid in the bottom-right."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .card_config import PILLAR_BARS
from .color_utils import theme_text_vars
from .goalie_renderer import _stat_tile
from .html_renderer import _cap_row, shared_card_css
from .photo_layout import embed_photo
from .png_export import html_to_png
from .team_charts import render_season_form_waffle

_GOOD = "#0ca30c"
_CRITICAL = "#d03b3b"
_NEUTRAL = "#6b7280"


def _streak_badge(streak_code: str | None, streak_count: int | None) -> str:
    if not streak_code or not streak_count:
        return ""
    color = _GOOD if streak_code == "W" else (_CRITICAL if streak_code == "L" else _NEUTRAL)
    return f'<span class="status-badge" style="background:#fff;color:{color}">{html.escape(streak_code)}{streak_count}</span>'


def _diff_badge(goal_diff: int | float | None) -> str:
    if goal_diff is None:
        return '<span class="status-badge" style="background:#0000;color:var(--muted)">—</span>'
    color = _GOOD if goal_diff > 0 else (_CRITICAL if goal_diff < 0 else _NEUTRAL)
    disp = f"+{goal_diff}" if goal_diff > 0 else str(goal_diff)
    return f'<span class="status-badge" style="background:{color}22;color:{color};border:1px solid {color}55">{disp}</span>'


def _style_pillar(title: str, keys: list[tuple[str, str]], averages: dict[str, float | None]) -> str:
    """Self-normalized (min-max within this pillar's own metrics) bar rows -
    honest 'which of this team's own numbers stand out' emphasis, since there's
    no 32-team InStat pool to percentile these against yet."""
    vals = [(k, lbl, averages.get(k)) for k, lbl in keys]
    numeric = [v for _, _, v in vals if v is not None]
    lo, hi = (min(numeric), max(numeric)) if numeric else (0.0, 1.0)
    span = (hi - lo) or 1.0
    top_key = max(vals, key=lambda t: (t[2] if t[2] is not None else -1))[0] if numeric else None
    rows = []
    for k, lbl, v in vals:
        if v is None:
            rows.append(
                f'<div class="bar-row"><span class="bar-row__lbl">{html.escape(lbl)}</span>'
                f'<span class="bar-row__track"><span class="bar-row__fill" style="width:0%"></span></span>'
                f'<span class="bar-row__pct">—</span></div>'
            )
            continue
        width = 18 + 82 * ((v - lo) / span)
        is_top = k == top_key
        fill = "var(--accent)" if is_top else "#c7cdd6"
        rows.append(
            f'<div class="bar-row"><span class="bar-row__lbl">{html.escape(lbl)}{" ★" if is_top else ""}</span>'
            f'<span class="bar-row__track"><span class="bar-row__fill" style="width:{width:.0f}%;background:{fill}"></span></span>'
            f'<span class="bar-row__pct">{v:.2f}</span></div>'
        )
    return (
        f'<div class="pillar"><div class="pillar__head">'
        f'<span class="pillar__title">{html.escape(title)}</span></div>'
        f'<div class="pillar__rows">{"".join(rows)}</div></div>'
    )


_TONE_COLOR = {"good": _GOOD, "bad": _CRITICAL, "neutral": None}


def _funnel_row(label: str, value: float | None, max_value: float, tone: str) -> str:
    color = _TONE_COLOR.get(tone) or "var(--primary)"
    v = value or 0.0
    width = max(6.0, min(100.0, (v / max_value * 100))) if max_value else 6.0
    return (
        f'<div class="funnel-row"><span class="funnel-row__lbl">{html.escape(label)}</span>'
        f'<span class="funnel-row__track"><span class="funnel-row__fill" style="width:{width:.0f}%;background:{color}"></span></span>'
        f'<span class="funnel-row__val" style="color:{color}">{v:.1f}</span></div>'
    )


def _funnel_section(title: str, subtitle: str, steps: list[tuple[str, float | None, str]]) -> str:
    max_value = max((v for _, v, _ in steps if v is not None), default=1.0) or 1.0
    rows = "".join(_funnel_row(lbl, v, max_value, tone) for lbl, v, tone in steps)
    return (
        f'<div class="pillar funnel-pillar"><div class="pillar__head">'
        f'<span class="pillar__title">{html.escape(title)}</span>'
        f'<span class="pillar__avg funnel-pillar__sub">{html.escape(subtitle)}</span></div>'
        f'<div class="pillar__rows">{rows}</div></div>'
    )


def render_team_card_html(profile: dict[str, Any]) -> str:
    colors = profile.get("colors") or {"primary": "#1a1a1a", "accent": "#666", "light": "#f1f5f9"}
    primary, accent = colors["primary"], colors["accent"]
    light = colors.get("light", "#f1f5f9")
    theme = theme_text_vars(primary, accent)

    team_name = profile.get("team_name", profile.get("team", ""))
    standing = profile.get("standing") or {}
    averages = profile.get("skater_averages") or {}
    goalies = profile.get("goalies") or {}
    zone_events = profile.get("zone_events") or {}
    game_log = profile.get("game_log") or []
    games = profile.get("games") or 1
    front_office = profile.get("front_office") or {}
    official_row = profile.get("official") or {}
    leaders = profile.get("leaders") or []

    logo_src = embed_photo(str(profile.get("logo_png_url") or profile.get("logo_url") or ""))[0]

    pts = standing.get("points")
    w, l, otl = standing.get("wins", "—"), standing.get("losses", "—"), standing.get("ot_losses", "—")
    division = standing.get("division") or "—"
    div_rank = standing.get("division_rank")
    conf = standing.get("conference") or "—"
    vitals_line = (
        f"{conf} Conference · {division} Division"
        + (f" (#{div_rank})" if div_rank else "")
        + f" · {profile.get('player_count', 0)}/{profile.get('roster_size', 0)} skaters tracked"
    )
    pts_disp = str(pts) if pts is not None else "—"

    top_prospects_str = profile.get("top_prospects")

    cap_space = front_office.get("cap_space")
    cap_hit = front_office.get("cap_hit_total")
    front_office_html = "".join([
        _cap_row("GM", front_office.get("gm")),
        _cap_row("Coach", front_office.get("coach")),
        _cap_row("Top Prospects", top_prospects_str),
        _cap_row("Cap Space", f"${cap_space/1e6:.1f}M" if cap_space is not None else None, accent=True),
        _cap_row("Cap Hit", f"${cap_hit/1e6:.1f}M" if cap_hit is not None else None),
    ])

    style_pillars = "".join(_style_pillar(p["title"], p["keys"], averages) for p in PILLAR_BARS)

    entries_funnel = _funnel_section(
        "Zone Entries", "per game",
        [
            ("Zone Entries", averages.get("zone_entries_per_60"), "neutral"),
            ("→ Led to a Chance", averages.get("entries_w_chance_per_60"), "good"),
            ("→ Failed / Turned Over", averages.get("failed_entries_per_60"), "bad"),
        ],
    )
    exits_funnel = _funnel_section(
        "Zone Exits", "per game",
        [
            ("Zone Exits", averages.get("zone_exits_per_60"), "neutral"),
            ("→ With Possession", averages.get("exits_w_possession_per_60"), "good"),
            ("→ Failed Exit", averages.get("failed_exit_per_60"), "bad"),
        ],
    )
    nz_total = zone_events.get("nz_turnovers", 0)
    nz_to_shot = zone_events.get("nz_turnovers_to_shot_against", 0)
    nz_funnel = _funnel_section(
        "Neutral Zone Turnovers", "per game",
        [
            ("NZ Turnovers", nz_total / games, "neutral"),
            ("→ Led to Shot Against", nz_to_shot / games, "bad"),
        ],
    )

    l10 = f"{standing.get('l10_wins','—')}-{standing.get('l10_losses','—')}-{standing.get('l10_ot_losses','—')}"
    pp_pct = official_row.get("powerPlayPct")
    pk_pct = official_row.get("penaltyKillPct")
    fo_pct = official_row.get("faceoffWinPct")
    season_tiles = "".join([
        _stat_tile("Record (W-L-OTL)", f"{w}-{l}-{otl}"),
        _stat_tile("Points", pts_disp),
        _stat_tile("Team SV%", f"{goalies.get('team_sv_pct')}%" if goalies.get("team_sv_pct") is not None else "—"),
        _stat_tile("Team GAA", str(goalies.get("team_gaa", "—"))),
        _stat_tile("Shutouts", str(goalies.get("shutouts", "—"))),
        _stat_tile("Last 10", l10),
        _stat_tile("Power Play %", f"{pp_pct*100:.1f}%" if pp_pct is not None else "—"),
        _stat_tile("Penalty Kill %", f"{pk_pct*100:.1f}%" if pk_pct is not None else "—"),
        _stat_tile("Faceoff %", f"{fo_pct*100:.1f}%" if fo_pct is not None else "—"),
    ])
    goalie_rows = "".join(
        f'<div class="bar-row"><span class="bar-row__lbl">{html.escape(g["name"])} ({g["gp"]} GP)</span>'
        f'<span class="bar-row__track"><span class="bar-row__fill" style="width:{min(100, g["sv_pct"] or 0):.0f}%"></span></span>'
        f'<span class="bar-row__pct">{g["sv_pct"]}%</span></div>'
        for g in goalies.get("goalies", [])
    ) or '<div class="bar-row"><span class="bar-row__lbl">No goalie data</span></div>'

    leader_rows = "".join(
        f'<div class="leader-row"><span class="leader-row__name">{html.escape(ld["name"])}</span>'
        f'<span class="leader-row__stat">{ld["goals"]}G {ld["assists"]}A {ld["points"]}P</span></div>'
        for ld in leaders[:5]
    ) or '<div class="leader-row"><span class="leader-row__name">No scoring data</span></div>'

    waffle_html = render_season_form_waffle(game_log, cols=11)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Russo+One&display=swap" rel="stylesheet">
<style>
{shared_card_css(primary, accent, theme, light)}
.status-badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-family: 'Russo One', sans-serif; font-size: 0.85rem; margin-left: 8px; }}
.front-office-box {{ justify-self: center; align-self: center; min-width: 168px; }}
.main-grid {{ grid-template-columns: 1fr; }}
.pillars-wrap {{ border-right: none; }}
.g-tile-row {{ background: #fff; padding: 10px 20px 12px; }}
.g-tile-row .section-tag {{ padding: 0 0 8px; }}
.footer-grid {{ display: grid; grid-template-columns: 1.6fr 1fr 1fr; gap: 0; border-top: 1px solid var(--line); }}
.footer-grid > div {{ padding: 12px 20px; border-right: 1px solid var(--line); }}
.footer-grid > div:last-child {{ border-right: none; }}
.leader-row {{ display: flex; justify-content: space-between; padding: 4px 0; font-size: 0.62rem; }}
.leader-row__name {{ color: var(--ink); font-weight: 600; }}
.leader-row__stat {{ color: var(--muted); font-family: 'Russo One', sans-serif; font-size: 0.6rem; }}
.point-leaders-title {{ margin-top: 12px; }}
.g-tile-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
.g-stat-tile {{ background: #fafaf8; border: 1px solid var(--line); border-radius: 8px; padding: 10px 6px; text-align: center; }}
.g-stat-tile__val {{ font-family: 'Russo One', sans-serif; font-size: 1.35rem; color: var(--ink); line-height: 1; }}
.g-stat-tile__lbl {{ font-size: 0.46rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted); margin-top: 4px; }}
.funnel-pillar__sub {{ font-size: 0.62rem; font-weight: 600; color: var(--muted); font-family: Inter, sans-serif; }}
.funnel-row {{ display: grid; grid-template-columns: 118px 1fr 32px; gap: 8px; align-items: center; padding: 6px 0; }}
.funnel-row__lbl {{ font-size: 0.52rem; font-weight: 500; color: var(--muted); }}
.funnel-row__track {{ height: 9px; background: #e2e5ea; border-radius: 3px; overflow: hidden; }}
.funnel-row__fill {{ display: block; height: 100%; border-radius: 3px; }}
.funnel-row__val {{ font-family: 'Russo One', sans-serif; font-size: 0.66rem; text-align: right; }}
.waffle-form__title {{ font-size: 0.5rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 6px; }}
</style>
</head>
<body>
<article class="card">
  <div class="photo-col" style="background: linear-gradient(165deg, {primary} 0%, {primary} 60%, {accent} 150%); display:flex; align-items:center; justify-content:center;">
    <img src="{html.escape(logo_src)}" alt="{html.escape(team_name)}" style="max-width:70%; max-height:220px; filter: drop-shadow(0 6px 18px rgba(0,0,0,0.35));">
  </div>
  <div class="content">
    <header class="top">
      <div class="name-block">
        <h1>{html.escape(team_name)}</h1>
        <div class="vitals">{vitals_line}</div>
      </div>
      <div class="cap-box front-office-box">
        <div class="cap-box__head">Front Office</div>
        <div class="cap-box__rows">{front_office_html}</div>
      </div>
      <div class="score-cluster">
        <div class="hero-block">
          <div class="gs-hero">
            <div class="gs-hero__val">{html.escape(pts_disp)}</div>
            <div class="gs-hero__lbl">POINTS</div>
            <div class="gs-hero__sub">{w}-{l}-{otl} {_streak_badge(standing.get("streak_code"), standing.get("streak_count"))}</div>
          </div>
        </div>
        <div class="ctx-box">
          <div>GP<b>{standing.get("games_played", "—")}</b></div>
          <div>DIFF<b>{_diff_badge(standing.get("goal_diff"))}</b></div>
        </div>
      </div>
    </header>
    <div class="ribbon"></div>

    <div class="main-grid">
      <div class="pillars-wrap">
        <div class="section-tag">Team Averages · <span>raw per-game average (no 32-team pool yet — generate the full league to rank)</span></div>
        <div class="pillars">{style_pillars}</div>
      </div>
    </div>

    <div class="main-grid">
      <div class="pillars-wrap">
        <div class="section-tag">Transition · <span>per-game average through each stage</span></div>
        <div class="pillars">{entries_funnel}{exits_funnel}{nz_funnel}</div>
      </div>
    </div>

    <div class="footer-grid">
      <div>
        <div class="section-tag" style="padding:0 0 8px">Season Summary</div>
        <div class="g-tile-grid">{season_tiles}</div>
      </div>
      <div>
        <div class="section-tag" style="padding:0 0 8px">SV% by Goalie</div>
        {goalie_rows}
        <div class="section-tag point-leaders-title" style="padding:0 0 6px">Point Leaders</div>
        {leader_rows}
      </div>
      <div>
        <div class="waffle-form__title">Season Form · {len(game_log)} GP</div>
        {waffle_html}
      </div>
    </div>
  </div>
</article>
</body>
</html>"""


def write_team_card_html(profile: dict[str, Any], output: Path | str) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_team_card_html(profile), encoding="utf-8")
    return output


def generate_team_card_png(profile: dict[str, Any], output_png: Path | str) -> Path:
    output_png = Path(output_png)
    html_path = output_png.with_suffix(".html")
    write_team_card_html(profile, html_path)
    return html_to_png(html_path, output_png)
