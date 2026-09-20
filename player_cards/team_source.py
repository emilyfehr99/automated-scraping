"""Team-level card data: averages the same per-game PBP metrics used on
individual skater cards across a team's whole roster, and combines goalie
tandem stats from NHL official stats. A team card is the roster's numbers
summed/averaged together, not a new data source."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

import pandas as pd

from .build_store import roster_season
from .instat_pbp_fetch import ensure_team_pbp_files, team_pbp_dir
from .leagues import team_full_name
from .pbp_display import _pbp_values, _pct_rank
from .pbp_metrics import (
    SHOT_MAP_ACTIONS,
    SHOT_MAP_PRIORITY,
    _is_shot,
    _is_turnover,
    _play_df,
    _xg,
    aggregate_player_pbp,
)
from .pbp_team_cache import get_team_frames, warm_team_pbp
from .pwhl_bio import _is_team_match

logger = logging.getLogger(__name__)

NHL_API = "https://api-web.nhle.com/v1"


def fetch_team_roster_by_position(team: str, season: str | None = None) -> dict[str, list[dict[str, Any]]]:
    tri = team.upper()
    season = season or roster_season()
    resp = httpx.get(
        f"{NHL_API}/roster/{tri}/{season}",
        timeout=20.0,
        headers={"User-Agent": "PlayerCards/1.0"},
    )
    resp.raise_for_status()
    data = resp.json()
    out: dict[str, list[dict[str, Any]]] = {"forwards": [], "defensemen": [], "goalies": []}
    for group in out:
        for p in data.get(group) or []:
            first = (p.get("firstName") or {}).get("default") or ""
            last = (p.get("lastName") or {}).get("default") or ""
            name = f"{first} {last}".strip()
            if not name or not p.get("id"):
                continue
            out[group].append({"player_id": int(p["id"]), "name": name, "team": tri})
    return out


def _process_team_skater(args: tuple[dict[str, Any], str, list[Path], int | None, str]) -> tuple[str, dict[str, float] | None]:
    p, team, files, team_games, league = args
    from .pbp_metrics import aggregate_player_pbp
    from .pbp_display import _pbp_values
    try:
        agg = aggregate_player_pbp(p["name"], team, files=files, team_games=team_games, league=league)
        if not agg:
            return p["name"], None
        vals = _pbp_values(agg.get("per_game") or {})
        res = {k: v for k, v in vals.items() if not str(k).startswith("_")}
        return p["name"], res
    except Exception as e:
        logger.warning("Team-average skater aggregate failed for %s (%s): %s", p["name"], team, e)
        return p["name"], None

def aggregate_team_skater_averages(
    team: str,
    *,
    league: str = "nhl",
    season: str | None = None,
    instat_season_id: int | None = None,
    max_pbp_downloads: int | None = None,
) -> dict[str, Any]:
    """Average per-game PBP rate metrics across the team's rostered forwards+D.
    Same _pbp_values() shape as individual skater cards - just averaged over
    the roster instead of shown per player."""
    from collections import defaultdict
    from .disk_cache import cache_path, load_json, save_json
    from .instat_source import _match_player_name
    from .leagues import detect_active_season, instat_season_id as resolve_instat_sid
    from .pbp_metrics import (
        COUNT_MAP,
        PASS_ACTIONS,
        _is_assist_shot,
        _is_turnover,
        _resolve_team_name,
        _xg,
    )
    from .pbp_team_cache import pbp_files_fingerprint
    from .qoc_qot import compute_microstat_game_score

    if not season or instat_season_id is None:
        active_tag, active_sid = detect_active_season(league)
        season = season or active_tag
        instat_season_id = instat_season_id if instat_season_id is not None else resolve_instat_sid(season, league)

    roster = fetch_team_roster_by_position(team)
    skaters = roster["forwards"] + roster["defensemen"]
    skater_names = [s["name"] for s in skaters]

    pbp_dir = team_pbp_dir(team, league=league, a3z_season=season, season_id=instat_season_id)
    meta = ensure_team_pbp_files(
        team, pbp_dir, league=league, a3z_season=season, season_id=instat_season_id,
        max_downloads=max_pbp_downloads,
    )
    files = [Path(p) for p in meta.get("files", [])]
    match_ids = meta.get("match_ids") or []
    team_games = len(match_ids) if match_ids else (len(files) or None)

    if files:
        warm_team_pbp(files)

    fp = pbp_files_fingerprint(files)
    cache_file = cache_path("team_skater_averages", fp, f"{league}-v1-{team.upper()}.json")
    hit = load_json(cache_file, ttl_seconds=86400)
    if isinstance(hit, dict) and hit.get("averages"):
        hit["files"] = files
        return hit

    team_full = team_full_name(league, team)
    totals: dict[str, dict[str, float]] = {n: defaultdict(float) for n in skater_names}
    played: dict[str, int] = {n: 0 for n in skater_names}

    for _path, df in get_team_frames(files):
        tm = _resolve_team_name(df, team_full)
        if not tm:
            continue
        if "player" not in df.columns or "action" not in df.columns:
            continue

        try:
            gs_df = compute_microstat_game_score(df, tm)
        except Exception:
            gs_df = None
        if gs_df is not None and not gs_df.empty:
            for _, row in gs_df.iterrows():
                raw = str(row.get("player") or "")
                for n in skater_names:
                    if _match_player_name(raw, n):
                        totals[n]["Microstat Game Score"] += float(row.get("game_score") or 0)
                        totals[n]["Microstat Offense"] += float(row.get("offense_gs") or 0)
                        totals[n]["Microstat Defense"] += float(row.get("defense_gs") or 0)
                        break

        team_mask = df["team"].astype(str).apply(lambda x, _tm=tm: _is_team_match(x, _tm))
        sub = df.loc[team_mask]
        if sub.empty:
            continue

        raw_players = sub["player"].astype(str)
        mapped = {}
        for raw in raw_players.unique():
            for n in skater_names:
                if _match_player_name(raw, n):
                    mapped[raw] = n
                    break
        if not mapped:
            continue

        sub = sub[raw_players.isin(mapped.keys())].copy()
        sub["_roster"] = sub["player"].astype(str).map(mapped)
        played_tonight = set(sub["_roster"].unique())
        for n in played_tonight:
            played[n] += 1

        acts = sub["action"].astype(str).str.strip()
        for act, label in COUNT_MAP.items():
            h = sub.loc[acts == act]
            if h.empty:
                continue
            for n, cnt in h.groupby("_roster").size().items():
                totals[n][label] += float(cnt)

        # Fast single-pass Chance Assists & One Timers
        game_sub = sub.copy()
        if "start" in game_sub.columns:
            game_sub["start"] = pd.to_numeric(game_sub["start"], errors="coerce")
            game_sub = game_sub.sort_values(["half", "start"]).reset_index(drop=True)
        g_acts = game_sub["action"].astype(str).tolist()
        g_rost = game_sub["_roster"].tolist()
        g_starts = game_sub["start"].tolist() if "start" in game_sub.columns else [None] * len(game_sub)
        g_px = pd.to_numeric(game_sub.get("pos_x"), errors="coerce").tolist()
        g_py = pd.to_numeric(game_sub.get("pos_y"), errors="coerce").tolist()
        g_xg = [_xg(float(px), float(py)) if pd.notna(px) and pd.notna(py) else 0.0 for px, py in zip(g_px, g_py)]

        for i, act in enumerate(g_acts):
            if not _is_assist_shot(act):
                continue
            shooter = g_rost[i]
            if shooter and act != "Blocked shots":
                shot_time = g_starts[i]
                for j in range(i - 1, max(i - 4, -1), -1):
                    if _is_turnover(g_acts[j]):
                        break
                    if g_acts[j] in PASS_ACTIONS:
                        if g_rost[j] != shooter:
                            if shot_time is not None and g_starts[j] is not None:
                                if float(shot_time) - float(g_starts[j]) <= 1.0:
                                    totals[shooter]["One Timers"] += 1.0
                            elif j == i - 1:
                                totals[shooter]["One Timers"] += 1.0
                        break
                    if _is_assist_shot(g_acts[j]):
                        break
            is_chance = g_xg[i] >= 0.08 or (pd.notna(g_px[i]) and g_px[i] >= 70 and pd.notna(g_py[i]) and 30 <= g_py[i] <= 55)
            if not is_chance:
                continue
            for j in range(i - 1, max(i - 4, -1), -1):
                if g_acts[j] in PASS_ACTIONS:
                    passer = g_rost[j]
                    if passer and passer != shooter:
                        totals[passer]["Chance Assists"] += 1.0
                    break
                if _is_turnover(g_acts[j]) or _is_assist_shot(g_acts[j]):
                    break

    per_player: dict[str, dict[str, float]] = {}
    tg = team_games or (len(files) or 1)
    for n in skater_names:
        if played[n] == 0:
            continue
        per_game = {k: round(v / tg, 2) for k, v in totals[n].items()}
        vals = _pbp_values(per_game)
        per_player[n] = {k: v for k, v in vals.items() if not str(k).startswith("_")}

    averages: dict[str, float | None] = {}
    if per_player:
        keys: set[str] = set()
        for v in per_player.values():
            keys.update(v.keys())
        for k in keys:
            vals = [v[k] for v in per_player.values() if v.get(k) is not None]
            averages[k] = round(sum(vals) / len(vals), 3) if vals else None

    result = {
        "averages": averages,
        "player_count": len(per_player),
        "roster_size": len(skaters),
        "games": team_games,
        "per_player": per_player,
        "files": files,
    }
    if result.get("averages"):
        save_json(cache_file, result)
    return result


def compute_team_totals(per_player: dict[str, dict[str, float]], games: int | None) -> dict[str, float]:
    """Recover team-wide totals from per-player per-game rates: each player's
    rate already = their own total / games (same divisor for the whole roster),
    so games * sum(rates) = sum(totals) - no need to re-scan PBP for this."""
    if not games or not per_player:
        return {}
    keys: set[str] = set()
    for v in per_player.values():
        keys.update(v.keys())
    return {k: round(games * sum(v.get(k, 0) or 0 for v in per_player.values()), 1) for k in keys}


def aggregate_team_zone_events(
    team: str, *, league: str = "nhl", files: list[Path] | None = None,
) -> dict[str, Any]:
    """Team-wide shots-for/shots-against (for the rink shot maps) and neutral-
    zone-turnover tracking, scanned once across every cached PBP game. Mirrors
    the sequence-scan approach used for the Clarkson NZTSA metric (own-zone
    puck loss -> does an opponent shot land within the next few events?), but
    reuses InStat's own zone-tagged action ("Puck losses in NZ") instead of a
    position-band filter.

    Coordinate note: verified empirically (see team_source dev notes) that a
    team's own PBP export already attack-normalizes BOTH teams' shot rows
    toward the same net (both sides' pos_x cluster near the same high value) -
    so shots_against needs no coordinate mirroring before feeding into the
    same half-rink shot_map.py renderer used for shots_for."""
    if not files:
        return {"shots_for": [], "shots_against": [], "nz_turnovers": 0, "nz_turnovers_to_shot_against": 0}

    team_full = team_full_name(league, team)
    warm_team_pbp(files)

    shots_for: list[dict[str, Any]] = []
    shots_against: list[dict[str, Any]] = []
    nz_turnovers = 0
    nz_turnovers_to_shot_against = 0

    for _path, df in get_team_frames(files):
        if df.empty or "team" not in df.columns:
            continue
        teams_in_game = [t for t in df["team"].dropna().unique() if str(t).strip()]
        own_name = next((t for t in teams_in_game if _is_team_match(str(t), team_full)), None)
        if not own_name:
            continue

        # Same InStat multi-row dedupe as skater shot maps (SHOT_MAP_ACTIONS).
        outcome_rows = df[df["action"].isin(SHOT_MAP_ACTIONS)]
        for (_start, _player, _team), grp in outcome_rows.groupby(
            ["start", "player", "team"], dropna=False
        ):
            best = (
                grp.assign(_p=grp["action"].map(lambda a: SHOT_MAP_PRIORITY.get(a, 9)))
                .sort_values("_p")
                .iloc[0]
            )
            px, py = best.get("pos_x"), best.get("pos_y")
            if pd.isna(px) or pd.isna(py):
                continue
            point = {
                "x": round(float(px), 2),
                "y": round(float(py), 2),
                "xg": round(_xg(float(px), float(py)), 3),
                "goal": best["action"] == "Goals",
            }
            (shots_for if _team == own_name else shots_against).append(point)

        own_mask = df["team"] == own_name
        nz_loss_idx = df[own_mask & (df["action"] == "Puck losses in NZ")].index.tolist()
        nz_turnovers += len(nz_loss_idx)
        for idx in nz_loss_idx:
            window = _play_df(df.iloc[idx + 1: idx + 11])
            for _, r in window.iterrows():
                if r["team"] == own_name:
                    if _is_turnover(r["action"]):
                        break
                    continue
                if _is_shot(str(r["action"])):
                    nz_turnovers_to_shot_against += 1
                    break

    return {
        "shots_for": shots_for, "shots_against": shots_against,
        "nz_turnovers": nz_turnovers, "nz_turnovers_to_shot_against": nz_turnovers_to_shot_against,
    }


def fetch_team_goalie_summary(team: str, season_str: str | None = None) -> dict[str, Any]:
    """Combined tandem SV%/GAA/record from NHL official stats, weighted by GP played."""
    from .leagues import nhl_api_season_id

    _ = season_str or nhl_api_season_id()  # reserved for future season-scoped landing stats
    roster = fetch_team_roster_by_position(team)
    goalies = roster["goalies"]
    total_gp = total_w = total_l = total_otl = total_so = 0
    weighted_sv = 0.0
    weighted_gaa = 0.0
    lines: list[dict[str, Any]] = []

    for g in goalies:
        try:
            resp = httpx.get(
                f"{NHL_API}/player/{g['player_id']}/landing",
                timeout=12.0,
                headers={"User-Agent": "PlayerCards/1.0"},
            )
            resp.raise_for_status()
            sub = (resp.json().get("featuredStats") or {}).get("regularSeason", {}).get("subSeason", {})
        except Exception as e:
            logger.warning("Goalie official stats failed for %s: %s", g["name"], e)
            continue
        gp = sub.get("gamesPlayed") or 0
        if gp <= 0:
            continue
        sv = sub.get("savePctg")
        gaa = sub.get("goalsAgainstAvg")
        w, l, otl = sub.get("wins") or 0, sub.get("losses") or 0, sub.get("otLosses") or 0
        so = sub.get("shutouts") or 0
        total_gp += gp
        total_w += w
        total_l += l
        total_otl += otl
        total_so += so
        if sv is not None:
            weighted_sv += sv * gp
        if gaa is not None:
            weighted_gaa += gaa * gp
        lines.append({
            "name": g["name"], "gp": gp,
            "sv_pct": round(sv * 100, 1) if sv is not None else None,
            "gaa": gaa, "record": f"{w}-{l}-{otl}",
        })

    return {
        "goalies": lines,
        "team_sv_pct": round(weighted_sv / total_gp * 100, 1) if total_gp else None,
        "team_gaa": round(weighted_gaa / total_gp, 2) if total_gp else None,
        "record": f"{total_w}-{total_l}-{total_otl}",
        "shutouts": total_so,
        "games": total_gp,
    }


def fetch_team_game_log(team: str, season_id: int | str | None = None) -> list[dict[str, Any]]:
    """Real game-by-game W/L/OTL sequence for the season-form grid - not a
    derived stat, straight from the NHL schedule/results endpoint."""
    from .leagues import nhl_api_season_id

    tri = team.upper()
    sid = int(season_id) if season_id is not None else int(nhl_api_season_id())
    resp = httpx.get(
        f"{NHL_API}/club-schedule-season/{tri}/{sid}",
        timeout=15.0, headers={"User-Agent": "PlayerCards/1.0"}, follow_redirects=True,
    )
    resp.raise_for_status()
    games = [
        g for g in resp.json().get("games", [])
        if g.get("gameType") == 2 and g.get("gameState") in ("OFF", "FINAL")
    ]
    out = []
    for g in games:
        home, away = g["homeTeam"], g["awayTeam"]
        is_home = home.get("abbrev") == tri
        us, them = (home, away) if is_home else (away, home)
        win = (us.get("score") or 0) > (them.get("score") or 0)
        last_period = (g.get("gameOutcome") or {}).get("lastPeriodType", "REG")
        result = "W" if win else ("L" if last_period == "REG" else "OTL")
        out.append({
            "date": g.get("gameDate"), "result": result,
            "opponent": them.get("abbrev"), "score_for": us.get("score"), "score_against": them.get("score"),
        })
    return out


def _team_capwages_slug(team: str) -> str | None:
    from .instat_source import NHL_TEAM_SEARCH

    full = NHL_TEAM_SEARCH.get(team.upper())
    if not full:
        return None
    import re
    return re.sub(r"[^a-z0-9]+", "_", full.lower()).strip("_")


def fetch_team_front_office(team: str) -> dict[str, Any] | None:
    """GM, coach, and real cap space from CapWages' public team page (same
    __NEXT_DATA__-extraction technique as cap_source.py's player pages - no
    API key needed, unlike the gateway API)."""
    slug = _team_capwages_slug(team)
    if not slug:
        return None
    try:
        resp = httpx.get(
            f"https://capwages.com/teams/{slug}",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=15.0, follow_redirects=True,
        )
        resp.raise_for_status()
        import json
        import re
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S)
        if not m:
            return None
        props = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
        meta = props.get("teamMetadata") or {}
        summary = props.get("teamSummary") or {}
    except Exception as e:
        logger.warning("CapWages team page failed for %s: %s", team, e)
        return None
    return {
        "gm": meta.get("gm"),
        "coach": meta.get("coach"),
        "cap_space": summary.get("capSpace"),
        "cap_hit_total": (summary.get("capHit") or {}).get("total"),
        "upper_limit": summary.get("upperLimit"),
    }


def fetch_team_standing(team: str) -> dict[str, Any] | None:
    try:
        resp = httpx.get(
            f"{NHL_API}/standings/now", timeout=12.0,
            headers={"User-Agent": "PlayerCards/1.0"}, follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Standings fetch failed: %s", e)
        return None
    tri = team.upper()
    row = next(
        (t for t in data.get("standings", []) if (t.get("teamAbbrev") or {}).get("default") == tri), None
    )
    if not row:
        return None
    return {
        "wins": row.get("wins"), "losses": row.get("losses"), "ot_losses": row.get("otLosses"),
        "points": row.get("points"), "games_played": row.get("gamesPlayed"),
        "division": row.get("divisionName"), "division_rank": row.get("divisionSequence"),
        "conference": row.get("conferenceName"), "conference_rank": row.get("conferenceSequence"),
        "goal_diff": row.get("goalDifferential"),
        "streak_code": row.get("streakCode"), "streak_count": row.get("streakCount"),
        "l10_wins": row.get("l10Wins"), "l10_losses": row.get("l10Losses"), "l10_ot_losses": row.get("l10OtLosses"),
    }


def fetch_league_team_skater_averages(
    *, league: str = "nhl", season: str | None = None, instat_season_id: int | None = None,
    teams: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Precompute every NHL team's skater averages once, so a batch of team-card
    generations reuses one pool instead of re-aggregating 32 rosters per card
    (same reuse pattern as goalie_profile.py's league_goalie_rows)."""
    from .leagues import detect_active_season, get_league, instat_season_id as resolve_instat_sid

    cfg = get_league(league)
    if not season or instat_season_id is None:
        active_tag, active_sid = detect_active_season(league)
        season = season or active_tag
        instat_season_id = instat_season_id if instat_season_id is not None else resolve_instat_sid(season, league)
    team_list = teams or list(cfg.teams.keys())
    out: dict[str, dict[str, Any]] = {}
    for tri in team_list:
        try:
            out[tri] = aggregate_team_skater_averages(
                tri, league=league, season=season, instat_season_id=instat_season_id,
            )
        except Exception as e:
            logger.warning("League team-average failed for %s: %s", tri, e)
    return out


NHL_STATS_API = "https://api.nhle.com/stats/rest/en"

# Official-stat metrics where a LOWER raw value is the better outcome (goals/shots
# allowed) - percentile must rank on the inverted value so "90th percentile" always
# means "well above average", same convention as every percentile-tier metric.
_LOWER_IS_BETTER = {"goalsAgainstPerGame", "shotsAgainstPerGame"}


def _team_id_to_tricode() -> dict[int, str]:
    resp = httpx.get(f"{NHL_STATS_API}/team", timeout=15.0, headers={"User-Agent": "PlayerCards/1.0"})
    resp.raise_for_status()
    return {row["id"]: row["triCode"] for row in resp.json().get("data", [])}


def fetch_league_team_official_stats(season_id: int | str | None = None) -> dict[str, dict[str, Any]]:
    """One cheap call (NHL's own official team-summary endpoint) covering all 32
    teams at once - real PP%/PK%/faceoff%/GF-GA per game, no InStat download
    needed. This is what makes the League Percentiles section real instead of
    a flat, ungraded bar."""
    from .leagues import nhl_api_season_id

    sid = int(season_id) if season_id is not None else int(nhl_api_season_id())
    resp = httpx.get(
        f"{NHL_STATS_API}/team/summary",
        params={"cayenneExp": f"seasonId={sid} and gameTypeId=2"},
        timeout=15.0, headers={"User-Agent": "PlayerCards/1.0"},
    )
    resp.raise_for_status()
    id_map = _team_id_to_tricode()
    out: dict[str, dict[str, Any]] = {}
    for row in resp.json().get("data", []):
        tri = id_map.get(row.get("teamId"))
        if tri:
            out[tri] = row
    return out


def compute_official_stat_percentiles(
    team_row: dict[str, Any], league_rows: dict[str, dict[str, Any]], keys: list[str],
) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for k in keys:
        pop = [r[k] for r in league_rows.values() if r.get(k) is not None]
        val = team_row.get(k)
        if val is None or not pop:
            out[k] = None
            continue
        pct = _pct_rank(float(val), [float(v) for v in pop])
        out[k] = (1.0 - pct) if k in _LOWER_IS_BETTER and pct is not None else pct
    return out


def fetch_team_scoring_leaders(team: str, season_id: int | str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    from .leagues import nhl_api_season_id

    sid = int(season_id) if season_id is not None else int(nhl_api_season_id())
    id_map = _team_id_to_tricode()
    team_id = next((tid for tid, tri in id_map.items() if tri == team.upper()), None)
    if team_id is None:
        return []
    resp = httpx.get(
        f"{NHL_STATS_API}/skater/summary",
        params={
            "cayenneExp": f"seasonId={sid} and gameTypeId=2 and teamId={team_id}",
            "sort": '[{"property":"points","direction":"DESC"}]',
        },
        timeout=15.0, headers={"User-Agent": "PlayerCards/1.0"},
    )
    resp.raise_for_status()
    rows = resp.json().get("data", [])[:limit]
    return [
        {
            "name": r.get("skaterFullName"), "goals": r.get("goals"), "assists": r.get("assists"),
            "points": r.get("points"), "gp": r.get("gamesPlayed"),
        }
        for r in rows
    ]


def compute_team_percentiles(
    team_averages: dict[str, float | None], league_team_averages: dict[str, dict[str, Any]],
) -> dict[str, float | None]:
    keys: set[str] = set()
    for t in league_team_averages.values():
        keys.update((t.get("averages") or {}).keys())
    out: dict[str, float | None] = {}
    for k in keys:
        pop = [
            t["averages"][k] for t in league_team_averages.values()
            if t.get("averages", {}).get(k) is not None
        ]
        val = team_averages.get(k)
        out[k] = _pct_rank(float(val), [float(v) for v in pop]) if val is not None and pop else None
    return out
