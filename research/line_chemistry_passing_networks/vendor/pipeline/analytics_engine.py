"""League-wide PWHL microstats from INstat PBP CSV exports."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from .constants import (
    BREAKOUT_ACTIONS,
    DZ_LIMIT,
    ENTRY_ACTIONS,
    NET_X,
    NET_Y,
    NZ_LIMIT,
    RECOVERY_ACTIONS,
    SEQ_WINDOW,
    SHIFT_ACTIONS,
    SHOT_ACTIONS,
    XG_SUM_ACTIONS,
)
from .json_utils import safe_float
from .roster_utils import (
    build_position_by_instat,
    defense_mask_for_pdf,
    is_defense,
    is_goalie_player,
    load_goalie_name_set,
)

ROOT = Path(__file__).resolve().parents[1]
PBP_DIR = ROOT / "data" / "pbp"
GOALIE_ROSTER_FILE = ROOT / "data" / "goalie_roster.json"
GAME_GOALIES_FILE = ROOT / "data" / "game_goalies.json"


def load_goalie_roster() -> dict[str, list[str]]:
    if not GOALIE_ROSTER_FILE.exists():
        return {}
    import json
    with open(GOALIE_ROSTER_FILE) as f:
        return json.load(f)


def load_game_goalies() -> dict[str, dict[str, str]]:
    if not GAME_GOALIES_FILE.exists():
        return {}
    import json
    with open(GAME_GOALIES_FILE) as f:
        return json.load(f)


def _norm_team(name: str) -> str:
    return name.replace("é", "e").strip().lower()


def shot_attempt_rows(pdf: pd.DataFrame) -> pd.DataFrame:
    """One row per shot attempt for xG (SOG + goals not already counted as SOG)."""
    sog = pdf[pdf["action"] == "Shots on goal"]
    goals = pdf[pdf["action"] == "Goals"]
    if sog.empty and goals.empty:
        return pdf.iloc[0:0].copy()
    sog_keys = set(zip(sog["game_id"], sog["start"], sog["player"]))
    extra = goals[
        ~goals.apply(lambda r: (r["game_id"], r["start"], r["player"]) in sog_keys, axis=1)
    ]
    if extra.empty:
        return sog.copy()
    return pd.concat([sog, extra])


def goal_event_keys(pdf: pd.DataFrame) -> set[tuple[str, int, str]]:
    """Keys for scored goals: (game_id, start, player)."""
    keys: set[tuple[str, int, str]] = set()
    goals = pdf[pdf["action"] == "Goals"]
    for _, row in goals.iterrows():
        if pd.isna(row.get("start")):
            continue
        keys.add((
            str(row.get("game_id") or ""),
            int(row["start"]),
            str(row.get("player") or ""),
        ))
    return keys


def row_is_goal(row: pd.Series, goal_keys: set[tuple[str, int, str]] | None = None) -> bool:
    """True when a shot attempt row represents a scored goal."""
    if str(row.get("action") or "") == "Goals":
        return True
    if goal_keys is not None and pd.notna(row.get("start")):
        key = (str(row.get("game_id") or ""), int(row["start"]), str(row.get("player") or ""))
        if key in goal_keys:
            return True
    if "Result" in row.index and pd.notna(row.get("Result")):
        return "Goal" in str(row["Result"])
    return False


def sum_shot_xg(pdf: pd.DataFrame) -> float:
    """Sum xG once per shot attempt (SOG + goals not already counted as SOG)."""
    attempts = shot_attempt_rows(pdf)
    if attempts.empty:
        return 0.0
    return sum(safe_float(x) for x in attempts["xG_final"])


def _instat_name_variants(display: str) -> list[str]:
    parts = str(display or "").strip().split()
    if len(parts) < 2:
        return [display] if display else []
    return [display, f"{parts[-1]} {' '.join(parts[:-1])}"]


def _goalie_from_shifts(
    gdf: pd.DataFrame,
    team: str,
    roster_goalies: list[str],
) -> str | None:
    """Infer starting goalie from shift rows when game_goalies map is missing."""
    if not roster_goalies:
        return None
    players = gdf.loc[gdf["team"] == team, "player"].dropna().astype(str)
    counts = players.value_counts()
    best: tuple[int, str] | None = None
    for rn in roster_goalies:
        for variant in _instat_name_variants(rn):
            c = int(counts.get(variant, 0))
            if c and (best is None or c > best[0]):
                best = (c, variant)
    return best[1] if best else None


def _goalie_for_game(game_goalies: dict[str, dict[str, str]], game_id: str, team: str) -> str | None:
    gmap = game_goalies.get(str(game_id), {})
    if team in gmap:
        return gmap[team]
    for tname, gname in gmap.items():
        if _norm_team(tname) == _norm_team(team):
            return gname
    return None


def calculate_location_xg(x: float, y: float) -> float:
    """Distance/angle expected goal probability (PWHL-calibrated logistic)."""
    from .xg_model import compute_location_xg

    return compute_location_xg(x, y)


def _normalize_shot_context_columns(g: pd.DataFrame) -> None:
    """Map joined INstat shot columns (visibility, goalie position, save detail) to model flags."""
    vis = g.get("Visibility")
    if vis is not None:
        vs = vis.astype(str).str.lower()
        g["is_screen_shot"] = vs.str.contains("screen", na=False)
        g["is_clean_view"] = vs.str.contains("clean", na=False)
    pos = g.get("Position_Save_Detail")
    if pos is not None:
        ps = pos.astype(str).str.lower()
        g["is_butterfly"] = ps.str.contains("butterfly", na=False)
        g["is_goalie_in_motion"] = ps.str.contains("motion", na=False)
    save = g.get("Save_Detail")
    if save is not None:
        ss = save.astype(str).str.lower()
        g["is_uncontrolled_rebound"] = ss.str.contains("uncontrolled rebound", na=False)
    if "is_rebound_after" in g.columns:
        g["is_rebound_shot"] = g["is_rebound_shot"] | g["is_rebound_after"].fillna(False)

    from .goalie_shot_enrichment import enrich_shot_context_dataframe
    from .strength_inference import annotate_strength_state
    from .xg_shot_proxies import apply_xg_shot_proxies

    annotate_strength_state(g)
    enrich_shot_context_dataframe(g)
    apply_xg_shot_proxies(g)


def load_pbp_files(directory: Path | None = None) -> pd.DataFrame:
    pbp_dir = directory or PBP_DIR
    files = sorted(pbp_dir.glob("game_*_pbp.csv"))
    if not files:
        return pd.DataFrame()
    parts: list[pd.DataFrame] = []
    for f in files:
        try:
            d = pd.read_csv(f, low_memory=False)
            d["game_id"] = f.stem.replace("game_", "").replace("_pbp", "")
            parts.append(d)
        except Exception:
            continue
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    numeric_cols = ("pos_x", "pos_y", "start", "end", "duration", "xG", "Net_Goalie_X", "Net_Goalie_Y")
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["team"].notna() & (df["team"].astype(str).str.strip() != "")]
    return df


def _zone(pos_x: float) -> str:
    if pd.isna(pos_x):
        return "NZ"
    if pos_x <= DZ_LIMIT:
        return "DZ"
    if pos_x > NZ_LIMIT:
        return "OZ"
    return "NZ"


CYCLE_ACTION = "Puck recoveries in OZ"
CYCLE_SHOT_ACTIONS = frozenset({
    *SHOT_ACTIONS,
    "Missed shots",
    "Power play shots",
    "Short-handed shots",
})


def _mark_cycle_shots(df: pd.DataFrame) -> None:
    """Flag shot attempts that follow an OZ forecheck recovery (within 5 prior plays)."""
    from .sequence_logic import is_sequence_neutral

    actions = df["action"].astype(str).values
    teams = df["team"].astype(str).values
    flags = df["is_cycle_shot"].values.copy()
    for i in range(len(df)):
        if actions[i] not in CYCLE_SHOT_ACTIONS:
            continue
        team_i = teams[i]
        for j in range(i - 1, max(i - 6, -1), -1):
            if is_sequence_neutral(actions[j]):
                continue
            if teams[j] != team_i:
                break
            if actions[j] == CYCLE_ACTION:
                flags[i] = True
                break
    df["is_cycle_shot"] = flags


SHOT_ACTION_STRS = frozenset(SHOT_ACTIONS)
ENTRY_SHOT_ACTIONS = SHOT_ACTION_STRS | {"Missed shots", "Power play shots", "Short-handed shots"}
# Shot attempts used for rebound detection (exclude duplicate "Shots" precursor rows).
REBOUND_PRIOR_ACTIONS = frozenset({
    "Shots on goal", "Goals", "Missed shots", "Power play shots", "Short-handed shots",
})


def _process_game_sequences(game: pd.DataFrame) -> pd.DataFrame:
    """Sequence flags for one game (sorted play stream, no cross-game leakage)."""
    sort_cols = [c for c in ("half", "start") if c in game.columns]
    g = game.sort_values(sort_cols).copy() if sort_cols else game.copy()
    g["zone"] = g["pos_x"].map(_zone)

    for c in (
        "is_support", "is_ret_succ", "is_botched", "is_entry_shot", "is_breakout_entry",
        "is_entry_denial", "is_rush_shot", "is_cycle_shot", "is_interception", "royal_road",
        "is_rebound_shot",
    ):
        g[c] = False

    teams = g["team"].astype(str).values
    actions = g["action"].astype(str).values
    players = g["player"].astype(str).values
    zones = g["zone"].astype(str).values
    pos_x = g["pos_x"].values
    pos_y = g["pos_y"].values
    from .sequence_logic import (
        breakout_leads_to_entry,
        entry_retains_possession,
        is_sequence_neutral,
        recovery_botched,
        retrieval_leads_to_breakout,
    )

    n = len(g)

    ret_succ = g["is_ret_succ"].values
    botched = g["is_botched"].values
    support = g["is_support"].values
    entry_shot = g["is_entry_shot"].values
    breakout_entry = g["is_breakout_entry"].values
    rush_shot = g["is_rush_shot"].values
    royal = g["royal_road"].values

    for i in range(n):
        if actions[i] in BREAKOUT_ACTIONS and breakout_leads_to_entry(actions, teams, i):
            breakout_entry[i] = True

    for i in range(n):
        team_i = teams[i]
        act_i = actions[i]
        if zones[i] == "DZ" and act_i in RECOVERY_ACTIONS:
            if retrieval_leads_to_breakout(actions, teams, i):
                ret_succ[i] = True
            if recovery_botched(actions, teams, i):
                botched[i] = True
        elif act_i == "Passes" and zones[i] == "DZ":
            if retrieval_leads_to_breakout(actions, teams, i):
                ret_succ[i] = True
        if act_i in ENTRY_ACTIONS:
            if entry_retains_possession(actions, teams, i, require_shot=True):
                entry_shot[i] = True
            for j in range(i + 1, min(i + SEQ_WINDOW + 1, n)):
                if is_sequence_neutral(actions[j]):
                    continue
                if teams[j] != team_i:
                    break
                if players[j] != players[i] and actions[j] in ("Passes", "Shots"):
                    support[i] = True
                    break

    for i in range(n):
        if actions[i] not in ENTRY_SHOT_ACTIONS:
            continue
        team_i = teams[i]
        for j in range(i - 1, max(i - 6, -1), -1):
            if is_sequence_neutral(actions[j]):
                continue
            if teams[j] != team_i:
                break
            if actions[j] in ("Entries via stickhandling", "Entries via pass"):
                rush_shot[i] = True
                break

    g["is_ret_succ"] = ret_succ
    g["is_botched"] = botched
    g["is_support"] = support
    g["is_entry_shot"] = entry_shot
    g["is_breakout_entry"] = breakout_entry
    g["is_rush_shot"] = rush_shot

    _mark_cycle_shots(g)

    # Royal road: same-team pass crossing center ice (y = NET_Y) within 4s before shot.
    starts = pd.to_numeric(g["start"], errors="coerce").values
    for i in range(n):
        if actions[i] not in ENTRY_SHOT_ACTIONS or actions[i] == "Shots":
            continue
        team_i = teams[i]
        cy = pos_y[i]
        t_i = starts[i]
        if pd.isna(cy):
            continue
        cy = float(cy)
        for j in range(i - 1, max(i - 8, -1), -1):
            if teams[j] != team_i:
                break
            if is_sequence_neutral(actions[j]) or actions[j] == "Shots":
                continue
            if actions[j] != "Passes":
                continue
            ly = pos_y[j]
            if pd.isna(ly):
                continue
            ly = float(ly)
            if pd.notna(t_i) and pd.notna(starts[j]) and float(t_i) - float(starts[j]) > 4.0:
                break
            if (ly > NET_Y >= cy) or (ly < NET_Y <= cy):
                royal[i] = True
                break
    g["royal_road"] = royal

    from .sequence_logic import shot_origin_zone_at_index

    origin = list(zones)
    halves = g["half"].values
    starts = pd.to_numeric(g["start"], errors="coerce").values
    for i in range(n):
        if actions[i] not in ENTRY_SHOT_ACTIONS:
            continue
        origin[i] = shot_origin_zone_at_index(
            list(actions), list(teams), list(zones), halves, starts, i
        )
    g["origin_zone"] = origin

    rebound = g["is_rebound_shot"].values
    for i in range(n):
        if actions[i] not in ENTRY_SHOT_ACTIONS or actions[i] == "Shots":
            continue
        team_i = teams[i]
        t_i = starts[i]
        for j in range(i - 1, max(i - 8, -1), -1):
            if is_sequence_neutral(actions[j]):
                continue
            if teams[j] != team_i:
                break
            if actions[j] == "Shots":
                continue
            if actions[j] not in REBOUND_PRIOR_ACTIONS:
                continue
            if pd.notna(t_i) and pd.notna(starts[j]) and float(t_i) - float(starts[j]) > 4.0:
                break
            rebound[i] = True
            break
    g["is_rebound_shot"] = rebound

    _normalize_shot_context_columns(g)

    from .xg_model import compute_row_xg

    g["calc_xg"] = g.apply(compute_row_xg, axis=1)
    if "xG" in g.columns:
        xg_col = pd.to_numeric(g["xG"], errors="coerce")
        g["xG_final"] = xg_col.where(xg_col > 0, g["calc_xg"])
    else:
        g["xG_final"] = g["calc_xg"]

    for i in range(n):
        act = actions[i]
        px = float(pos_x[i] or 0)
        g.iat[i, g.columns.get_loc("is_entry_denial")] = (
            act == "Hits"
            or (
                act in ("Puck recoveries", "Puck battles won", "Puck recoveries in NZ")
                and 20 <= px <= 32
            )
        )
        if i > 0 and act in ("Puck recoveries", "Puck battles won", "Puck recoveries in NZ"):
            if teams[i - 1] != teams[i]:
                g.iat[i, g.columns.get_loc("is_interception")] = True

    return g


def process_sequences(df: pd.DataFrame) -> pd.DataFrame:
    """Add tactical sequence flags (per-game windows only)."""
    if df.empty:
        return df
    parts = [_process_game_sequences(g) for _, g in df.groupby("game_id", sort=False)]
    return pd.concat(parts).sort_index()


def _pct(num: float, den: float) -> float | None:
    if den <= 0:
        return None
    return round(100.0 * num / den, 1)


def _mean_bool(series: pd.Series) -> float | None:
    s = series.dropna()
    if len(s) == 0:
        return None
    return round(float(s.mean()) * 100, 1)


def compute_skater_metrics(
    df: pd.DataFrame,
    team: str,
    position_by_instat: dict[str, str] | None = None,
    goalie_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    from .player_profiles import _game_metrics

    tdf = df[df["team"] == team].copy()
    if tdf.empty:
        return []
    skaters = tdf[~tdf["action"].isin(SHIFT_ACTIONS)]["player"].dropna().unique()
    gp = tdf.groupby("player")["game_id"].nunique()
    rows: list[dict[str, Any]] = []
    goalie_names = goalie_names if goalie_names is not None else load_goalie_name_set()

    per_game_keys = (
        "Goals", "Assists", "Shots", "Chances", "Passes", "Primary Shot Assists", "Chance Assists",
        "Rush Shots", "Cycle/FC Shots", "Zone Entries", "Carry-ins", "Dump-ins", "Pass Entries",
        "Carries w/ Chances", "Dump-in Chances", "Entries w/ Chance", "Failed Entries",
        "Forecheck Recoveries", "DZ Retrievals", "Retrievals Leading to Exits",
        "Zone Exits", "Exits w Possession", "Botched Retrievals", "Failed Exits",
        "Failed Breakouts", "Passes to Breakouts",
        "OZ Shots", "NZ Shots", "DZ Shots", "NZT", "NZTSA",
        "Entry Denials", "Interceptions", "Blocked Shots", "Hits",
        "Royal Road Shots", "High Danger Chances", "Missed Shots",
        "Power Play Shots", "Short-Handed Shots",
        "Faceoffs Won", "Faceoffs Lost", "Penalties", "Dump Outs",
        "Puck Battles Won", "Puck Battles Lost", "Rebounds Against",
        "PP TOI (min)", "SH TOI (min)",
    )
    hub_aliases = {
        "Scoring Chances": "Chances",
        "Shot Assists": "Primary Shot Assists",
        "Possession Exits": "Exits w Possession",
        "Exit off Retrieval": "Retrievals Leading to Exits",
        "Entry Scoring Chance": "Entries w/ Chance",
        "NZ Turnovers": "NZT",
        "SOGA off NZ": "NZTSA",
        "Shots off Forecheck": "Cycle/FC Shots",
    }

    for player in skaters:
        pdf = tdf[tdf["player"] == player]
        games = int(gp.get(player, 0))
        if games == 0:
            continue
        pos = (position_by_instat or {}).get(str(player), "")
        game_ids = pdf["game_id"].unique()
        game_ctx = df[df["game_id"].isin(game_ids)]
        base = _game_metrics(
            pdf,
            team,
            position=pos,
            player=str(player),
            goalie_names=goalie_names,
            context_df=game_ctx,
        )
        from .roster_utils import is_defense

        if is_defense(pos):
            dz = float(base.get("DZ Retrievals") or 0)
            if dz > 0:
                if base.get("Retrieval Success %") is None:
                    ret = float(base.get("Retrievals w Exit") or base.get("Retrievals Leading to Exits") or 0)
                    base["Retrieval Success %"] = round(100 * ret / dz, 1)
                if base.get("Botched Retrieval %") is None:
                    bot = float(base.get("Botched Retrievals") or 0)
                    base["Botched Retrieval %"] = round(100 * bot / dz, 1)
        row: dict[str, Any] = {
            "Player": player,
            "Team": team,
            "GP": games,
            **base,
        }
        row["Points"] = int(row.get("Goals") or 0) + int(row.get("Assists") or 0)
        row["Forecheck Rec."] = row.get("Forecheck Recoveries")
        for k in per_game_keys:
            v = row.get(k)
            if isinstance(v, (int, float)) and games > 0:
                row[f"{k}/G"] = round(float(v) / games, 1)
        row["xG/G"] = round(float(row.get("Total xG") or 0) / games, 2)
        if row.get("Forecheck Recoveries/G") is not None:
            row["Forecheck Rec./G"] = row["Forecheck Recoveries/G"]
        display_pg_aliases = {
            "FO Won/G": "Faceoffs Won/G",
            "FO Lost/G": "Faceoffs Lost/G",
            "PP Shots/G": "Power Play Shots/G",
            "SH Shots/G": "Short-Handed Shots/G",
        }
        for display, source in display_pg_aliases.items():
            if row.get(source) is not None:
                row[display] = row[source]
        for alias, source in hub_aliases.items():
            if row.get(source) is not None:
                row[alias] = row[source]
            src_pg = f"{source}/G"
            alias_pg = f"{alias}/G"
            if row.get(src_pg) is not None:
                row[alias_pg] = row[src_pg]
        rows.append(row)
    return rows


def _identify_goalies(df: pd.DataFrame, team: str, roster: dict[str, list[str]]) -> list[str]:
    if roster.get(team):
        return roster[team]
    # Fuzzy team match (Montréal vs Montreal)
    for tname, names in roster.items():
        if tname.replace("é", "e").lower() == team.replace("é", "e").lower():
            return names
    return []


def _shot_result(row: pd.Series) -> str:
    action = str(row.get("action", ""))
    if action == "Goals":
        return "Goal"
    if "Result" in row.index and pd.notna(row.get("Result")):
        res = str(row["Result"])
        if "Goal" in res:
            return "Goal"
    return "Save"


def compute_goalie_metrics(
    df: pd.DataFrame,
    team: str,
    roster: dict[str, list[str]] | None = None,
    game_goalies: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    from collections import defaultdict

    from .goalie_metrics import aggregate_goalie_shots, build_goalie_shots_for_game

    def _goalie_key(name: str) -> str:
        return " ".join(sorted(str(name or "").strip().lower().split()))

    game_goalies = game_goalies or load_game_goalies()
    roster_goalies = (roster or {}).get(team) or []
    if not roster_goalies:
        for tname, names in (roster or {}).items():
            if _norm_team(tname) == _norm_team(team):
                roster_goalies = names
                break
    by_goalie: dict[str, dict[str, Any]] = {}

    for gid in df["game_id"].unique():
        gid_s = str(gid)
        gdf = df[df["game_id"] == gid]
        goalie = _goalie_for_game(game_goalies, gid_s, team)
        if not goalie:
            goalie = _goalie_from_shifts(gdf, team, roster_goalies)
        if not goalie:
            continue
        shots = build_goalie_shots_for_game(gdf, team, goalie, gid_s)
        gk = _goalie_key(goalie)
        bucket = by_goalie.setdefault(gk, {"names": defaultdict(int), "shots": [], "games": set()})
        bucket["names"][goalie] += 1
        bucket["shots"].extend(shots)
        bucket["games"].add(gid_s)

    out: list[dict[str, Any]] = []
    for bucket in by_goalie.values():
        display = max(bucket["names"], key=bucket["names"].get)
        shots = bucket["shots"]
        agg = aggregate_goalie_shots(shots)
        if not agg:
            continue
        out.append({
            "Goalie": display,
            "Team": team,
            "GP": len(bucket["games"]),
            **agg,
        })
    return out


def compute_team_tactical(
    df: pd.DataFrame,
    team: str,
    position_by_instat: dict[str, str] | None = None,
    goalie_names: set[str] | None = None,
) -> dict[str, Any]:
    tdf = df[df["team"] == team]
    if tdf.empty:
        return {"team": team}
    goalie_names = goalie_names if goalie_names is not None else load_goalie_name_set()
    d_mask = defense_mask_for_pdf(tdf, position_by_instat, goalie_names)
    entries = int(tdf["action"].isin(ENTRY_ACTIONS).sum())
    carry = int((tdf["action"] == "Entries via stickhandling").sum())
    dz_rec_rows = tdf[tdf["action"].isin(RECOVERY_ACTIONS) & (tdf["zone"] == "DZ")]
    dz_rec = int(dz_rec_rows.shape[0])
    ret_w_exit = int(dz_rec_rows["is_ret_succ"].sum())
    poss_exits = int(tdf["action"].isin(["Breakouts via pass", "Breakouts via stickhandling"]).sum())
    zone_exits = int(tdf["action"].isin(list(BREAKOUT_ACTIONS) + ["Dump outs"]).sum())
    breakouts = int(tdf["action"].isin(BREAKOUT_ACTIONS).sum())
    breakouts_w_entry = int(tdf[tdf["action"].isin(BREAKOUT_ACTIONS)]["is_breakout_entry"].sum())
    from .sequence_logic import ENTRY_SHOT_ACTIONS

    shots = int(tdf["action"].isin(ENTRY_SHOT_ACTIONS).sum())
    sog = int((tdf["action"] == "Shots on goal").sum())
    goals = int((tdf["action"] == "Goals").sum())
    games = int(tdf["game_id"].nunique())
    xg = round(sum_shot_xg(tdf), 2)
    from .advanced_metrics import enrich_team_advanced

    game_ids = tdf["game_id"].unique()
    full_games = df[df["game_id"].isin(game_ids)]
    adv = enrich_team_advanced(full_games, team)
    shot_rows = tdf[tdf["action"].isin(SHOT_ACTIONS)]
    dz_d = tdf[d_mask & tdf["action"].isin(RECOVERY_ACTIONS) & (tdf["zone"] == "DZ")]
    pass_dz_d = tdf[d_mask & (tdf["action"] == "Passes") & (tdf["zone"] == "DZ")]
    return {
        "team": team,
        "games": games,
        "entries": entries,
        "carry_ins": carry,
        "carry_in_pct": _pct(carry, entries),
        "dz_retrievals": dz_rec,
        "possession_exits": poss_exits,
        "breakouts": breakouts,
        "breakouts_w_entry": breakouts_w_entry,
        "exit_off_retrieval_pct": _pct(ret_w_exit, dz_rec),
        "retrieval_success_pct": _mean_bool(dz_d["is_ret_succ"]),
        "pass_to_breakout_pct": _mean_bool(pass_dz_d["is_ret_succ"]),
        "shots": shots,
        "sog": sog,
        "goals": goals,
        "total_xg": xg,
        "xg_per_game": round(xg / max(1, games), 2),
        "nzt": adv.get("NZT"),
        "nztsa": adv.get("NZTSA"),
        "hd_chances": adv.get("High Danger Chances"),
        "failed_entries": adv.get("Failed Entries"),
        "failed_breakouts": adv.get("Failed Breakouts"),
        "entries_w_chance": adv.get("Entries w/ Chance"),
        "ozs_pct": adv.get("OZS %"),
        "nzs_pct": adv.get("NZS %"),
        "dzs_pct": adv.get("DZS %"),
        "rebounds_against": adv.get("Rebounds Against"),
        "rush_shots": int(tdf["is_rush_shot"].sum()),
        "cycle_shots": int(tdf["is_cycle_shot"].sum()),
        "exit_poss_pct": _pct(poss_exits, zone_exits),
        "botched_retrieval_pct": _mean_bool(dz_d["is_botched"]) if not dz_d.empty else None,
        "passes_to_breakouts": adv.get("Passes to Breakouts"),
        "failed_breakout_pct": adv.get("Failed Breakout %"),
    }


def run_league_analytics(
    pbp_dir: Path | None = None,
    rosters: dict[str, list[dict]] | None = None,
    df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    if df is None:
        raw = load_pbp_files(pbp_dir)
        if raw.empty:
            return {"error": "no_pbp_data", "teams": [], "skaters": [], "goalies": []}
        df = process_sequences(raw)
    elif df.empty:
        return {"error": "no_pbp_data", "teams": [], "skaters": [], "goalies": []}
    elif "is_entry_shot" not in df.columns:
        df = process_sequences(df)
    goalie_roster = load_goalie_roster()
    game_goalies = load_game_goalies()
    position_by_instat = build_position_by_instat(rosters or {})
    goalie_names = load_goalie_name_set()
    teams = sorted(df["team"].unique())
    team_rows = [
        compute_team_tactical(df, t, position_by_instat, goalie_names) for t in teams
    ]
    skater_rows: list[dict[str, Any]] = []
    goalie_rows: list[dict[str, Any]] = []
    for t in teams:
        skater_rows.extend(
            compute_skater_metrics(df, t, position_by_instat, goalie_names)
        )
        goalie_rows.extend(compute_goalie_metrics(df, t, goalie_roster, game_goalies))

    from .composite_scores import apply_composite_scores

    apply_composite_scores(skater_rows)
    return {
        "n_games": int(df["game_id"].nunique()),
        "n_teams": len(teams),
        "teams": team_rows,
        "skaters": skater_rows,
        "goalies": goalie_rows,
    }
