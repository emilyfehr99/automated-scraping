"""Per-player PBP microstats + shot map from local InStat CSVs."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from .instat_source import NHL_TEAM_SEARCH, _match_player_name, discover_team_pbp_files
from .pbp_team_cache import get_team_frames, warm_team_pbp

DZ_LIMIT = 22.86
NZ_LIMIT = 38.10
NET_X, NET_Y = 60.96, 12.96

ENTRY_ACTIONS = ["Entries", "Entries via pass", "Entries via stickhandling", "Entries via dump in"]
EXIT_ACTIONS = ["Breakouts", "Breakouts via pass", "Breakouts via stickhandling", "Breakouts via dump out", "Dump outs"]
POSSESSION_EXITS = ["Breakouts via pass", "Breakouts via stickhandling"]
NON_PLAY = {"Even strength shifts", "Power play shifts", "Penalty kill shifts"}
SHOT_ACTIONS = {"Shots", "Shots on goal", "Goals", "Missed shots", "Blocked shots"}
TURNOVER_ACTIONS = {
    "Puck losses", "Puck losses in DZ", "Puck losses in NZ", "Puck losses in OZ", "Inaccurate passes",
}

COUNT_MAP = {
    "Entries": "Zone Entries",
    "Entries via stickhandling": "Carry-ins",
    "Entries via pass": "Pass Entries",
    "Entries via dump in": "Dump-in Entries",
    "Dump ins": "Dump ins",
    "Shots": "Shots",
    "Shots on goal": "SOG",
    "Goals": "Goals",
    "Scoring chances": "Chances",
    "Passes": "Passes",
    "Puck recoveries in DZ": "DZ Retrievals",
    "Breakouts": "Zone Exits",
    "Breakouts via pass": "Pass Exits",
    "Breakouts via stickhandling": "Carried Exits",
    "Forecheck recoveries": "Forecheck Recoveries",
    "Blocked shots": "Blocked Shots",
    "Shots blocking": "Blocked Shots (DF)",
    "Faceoffs in DZ": "Faceoffs DZ",
    "Faceoffs in NZ": "Faceoffs NZ",
    "Faceoffs in OZ": "Faceoffs OZ",
    "Faceoffs won": "Faceoffs Won",
    "Faceoffs lost": "Faceoffs Lost",
}


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _is_turnover(action: str) -> bool:
    a = _norm(action)
    return a in {x.lower() for x in TURNOVER_ACTIONS} or a.startswith("puck losses") or "inaccurate" in a


def _is_shot(action: str) -> bool:
    a = _norm(action)
    return a in {x.lower() for x in SHOT_ACTIONS} or a.startswith("shot")


def _xg(px: float, py: float) -> float:
    try:
        dx = max(0.0, NET_X - float(px))
        dy = abs(NET_Y - float(py))
    except (TypeError, ValueError):
        return 0.0
    dist = math.hypot(dx, dy)
    ang = math.atan2(dy, dx + 1e-9)
    z = -1.12 - 0.09 * dist - 1.6 * ang
    return 1.0 / (1.0 + math.exp(-z))


def _play_df(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df["action"].isin(NON_PLAY)].reset_index(drop=True)


def _player_mask(df: pd.DataFrame, player_name: str, team_full: str) -> pd.Series:
    pm = df["player"].apply(lambda p: _match_player_name(p, player_name))
    if team_full:
        tm = df["team"].astype(str).str.contains(team_full.split()[-1], case=False, na=False)
        # Traded players may appear under a prior team in this season's PBP files.
        if (pm & tm).any():
            return pm & tm
    return pm


def _analyze_game(df: pd.DataFrame, player_name: str, team_full: str) -> dict[str, Any] | None:
    if df.empty:
        return None
    df = df.copy()
    df["pos_x"] = pd.to_numeric(df.get("pos_x"), errors="coerce")
    df["pos_y"] = pd.to_numeric(df.get("pos_y"), errors="coerce")
    if "start" in df.columns:
        df = df.sort_values(["half", "start"]).reset_index(drop=True)
    mask = _player_mask(df, player_name, team_full)
    if not mask.any():
        return None

    stats: dict[str, float] = {v: 0.0 for v in set(COUNT_MAP.values())}
    shots: list[dict[str, Any]] = []
    xg_total = 0.0
    chances_xg = 0.0

    for _, row in df[mask].iterrows():
        act = str(row.get("action", "")).strip()
        label = COUNT_MAP.get(act)
        if label:
            stats[label] = stats.get(label, 0) + 1
        if _is_shot(act) and act != "Blocked shots":
            px, py = row.get("pos_x"), row.get("pos_y")
            if pd.notna(px) and pd.notna(py):
                xg = _xg(px, py)
                xg_total += xg
                if xg >= 0.08:
                    chances_xg += 1
                shots.append({
                    "x": round(float(px), 2),
                    "y": round(float(py), 2),
                    "xg": round(xg, 3),
                    "goal": act == "Goals",
                })

    stats["xG"] = round(xg_total, 3)
    if stats.get("Chances", 0) == 0:
        stats["Chances"] = chances_xg

    # Zone exits rollup
    stats["Zone Exits"] = (
        stats.get("Zone Exits", 0) + stats.get("Pass Exits", 0) + stats.get("Carried Exits", 0)
    )
    stats["Exits w/ Possession"] = stats.get("Pass Exits", 0) + stats.get("Carried Exits", 0)

    # Computed sequence metrics (player as actor)
    failed_entries = successful_entries = dump_chances = entries_w_chance = 0
    failed_exits = successful_breakouts = botched_ret = 0
    rush_shots = fc_shots = 0

    pmask = mask
    entry_idx = df[pmask & df["action"].isin(ENTRY_ACTIONS)].index.tolist()
    for idx in entry_idx:
        row = df.loc[idx]
        window = _play_df(df.iloc[idx + 1 : idx + 31])
        if window.empty:
            continue
        is_dump = "dump" in _norm(row["action"])
        success = False
        to_shot = False
        if not is_dump:
            first2 = window.iloc[:2]
            if len(first2) == 2:
                opp = bool((first2["team"] != row["team"]).any())
                to = bool(((first2["team"] == row["team"]) & first2["action"].apply(_is_turnover)).any())
                success = not opp and not to
            elif len(first2) == 1:
                nxt = first2.iloc[0]
                success = nxt["team"] == row["team"] and not _is_turnover(nxt["action"])
        else:
            look = window.iloc[:10]
            oz = look[
                (look["team"] == row["team"])
                & (look["pos_x"] >= NZ_LIMIT)
                & (look["action"].isin(["Puck recoveries", "Puck recoveries in DZ", "Puck battles", "Puck battles in OZ"]))
            ]
            if not oz.empty:
                success = True
                dump_chances += 1
        if success:
            successful_entries += 1
        fut3 = df.iloc[idx + 1 : idx + 4]
        if not fut3.empty and bool(((fut3["team"] == row["team"]) & fut3["action"].apply(_is_turnover)).any()):
            failed_entries += 1
        for _, r in window.iloc[:10].iterrows():
            if r["team"] != row["team"]:
                break
            if _is_turnover(r["action"]):
                break
            if _norm(r["action"]) == "shots":
                to_shot = True
                break
        if to_shot:
            entries_w_chance += 1

    exit_idx = df[pmask & df["action"].isin(EXIT_ACTIONS) & (df["pos_x"] <= DZ_LIMIT)].index.tolist()
    for idx in exit_idx:
        window = _play_df(df.iloc[idx + 1 : idx + 21])
        exited = window[(window["team"] == df.loc[idx, "team"]) & (window["pos_x"] > DZ_LIMIT)]
        if not exited.empty:
            post = window.loc[exited.index[0] + 1 : exited.index[0] + 3]
            if post.empty or not bool((post["team"] != df.loc[idx, "team"]).any()):
                to_mask = (post["team"] == df.loc[idx, "team"]) & post["action"].apply(_is_turnover)
                if not bool(to_mask.any()):
                    successful_breakouts += 1
        fut = _play_df(df.iloc[idx + 1 : idx + 8])
        opp_press = (fut["team"] != df.loc[idx, "team"]) & fut["action"].apply(
            lambda a: _norm(a) in {"entries", "shots"} or _is_shot(a)
        )
        if not fut.empty and bool(opp_press.any()):
            failed_exits += 1

    ret_idx = df[pmask & df["action"].isin(["Puck recoveries in DZ", "Puck recoveries"])].index.tolist()
    for idx in ret_idx:
        nxt = df.iloc[idx + 1] if idx + 1 < len(df) else None
        if nxt is not None and _is_turnover(nxt.get("action", "")) and nxt["team"] == df.loc[idx, "team"]:
            botched_ret += 1

    stats["Failed Entries"] = failed_entries
    stats["Successful Entries"] = successful_entries
    stats["Dump-in Chances"] = dump_chances
    stats["Entries w/ Chance"] = entries_w_chance
    stats["Failed Exits"] = failed_exits
    stats["Successful Breakouts"] = successful_breakouts
    stats["Botched Retrievals"] = botched_ret
    stats["Rush Shots"] = rush_shots
    stats["FC/Cycle Shots"] = fc_shots
    stats["Retrievals Leading to Exits"] = 0  # needs sequence; leave 0 unless we add later

    entries = stats.get("Zone Entries", 0)
    if entries > 0:
        stats["Carry-in%"] = round(100 * stats.get("Carry-ins", 0) / entries, 1)
    exits = stats.get("Zone Exits", 0)
    if exits > 0:
        stats["Exits w/ Possession %"] = round(100 * stats.get("Exits w/ Possession", 0) / exits, 1)

    return {"stats": stats, "shots": shots}


def aggregate_player_pbp(
    player_name: str,
    team: str,
    *,
    files: list[Path] | None = None,
    team_games: int | None = None,
) -> dict[str, Any] | None:
    """Aggregate PBP microstats across every team game file (rates / team games)."""
    files = files or discover_team_pbp_files(team)
    if not files:
        return None
    team_full = NHL_TEAM_SEARCH.get(team.upper(), team)
    totals: dict[str, float] = {}
    all_shots: list[dict] = []
    game_files: list[dict[str, Any]] = []
    games = team_games if team_games is not None else len(files)
    games_played = 0

    warm_team_pbp(files)
    for path, df in get_team_frames(files):
        entry: dict[str, Any] = {"file": path.name, "path": str(path), "played": False, "events": 0}
        mask = _player_mask(df, player_name, team_full)
        entry["events"] = int(mask.sum())
        result = _analyze_game(df, player_name, team_full)
        if not result:
            game_files.append(entry)
            continue
        entry["played"] = True
        games_played += 1
        for k, v in result["stats"].items():
            totals[k] = totals.get(k, 0) + float(v)
        all_shots.extend(result["shots"])
        game_files.append(entry)

    if games_played == 0:
        return None

    # Per-game rates use the full team game sample (including games the player did not dress).
    per_game = {k: round(v / games, 2) for k, v in totals.items()}
    return {
        "games": games,
        "games_played": games_played,
        "game_files": game_files,
        "per_game": per_game,
        "shots": all_shots,
        "xg_total": round(sum(s["xg"] for s in all_shots), 2),
        "goals": int(totals.get("Goals", 0)),
        "source": "instat_api",
    }
