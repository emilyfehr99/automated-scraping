"""Shared constants for PWHL analytics (ported from Master_Analytics_Engine_V1.R)."""

from __future__ import annotations

DZ_LIMIT = 22.86
NZ_LIMIT = 38.10
SEQ_WINDOW = 10
NET_X, NET_Y = 60.0, 15.0
Y_MAX = 42.5

ENTRY_ACTIONS = frozenset({
    "Entries", "Entries via pass", "Entries via stickhandling", "Entries via dump in",
})
BREAKOUT_ACTIONS = frozenset({
    "Breakouts", "Breakouts via pass", "Breakouts via stickhandling",
})
RECOVERY_ACTIONS = frozenset({
    "Puck recoveries", "Puck recovery", "Puck recoveries in DZ",
    "Puck recoveries in NZ", "Puck recoveries in OZ",
})
SHOT_ACTIONS = frozenset({"Shots", "Goals", "Shots on goal"})
"""Actions used when summing expected goals (avoids triple-counting shot attempts)."""
XG_SUM_ACTIONS = frozenset({"Shots on goal", "Goals"})
SHIFT_ACTIONS = frozenset({
    "Even strength shifts", "Power play shifts", "Penalty kill shifts",
})
GOALIE_SHIFT_HINTS = frozenset({"Goalie shifts", "Goalie shift"})
