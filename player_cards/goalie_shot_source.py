"""Real per-shot goalie data from InStat's dedicated shot-charting endpoint
(`scout_match_map_shoot_goalie_new_scout`) — not the geometry proxies in
goalie_pbp_metrics.py. This is the same feed the Clarkson/ECAC goalie reports
were built from (see hudl-scraping/acquire_goalie_metrics.py and
scrape_all_ecac_goalie_shots.py), pointed at an NHL team/goalie instead.

Every lex_* code below was decoded live via InStat's own scout_param_lexical
labels (not guessed/hardcoded from the older ECAC script, which only covered
a handful of values) — see the mapping dicts for the confirmed text.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from .pbp_metrics import NET_X, NET_Y
from .shooter_hands import _norm as _norm_hand_name

logger = logging.getLogger(__name__)

# lex_pos: goalie's save posture
POSITION_LEX = {
    6120: "Beaten",
    20021: "Butterfly",
    20022: "In Motion",
}
# lex_obzor: shot visibility
VISIBILITY_LEX = {
    6085: "Screen",
    6086: "Clean View",
}
# lex_saves: rebound control detail
SAVE_DETAIL_LEX = {
    6100: "Uncontrolled Rebound",
    6101: "Controlled Rebound",
    6102: "Froze After Rebound",
    6103: "Froze Straight Away",
}
# lex_shoot: shot type
SHOT_TYPE_LEX = {
    4058: "Slapshot", 4059: "Wrist Shot", 5683: "Backhand", 6031: "Hard Slapshot",
    6043: "Deflection", 6224: "Deflection", 6225: "Rebound Shot", 6226: "From Behind Goal",
}
# lex_dest: where on the goalie/net the shot was directed (real shot-placement zone)
DEST_LEX = {
    6045: "Blocker Side High", 6046: "Glove Side High", 6047: "Under Blocker",
    6048: "Under Glove", 6049: "Five-Hole", 6050: "Chest/Head", 6056: "Left Shoulder",
    8390: "Left Armpit", 8391: "Right Armpit", 8393: "Left Pad", 8394: "Right Pad",
    8425: "Right Shoulder",
}
# lex_act: shot result
RESULT_LEX = {3405: "SOG", 3426: "Goal", 5881: "Missed Shot"}
# lex_att: real attack-type classification
ATTACK_TYPE_LEX = {920: "Positional Attack", 6044: "Counterattack"}
# lex_half: period / game situation
SITUATION_LEX = {12840: "1st", 12841: "2nd", 12842: "3rd", 2963: "Overtime", 3053: "Shootout"}
# gz: 3x3 net grid, confirmed against Clarkson's Goal_Zone/Goal_Zone_Desc pairing
GOAL_ZONE_DESC = {
    1: "Top Left", 2: "Top Center", 3: "Top Right",
    4: "Mid Left", 5: "Mid Center", 6: "Mid Right",
    7: "Bottom Left", 8: "Bottom Center (Five-Hole)", 9: "Bottom Right",
}


def _dist_angle(x: float, y: float) -> tuple[float, float]:
    dx = max(0.0, NET_X - x)
    dy = abs(NET_Y - y)
    return math.hypot(dx, dy), math.degrees(math.atan2(dy, dx + 1e-9))


def _off_wing(hand: str | None, ice_side: str) -> bool | None:
    if hand not in ("R", "L"):
        return None
    return (hand == "R" and ice_side == "Left") or (hand == "L" and ice_side == "Right")


async def fetch_real_goalie_shot_data(
    team_instat_id: int,
    season_id: int,
    player_name: str,
    shooter_hands: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Full flow in one Playwright session: resolve this goalie's InStat
    player_id from the team roster, pull every match_id for the season, fetch
    their real per-shot data, and enrich it. Returns [] if InStat has no
    shot-charted games for this goalie (common — this endpoint isn't run for
    every team/game, unlike the always-on PBP export)."""
    try:
        from playwright.async_api import async_playwright
        from instat_api import InStatAPI
    except ImportError:
        return []

    from .instat_source import HUDL_ROOT
    if not (HUDL_ROOT / "auth.json").exists():
        return []

    import instat_api as instat_mod
    from .instat_source import _match_player_name

    api = InStatAPI()
    async with async_playwright() as p:
        if not await api.init_session(p):
            return []
        try:
            instat_mod.TEAM_ID = team_instat_id
            instat_mod.SEASON_ID = season_id
            matches = await api.get_matches_list()
            match_ids = api._extract_match_ids(matches)
            if not match_ids:
                return []

            goalies = await api.get_team_goalies(match_ids)
            row = next((g for g in goalies if _match_player_name(str(g.get("name_eng") or ""), player_name)), None)
            if not row or not row.get("player_id"):
                logger.warning("Could not resolve InStat player_id for goalie %s", player_name)
                return []

            raw = await fetch_goalie_shots_raw(api, int(row["player_id"]), match_ids)
        finally:
            await api.close()

    return build_enriched_shots(raw, shooter_hands=shooter_hands)


async def fetch_goalie_shots_raw(api, player_instat_id: int, match_ids: list[int]) -> list[dict[str, Any]]:
    """Raw shoots_data rows (is_opp only) + a pl_id -> shooter name lookup."""
    resp = await api.api_call(
        "scout_match_map_shoot_goalie_new_scout",
        {"_p_player_id": player_instat_id, "_p_match_arr": match_ids},
    )
    if not resp or "data" not in resp or not resp["data"]:
        return []
    proc = resp["data"][0].get("scout_match_map_shoot_goalie_new_scout", {})
    shoots = proc.get("shoots_data", [])

    player_map: dict[str, str] = {}
    raw_players = proc.get("player_data", [])
    import json as _json
    for pl in raw_players:
        if isinstance(pl, str):
            try:
                pl = _json.loads(pl)
            except Exception:
                continue
        if isinstance(pl, dict):
            pid = pl.get("id")
            name = pl.get("n_en")
            if pid and name:
                player_map[str(pid)] = name

    # Keep both directions here — is_opp=False (the goalie's own team shooting)
    # is needed to reconstruct the live score state a shot was faced under, since
    # scr/opp_scr on each row is the game's *final* score, not a running one
    # (verified empirically: identical on every row of a game from puck drop on).
    for s in shoots:
        s["_shooter_name"] = player_map.get(str(s.get("pl_id")), "")
    return shoots


# Chronological period order for sorting — raw lex_half codes for OT/Shootout
# (2963/3053) are numerically *smaller* than the period 1-3 codes (12840-12842),
# so they can't be sorted as-is.
_PERIOD_ORDER = {12840: 1, 12841: 2, 12842: 3, 2963: 4, 3053: 5}


def build_enriched_shots(
    raw_shots: list[dict[str, Any]],
    *,
    shooter_hands: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Decode + geometrically enrich raw InStat goalie shot rows (is_opp=True only
    in the output — is_opp=False rows are used only to reconstruct the live score)."""
    hands = shooter_hands or {}
    enriched: list[dict[str, Any]] = []

    # Pressure context: shots-in-preceding-2min against this goalie specifically.
    opp_shots_only = [s for s in raw_shots if s.get("is_opp")]
    by_game_half: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for s in opp_shots_only:
        by_game_half.setdefault((s.get("m"), s.get("h")), []).append(s)

    # Live score state: scr/opp_scr on each row is the game's *final* score, not
    # a running one (verified: identical across every row of a game from puck
    # drop on) — so replay goals chronologically ourselves, using both shot
    # directions, to know the real score at the moment each shot was faced.
    by_match: dict[Any, list[dict[str, Any]]] = {}
    for s in raw_shots:
        by_match.setdefault(s.get("m"), []).append(s)

    score_at: dict[int, tuple[int, int]] = {}  # shot "id" -> (team_score, opp_score) before this shot
    for match_id, rows in by_match.items():
        ordered = sorted(
            rows,
            key=lambda r: (_PERIOD_ORDER.get(int(r.get("h") or 0), 99), r.get("s") or 0),
        )
        team_score = opp_score = 0
        for r in ordered:
            score_at[r.get("id")] = (team_score, opp_score)
            r_is_goal = r.get("lex_act") is not None and RESULT_LEX.get(int(r["lex_act"])) == "Goal"
            if r_is_goal:
                if r.get("is_opp"):
                    opp_score += 1
                else:
                    team_score += 1

    for s in opp_shots_only:
        x, y = s.get("x"), s.get("y")
        if x is None or y is None:
            continue
        x, y = float(x), float(y)
        dist, angle = _dist_angle(x, y)
        ice_side = "Left" if y < NET_Y else "Right"

        cx = s.get("cx")
        net_side = ("Left" if float(cx) < 0 else "Right") if cx is not None else None
        short_side = (ice_side == net_side) if net_side else None

        # n_en from this endpoint comes as "First Last" already (unlike the PBP
        # CSV's "Last First" player column) — use it as-is.
        shooter_display = str(s.get("_shooter_name") or "")
        hand = hands.get(_norm_hand_name(shooter_display)) if shooter_display else None
        off_wing = _off_wing(hand, ice_side)

        result = RESULT_LEX.get(int(s["lex_act"])) if s.get("lex_act") is not None else None
        is_goal = result == "Goal"

        t = s.get("s")
        pressure_n = 0
        if t is not None:
            window = by_game_half.get((s.get("m"), s.get("h")), [])
            pressure_n = sum(1 for w in window if w.get("s") is not None and 0 <= (t - w["s"]) <= 120)

        team_sc, opp_sc = score_at.get(s.get("id"), (0, 0))

        enriched.append({
            "shot_id": s.get("id"),
            "match_id": s.get("m"),
            "period_code": s.get("h"),
            "time_s": t,
            "shooter": shooter_display,
            "opponent": s.get("opp_tm_en"),
            "x": x, "y": y,
            "distance_ft": round(dist * 3.28084, 1),
            "angle_deg": round(angle, 1),
            "net_x": cx, "net_y": s.get("cy"),
            "goal_zone": s.get("gz"),
            "goal_zone_desc": GOAL_ZONE_DESC.get(int(s["gz"])) if s.get("gz") is not None else None,
            "xg": s.get("xg"),
            "is_goal": is_goal,
            "result": result,
            "shot_type": SHOT_TYPE_LEX.get(int(s["lex_shoot"])) if s.get("lex_shoot") is not None else None,
            "save_position": POSITION_LEX.get(int(s["lex_pos"])) if s.get("lex_pos") is not None else None,
            "visibility": VISIBILITY_LEX.get(int(s["lex_obzor"])) if s.get("lex_obzor") is not None else None,
            "save_detail": SAVE_DETAIL_LEX.get(int(s["lex_saves"])) if s.get("lex_saves") is not None else None,
            "shot_placement": DEST_LEX.get(int(s["lex_dest"])) if s.get("lex_dest") is not None else None,
            "attack_type": ATTACK_TYPE_LEX.get(int(s["lex_att"])) if s.get("lex_att") is not None else None,
            "situation": SITUATION_LEX.get(int(s["lex_half"])) if s.get("lex_half") is not None else None,
            "ice_side": ice_side,
            "short_side": short_side,
            "shooter_hand": hand,
            "off_wing": off_wing,
            "score_state": f"{team_sc}-{opp_sc}",
            "score_situation": (
                "Leading" if team_sc > opp_sc else "Trailing" if team_sc < opp_sc else "Tied"
            ),
            "pressure_shots_2m": pressure_n,
            "high_pressure": pressure_n >= 5,
        })
    return enriched


def _pct(saves: int, total: int) -> float | None:
    return round(100.0 * saves / total, 1) if total > 0 else None


def _sv_bucket(group: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(group)
    goals = sum(1 for s in group if s["is_goal"])
    return {"sv_pct": _pct(n - goals, n), "shots": n, "low_sample": n < 25}


def _share_bucket(group: list[dict[str, Any]], denominator: int) -> dict[str, Any]:
    """% of `denominator` (e.g. total saves) this group represents — for fields
    like save_detail that only exist on saves, where an "SV%" would be a
    tautological ~100% every time."""
    n = len(group)
    return {"share_pct": _pct(n, denominator), "shots": n, "low_sample": n < 25}


def aggregate_real_shot_data(shots: list[dict[str, Any]]) -> dict[str, Any]:
    """Summary splits from real (non-proxy) InStat per-shot goalie data.
    Only covers games InStat manually shot-charted for this goalie — see
    'games_tracked' / 'total_games' for how much of the season that is."""
    attempts = [s for s in shots if s["result"] in ("SOG", "Goal")]
    if not attempts:
        return {}
    n = len(attempts)
    games_tracked = len({s["match_id"] for s in attempts})

    def by(field: str) -> dict[str, dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for s in attempts:
            k = s.get(field)
            if k:
                buckets.setdefault(k, []).append(s)
        return {k: _sv_bucket(v) for k, v in buckets.items()}

    hand_groups = {
        "vs_right_shot": [s for s in attempts if s["shooter_hand"] == "R"],
        "vs_left_shot": [s for s in attempts if s["shooter_hand"] == "L"],
        "off_wing": [s for s in attempts if s["off_wing"] is True],
        "on_wing": [s for s in attempts if s["off_wing"] is False],
        "short_side": [s for s in attempts if s["short_side"] is True],
        "long_side": [s for s in attempts if s["short_side"] is False],
    }

    # save_detail (rebound handling) only ever gets tagged on saves — a goal by
    # definition has no "how was the rebound controlled" — so grouping by it and
    # computing SV% is tautological (~100% every time). Report it as a share of
    # total saves instead (a real, non-circular distribution).
    saves_n = n - sum(1 for s in attempts if s["is_goal"])
    save_detail_buckets: dict[str, list[dict[str, Any]]] = {}
    for s in attempts:
        k = s.get("save_detail")
        if k:
            save_detail_buckets.setdefault(k, []).append(s)

    return {
        "shots": n,
        "games_tracked": games_tracked,
        "sv_pct_overall": _pct(n - sum(1 for s in attempts if s["is_goal"]), n),
        "by_goal_zone": by("goal_zone_desc"),
        "by_shot_placement": by("shot_placement"),
        "by_attack_type": by("attack_type"),
        "by_visibility": by("visibility"),
        "save_detail_share": {k: _share_bucket(v, saves_n) for k, v in save_detail_buckets.items()},
        "by_score_situation": by("score_situation"),
        "by_situation": by("situation"),
        "by_shot_type": by("shot_type"),
        "handedness_splits": {k: _sv_bucket(v) for k, v in hand_groups.items()},
        "real_style_of_play": by("save_position"),
        "high_pressure_sv_pct": _sv_bucket([s for s in attempts if s["high_pressure"]]),
        "normal_pressure_sv_pct": _sv_bucket([s for s in attempts if not s["high_pressure"]]),
        "heatmap_zones": {
            zone: {
                "shots": len(g),
                "goals": sum(1 for s in g if s["is_goal"]),
                "sv_pct": _sv_bucket(g)["sv_pct"],
            }
            for zone, g in {
                z: [s for s in attempts if s["goal_zone_desc"] == z]
                for z in GOAL_ZONE_DESC.values()
            }.items()
        },
    }
