#!/usr/bin/env python3
"""
Line/pairing chemistry via passing networks — NHL InStat PBP analysis.

Builds complementary-skill scores from microstat profiles and pass-network
density, then validates against on-ice xGF%.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
VENDOR_PIPELINE = Path(__file__).resolve().parent / "vendor"
sys.path.insert(0, str(ROOT))
for _pwhl in (ROOT.parent / "pwhl-analytics", VENDOR_PIPELINE):
    if _pwhl.is_dir():
        sys.path.insert(0, str(_pwhl))
        break

# PBP lives in GitHub Actions cache at PLAYER_CARDS_WORK_ROOT (not Desktop).
_GH_PBP_ROOT = ROOT / ".player-cards-data"
if _GH_PBP_ROOT.is_dir() and not os.environ.get("PLAYER_CARDS_WORK_ROOT"):
    if any(_GH_PBP_ROOT.glob("**/Instat_API_Downloads/*_pbp.csv")):
        os.environ["PLAYER_CARDS_WORK_ROOT"] = str(_GH_PBP_ROOT)

from player_cards.instat_source import NHL_TEAM_SEARCH, _match_player_name  # noqa: E402
from player_cards.leagues import player_cards_work_root  # noqa: E402

from pipeline.line_pairing_engine import (  # noqa: E402
    UnitKey,
    _build_team_units,
    _empty_counts,
    _event_counts_for_units,
    _identify_goalies,
    _pack_unit,
    _sweep_segments,
    _unit_seconds,
)

OUT_DIR = Path(__file__).resolve().parent / "outputs"
NHL_API = "https://api-web.nhle.com/v1"
ROSTER_SEASON = "20252026"

DZ_LIMIT = 22.86
NZ_LIMIT = 38.10
NET_X, NET_Y = 60.96, 12.96

PASS_ACTIONS = frozenset({
    "Passes", "Accurate passes", "Passes to the slot", "Breakouts via pass",
    "Entries via pass",
})
NEUTRAL_ACTIONS = frozenset({
    "Even strength shifts", "Power play shifts", "Penalty kill shifts",
})
ENTRY_ACTIONS = frozenset({
    "Entries", "Entries via pass", "Entries via stickhandling", "Entries via dump in",
})
RETRIEVAL_ACTIONS = frozenset({"Puck recoveries in DZ", "Puck recoveries"})
SHOT_ACTIONS = frozenset({"Shots", "Shots on goal", "Goals", "Missed shots"})

SKILL_KEYS = ("entry_rate", "retrieval_rate", "exit_rate", "pass_rate", "shot_xg_rate")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.lower().strip())


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


def discover_nhl_pbp_files() -> list[Path]:
    """One PBP file per game_id from PLAYER_CARDS_WORK_ROOT (GitHub Actions cache layout)."""
    root = Path(os.environ.get("PLAYER_CARDS_WORK_ROOT", "") or player_cards_work_root())
    by_game: dict[str, Path] = {}
    for team_full in NHL_TEAM_SEARCH.values():
        d = root / team_full / "Instat_API_Downloads"
        if not d.is_dir():
            continue
        for fp in d.glob("*_pbp.csv"):
            gid = _game_id_from_path(fp)
            prev = by_game.get(gid)
            if prev is None or fp.stat().st_size > prev.stat().st_size:
                by_game[gid] = fp
    return sorted(by_game.values(), key=lambda p: p.name)


def _game_id_from_path(p: Path) -> str:
    m = re.search(r"_(\d+)_pbp\.csv$", p.name)
    return m.group(1) if m else p.stem


def load_pbp(files: list[Path]) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for fp in files:
        try:
            df = pd.read_csv(fp)
        except Exception:
            continue
        if df.empty:
            continue
        gid = _game_id_from_path(fp)
        df = df.copy()
        df["game_id"] = gid
        df["pos_x"] = pd.to_numeric(df.get("pos_x"), errors="coerce")
        df["pos_y"] = pd.to_numeric(df.get("pos_y"), errors="coerce")
        if "start" in df.columns:
            df["start"] = pd.to_numeric(df["start"], errors="coerce")
        parts.append(df)
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    sort_cols = [c for c in ("game_id", "half", "start") if c in out.columns]
    return out.sort_values(sort_cols).reset_index(drop=True)


def attach_xg(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    xgs: list[float] = []
    for _, row in out.iterrows():
        act = str(row.get("action", ""))
        if act in SHOT_ACTIONS and act != "Blocked shots":
            px, py = row.get("pos_x"), row.get("pos_y")
            xgs.append(_xg(px, py) if pd.notna(px) and pd.notna(py) else 0.0)
        else:
            xgs.append(0.0)
    out["xG_final"] = xgs
    return out


def fetch_nhl_positions() -> dict[str, str]:
    """Map InStat 'Last First' name -> position group (F/D/G)."""
    pos: dict[str, str] = {}
    for tri in NHL_TEAM_SEARCH:
        try:
            resp = httpx.get(
                f"{NHL_API}/roster/{tri}/{ROSTER_SEASON}",
                timeout=20.0,
                headers={"User-Agent": "LineChemistry/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue
        for group, code in (("forwards", "F"), ("defensemen", "D"), ("goalies", "G")):
            for p in data.get(group) or []:
                first = (p.get("firstName") or {}).get("default") or ""
                last = (p.get("lastName") or {}).get("default") or ""
                name = f"{last} {first}".strip()  # InStat format
                if name:
                    pos[name] = code
                alt = f"{first} {last}".strip()
                if alt:
                    pos.setdefault(alt, code)
    return pos


def _es_seconds_by_player(df: pd.DataFrame) -> dict[tuple[str, str], float]:
    """Approximate ES TOI from shift rows (player, team) -> seconds."""
    secs: dict[tuple[str, str], float] = defaultdict(float)
    shifts = df[df["action"] == "Even strength shifts"]
    for _, row in shifts.iterrows():
        st, en = row.get("start"), row.get("end")
        if pd.isna(st) or pd.isna(en):
            continue
        dt = float(en) - float(st)
        if dt <= 0:
            continue
        key = (str(row["player"]), str(row["team"]))
        secs[key] += dt
    return dict(secs)


def build_player_skills(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Per-player per-60 skill rates keyed by InStat name."""
    es_secs = _es_seconds_by_player(df)
    counts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    xg_sum: dict[str, float] = defaultdict(float)

    play = df[~df["action"].isin(NEUTRAL_ACTIONS)]
    for _, row in play.iterrows():
        player = str(row["player"])
        act = str(row["action"])
        team = str(row["team"])
        mins = es_secs.get((player, team), 0) / 60.0
        if mins < 5:
            continue
        if act in ENTRY_ACTIONS:
            counts[player]["entries"] += 1
        if act in RETRIEVAL_ACTIONS:
            counts[player]["retrievals"] += 1
        if act in ("Breakouts via pass", "Breakouts via stickhandling", "Breakouts"):
            counts[player]["exits"] += 1
        if act in PASS_ACTIONS:
            counts[player]["passes"] += 1
        if act in SHOT_ACTIONS and act != "Blocked shots":
            xg_sum[player] += float(row.get("xG_final") or 0)

    skills: dict[str, dict[str, float]] = {}
    for player, c in counts.items():
        team = next((t for (p, t), s in es_secs.items() if p == player and s > 0), "")
        mins = es_secs.get((player, team), 0) / 60.0
        if mins < 20:
            continue
        skills[player] = {
            "entry_rate": round(60 * c.get("entries", 0) / mins, 3),
            "retrieval_rate": round(60 * c.get("retrievals", 0) / mins, 3),
            "exit_rate": round(60 * c.get("exits", 0) / mins, 3),
            "pass_rate": round(60 * c.get("passes", 0) / mins, 3),
            "shot_xg_rate": round(60 * xg_sum.get(player, 0) / mins, 3),
            "es_min": round(mins, 1),
        }
    return skills


def infer_pass_edges(df: pd.DataFrame) -> list[tuple[str, str, str, str]]:
    """Return (game_id, passer, receiver, team) for inferred completed passes."""
    edges: list[tuple[str, str, str, str]] = []
    sort_cols = [c for c in ("half", "start") if c in df.columns]
    for gid, game in df.groupby("game_id"):
        g = game.sort_values(sort_cols) if sort_cols else game
        actions = g["action"].astype(str).tolist()
        teams = g["team"].astype(str).tolist()
        players = g["player"].astype(str).tolist()
        n = len(actions)
        for i in range(n):
            if actions[i] not in PASS_ACTIONS:
                continue
            passer, team = players[i], teams[i]
            for j in range(i + 1, min(i + 4, n)):
                if teams[j] != team:
                    break
                if actions[j] in NEUTRAL_ACTIONS:
                    continue
                recv = players[j]
                if recv != passer:
                    edges.append((str(gid), passer, recv, team))
                break
    return edges


def _zscore(vals: dict[str, float]) -> dict[str, float]:
    if not vals:
        return {}
    arr = np.array(list(vals.values()), dtype=float)
    mu, sigma = arr.mean(), arr.std()
    if sigma < 1e-9:
        return {k: 0.0 for k in vals}
    return {k: (v - mu) / sigma for k, v in vals.items()}


def complementarity_score(players: tuple[str, ...], skills: dict[str, dict[str, float]], kind: str) -> float:
    """
    Cross-skill complementarity: high entry × high retrieval across unit members.
    For D pairs emphasize entry↔retrieval; for F lines emphasize pass↔shot_xg diversity.
    """
    vecs = [skills.get(p) for p in players]
    vecs = [v for v in vecs if v]
    if len(vecs) < len(players):
        return float("nan")

    if kind == "pairing":
        # D pair: sum of entry_i * retrieval_j for i != j (classic transporter + retriever)
        score = 0.0
        for i, vi in enumerate(vecs):
            for j, vj in enumerate(vecs):
                if i == j:
                    continue
                score += vi["entry_rate"] * vj["retrieval_rate"]
                score += vi["exit_rate"] * vj["retrieval_rate"] * 0.5
        return round(score, 3)

    # Forward line: pass connectivity potential + entry/shot complementarity
    pass_rates = [v["pass_rate"] for v in vecs]
    entry_rates = [v["entry_rate"] for v in vecs]
    shot_rates = [v["shot_xg_rate"] for v in vecs]
    pass_var = float(np.std(pass_rates)) if len(pass_rates) > 1 else 0.0
    cross = 0.0
    for i in range(len(vecs)):
        for j in range(len(vecs)):
            if i != j:
                cross += entry_rates[i] * shot_rates[j]
    return round(cross + pass_var * 2.0, 3)


def pass_density(players: tuple[str, ...], edges: Counter[tuple[str, str]]) -> float:
    """Directed pass count among unit members (both directions)."""
    total = 0
    for a in players:
        for b in players:
            if a != b:
                total += edges.get((a, b), 0)
    return total


def build_unit_records(
    df: pd.DataFrame,
    teams: list[str],
    position_by_player: dict[str, str],
    skills: dict[str, dict[str, float]],
    pass_edges: list[tuple[str, str, str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    edge_counter: Counter[tuple[str, str]] = Counter()
    for _, passer, recv, _ in pass_edges:
        edge_counter[(passer, recv)] += 1

    all_lines: list[dict[str, Any]] = []
    all_pairs: list[dict[str, Any]] = []

    roster_g: dict[str, list[str]] = {}

    for team in teams:
        tdf = df[df["team"] == team]
        if tdf.empty:
            continue
        defense = {p for p in tdf["player"].astype(str).unique()
                   if position_by_player.get(str(p), "") == "D"}
        goalies = _identify_goalies(tdf, set())
        pos_map = {str(p): position_by_player.get(str(p), "") for p in tdf["player"].unique()}

        units = _build_team_units(df, team, defense, set(), pos_map)
        for u in units.get("all_lines", []):
            players = tuple(u["players"])
            rec = dict(u)
            rec["team"] = team
            rec["complementarity"] = complementarity_score(players, skills, "line")
            rec["pass_links"] = pass_density(players, edge_counter)
            rec["pass_links_per60"] = round(
                3600 * rec["pass_links"] / max(rec["toi_sec"], 1), 2
            )
            all_lines.append(rec)
        for u in units.get("all_pairings", []):
            players = tuple(u["players"])
            rec = dict(u)
            rec["team"] = team
            rec["complementarity"] = complementarity_score(players, skills, "pairing")
            rec["pass_links"] = pass_density(players, edge_counter)
            rec["pass_links_per60"] = round(
                3600 * rec["pass_links"] / max(rec["toi_sec"], 1), 2
            )
            all_pairs.append(rec)

    return all_lines, all_pairs


def validate_model(units: list[dict[str, Any]], *, min_shots: int = 8) -> dict[str, Any]:
    """Correlate chemistry metrics with on-ice xGF%."""
    rows = []
    for u in units:
        if u.get("toi_sec", 0) < 300:
            continue
        sf, sa = int(u.get("sf") or 0), int(u.get("sa") or 0)
        if sf + sa < min_shots:
            continue
        comp = u.get("complementarity")
        if comp is None or (isinstance(comp, float) and math.isnan(comp)):
            continue
        xgf_pct = u.get("xgf_pct")
        if xgf_pct is None or (isinstance(xgf_pct, float) and math.isnan(xgf_pct)):
            continue
        rows.append(u)

    if len(rows) < 10:
        return {"n": len(rows), "error": "insufficient units"}

    xgf = np.array([u["xgf_pct"] for u in rows], dtype=float)
    xgf60 = np.array([
        3600 * float(u.get("xgf") or 0) / max(int(u.get("toi_sec") or 1), 1)
        for u in rows
    ], dtype=float)
    comp = np.array([float(u["complementarity"]) for u in rows], dtype=float)
    pass60 = np.array([float(u.get("pass_links_per60") or 0) for u in rows], dtype=float)
    toi = np.array([u["toi_sec"] for u in rows], dtype=float)

    def _corr(a: np.ndarray, b: np.ndarray) -> float:
        mask = np.isfinite(a) & np.isfinite(b)
        a, b = a[mask], b[mask]
        if len(a) < 3 or np.std(a) < 1e-9 or np.std(b) < 1e-9:
            return float("nan")
        return float(np.corrcoef(a, b)[0, 1])

    # Combined chemistry index (z-scored)
    comp_mu, comp_sd = comp.mean(), comp.std()
    pass_mu, pass_sd = pass60.mean(), pass60.std()
    chem_index = np.zeros(len(rows))
    if comp_sd > 1e-9:
        chem_index += 0.6 * (comp - comp_mu) / comp_sd
    if pass_sd > 1e-9:
        chem_index += 0.4 * (pass60 - pass_mu) / pass_sd

    w = toi / toi.sum()
    x_mean = np.average(chem_index, weights=w)
    y_mean = np.average(xgf, weights=w)
    cov = np.average((chem_index - x_mean) * (xgf - y_mean), weights=w)
    var = np.average((chem_index - x_mean) ** 2, weights=w)
    slope = cov / var if var > 1e-9 else 0.0
    intercept = y_mean - slope * x_mean
    pred = intercept + slope * chem_index
    ss_res = np.average((xgf - pred) ** 2, weights=w)
    ss_tot = np.average((xgf - y_mean) ** 2, weights=w)
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-9 else 0.0

    # High vs low chemistry quartile comparison
    q75 = float(np.percentile(chem_index, 75))
    q25 = float(np.percentile(chem_index, 25))
    high = [u for u, c in zip(rows, chem_index) if c >= q75]
    low = [u for u, c in zip(rows, chem_index) if c <= q25]

    def _mean_xgf_pct(group: list[dict[str, Any]]) -> float:
        if not group:
            return float("nan")
        return float(np.mean([u["xgf_pct"] for u in group]))

    top = sorted(rows, key=lambda u: u.get("xgf_pct") or 0, reverse=True)[:8]
    bottom = sorted(rows, key=lambda u: u.get("xgf_pct") or 0)[:8]

    return {
        "n_units": len(rows),
        "corr_complementarity_xgf_pct": round(_corr(comp, xgf), 3),
        "corr_complementarity_xgf60": round(_corr(comp, xgf60), 3),
        "corr_pass_links_per60_xgf_pct": round(_corr(pass60, xgf), 3),
        "corr_chemistry_index_xgf_pct": round(_corr(chem_index, xgf), 3),
        "corr_chemistry_index_xgf60": round(_corr(chem_index, xgf60), 3),
        "weighted_r2_chemistry_index": round(float(r2), 3),
        "slope_chemistry_to_xgf_pct": round(float(slope), 3),
        "high_chem_quartile_mean_xgf_pct": round(_mean_xgf_pct(high), 1),
        "low_chem_quartile_mean_xgf_pct": round(_mean_xgf_pct(low), 1),
        "top_xgf_units": [
            {"unit": u["unit"], "team": u["team"], "xgf_pct": u["xgf_pct"],
             "complementarity": u.get("complementarity"), "pass_links_per60": u.get("pass_links_per60"),
             "toi_min": u.get("toi_min")}
            for u in top
        ],
        "bottom_xgf_units": [
            {"unit": u["unit"], "team": u["team"], "xgf_pct": u["xgf_pct"],
             "complementarity": u.get("complementarity"), "pass_links_per60": u.get("pass_links_per60"),
             "toi_min": u.get("toi_min")}
            for u in bottom
        ],
    }


def run() -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    work_root = os.environ.get("PLAYER_CARDS_WORK_ROOT") or str(player_cards_work_root())
    print(f"PLAYER_CARDS_WORK_ROOT={work_root}")
    files = discover_nhl_pbp_files()
    if not files:
        raise SystemExit(
            "No InStat PBP CSVs found. Sync from GitHub Actions:\n"
            "  python research/line_chemistry_passing_networks/sync_pbp_from_actions.py\n"
            "Or set PLAYER_CARDS_WORK_ROOT to .player-cards-data after unpacking pbp-cache-shard-*.tar.gz"
        )
    print(f"Found {len(files)} unique NHL games (deduped by game_id)")

    df = load_pbp(files)
    df = attach_xg(df)
    teams = sorted(df["team"].dropna().unique().tolist())
    print(f"Loaded {df['game_id'].nunique()} games, {len(teams)} team labels")

    position_by_player = fetch_nhl_positions()
    skills = build_player_skills(df)
    pass_edges = infer_pass_edges(df)
    print(f"Player skill profiles: {len(skills)} | Inferred pass edges: {len(pass_edges)}")

    lines, pairs = build_unit_records(df, teams, position_by_player, skills, pass_edges)
    line_val = validate_model(lines)
    pair_val = validate_model(pairs)

    # Skill z-scores for paper tables
    skill_table = sorted(
        [{"player": p, **v} for p, v in skills.items()],
        key=lambda x: x.get("entry_rate", 0) + x.get("retrieval_rate", 0),
        reverse=True,
    )[:30]

    summary = {
        "dataset": {
            "n_games": int(df["game_id"].nunique()),
            "n_events": len(df),
            "n_pbp_files": len(files),
            "n_teams_with_data": len({p for p in NHL_TEAM_SEARCH.values()
                                      if (player_cards_work_root() / p / "Instat_API_Downloads").is_dir()}),
            "season": "2025-26",
            "source": "InStat/Hudl PBP + NHL API rosters",
        },
        "pass_network": {
            "n_inferred_edges": len(pass_edges),
            "n_unique_passers": len({e[1] for e in pass_edges}),
        },
        "forward_lines": {
            "n_units": len(lines),
            "validation": line_val,
        },
        "defensive_pairs": {
            "n_units": len(pairs),
            "validation": pair_val,
        },
        "top_skill_profiles": skill_table,
    }

    (OUT_DIR / "analysis_summary.json").write_text(json.dumps(summary, indent=2))
    pd.DataFrame(lines).to_csv(OUT_DIR / "forward_lines.csv", index=False)
    pd.DataFrame(pairs).to_csv(OUT_DIR / "defensive_pairs.csv", index=False)
    pd.DataFrame(skill_table).to_csv(OUT_DIR / "player_skills.csv", index=False)

    print(json.dumps({
        "games": summary["dataset"]["n_games"],
        "lines": line_val.get("n_units"),
        "pairs": pair_val.get("n_units"),
        "line_corr": line_val.get("corr_chemistry_index_xgf_pct"),
        "pair_corr": pair_val.get("corr_chemistry_index_xgf_pct"),
    }, indent=2))
    return summary


if __name__ == "__main__":
    run()
