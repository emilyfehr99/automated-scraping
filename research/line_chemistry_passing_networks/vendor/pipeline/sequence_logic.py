"""Possession-aware play sequence helpers (shifts/faceoffs skipped)."""

from __future__ import annotations

from .constants import (
    BREAKOUT_ACTIONS,
    DZ_LIMIT,
    ENTRY_ACTIONS,
    SEQ_WINDOW,
    SHIFT_ACTIONS,
)

SEQUENCE_SKIP_ACTIONS = frozenset({
    *SHIFT_ACTIONS,
    "Goalie shifts", "Goalie shift",
})

TURNOVER_ACTIONS = frozenset({
    "Puck losses", "Puck losses in DZ", "Puck losses in NZ", "Puck losses in OZ",
    "Inaccurate passes",
})

ENTRY_SHOT_ACTIONS = frozenset({
    "Shots", "Goals", "Shots on goal",
    "Missed shots", "Power play shots", "Short-handed shots",
})


def is_sequence_neutral(action: str) -> bool:
    a = str(action or "").strip()
    al = a.lower()
    if a in SEQUENCE_SKIP_ACTIONS:
        return True
    return "shift" in al or "faceoff" in al


def next_play_index(actions: list[str], start: int) -> int | None:
    for j in range(start + 1, len(actions)):
        if is_sequence_neutral(actions[j]):
            continue
        return j
    return None


def is_turnover_action(action: str) -> bool:
    a = str(action or "").strip()
    al = a.lower()
    return a in TURNOVER_ACTIONS or al.startswith("puck losses")


def is_shot_action(action: str) -> bool:
    a = str(action or "").strip()
    return a in ENTRY_SHOT_ACTIONS or a.startswith("Shot")


def is_giveaway(actions: list[str], teams: list[str], i: int) -> bool:
    """Turnover where the opponent has the next meaningful play."""
    if not is_turnover_action(actions[i]):
        return False
    j = next_play_index(actions, i)
    return j is not None and teams[j] != teams[i]


def entry_retains_possession(
    actions: list[str],
    teams: list[str],
    i: int,
    *,
    window: int = SEQ_WINDOW,
    require_shot: bool = False,
) -> bool:
    """True when the entering team keeps the puck until a shot or breakout."""
    team = teams[i]
    for j in range(i + 1, min(i + window + 1, len(actions))):
        if is_sequence_neutral(actions[j]):
            continue
        if teams[j] != team:
            return False
        if is_shot_action(actions[j]):
            return True
        if not require_shot and actions[j] in BREAKOUT_ACTIONS:
            return True
    return False


def breakout_clears_possession(
    actions: list[str],
    teams: list[str],
    pos_x: list[float],
    i: int,
    *,
    window: int = SEQ_WINDOW,
) -> bool:
    """True when a breakout leads to NZ/OZ possession before the opponent touches."""
    team = teams[i]
    for j in range(i + 1, min(i + window + 1, len(actions))):
        if is_sequence_neutral(actions[j]):
            continue
        if teams[j] != team:
            return False
        if actions[j] in ENTRY_ACTIONS:
            return True
        if actions[j] in BREAKOUT_ACTIONS and float(pos_x[j] or 0) > DZ_LIMIT:
            return True
    return False


def retrieval_leads_to_breakout(
    actions: list[str],
    teams: list[str],
    i: int,
    *,
    window: int = SEQ_WINDOW,
) -> bool:
    team = teams[i]
    for j in range(i + 1, min(i + window + 1, len(actions))):
        if is_sequence_neutral(actions[j]):
            continue
        if teams[j] != team:
            return False
        if actions[j] in BREAKOUT_ACTIONS:
            return True
    return False


def recovery_botched(
    actions: list[str],
    teams: list[str],
    i: int,
    *,
    window: int = SEQ_WINDOW,
) -> bool:
    """DZ recovery followed by a giveaway before a clean breakout."""
    team = teams[i]
    for j in range(i + 1, min(i + window + 1, len(actions))):
        if is_sequence_neutral(actions[j]):
            continue
        if teams[j] != team:
            return False
        if actions[j] in BREAKOUT_ACTIONS:
            return False
        if is_giveaway(actions, teams, j):
            return True
    return False


def breakout_leads_to_entry(
    actions: list[str],
    teams: list[str],
    i: int,
    *,
    window: int = SEQ_WINDOW,
) -> bool:
    team = teams[i]
    for j in range(i + 1, min(i + window + 1, len(actions))):
        if is_sequence_neutral(actions[j]):
            continue
        if teams[j] != team:
            return False
        if actions[j] in ENTRY_ACTIONS:
            return True
    return False


ORIGIN_TRIGGER_ACTIONS = frozenset({
    "Hits",
    "Faceoffs won",
    "Puck battles won",
    "Puck recoveries",
    "Puck recoveries in DZ",
    "Puck recoveries in NZ",
})


def _event_zone(action: str, zone: str) -> str:
    """Zone for a play; INstat recovery actions encode zone in the action name."""
    if action == "Puck recoveries in DZ":
        return "DZ"
    if action == "Puck recoveries in NZ":
        return "NZ"
    if action == "Puck recoveries in OZ":
        return "OZ"
    return zone


def shot_origin_zone_at_index(
    actions: list[str],
    teams: list[str],
    zones: list[str],
    halves,
    starts,
    i: int,
    *,
    max_lookback: int = 10,
    max_seconds: float = 20.0,
) -> str:
    """
    Zone where the attack sequence leading to this shot originated.
    Port of automated-post-game-reports ``_get_shot_origin_zone`` for INstat PBP.
    """
    shot_zone = zones[i]
    team_i = teams[i]
    half_i = halves[i]
    try:
        t_i = float(starts[i] or 0)
    except (TypeError, ValueError):
        t_i = 0.0

    for j in range(i - 1, max(i - max_lookback - 1, -1), -1):
        if teams[j] != team_i or halves[j] != half_i:
            continue
        try:
            t_j = float(starts[j] or 0)
        except (TypeError, ValueError):
            t_j = 0.0
        if t_i - t_j > max_seconds:
            break

        act_j = actions[j]
        zone_j = _event_zone(act_j, zones[j])

        if act_j in ORIGIN_TRIGGER_ACTIONS:
            if zone_j in ("DZ", "NZ"):
                return zone_j

        if zone_j in ("DZ", "NZ"):
            return zone_j

        if is_shot_action(act_j):
            return "OZ"

    return shot_zone
