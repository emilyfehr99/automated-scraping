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
    """Per-player microstat game score for one team in one game (R port)."""
    team_df = df[(df["team"] == team_name) & df["player"].notna() & (df["player"] != "")].copy()
    if team_df.empty:
        return pd.DataFrame(columns=["player", "game_score"])

    skaters = [
        p for p in team_df["player"].unique()
        if p and not _is_probable_goalie(p, team_df)
    ]
    if not skaters:
        return pd.DataFrame(columns=["player", "game_score"])

    tg = team_df[team_df["player"].isin(skaters)].reset_index(drop=True)
    tg_idx = tg.index.tolist()

    def _count(mask: pd.Series, col: str) -> pd.Series:
        return tg.loc[mask, "player"].value_counts().rename(col)

    scoring = _count(
        (tg["action"] == "Shots") & (tg["pos_x"] >= 50) & (tg["pos_y"] >= 11) & (tg["pos_y"] <= 14),
        "Scoring_Chances",
    )

    assist_idx = [i for i in tg_idx if tg.at[i, "action"] == "Passes" and i < len(tg) - 1 and tg.at[i + 1, "action"] == "Shots"]
    shot_assists = tg.loc[assist_idx, "player"].value_counts().rename("Shot_Assists") if assist_idx else pd.Series(dtype=int)

    zone_entries = tg[tg["action"].isin(
        ["Entries", "Entries via stickhandling", "Entries via pass", "Entries via dump in"]
    )]["player"].value_counts().rename("Zone_Entries")

    carry_ins = tg[tg["action"].isin(["Entries", "Entries via stickhandling", "Entries via pass"])]["player"].value_counts().rename("Carry_ins")

    carry_idx = tg.index[tg["action"] == "Entries via stickhandling"].tolist()
    carry_hits = [i for i in carry_idx if _window_has(tg, i, 10, {"Shots"}, team_name)]
    carry_chance = tg.loc[carry_hits, "player"].value_counts().rename("Carries_with_Chances") if carry_hits else pd.Series(dtype=int)

    dump_idx = tg.index[tg["action"] == "Entries via dump in"].tolist()
    dump_hits = [i for i in dump_idx if _window_has(tg, i, 10, {"Shots"}, team_name)]
    dump_chance = tg.loc[dump_hits, "player"].value_counts().rename("Dump_in_Chances") if dump_hits else pd.Series(dtype=int)

    poss_exits = tg[
        tg["action"].isin(["Breakouts via stickhandling", "Breakouts via pass"]) & (tg["pos_x"] <= DZ_MAX)
    ]["player"].value_counts().rename("Possession_Exits")

    dz_idx = tg.index[(tg["action"] == "Puck recoveries in DZ") & (tg["pos_x"] <= DZ_MAX)].tolist()
    dz_hits = [i for i in dz_idx if _window_has(tg, i, 10, {"Shots"}, team_name)]
    dz_shots = tg.loc[dz_hits, "player"].value_counts().rename("DZ_Shots") if dz_hits else pd.Series(dtype=int)

    nz_idx = tg.index[(tg["action"] == "Puck recoveries") & (tg["pos_x"] > DZ_MAX) & (tg["pos_x"] <= NZ_MAX)].tolist()
    nz_hits = [i for i in nz_idx if _window_has(tg, i, 10, {"Shots"}, team_name)]
    nz_shots = tg.loc[nz_hits, "player"].value_counts().rename("NZ_Shots") if nz_hits else pd.Series(dtype=int)

    nz_turnovers = tg[
        tg["action"].isin(["Puck losses in NZ", "Inaccurate passes"])
        & (tg["pos_x"] > DZ_MAX)
        & (tg["pos_x"] <= NZ_MAX)
    ]["player"].value_counts().rename("NZ_Turnovers")

    df_off = tg.copy()
    df_off["offense_type"] = None
    df_off.loc[df_off["action"].isin(RUSH_ACTIONS), "offense_type"] = "Rush"
    df_off.loc[df_off["action"].isin(CYCLE_ACTIONS), "offense_type"] = "Cycle/Forecheck"
    lead_type = []
    for i in range(len(df_off)):
        if df_off.iloc[i]["action"] != "Shots":
            lead_type.append(np.nan)
            continue
        found = np.nan
        for k in range(1, 11):
            j = i - k
            if j < 0:
                break
            ot = df_off.iloc[j]["offense_type"]
            if pd.notna(ot):
                found = ot
                break
        lead_type.append(found)
    df_off["offense_lead"] = lead_type
    rush_shots = df_off[df_off["offense_lead"] == "Rush"]["player"].value_counts().rename("Shots_off_Rush")
    forec_shots = df_off[df_off["offense_lead"] == "Cycle/Forecheck"]["player"].value_counts().rename("Shots_off_Forecheck")

    fc_hits = [
        i for i in dump_idx
        if _window_has(tg, i, 10, {"Puck battles in OZ", "Shots", "Goals", "Passes"}, team_name)
    ]
    fc_recoveries = tg.loc[fc_hits, "player"].value_counts().rename("Forecheck_Recoveries") if fc_hits else pd.Series(dtype=int)

    parts = [
        scoring, shot_assists, zone_entries, carry_ins, carry_chance, dump_chance,
        poss_exits, dz_shots, nz_shots, nz_turnovers, rush_shots, forec_shots, fc_recoveries,
    ]
    out = pd.DataFrame({"player": skaters}).set_index("player")
    for s in parts:
        if s is not None and len(s):
            out = out.join(s.to_frame(), how="left")
    out = out.fillna(0)
    out["game_score"] = out.sum(axis=1)
    return out.reset_index()[["player", "game_score"]]


def _lookup_gs(player: str, game_id: str, gs_game: dict[tuple[str, str], float], gs_season: dict[str, float]) -> float:
    key = (player, game_id)
    if key in gs_game:
        return gs_game[key]
    return gs_season.get(player, float("nan"))


def _qoc_qot_game(df: pd.DataFrame, team_name: str, game_id: str, gs_game: dict, gs_season: dict) -> pd.DataFrame:
    shifts = df[df["action"].isin(SHIFT_ACTIONS) & df["player"].notna() & (df["player"] != "")].copy()
    if shifts.empty:
        return pd.DataFrame(columns=["player", "qoc", "qot", "shift_events"])

    rows: list[dict[str, Any]] = []
    for (start, action), block in shifts.groupby(["start", "action"], sort=False):
        team_players = block[block["team"] == team_name]["player"].unique().tolist()
        if not team_players:
            continue
        opp_players = block[block["team"] != team_name]["player"].unique().tolist()
        opp_players = [p for p in opp_players if not _is_probable_goalie(p, df)]
        skaters = [p for p in team_players if not _is_probable_goalie(p, df)]

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
