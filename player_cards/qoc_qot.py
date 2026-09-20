"""QOC / QOT from InStat shift deployment (Clarkson run_deployment_qoc_qot.R logic)."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .instat_source import _match_player_name

DZ_MAX = 22.86
NZ_MAX = 38.10

SHIFT_ACTIONS = {"Even strength shifts", "Power play shifts", "Penalty kill shifts"}
DEPLOYMENT_SHIFT = "Even strength shifts"
PLAY_ACTIONS = {
    "Shots", "Shots on goal", "Goals", "Missed shots", "Blocked shots",
    "Passes", "Entries via stickhandling", "Entries via pass", "Entries via dump in",
    "Breakouts", "Breakouts via pass", "Breakouts via stickhandling",
    "Puck recoveries in DZ", "Puck recoveries in OZ", "Puck recoveries in NZ",
    "Puck recoveries", "Puck losses", "Inaccurate passes",
}
RUSH_ACTIONS = {
    "Breakouts", "Breakouts via pass", "Breakouts via stickhandling",
    "Entries", "Entries via pass", "Entries via stickhandling",
}
CYCLE_ACTIONS = {"Dump ins", "Puck recoveries in OZ", "Puck battles in OZ", "Passes to the slot"}

MICROSTAT_OFFENSE_COLS = [
    "Scoring_Chances",
    "Shot_Assists",
    "Zone_Entries",
    "Carry_ins",
    "Carries_with_Chances",
    "Dump_in_Chances",
    "DZ_Shots",
    "NZ_Shots",
    "Shots_off_Rush",
    "Shots_off_Forecheck",
]
MICROSTAT_DEFENSE_COLS = [
    "Possession_Exits",
    "Forecheck_Recoveries",
    "NZ_Turnovers",
]


def _game_id(path: Path) -> str:
    m = re.search(r"game_(?:\d{4}-\d{2}-\d{2}_)?(\d+)_pbp\.csv", path.name, re.I)
    return m.group(1) if m else path.stem


def _norm_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    if "player" not in df.columns and "Player" in df.columns:
        df = df.rename(columns={"Player": "player", "Team": "team", "Action": "action"})
    df["player"] = df["player"].astype(str).str.strip()
    df["team"] = df["team"].astype(str).str.strip()
    df["action"] = df["action"].astype(str).str.strip()
    df["pos_x"] = pd.to_numeric(df.get("pos_x"), errors="coerce")
    df["pos_y"] = pd.to_numeric(df.get("pos_y"), errors="coerce")
    return df


def _is_probable_goalie(player: str, team_df: pd.DataFrame) -> bool:
    rows = team_df[team_df["player"] == player]
    if rows.empty:
        return False
    play_n = rows["action"].isin(PLAY_ACTIONS).sum()
    shift_n = rows["action"].str.contains("shifts", case=False, na=False).sum()
    return shift_n >= 5 and play_n <= 2


def _window_has(tg: pd.DataFrame, idx: int, lookahead: int, actions: set[str], team: str) -> bool:
    end = min(idx + lookahead, len(tg) - 1)
    if idx >= end:
        return False
    window = tg.iloc[idx + 1 : end + 1]
    return bool(((window["action"].isin(actions)) & (window["team"] == team)).any())


def compute_microstat_game_score(df: pd.DataFrame, team_name: str) -> pd.DataFrame:
    """Per-player microstat game score for one team in one game.

    InStat-derived formula (Clarkson / internal R port). Each counted event
    contributes +1 to the relevant bucket; totals are unweighted sums:

      Offense GS =
          Scoring_Chances + Shot_Assists + Zone_Entries + Carry_ins
        + Carries_with_Chances + Dump_in_Chances + DZ_Shots + NZ_Shots
        + Shots_off_Rush + Shots_off_Forecheck

      Defense GS =
          Possession_Exits + Forecheck_Recoveries + NZ_Turnovers

      Game Score = Offense GS + Defense GS
                 (+ any other counted event keys on the player that game)

    Event definitions (from InStat PBP actions / location windows):
      Scoring_Chances     — Shots from home-plate (px≥50, 11≤py≤14)
      Shot_Assists        — Pass immediately followed by a teammate Shot
      Zone_Entries        — Entries / via stickhandling / pass / dump-in
      Carry_ins           — Entries via stickhandling or pass (controlled)
      Carries_with_Chances— Stickhandle entry with a Shot in next 10 events
      Dump_in_Chances     — Dump-in entry with a Shot in next 10 events
      Forecheck_Recoveries— Dump-in followed by OZ battle/shot/pass/goal window
      Possession_Exits    — Controlled breakouts (pass/stickhandle) from DZ
      DZ_Shots / NZ_Shots — DZ/NZ recoveries that lead to a Shot within 10
      NZ_Turnovers        — NZ puck losses / inaccurate passes
      Shots_off_Rush/FC   — Shot preceded by rush vs cycle/forecheck context

    A3Z publishes a related proprietary Game Score; we do not use their
    weights. This is our reproducible InStat PBP implementation.
    """
    team_mask = (df["team"] == team_name) & df["player"].notna() & (df["player"] != "")
    team_df = df[team_mask]
    if team_df.empty:
        return pd.DataFrame(columns=["player", "game_score", "offense_gs", "defense_gs"])

    skaters = [
        p for p in team_df["player"].unique()
        if p and not _is_probable_goalie(p, team_df)
    ]
    if not skaters:
        return pd.DataFrame(columns=["player", "game_score", "offense_gs", "defense_gs"])

    tg = team_df[team_df["player"].isin(skaters)].reset_index(drop=True)
    if tg.empty:
        return pd.DataFrame(columns=["player", "game_score", "offense_gs", "defense_gs"])

    actions = tg["action"].astype(str).tolist()
    players = tg["player"].astype(str).tolist()
    teams = tg["team"].astype(str).tolist()
    n_rows = len(actions)

    pos_x = pd.to_numeric(tg.get("pos_x"), errors="coerce").fillna(0).tolist()
    pos_y = pd.to_numeric(tg.get("pos_y"), errors="coerce").fillna(0).tolist()

    counts: dict[str, dict[str, int]] = {p: defaultdict(int) for p in skaters}

    def _has_window(idx: int, lookahead: int, target_acts: set[str]) -> bool:
        end = min(idx + lookahead + 1, n_rows)
        for k in range(idx + 1, end):
            if actions[k] in target_acts and teams[k] == team_name:
                return True
        return False

    shots_set = {"Shots"}
    fc_window_set = {"Puck battles in OZ", "Shots", "Goals", "Passes"}
    offense_type = [("Rush" if a in RUSH_ACTIONS else ("Cycle/Forecheck" if a in CYCLE_ACTIONS else None)) for a in actions]

    for i in range(n_rows):
        act = actions[i]
        p = players[i]
        px, py = pos_x[i], pos_y[i]

        if act == "Shots":
            if px >= 50 and 11 <= py <= 14:
                counts[p]["Scoring_Chances"] += 1
            for k in range(1, 11):
                j = i - k
                if j < 0:
                    break
                ot = offense_type[j]
                if ot == "Rush":
                    counts[p]["Shots_off_Rush"] += 1
                    break
                elif ot == "Cycle/Forecheck":
                    counts[p]["Shots_off_Forecheck"] += 1
                    break
        elif act == "Passes":
            if i < n_rows - 1 and actions[i + 1] == "Shots":
                counts[p]["Shot_Assists"] += 1

        if act in ("Entries", "Entries via stickhandling", "Entries via pass", "Entries via dump in"):
            counts[p]["Zone_Entries"] += 1
        if act in ("Entries", "Entries via stickhandling", "Entries via pass"):
            counts[p]["Carry_ins"] += 1
        if act == "Entries via stickhandling" and _has_window(i, 10, shots_set):
            counts[p]["Carries_with_Chances"] += 1
        elif act == "Entries via dump in":
            if _has_window(i, 10, shots_set):
                counts[p]["Dump_in_Chances"] += 1
            if _has_window(i, 10, fc_window_set):
                counts[p]["Forecheck_Recoveries"] += 1

        if act in ("Breakouts via stickhandling", "Breakouts via pass") and px <= DZ_MAX:
            counts[p]["Possession_Exits"] += 1
        elif act == "Puck recoveries in DZ" and px <= DZ_MAX:
            if _has_window(i, 10, shots_set):
                counts[p]["DZ_Shots"] += 1
        elif act == "Puck recoveries" and DZ_MAX < px <= NZ_MAX:
            if _has_window(i, 10, shots_set):
                counts[p]["NZ_Shots"] += 1
        elif act in ("Puck losses in NZ", "Inaccurate passes") and DZ_MAX < px <= NZ_MAX:
            counts[p]["NZ_Turnovers"] += 1

    rows = []
    for p in skaters:
        c = counts[p]
        total_gs = sum(c.values())
        off_gs = sum(c[col] for col in MICROSTAT_OFFENSE_COLS if col in c)
        def_gs = sum(c[col] for col in MICROSTAT_DEFENSE_COLS if col in c)
        rows.append({
            "player": p,
            "game_score": float(total_gs),
            "offense_gs": float(off_gs),
            "defense_gs": float(def_gs),
        })

    return pd.DataFrame(rows)


def _lookup_gs(player: str, game_id: str, gs_game: dict[tuple[str, str], float], gs_season: dict[str, float]) -> float:
    key = (player, game_id)
    if key in gs_game:
        return gs_game[key]
    return gs_season.get(player, float("nan"))


def _qoc_qot_game(df: pd.DataFrame, team_name: str, game_id: str, gs_game: dict, gs_season: dict) -> pd.DataFrame:
    shifts = df[df["action"].isin(SHIFT_ACTIONS) & df["player"].notna() & (df["player"] != "")].copy()
    if shifts.empty:
        return pd.DataFrame(columns=["player", "qoc", "qot", "shift_events"])

    is_goalie_cache = {}
    def check_goalie(p: str) -> bool:
        if p not in is_goalie_cache:
            is_goalie_cache[p] = _is_probable_goalie(p, df)
        return is_goalie_cache[p]

    rows: list[dict[str, Any]] = []
    for (start, action), block in shifts.groupby(["start", "action"], sort=False):
        team_players = block[block["team"] == team_name]["player"].unique().tolist()
        if not team_players:
            continue
        opp_players = block[block["team"] != team_name]["player"].unique().tolist()
        opp_players = [p for p in opp_players if not check_goalie(p)]
        skaters = [p for p in team_players if not check_goalie(p)]

        opp_gs = [_lookup_gs(p, game_id, gs_game, gs_season) for p in opp_players]
        opp_gs = [g for g in opp_gs if np.isfinite(g)]
        qoc_val = float(np.mean(opp_gs)) if opp_gs else float("nan")

        for pl in skaters:
            mates = [p for p in skaters if p != pl]
            mate_gs = [_lookup_gs(p, game_id, gs_game, gs_season) for p in mates]
            mate_gs = [g for g in mate_gs if np.isfinite(g)]
            qot_val = float(np.mean(mate_gs)) if mate_gs else float("nan")
            rows.append({"player": pl, "qoc": qoc_val, "qot": qot_val, "shift_events": 1})

    if not rows:
        return pd.DataFrame(columns=["player", "qoc", "qot", "shift_events"])

    gdf = pd.DataFrame(rows)
    out = []
    for player, grp in gdf.groupby("player"):
        def _wmean(col: str) -> float:
            mask = np.isfinite(grp[col].values)
            if not mask.any():
                return float("nan")
            w = grp.loc[mask, "shift_events"].values
            return float(np.average(grp.loc[mask, col].values, weights=w))

        out.append({
            "player": player,
            "qoc": _wmean("qoc"),
            "qot": _wmean("qot"),
            "shift_events": int(grp["shift_events"].sum()),
        })
    return pd.DataFrame(out)


def _resolve_team_name(df: pd.DataFrame, team_hint: str) -> str | None:
    teams = [t for t in df["team"].unique() if t and str(t) != "nan"]
    if team_hint in teams:
        return team_hint
    hint = team_hint.lower()
    for tm in teams:
        if hint in tm.lower():
            return tm
    return None


def compute_league_context(pbp_files: list[Path], team_hint: str) -> dict[str, Any]:
    """Game-score lookup + season QOC/QOT for all skaters in the PBP sample."""
    from .disk_cache import cache_path, load_json, pbp_files_fingerprint, save_json

    fp = pbp_files_fingerprint(pbp_files)
    cache_file = cache_path("league_ctx", fp, "context.json")
    hit = load_json(cache_file, ttl_seconds=7 * 86_400)
    if isinstance(hit, dict) and hit.get("players") is not None:
        return hit

    result = _compute_league_context(pbp_files, team_hint)
    save_json(cache_file, result)
    return result


def _compute_league_context(pbp_files: list[Path], team_hint: str) -> dict[str, Any]:
    """Uncached league context build."""
    from .pbp_team_cache import get_team_frames, warm_team_pbp

    warm_team_pbp(pbp_files)
    game_frames = get_team_frames(pbp_files)

    gs_game: dict[tuple[str, str], float] = {}
    gs_season_acc: dict[str, list[float]] = defaultdict(list)

    for path, raw in game_frames:
        try:
            df = _norm_df(raw)
        except Exception:
            continue
        if not {"team", "player", "action"}.issubset(df.columns):
            continue
        gid = _game_id(path)
        for tm in df["team"].unique():
            if not tm or str(tm) == "nan":
                continue
            gs = compute_microstat_game_score(df, tm)
            for _, row in gs.iterrows():
                gs_game[(row["player"], gid)] = float(row["game_score"])
                gs_season_acc[row["player"]].append(float(row["game_score"]))

    gs_season = {p: float(np.mean(v)) for p, v in gs_season_acc.items() if v}

    qoc_game_rows: list[dict[str, Any]] = []

    for path, raw in game_frames:
        try:
            df = _norm_df(raw)
        except Exception:
            continue
        gid = _game_id(path)
        for tm in df["team"].unique():
            if not tm or str(tm) == "nan":
                continue
            qdf = _qoc_qot_game(df, tm, gid, gs_game, gs_season)
            for _, row in qdf.iterrows():
                qoc_game_rows.append({
                    "player": row["player"],
                    "team": tm,
                    "game_id": gid,
                    "qoc": row["qoc"],
                    "qot": row["qot"],
                })

    if not qoc_game_rows:
        return {"players": {}, "gs_season": gs_season}

    qdf = pd.DataFrame(qoc_game_rows)
    season = qdf.groupby("player", as_index=False).agg(
        qoc=("qoc", "mean"),
        qot=("qot", "mean"),
        gp=("game_id", "nunique"),
    )
    for col in ("qoc", "qot"):
        vals = season[col].dropna()
        if len(vals) > 1:
            season[f"{col}_pct"] = season[col].rank(pct=True).round(3)

    players: dict[str, dict[str, Any]] = {}
    for _, row in season.iterrows():
        players[row["player"]] = {
            "qoc": round(float(row["qoc"]), 2) if pd.notna(row["qoc"]) else None,
            "qot": round(float(row["qot"]), 2) if pd.notna(row["qot"]) else None,
            "qoc_pct": float(row["qoc_pct"]) if pd.notna(row.get("qoc_pct")) else None,
            "qot_pct": float(row["qot_pct"]) if pd.notna(row.get("qot_pct")) else None,
            "gp": int(row["gp"]),
        }

    return {"players": players, "gs_season": gs_season}


def compute_player_qoc_qot(
    pbp_files: list[Path],
    player_name: str,
    team_full: str,
) -> dict[str, Any] | None:
    """QOC/QOT metrics for one player from deployment shift blocks."""
    ctx = compute_league_context(pbp_files, team_full)
    for pname, metrics in ctx["players"].items():
        if _match_player_name(pname, player_name):
            return {
                "qoc": {"label": "QOC", "key": "qoc", "value": metrics["qoc"], "percentile": metrics.get("qoc_pct")},
                "qot": {"label": "QOT", "key": "qot", "value": metrics["qot"], "percentile": metrics.get("qot_pct")},
                "gp": metrics.get("gp"),
                "source": "pbp_deployment",
            }
    return None
