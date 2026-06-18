"""Forward lines, defensive pairings, zone deployment, and QoC/QoT from INstat PBP."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from .analytics_engine import load_goalie_roster, shot_attempt_rows, goal_event_keys, row_is_goal
from .roster_utils import is_goalie_player, load_goalie_name_set
from .constants import DZ_LIMIT, NZ_LIMIT, SHIFT_ACTIONS

ES_SHIFT = "Even strength shifts"
GOAL_ACTION = "Goals"


@dataclass(frozen=True)
class UnitKey:
    players: tuple[str, ...]

    def label(self) -> str:
        return ", ".join(self.players)


def _short_label(players: list[str]) -> str:
    return "-".join(p.split(" ", 1)[0] for p in players if p)


def _pct(num: float, den: float) -> float | None:
    if den <= 0:
        return None
    return round(100.0 * num / den, 1)


def _empty_counts() -> dict[str, Any]:
    return {"sog_for": 0, "sog_against": 0, "g_for": 0, "g_against": 0, "xg_for": 0.0, "xg_against": 0.0}


def _is_goal_row(row: pd.Series, goal_keys: set[tuple[str, int, str]] | None = None) -> bool:
    return row_is_goal(row, goal_keys)


def _identify_goalies(df: pd.DataFrame, roster_goalies: set[str]) -> set[str]:
    goalies = set(roster_goalies)
    if df.empty:
        return goalies
    for p, g in df.groupby("player"):
        pname = str(p)
        if pname in roster_goalies:
            goalies.add(pname)
            continue
        shift_rows = g[g["action"] == ES_SHIFT]
        other_n = len(g) - len(shift_rows)
        total_shift = int(shift_rows["duration"].sum()) if not shift_rows.empty else 0
        max_shift = int((shift_rows["end"] - shift_rows["start"]).max()) if not shift_rows.empty else 0
        if (total_shift >= 2000 and other_n <= 30) or (max_shift >= 500 and other_n <= 50):
            goalies.add(pname)
    return goalies


def _sweep_segments(
    shifts: pd.DataFrame,
    goalies: set[str],
    team: str,
    position_by_player: dict[str, str] | None = None,
) -> list[tuple[int, int, tuple[str, ...]]]:
    s = shifts[(shifts["team"] == team) & (shifts["action"] == ES_SHIFT)].copy()
    if s.empty:
        return []
    goalie_names = load_goalie_name_set() | goalies
    s = s[
        ~s["player"].apply(
            lambda p: is_goalie_player(
                str(p),
                (position_by_player or {}).get(str(p), ""),
                goalie_names,
            )
        )
    ]
    events: list[tuple[int, int, str]] = []
    for _, r in s.iterrows():
        if pd.isna(r.get("start")) or pd.isna(r.get("end")):
            continue
        st, en = int(r["start"]), int(r["end"])
        p = str(r["player"])
        if en <= st:
            continue
        events.append((st, +1, p))
        events.append((en, -1, p))
    events.sort(key=lambda x: (x[0], -x[1]))

    on: dict[str, int] = defaultdict(int)
    segments: list[tuple[int, int, tuple[str, ...]]] = []
    last_t: int | None = None

    def cur() -> tuple[str, ...]:
        return tuple(sorted(p for p, n in on.items() if n > 0))

    for t, delta, p in events:
        if last_t is not None and t > last_t:
            sk = cur()
            if len(sk) == 5:
                segments.append((last_t, t, sk))
        on[p] += delta
        if on[p] <= 0:
            on.pop(p, None)
        last_t = t
    return segments


def _unit_seconds(segments: Iterable[tuple[int, int, tuple[str, ...]]], k: int) -> dict[UnitKey, int]:
    secs: dict[UnitKey, int] = defaultdict(int)
    for t0, t1, skaters in segments:
        dt = int(t1 - t0)
        if dt <= 0 or len(skaters) != 5:
            continue
        sk = list(skaters)
        if k == 2:
            for i in range(5):
                for j in range(i + 1, 5):
                    secs[UnitKey(tuple(sorted((sk[i], sk[j]))))] += dt
        elif k == 3:
            for i in range(5):
                for j in range(i + 1, 5):
                    for m in range(j + 1, 5):
                        secs[UnitKey(tuple(sorted((sk[i], sk[j], sk[m]))))] += dt
    return secs


def _units_in_segment(skaters: tuple[str, ...], unit_keys: set[UnitKey], k: int) -> list[UnitKey]:
    sk = list(skaters)
    out: list[UnitKey] = []
    if k == 2:
        for i in range(5):
            for j in range(i + 1, 5):
                uk = UnitKey(tuple(sorted((sk[i], sk[j]))))
                if uk in unit_keys:
                    out.append(uk)
    else:
        for i in range(5):
            for j in range(i + 1, 5):
                for m in range(j + 1, 5):
                    uk = UnitKey(tuple(sorted((sk[i], sk[j], sk[m]))))
                    if uk in unit_keys:
                        out.append(uk)
    return out


def _event_counts_for_units(
    segments: list[tuple[int, int, tuple[str, ...]]],
    df: pd.DataFrame,
    *,
    team: str,
    unit_keys: set[UnitKey],
    k: int,
) -> dict[UnitKey, dict[str, Any]]:
    counts = {uk: _empty_counts() for uk in unit_keys}
    if not segments or not unit_keys:
        return counts
    segs = sorted(segments, key=lambda x: x[0])
    ev = shot_attempt_rows(df).sort_values("start")
    goal_keys_by_game: dict[str, set[tuple[str, int, str]]] = {}
    for gid in ev["game_id"].dropna().unique():
        goal_keys_by_game[str(gid)] = goal_event_keys(df[df["game_id"] == gid])
    si = 0
    nseg = len(segs)
    for _, r in ev.iterrows():
        t = int(r["start"])
        while si < nseg and segs[si][1] <= t:
            si += 1
        if si >= nseg:
            break
        t0, t1, skaters = segs[si]
        if not (t0 <= t < t1) or len(skaters) != 5:
            continue
        is_for = str(r["team"]) == team
        xgk = "xg_for" if is_for else "xg_against"
        sk = "sog_for" if is_for else "sog_against"
        xg = float(r.get("xG_final") or 0)
        gk_keys = goal_keys_by_game.get(str(r.get("game_id") or ""), set())
        is_goal = _is_goal_row(r, gk_keys)
        for uk in _units_in_segment(skaters, unit_keys, k):
            counts[uk][sk] += 1
            counts[uk][xgk] += xg
            if is_goal:
                gk = "g_for" if is_for else "g_against"
                counts[uk][gk] += 1
    return counts


def _pack_unit(uk: UnitKey, seconds: int, counts: dict[str, Any], kind: str) -> dict[str, Any]:
    sog_f, sog_a = int(counts.get("sog_for", 0)), int(counts.get("sog_against", 0))
    g_f, g_a = int(counts.get("g_for", 0)), int(counts.get("g_against", 0))
    xg_f, xg_a = float(counts.get("xg_for", 0)), float(counts.get("xg_against", 0))
    return {
        "unit": _short_label(list(uk.players)),
        "players": list(uk.players),
        "type": kind,
        "toi_sec": seconds,
        "toi_min": round(seconds / 60, 1),
        "gf": g_f,
        "ga": g_a,
        "sf": sog_f,
        "sa": sog_a,
        "xgf": round(xg_f, 2),
        "xga": round(xg_a, 2),
        "gf_pct": _pct(g_f, g_f + g_a),
        "sf_pct": _pct(sog_f, sog_f + sog_a),
        "xgf_pct": _pct(xg_f, xg_f + xg_a),
    }


def _pick_unique(units: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    picked: list[dict[str, Any]] = []
    used: set[str] = set()
    for u in sorted(units, key=lambda x: x.get("toi_sec", 0), reverse=True):
        players = set(u.get("players", []))
        if players and used.isdisjoint(players):
            picked.append(u)
            used |= players
        if len(picked) >= n:
            return picked
    for u in sorted(units, key=lambda x: x.get("toi_sec", 0), reverse=True):
        if u not in picked:
            picked.append(u)
        if len(picked) >= n:
            break
    return picked


def _zone_from_x(x: float) -> str | None:
    if pd.isna(x):
        return None
    if x <= DZ_LIMIT:
        return "DZ"
    if x > NZ_LIMIT:
        return "OZ"
    return "NZ"


def _game_score_row(pdf: pd.DataFrame) -> float:
    """Proxy game score from micro events (Clarkson deployment script)."""
    if pdf.empty:
        return 0.0
    score = 0.0
    score += int((pdf["action"] == "Goals").sum()) * 3
    score += int((pdf["action"] == "Shots").sum()) * 0.3
    score += int((pdf["action"].isin({"Entries via stickhandling", "Entries via pass"})).sum()) * 0.4
    score += int((pdf["action"].isin({"Breakouts via pass", "Breakouts via stickhandling"})).sum()) * 0.35
    score += int((pdf["action"] == "Puck recoveries in DZ").sum()) * 0.25
    score -= int((pdf["action"].isin({"Puck losses", "Inaccurate passes"})).sum()) * 0.2
    return score


def _compute_deployment_qoc(
    df_game: pd.DataFrame,
    team: str,
    skaters: set[str],
    goalies: set[str],
    gs_lookup: dict[tuple[str, str], float],
    game_id: str,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Return (deployment accum, qoc_qot accum) per player for one game."""
    dep: dict[str, dict[str, float]] = defaultdict(lambda: {"oz": 0.0, "nz": 0.0, "dz": 0.0})
    qoc: dict[str, dict[str, float]] = defaultdict(lambda: {"qoc_sum": 0.0, "qot_sum": 0.0, "n": 0.0})

    shifts = df_game[df_game["action"].isin(SHIFT_ACTIONS) & df_game["player"].notna()].copy()
    if shifts.empty:
        return dep, qoc

    for player in skaters:
        ps = shifts[(shifts["team"] == team) & (shifts["player"] == player) & (shifts["action"] == ES_SHIFT)]
        for _, row in ps.iterrows():
            z = _zone_from_x(float(row.get("pos_x") or float("nan")))
            if z == "OZ":
                dep[player]["oz"] += 1
            elif z == "NZ":
                dep[player]["nz"] += 1
            elif z == "DZ":
                dep[player]["dz"] += 1

    for (_, _), grp in shifts.groupby(["start", "action"], dropna=False):
        team_players = [
            str(p) for p in grp.loc[grp["team"] == team, "player"].dropna().unique()
            if str(p) in skaters and str(p) not in goalies
        ]
        if not team_players:
            continue
        opp = [str(p) for p in grp.loc[grp["team"] != team, "player"].dropna().unique() if str(p) not in goalies]
        opp_gs = [gs_lookup.get((game_id, p), 0.0) for p in opp]
        opp_gs = [g for g in opp_gs if g > 0]
        qoc_val = sum(opp_gs) / len(opp_gs) if opp_gs else 0.0
        for pl in team_players:
            mates = [m for m in team_players if m != pl]
            mate_gs = [gs_lookup.get((game_id, m), 0.0) for m in mates]
            mate_gs = [g for g in mate_gs if g > 0]
            qot_val = sum(mate_gs) / len(mate_gs) if mate_gs else 0.0
            qoc[pl]["qoc_sum"] += qoc_val
            qoc[pl]["qot_sum"] += qot_val
            qoc[pl]["n"] += 1
    return dep, qoc


def _finalize_deployment(dep_acc: dict[str, dict[str, float]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for player, z in dep_acc.items():
        total = z["oz"] + z["nz"] + z["dz"]
        if total <= 0:
            continue
        out[player] = {
            "OZ Shift %": _pct(z["oz"], total),
            "NZ Shift %": _pct(z["nz"], total),
            "DZ Shift %": _pct(z["dz"], total),
            "oz_shifts": int(z["oz"]),
            "nz_shifts": int(z["nz"]),
            "dz_shifts": int(z["dz"]),
        }
    return out


def _finalize_qoc(qoc_acc: dict[str, dict[str, float]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for player, v in qoc_acc.items():
        n = v["n"]
        if n <= 0:
            continue
        out[player] = {
            "QoC": round(v["qoc_sum"] / n, 2),
            "QoT": round(v["qot_sum"] / n, 2),
            "shift_blocks": int(n),
        }
    return out


def _is_defense(pos: str) -> bool:
    p = (pos or "").upper().strip()
    return p in {"D", "LD", "RD", "DG"} or p.startswith("D")


def _build_team_units(
    df: pd.DataFrame,
    team: str,
    defense_players: set[str],
    roster_goalies: set[str],
    position_by_player: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    goalies = _identify_goalies(df[df["team"] == team], roster_goalies)
    goalie_names = load_goalie_name_set() | goalies

    def is_forward_skater(name: str) -> bool:
        if is_goalie_player(name, position_by_player.get(name, ""), goalie_names):
            return False
        return name not in defense_players

    def is_defense_skater(name: str) -> bool:
        if is_goalie_player(name, position_by_player.get(name, ""), goalie_names):
            return False
        pos = position_by_player.get(name, "")
        return name in defense_players or _is_defense(pos)

    trio_secs: dict[UnitKey, int] = defaultdict(int)
    pair_secs: dict[UnitKey, int] = defaultdict(int)
    all_segments: list[tuple[int, int, tuple[str, ...]]] = []

    for gid, gdf in df.groupby("game_id"):
        gteam = gdf[gdf["team"] == team]
        if gteam.empty:
            continue
        segs = _sweep_segments(gteam, goalies, team, position_by_player)
        all_segments.extend(segs)
        for uk, sec in _unit_seconds(segs, 3).items():
            trio_secs[uk] += sec
        for uk, sec in _unit_seconds(segs, 2).items():
            pair_secs[uk] += sec

    min_line_sec = 45
    min_pair_sec = 90
    forward_all = [
        (uk, sec) for uk, sec in trio_secs.items()
        if sec >= min_line_sec and all(is_forward_skater(p) for p in uk.players)
    ]
    forward_all.sort(key=lambda x: x[1], reverse=True)
    pairs_all = [
        (uk, sec) for uk, sec in pair_secs.items()
        if sec >= min_pair_sec and all(is_defense_skater(p) for p in uk.players)
    ]
    pairs_all.sort(key=lambda x: x[1], reverse=True)

    trio_keys = {uk for uk, _ in forward_all}
    pair_keys = {uk for uk, _ in pairs_all}

    team_gids = df.loc[df["team"] == team, "game_id"].unique()
    events_df = df[df["game_id"].isin(team_gids)]
    trio_counts = _event_counts_for_units(all_segments, events_df, team=team, unit_keys=trio_keys, k=3)
    pair_counts = _event_counts_for_units(all_segments, events_df, team=team, unit_keys=pair_keys, k=2)

    all_trios = [_pack_unit(uk, sec, trio_counts.get(uk, _empty_counts()), "line") for uk, sec in forward_all]
    all_pairs = [_pack_unit(uk, sec, pair_counts.get(uk, _empty_counts()), "pairing") for uk, sec in pairs_all]

    return {
        "lines": _pick_unique(all_trios, 4),
        "pairings": _pick_unique(all_pairs, 3),
        "all_lines": all_trios,
        "all_pairings": all_pairs,
    }


def run_league_units_and_deployment(
    df: pd.DataFrame,
    teams: list[str],
    position_by_player: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """
    Returns:
      team_units: {team: {lines, pairings, ...}}
      player_deployment: {instat_name: {OZ Shift %, ...}}
      player_qoc: {instat_name: {QoC, QoT, ...}}
    """
    if df.empty:
        return {}, {}, {}

    roster_g = load_goalie_roster()
    all_goalies: set[str] = set()
    for names in roster_g.values():
        all_goalies.update(names)

    gs_lookup: dict[tuple[str, str], float] = {}
    for gid, gdf in df.groupby("game_id"):
        for team in teams:
            tdf = gdf[gdf["team"] == team]
            if tdf.empty:
                continue
            for player in tdf["player"].dropna().unique():
                pname = str(player)
                pdf = tdf[tdf["player"] == pname]
                gs_lookup[(str(gid), pname)] = _game_score_row(pdf)

    dep_acc: dict[str, dict[str, float]] = defaultdict(lambda: {"oz": 0.0, "nz": 0.0, "dz": 0.0})
    qoc_acc: dict[str, dict[str, float]] = defaultdict(lambda: {"qoc_sum": 0.0, "qot_sum": 0.0, "n": 0.0})

    team_units: dict[str, dict[str, Any]] = {}

    for team in teams:
        tdf = df[df["team"] == team]
        if tdf.empty:
            continue
        skaters = {str(p) for p in tdf["player"].dropna().unique() if str(p) not in all_goalies}
        defense = {p for p in skaters if _is_defense(position_by_player.get(p, ""))}
        team_goalies = set(roster_g.get(team, [])) | _identify_goalies(tdf, all_goalies)

        team_units[team] = _build_team_units(df, team, defense, team_goalies, position_by_player)

        for gid, gdf in df.groupby("game_id"):
            dep_g, qoc_g = _compute_deployment_qoc(
                gdf, team, skaters, team_goalies, gs_lookup, str(gid),
            )
            for pl, z in dep_g.items():
                for k in ("oz", "nz", "dz"):
                    dep_acc[pl][k] += z[k]
            for pl, v in qoc_g.items():
                qoc_acc[pl]["qoc_sum"] += v["qoc_sum"]
                qoc_acc[pl]["qot_sum"] += v["qot_sum"]
                qoc_acc[pl]["n"] += v["n"]

    return team_units, _finalize_deployment(dep_acc), _finalize_qoc(qoc_acc)
