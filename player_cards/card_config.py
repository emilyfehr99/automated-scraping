"""Editorial player card — balanced density."""

from __future__ import annotations

OFFENSE_GS_KEY = "offense"
DEFENSE_GS_KEY = "defense"
DEFENSE_GS_KEYS = ("dz_retrievals_per_60", "exits", "denials_per_60")


def _pg(label: str) -> str:
    return f"{label} per Game"


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
            ("successful_entries_per_60", "Successful Entries"),
            ("failed_entries_per_60", "Failed Entries"),
            ("entries_w_chance_per_60", "Entries w/ Chance"),
            ("forechecking", "Forecheck"),
        ],
    },
    {
        "title": "Defense",
        "keys": [
            ("dz_retrievals_per_60", "DZ Retrievals"),
            ("zone_exits_per_60", "Breakouts"),
            ("exits_w_possession_per_60", "Possession Exits"),
            ("failed_exit_per_60", "Failed Exits"),
            ("botched_retrievals_per_60", "Botched Ret."),
            ("denials_per_60", "Blocks"),
        ],
    },
]

# PWHL PBP has no one-timer tagging — offense pillar uses chance assists instead.
PWHL_PILLAR_BARS = [
    {
        "title": "Offense",
        "keys": [
            ("shots_per_60", "Shots"),
            ("chances_per_60", "Chances"),
            ("passes_per_60", "Passes"),
            ("chance_assists_per_60", "Chance Assists"),
            ("shots_on_goal_per_60", "Shooting"),
            ("entries_w_chance_per_60", "Entries w/ Chance"),
        ],
    },
    *PILLAR_BARS[1:],
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

# PWHL has no A3Z — hero shows raw GS; tiles label team percentiles explicitly.
PWHL_HIGHLIGHT_TILES = [
    ("microstat_game_score", "GS"),
    ("offense", "OFF"),
    ("defense_composite", "DEF"),
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
            {"label": _pg("Shots on Goal"), "key": "SOG"},
            {"label": _pg("Expected Goals"), "key": "xG"},
            {"label": _pg("Chances"), "key": "Chances"},
            {"label": _pg("Goals"), "key": "Goals"},
            {"label": _pg("Assists"), "key": "Assists"},
            {"label": _pg("Passes"), "key": "Passes"},
        ],
    },
    {
        "title": "Zone Entries",
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
        "title": "Defense",
        "metrics": [
            {"label": _pg("Defensive Zone Retrievals"), "key": "DZ Retrievals"},
            {"label": _pg("Zone Exits"), "key": "Zone Exits"},
            {"label": _pg("Possession Exits"), "key": "Exits w/ Possession"},
            {"label": _pg("Breakouts"), "key": "Successful Breakouts"},
            {"label": _pg("Failed exits"), "key": "Failed Exits", "negative": True},
            {"label": _pg("Blocks"), "keys": ["Blocked Shots (DF)", "Blocked Shots"]},
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


def format_rate_stat(value, fmt: str = "decimal") -> str:
    """Event-rate row value — keeps the grid slot even when empty."""
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if not (n == n):
        return "—"
    if n == 0:
        return "—"
    if fmt == "percent":
        return f"{n:.0f}%"
    if fmt == "compact" and abs(n) >= 10:
        return f"{n:.1f}"
    return f"{n:.2f}"


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
