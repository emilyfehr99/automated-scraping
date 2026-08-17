"""Per-player PBP microstats + shot map from local InStat CSVs."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from .instat_source import NHL_TEAM_SEARCH, _match_player_name, discover_team_pbp_files
from .leagues import team_full_name
from .pbp_team_cache import get_team_frames, warm_team_pbp
from .pwhl_bio import _is_team_match
from .qoc_qot import compute_microstat_game_score

DZ_LIMIT = 22.86
NZ_LIMIT = 38.10
NET_X, NET_Y = 60.96, 12.96

ENTRY_ACTIONS = ["Entries", "Entries via pass", "Entries via stickhandling", "Entries via dump in"]
EXIT_ACTIONS = ["Breakouts", "Breakouts via pass", "Breakouts via stickhandling", "Breakouts via dump out", "Dump outs"]
POSSESSION_EXITS = ["Breakouts via pass", "Breakouts via stickhandling"]
NON_PLAY = {"Even strength shifts", "Power play shifts", "Penalty kill shifts"}
SHOT_ACTIONS = {"Shots", "Shots on goal", "Goals", "Missed shots", "Blocked shots"}
# Offensive shot-map events only. InStat repeats the same physical shot as
# Shots + SOG (+ Goals); we dedupe those. Never plot "Shots blocking" (DF).
SHOT_MAP_ACTIONS = frozenset({
    "Shots",
    "Shots on goal",
    "Goals",
    "Missed shots",
    "Power play shots",
    "Short-handed shots",
})
SHOT_MAP_PRIORITY = {
    "Goals": 0,
    "Shots on goal": 1,
    "Power play shots": 2,
    "Short-handed shots": 2,
    "Shots": 3,
    "Missed shots": 4,
}
ASSIST_SHOT_ACTIONS = frozenset({
    "Shots", "Goals", "Shots on goal", "Missed shots", "Power play shots", "Short-handed shots",
})
PASS_ACTIONS = frozenset({"Passes", "Passes to the slot"})
TURNOVER_ACTIONS = {
    "Puck losses", "Puck losses in DZ", "Puck losses in NZ", "Puck losses in OZ", "Inaccurate passes",
}
HD_XG = 0.08
HD_DIST = 15.0

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
    if a in {"shots blocking", "blocked shots", "shots blocked"}:
        return False
    return a in {x.lower() for x in SHOT_ACTIONS} or (
        a.startswith("shot") and "block" not in a
    )


def _is_assist_shot(action: str) -> bool:
    a = str(action or "").strip()
    if not a or "block" in a.lower():
        return False
    return a in ASSIST_SHOT_ACTIONS or (a.startswith("Shot") and "block" not in a.lower())


def _pass_before_shot(
    actions: list[str],
    teams: list[str],
    players: list[str],
    shot_i: int,
    *,
    chance_only: bool = False,
    xg_vals: list[float] | None = None,
    pos_x: list[float] | None = None,
    pos_y: list[float] | None = None,
) -> bool:
    """True when the event before a shot is a teammate pass (primary assist)."""
    if actions[shot_i] == "Blocked shots" or "block" in str(actions[shot_i] or "").lower():
        return False
    if chance_only:
        xg = float(xg_vals[shot_i] if xg_vals else 0)
        px = float(pos_x[shot_i] if pos_x else 0)
        py = float(pos_y[shot_i] if pos_y else 0)
        dist = math.hypot(NET_X - px, abs(NET_Y - py))
        if xg < HD_XG and dist > HD_DIST:
            return False
    shooter = players[shot_i]
    team = teams[shot_i]
    for j in range(shot_i - 1, max(shot_i - 4, -1), -1):
        if teams[j] != team:
            return False
        if _is_turnover(actions[j]):
            return False
        if actions[j] in PASS_ACTIONS:
            return players[j] != shooter
        if _is_assist_shot(actions[j]):
            return False
    return False


def _count_chance_assists(
    df: pd.DataFrame,
    player_name: str,
    team_full: str,
) -> int:
    """Passes by player immediately preceding a teammate high-danger shot."""
    tm = _resolve_team_name(df, team_full)
    if not tm:
        return 0
    game = df.copy()
    game["pos_x"] = pd.to_numeric(game.get("pos_x"), errors="coerce")
    game["pos_y"] = pd.to_numeric(game.get("pos_y"), errors="coerce")
    if "start" in game.columns:
        game = game.sort_values(["half", "start"]).reset_index(drop=True)
    actions = game["action"].astype(str).tolist()
    teams = game["team"].astype(str).tolist()
    players = game["player"].astype(str).tolist()
    pos_x = game["pos_x"].tolist()
    pos_y = game["pos_y"].tolist()
    if "xG_final" in game.columns:
        xg_vals = pd.to_numeric(game["xG_final"], errors="coerce").fillna(0).tolist()
    else:
        xg_vals = [
            _xg(float(px), float(py)) if pd.notna(px) and pd.notna(py) else 0.0
            for px, py in zip(pos_x, pos_y)
        ]

    assists = 0
    for i, action in enumerate(actions):
        if not _is_assist_shot(action):
            continue
        if _match_player_name(players[i], player_name):
            continue
        if teams[i] != tm:
            continue
        if not _pass_before_shot(
            actions,
            teams,
            players,
            i,
            chance_only=True,
            xg_vals=xg_vals,
            pos_x=pos_x,
            pos_y=pos_y,
        ):
            continue
        for j in range(i - 1, max(i - 4, -1), -1):
            if teams[j] != teams[i]:
                break
            if actions[j] in PASS_ACTIONS and _match_player_name(players[j], player_name) and teams[j] == tm:
                assists += 1
                break
            if _is_turnover(actions[j]) or _is_assist_shot(actions[j]):
                break
    return assists


def _count_one_timers(
    df: pd.DataFrame,
    player_name: str,
    team_full: str,
    *,
    max_seconds: float = 1.0,
) -> int:
    """Shots by player within max_seconds of a preceding teammate pass."""
    tm = _resolve_team_name(df, team_full)
    if not tm:
        return 0
    game = df.copy()
    if "start" in game.columns:
        game["start"] = pd.to_numeric(game["start"], errors="coerce")
        game = game.sort_values(["half", "start"]).reset_index(drop=True)
    actions = game["action"].astype(str).tolist()
    teams = game["team"].astype(str).tolist()
    players = game["player"].astype(str).tolist()
    starts = game["start"].tolist() if "start" in game.columns else [None] * len(game)

    one_timers = 0
    for i, action in enumerate(actions):
        if not _is_assist_shot(action) or action == "Blocked shots":
            continue
        if not _match_player_name(players[i], player_name) or teams[i] != tm:
            continue
        shot_time = starts[i]
        for j in range(i - 1, max(i - 5, -1), -1):
            if teams[j] != teams[i]:
                break
            if _is_turnover(actions[j]):
                break
            if actions[j] in PASS_ACTIONS:
                if _match_player_name(players[j], player_name):
                    break
                if shot_time is not None and starts[j] is not None:
                    if float(shot_time) - float(starts[j]) <= max_seconds:
                        one_timers += 1
                elif j == i - 1:
                    one_timers += 1
                break
            if _is_assist_shot(actions[j]):
                break
    return one_timers


def _xg(px: float, py: float, row: dict[str, Any] | None = None) -> float:
    """Canonical xG via v3 pipeline when available; legacy logistic fallback."""
    try:
        analytics_metrics = Path(__file__).resolve().parents[2] / "analytics-metrics"
        if analytics_metrics.is_dir():
            import sys
            if str(analytics_metrics) not in sys.path:
                sys.path.insert(0, str(analytics_metrics))
            from python.pipeline_bridge import compute_row_xg
            payload = {"pos_x": px, "pos_y": py, **(row or {})}
            return float(compute_row_xg(payload, use_instat=False))
    except Exception:
        pass
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
    if df.empty or "player" not in df.columns:
        return pd.Series(False, index=df.index)
    raw_names = df["player"].dropna().unique()
    matching_names = [n for n in raw_names if _match_player_name(str(n), player_name)]
    if not matching_names:
        return pd.Series(False, index=df.index)
    pm = df["player"].isin(matching_names)
    if team_full and "team" in df.columns:
        tm = df["team"].astype(str).str.contains(team_full.split()[-1], case=False, na=False)
        if (pm & tm).any():
            return pm & tm
    return pm


def _analyze_game(df: pd.DataFrame, player_name: str, team_full: str) -> dict[str, Any] | None:
    if df.empty:
        return None
    mask = _player_mask(df, player_name, team_full)
    if not mask.any():
        return None

    stats: dict[str, float] = {v: 0.0 for v in set(COUNT_MAP.values())}
    shot_candidates: dict[tuple, dict[str, Any]] = {}
    xg_total = 0.0
    chances_xg = 0.0

    for _, row in df[mask].iterrows():
        act = str(row.get("action", "")).strip()
        label = COUNT_MAP.get(act)
        if label:
            stats[label] = stats.get(label, 0) + 1
        # Offensive shot map: one marker per physical shot (InStat emits
        # Shots + SOG + Goals as separate rows at the same start/end/pos).
        if act in SHOT_MAP_ACTIONS:
            px, py = row.get("pos_x"), row.get("pos_y")
            if pd.isna(px) or pd.isna(py):
                continue
            xg = _xg(px, py)
            start = row.get("start")
            end = row.get("end")
            half = row.get("half")
            key = (
                str(start) if pd.notna(start) else "",
                str(end) if pd.notna(end) else "",
                str(half) if pd.notna(half) else "",
                round(float(px), 3),
                round(float(py), 3),
            )
            cand = {
                "x": round(float(px), 2),
                "y": round(float(py), 2),
                "xg": round(xg, 3),
                "goal": act == "Goals",
                "action": act,
                "_pri": SHOT_MAP_PRIORITY.get(act, 9),
            }
            prev = shot_candidates.get(key)
            if prev is None or cand["_pri"] < prev["_pri"]:
                shot_candidates[key] = cand

    shots: list[dict[str, Any]] = []
    for cand in shot_candidates.values():
        xg = float(cand["xg"])
        xg_total += xg
        if xg >= 0.08:
            chances_xg += 1
        shots.append({
            "x": cand["x"],
            "y": cand["y"],
            "xg": cand["xg"],
            "goal": bool(cand["goal"]),
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
    stats["Chance Assists"] = float(_count_chance_assists(df, player_name, team_full))
    stats["One Timers"] = float(_count_one_timers(df, player_name, team_full))

    entries = stats.get("Zone Entries", 0)
    if entries > 0:
        stats["Carry-in%"] = round(100 * stats.get("Carry-ins", 0) / entries, 1)
    exits = stats.get("Zone Exits", 0)
    if exits > 0:
        stats["Exits w/ Possession %"] = round(100 * stats.get("Exits w/ Possession", 0) / exits, 1)

    return {"stats": stats, "shots": shots}


def _resolve_team_name(df: pd.DataFrame, team_full: str) -> str | None:
    for tm in df["team"].astype(str).unique():
        t = tm.strip()
        if not t or t.lower() == "nan":
            continue
        if _is_team_match(t, team_full):
            return t
    return None


def _game_microstat_gs(
    df: pd.DataFrame,
    player_name: str,
    team_full: str,
) -> tuple[float, float, float]:
    """Per-game microstat GS + offense/defense split for one skater."""
    tm = _resolve_team_name(df, team_full)
    if not tm:
        return 0.0, 0.0, 0.0
    gs_df = compute_microstat_game_score(df, tm)
    for _, row in gs_df.iterrows():
        if _match_player_name(str(row["player"]), player_name):
            return (
                float(row["game_score"]),
                float(row["offense_gs"]),
                float(row["defense_gs"]),
            )
    return 0.0, 0.0, 0.0


def aggregate_player_pbp(
    player_name: str,
    team: str,
    *,
    files: list[Path] | None = None,
    team_games: int | None = None,
    league: str | None = "nhl",
) -> dict[str, Any] | None:
    """Aggregate PBP microstats across every team game file (rates / team games)."""
    files = files or discover_team_pbp_files(team)
    if not files:
        return None
    team_full = team_full_name(league, team)
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
        gs, off_gs, def_gs = _game_microstat_gs(df, player_name, team_full)
        totals["Microstat Game Score"] = totals.get("Microstat Game Score", 0) + gs
        totals["Microstat Offense"] = totals.get("Microstat Offense", 0) + off_gs
        totals["Microstat Defense"] = totals.get("Microstat Defense", 0) + def_gs
        all_shots.extend(result["shots"])
        game_files.append(entry)

    if games_played == 0:
        return None

    # Per-game rates use the full team game sample (including games the player did not dress).
    per_game = {k: round(v / games, 2) for k, v in totals.items()}
    assists = int(totals.get("Assists", 0) or totals.get("Chance Assists", 0))
    # Map alignment: keep only markers the shot map will draw, then derive
    # Shots/Goals/xG rates from that same set (never COUNT_MAP alone).
    from .shot_map import _parse_shot

    plottable: list[dict] = [s for s in all_shots if _parse_shot(s) is not None]
    all_shots = plottable
    shot_count = len(all_shots)
    goals = sum(1 for s in all_shots if s.get("goal"))
    xg_total = round(sum(float(s.get("xg") or 0) for s in all_shots), 2)
    if games:
        per_game["Shots"] = round(shot_count / games, 2)
        per_game["Goals"] = round(goals / games, 2)
        per_game["xG"] = round(xg_total / games, 2)
        per_game["Assists"] = round(assists / games, 2)
        sog_n = float(totals.get("SOG", 0) or 0)
        if sog_n:
            per_game["SOG"] = round(sog_n / games, 2)
    # count_totals["Shots"/"Goals"] must match plottable markers (COUNT_MAP
    # rows inflate Shots when InStat logs Shots+SOG+Goals for one event).
    count_totals = {
        k: int(round(v)) for k, v in totals.items() if isinstance(v, (int, float))
    }
    count_totals["Shots"] = int(shot_count)
    count_totals["Goals"] = int(goals)
    if assists:
        count_totals["Assists"] = int(assists)
    return {
        "schema_version": 11,
        "games": games,
        "games_played": games_played,
        "game_files": game_files,
        "per_game": per_game,
        "shots": all_shots,
        "shot_count": shot_count,
        "xg_total": xg_total,
        "goals": goals,
        "assists": assists,
        "points": goals + assists,
        "count_totals": count_totals,
        "source": "instat_api",
    }


def aggregate_player_pbp_multi(
    player_name: str,
    teams: list[tuple[str, list[Path], int | None]],
    *,
    league: str | None = "nhl",
) -> dict[str, Any] | None:
    """Merge PBP across teams for players traded mid-season / dual-roster juniors.

    Absolute counting stats (Goals, Shots, …) are summed from each club's
    integer totals — never reconstructed from rounded per-game rates (that
    truncated e.g. 10 PBP goals → 9 on Schultz dual-roster cards).
    """
    rate_accum: dict[str, float] = {}
    count_totals: dict[str, float] = {}
    all_shots: list[dict[str, Any]] = []
    all_game_files: list[dict[str, Any]] = []
    games_played = 0
    team_games = 0
    goals = 0
    assists = 0
    shot_count = 0

    for team_abbrev, files, team_game_count in teams:
        if not files:
            continue
        agg = aggregate_player_pbp(
            player_name,
            team_abbrev,
            files=files,
            team_games=team_game_count,
            league=league,
        )
        if not agg:
            continue
        gp = int(agg.get("games_played") or 0)
        tg = int(agg.get("games") or 0)
        games_played += gp
        team_games += tg
        all_shots.extend(agg.get("shots") or [])
        all_game_files.extend(agg.get("game_files") or [])
        goals += int(agg.get("goals") or 0)
        assists += int(agg.get("assists") or 0)
        shot_count += int(agg.get("shot_count") or 0)
        # Prefer each club's integer count_totals (never rate*games — that
        # drifts SOG etc. after rounding). Fall back to rate*tg only if absent.
        club_counts = agg.get("count_totals") or {}
        if club_counts:
            for key, n in club_counts.items():
                if isinstance(n, (int, float)):
                    count_totals[key] = count_totals.get(key, 0.0) + float(n)
        for key, rate in (agg.get("per_game") or {}).items():
            rate_accum[key] = rate_accum.get(key, 0.0) + float(rate) * tg
            if key not in club_counts:
                count_totals[key] = count_totals.get(key, 0.0) + float(rate) * tg

    if games_played == 0 or team_games == 0:
        return None

    # Align map shots/goals with what the shot map actually draws.
    from .shot_map import _parse_shot

    plottable = [s for s in all_shots if _parse_shot(s) is not None]
    all_shots = plottable
    shot_count = len(all_shots)
    goals = sum(1 for s in all_shots if s.get("goal"))
    xg_total = round(sum(float(s.get("xg") or 0) for s in all_shots), 2)

    count_totals["Goals"] = float(goals)
    count_totals["Shots"] = float(shot_count)
    if assists:
        count_totals["Assists"] = float(assists)
        count_totals["Chance Assists"] = float(
            max(float(count_totals.get("Chance Assists") or 0), assists)
        )

    per_game = {k: round(v / team_games, 2) for k, v in rate_accum.items()}
    if team_games:
        per_game["Goals"] = round(goals / team_games, 2)
        per_game["Shots"] = round(shot_count / team_games, 2)
        per_game["xG"] = round(xg_total / team_games, 2)
        per_game["Assists"] = round(assists / team_games, 2)
        sog_n = float(count_totals.get("SOG", 0) or 0)
        if sog_n:
            per_game["SOG"] = round(sog_n / team_games, 2)

    return {
        "schema_version": 11,
        "games": team_games,
        "games_played": games_played,
        "game_files": all_game_files,
        "per_game": per_game,
        "shots": all_shots,
        "shot_count": shot_count,
        "xg_total": xg_total,
        "goals": goals,
        "assists": assists,
        "points": goals + assists,
        "source": "instat_api",
        "count_totals": {k: int(round(v)) for k, v in count_totals.items()},
    }
