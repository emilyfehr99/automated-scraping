"""Editorial player card — balanced density."""

from __future__ import annotations

OFFENSE_GS_KEY = "offense"
DEFENSE_GS_KEYS = ("entry_defense", "exits", "forechecking")


def _pg(label: str) -> str:
    return f"{label} / GP"


PILLAR_BARS = [
    {
        "title": "Offense",
        "keys": [
            ("shots_per_60", "Shots"),
            ("chances_per_60", "Chances"),
            ("passes_per_60", "Passes"),
            ("chance_assists_per_60", "Chance Assists"),
            ("shots_on_goal_per_60", "Shooting"),
            ("one_timer_per_60", "One-timers"),
        ],
    },
    {
        "title": "Transition",
        "keys": [
            ("zone_entries_per_60", "Zone Entries"),
            ("carries_per_60", "Carries"),
            ("exits_w_possession_per_60", "Possession Exits"),
            ("failed_entries_per_60", "Failed Entries"),
            ("forechecking", "Forecheck"),
            ("recoveries_per_60", "Recoveries"),
        ],
    },
    {
        "title": "Defense",
        "keys": [
            ("dz_retrievals_per_60", "DZ Retrievals"),
            ("exits", "Breakouts"),
            ("entry_defense", "Entry Defense"),
            ("botched_retrievals_per_60", "Botched Ret."),
            ("failed_exit_per_60", "Failed Exits"),
            ("denials_per_60", "Denials"),
        ],
    },
]

HIGHLIGHT_TILES = [
    ("microstat_game_score", "Game Score"),
    ("offense", "Offence"),
    ("defense_composite", "Defence"),
    ("chance_assists_per_60", "Playmaking"),
    ("shots_on_goal_per_60", "Finishing"),
    ("zone_entries_per_60", "Entries"),
    ("qoc", "Competition"),
    ("qot", "Teammates"),
]

PBP_RATE_GROUPS = [
    {
        "title": "Scoring",
        "metrics": [
            {"label": _pg("Shots"), "key": "Shots"},
            {"label": _pg("SOG"), "key": "SOG"},
            {"label": _pg("xG"), "key": "xG"},
            {"label": _pg("Chances"), "key": "Chances"},
            {"label": _pg("Goals"), "key": "Goals"},
            {"label": _pg("Passes"), "key": "Passes"},
        ],
    },
    {
        "title": "Zone Play",
        "metrics": [
            {"label": _pg("Entries"), "key": "Zone Entries"},
            {"label": _pg("Carry-ins"), "key": "Carry-ins"},
            {"label": _pg("Pass entries"), "key": "Pass Entries"},
            {"label": "Carry-in rate", "key": "Carry-in%", "format": "percent"},
            {"label": _pg("Success"), "key": "Successful Entries"},
            {"label": _pg("Failed"), "key": "Failed Entries", "negative": True},
        ],
    },
    {
        "title": "Without Puck",
        "metrics": [
            {"label": _pg("DZ retrievals"), "key": "DZ Retrievals"},
            {"label": _pg("Zone exits"), "key": "Zone Exits"},
            {"label": _pg("Poss exits"), "key": "Exits w/ Possession"},
            {"label": "Poss exit rate", "key": "Exits w/ Possession %", "format": "percent"},
            {"label": _pg("Breakouts"), "key": "Successful Breakouts"},
            {"label": "FO win rate", "key": "_fo_win_pct", "format": "percent"},
        ],
    },
]

GS_COMPONENTS = []
A3Z_TILE_GROUPS = PILLAR_BARS
PBP_SECTIONS = PBP_RATE_GROUPS
PROFILE_PILLARS = PILLAR_BARS
A3Z_DISPLAY_SECTIONS = PILLAR_BARS
HIGHLIGHT_METRICS = HIGHLIGHT_TILES
STAT_SECTIONS = []
HERO_RATES = []
PBP_HEADLINES = []


def format_stat(value, fmt: str = "decimal", *, hide_zero: bool = True) -> str:
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if not (n == n):
        return "—"
    if hide_zero and n == 0:
        return "—"
    if fmt == "percent":
        return f"{n:.0f}%"
    if fmt == "compact" and abs(n) >= 10:
        return f"{n:.1f}"
    return f"{n:.2f}"
