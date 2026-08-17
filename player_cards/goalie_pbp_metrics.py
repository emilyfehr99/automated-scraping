"""Per-shot situational SV% splits for one goalie, computed from local InStat PBP CSVs.

Headline SV%/GSAx comes from InStat's own season-aggregate model (goalie_source.py).
This module handles the finer situational cuts that aggregate model doesn't expose
(rush/cycle/royal-road/off-wing/high-danger/rebound control) by walking the same
per-game PBP files already used for skater microstats, using the exact zone/action
conventions already validated there (player_cards/pbp_metrics.py).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from .instat_source import _match_player_name
from .pbp_metrics import DZ_LIMIT, NET_X, NET_Y, NZ_LIMIT, _xg

HD_DIST = 15.0
HD_XG = 0.08
MED_DIST = 25.0

RUSH_ENTRY_ACTIONS = frozenset({"Entries via stickhandling", "Entries via pass"})
CYCLE_ACTION = "Puck recoveries in OZ"
SHIFT_OR_FACEOFF_HINTS = ("shift", "faceoff")
SHOT_RESULT_ACTIONS = {"Shots on goal", "Shots", "Goals"}
ENTRY_SHOT_ACTIONS = frozenset({
    "Shots on goal", "Shots", "Goals", "Missed shots", "Power play shots", "Short-handed shots",
})


def _sequence_neutral(action: str) -> bool:
    a = str(action or "")
    al = a.lower()
    return any(h in al for h in SHIFT_OR_FACEOFF_HINTS)


def _pct(num: float, den: float) -> float | None:
    if den <= 0:
        return None
    return round(100.0 * num / den, 1)


# ─── Goalie ↔ game attribution ──────────────────────────────────────────────

def fetch_goalie_game_dates(player_id: int, season: str = "20252026") -> dict[str, float]:
    """NHL API game log -> {gameDate: toi_seconds} for one goalie's appearances.

    Ground truth for "which of our downloaded PBP files did this goalie play in",
    since the InStat PBP export itself has no goalie-identity column.
    """
    resp = httpx.get(
        f"https://api-web.nhle.com/v1/player/{player_id}/game-log/{season}/2",
        headers={"User-Agent": "PlayerCards/1.0"}, timeout=15.0,
    )
    resp.raise_for_status()
    out: dict[str, float] = {}
    for game in resp.json().get("gameLog", []):
        date = str(game.get("gameDate") or "")
        toi = str(game.get("toi") or "0:00")
        try:
            mm, ss = toi.split(":")
            secs = int(mm) * 60 + int(ss)
        except ValueError:
            secs = 0
        if date:
            out[date] = secs
    return out


def games_for_goalie(
    pbp_files: list[Path],
    goalie_dates: dict[str, float],
    other_goalie_dates: dict[str, float] | None = None,
) -> list[Path]:
    """Filter a team's full PBP file list down to the games this goalie actually played.

    Filenames encode date as game_YYYY-MM-DD_<matchid>_pbp.csv. On a date where both
    goalies have a log entry (mid-game change), the file is assigned to whichever
    goalie logged more TOI that date — an approximation for split appearances, since
    the PBP rows themselves carry no goalie identity to split within a single game.
    """
    other = other_goalie_dates or {}
    matched: list[Path] = []
    for f in pbp_files:
        parts = f.name.split("_")
        if len(parts) < 2:
            continue
        date = parts[1]
        if date not in goalie_dates:
            continue
        if date in other and other[date] > goalie_dates[date]:
            continue
        matched.append(f)
    return matched


# ─── Per-shot sequence tagging (ported from pwhl-analytics, NET_X/Y kept as
#     already validated for this data source in pbp_metrics.py) ────────────

def _attack_type(x: float, y: float, xg: float) -> str:
    dist = math.hypot(NET_X - x, abs(NET_Y - y))
    if dist <= HD_DIST or xg >= HD_XG:
        return "High Danger"
    if dist <= MED_DIST:
        return "Medium"
    return "Long Range"


def _is_rush_shot(actions: list[str], teams: list[str], i: int) -> bool:
    team_i = teams[i]
    for j in range(i - 1, max(i - 6, -1), -1):
        if _sequence_neutral(actions[j]):
            continue
        if teams[j] != team_i:
            break
        if actions[j] in RUSH_ENTRY_ACTIONS:
            return True
    return False


def _is_cycle_shot(actions: list[str], teams: list[str], i: int) -> bool:
    team_i = teams[i]
    for j in range(i - 1, max(i - 6, -1), -1):
        if _sequence_neutral(actions[j]):
            continue
        if teams[j] != team_i:
            break
        if actions[j] == CYCLE_ACTION:
            return True
    return False


def _is_royal_road(actions: list[str], teams: list[str], pos_y: list[float], starts: list[float], i: int) -> bool:
    """Same-team pass whose origin crosses the royal road (center-ice y=NET_Y)
    within ~4s before this shot."""
    team_i = teams[i]
    cy = pos_y[i]
    t_i = starts[i]
    if cy is None or (isinstance(cy, float) and math.isnan(cy)):
        return False
    for j in range(i - 1, max(i - 8, -1), -1):
        if teams[j] != team_i:
            break
        if _sequence_neutral(actions[j]) or actions[j] == "Shots":
            continue
        if actions[j] != "Passes":
            continue
        ly = pos_y[j]
        if ly is None or (isinstance(ly, float) and math.isnan(ly)):
            continue
        t_j = starts[j]
        if t_i is not None and t_j is not None and not math.isnan(t_i) and not math.isnan(t_j) and (t_i - t_j) > 4.0:
            break
        if (ly > NET_Y >= cy) or (ly < NET_Y <= cy):
            return True
    return False


def _is_rebound_after(actions: list[str], teams: list[str], goalie_team: str, i: int) -> bool:
    if actions[i] == "Goals":
        return False
    for j in range(i + 1, min(i + 9, len(actions))):
        if teams[j] != goalie_team and actions[j] in SHOT_RESULT_ACTIONS:
            return True
    return False


def _style_of_play_estimate(is_rush: bool, dist: float, ang: float) -> str:
    """Geometry-based ESTIMATE of save posture — not real InStat tracking data.
    See goalie_pbp_metrics module docstring / card footnote for the caveat."""
    if is_rush:
        return "In Motion"
    if dist <= 22.0 and ang >= 0.55:
        return "Beaten"
    if dist <= 28.0:
        return "Butterfly"
    return "In Motion"


def build_goalie_shots(
    files: list[Path],
    team: str,
    goalie_name: str | None = None,
) -> list[dict[str, Any]]:
    """All opponent shot-on-goal events against this goalie's team across the given games.

    A single physical shot that scores is logged as BOTH a "Shots on goal" row and a
    "Goals" row at the same (start, player) — counting both would double the shot
    total and inflate SV%. Only "Shots on goal" rows plus any "Goals" rows that don't
    share a (start, player) with one are counted, mirroring pwhl-analytics'
    shot_attempt_rows(). Bare "Shots" is a separate, broader action (includes missed/
    blocked attempts) and is excluded — SV% is saves ÷ shots *on goal*, by definition.
    """
    shots: list[dict[str, Any]] = []
    for path in files:
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if df.empty or "action" not in df.columns:
            continue
        df = df.sort_values([c for c in ("half", "start") if c in df.columns]).reset_index(drop=True)
        actions = df["action"].astype(str).tolist()
        teams_col = df["team"].astype(str).tolist()
        players_col = df["player"].astype(str).tolist() if "player" in df.columns else [""] * len(df)
        pos_x = pd.to_numeric(df.get("pos_x"), errors="coerce").tolist()
        pos_y = pd.to_numeric(df.get("pos_y"), errors="coerce").tolist()
        starts = pd.to_numeric(df.get("start"), errors="coerce").tolist()

        sog_keys = {
            (starts[i], players_col[i])
            for i, act in enumerate(actions)
            if act == "Shots on goal"
        }
        # A goal's own "Shots on goal" twin has action == "Shots on goal", not
        # "Goals" — so whether a *counted* row is a goal has to come from
        # membership in goal_keys, not from that row's own action string.
        goal_keys = {
            (starts[i], players_col[i])
            for i, act in enumerate(actions)
            if act == "Goals"
        }

        for i, act in enumerate(actions):
            if act == "Shots on goal":
                pass
            elif act == "Goals" and (starts[i], players_col[i]) not in sog_keys:
                pass  # a goal not already represented by its own SOG row
            else:
                continue
            if teams_col[i] == team:
                continue  # this is our own team's shot, not a shot against
            x, y = pos_x[i], pos_y[i]
            if x is None or y is None or math.isnan(x) or math.isnan(y):
                continue
            xg = round(_xg(x, y), 3)
            is_goal = (starts[i], players_col[i]) in goal_keys
            dist = math.hypot(NET_X - x, abs(NET_Y - y))
            ang = math.atan2(abs(NET_Y - y), max(0.0, NET_X - x) + 1e-9)
            is_rush = _is_rush_shot(actions, teams_col, i)
            shots.append({
                "x": round(x, 2), "y": round(y, 2), "xg": xg, "is_goal": is_goal,
                "attack_type": _attack_type(x, y, xg),
                "is_rush": is_rush,
                "is_cycle": _is_cycle_shot(actions, teams_col, i),
                "is_royal_road": _is_royal_road(actions, teams_col, pos_y, starts, i),
                "is_rebound": _is_rebound_after(actions, teams_col, team, i),
                "ice_side": "Left" if y < NET_Y else "Right",
                "style_estimate": _style_of_play_estimate(is_rush, dist, ang),
                "game_file": path.name,
            })
    return shots


def _sv_pct(group: list[dict[str, Any]]) -> float | None:
    if not group:
        return None
    goals = sum(1 for s in group if s["is_goal"])
    return _pct(len(group) - goals, len(group))


def aggregate_goalie_situational(
    shots: list[dict[str, Any]],
    *,
    goalie_hand: str | None = None,
) -> dict[str, Any]:
    """Situational SV% splits — all plain counting stats (saves/shots), no proxy
    xG involved except in the clearly-separate style-of-play estimate."""
    if not shots:
        return {}

    hd = [s for s in shots if s["attack_type"] == "High Danger"]
    med = [s for s in shots if s["attack_type"] == "Medium"]
    lng = [s for s in shots if s["attack_type"] == "Long Range"]
    rush = [s for s in shots if s["is_rush"]]
    cycle = [s for s in shots if s["is_cycle"]]
    royal = [s for s in shots if s["is_royal_road"]]
    lh = [s for s in shots if s["ice_side"] == "Left"]
    rh = [s for s in shots if s["ice_side"] == "Right"]
    rebounds = sum(1 for s in shots if s["is_rebound"])

    style_counts: dict[str, int] = {}
    for s in shots:
        style_counts[s["style_estimate"]] = style_counts.get(s["style_estimate"], 0) + 1
    n = len(shots)

    # Splits this thin carry real season-to-season variance even with correct
    # logic (e.g. 84 cycle shots is a small enough bucket that a handful of
    # broken-play goals swings the rate hard) — flag rather than hide them.
    LOW_SAMPLE_THRESHOLD = 50

    def _bucket(group: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "sv_pct": _sv_pct(group),
            "shots": len(group),
            "low_sample": len(group) < LOW_SAMPLE_THRESHOLD,
        }

    return {
        "shots": n,
        "sv_pct_overall": _sv_pct(shots),
        "high_danger": _bucket(hd),
        "medium": _bucket(med),
        "long_range": _bucket(lng),
        "rush": _bucket(rush),
        "cycle": _bucket(cycle),
        "royal_road": _bucket(royal),
        "left_side": _bucket(lh),
        "right_side": _bucket(rh),
        "rebound_rate_pct": _pct(rebounds, n),
        "rebound_control_pct": round(100 - (rebounds / max(1, n) * 100), 1),
        "style_estimate_pct": {
            k: _pct(v, n) for k, v in style_counts.items()
        },
        "style_estimate_note": (
            "Estimated from shot distance/angle/rush-sequence — not observed InStat "
            "save-technique tracking."
        ),
    }
