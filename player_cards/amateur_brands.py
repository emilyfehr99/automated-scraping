"""Amateur / junior / NCAA team brand resolution (colours + logos).

Resolution order for colours:
  1. Explicit AMATEUR_TEAM_COLORS map (canonical full names + short aliases)
  2. Existing CHL_TEAM_COLORS / NHL TEAM_COLORS
  3. Dominant-colour sample from EP logo (cached)
  4. Neutral default
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from .ep_api import get_team_logo
from .team_colors import CHL_TEAM_COLORS, DEFAULT, TEAM_COLORS, get_team_colors

logger = logging.getLogger(__name__)

AMATEUR_TEAM_COLORS: dict[str, dict[str, str]] = {
    # WHL (extras / aliases)
    "EVERETT SILVERTIPS": {"primary": "#043927", "accent": "#C5A059", "light": "#E8F2EE"},
    "REGINA PATS": {"primary": "#00205B", "accent": "#CC0000", "light": "#E8EEFA"},
    "REGINA": {"primary": "#00205B", "accent": "#CC0000", "light": "#E8EEFA"},
    # Regina U18 AAA / U15
    "REGINA PAT CANADIANS U18 AAA": {"primary": "#00205B", "accent": "#C8102E", "light": "#E8EEFA"},
    "REGINA PAT CANADIANS": {"primary": "#00205B", "accent": "#C8102E", "light": "#E8EEFA"},
    "PAT CANADIANS": {"primary": "#00205B", "accent": "#C8102E", "light": "#E8EEFA"},
    "REGINA PAT BLUES U15 AA": {"primary": "#0033A0", "accent": "#FFFFFF", "light": "#E8EEFA"},
    "REGINA PAT BLUES": {"primary": "#0033A0", "accent": "#FFFFFF", "light": "#E8EEFA"},
    # Langley HA
    "LANGLEY HOCKEY ACADEMY U14": {"primary": "#1B1464", "accent": "#F15A29", "light": "#EEF0FA"},
    "LANGLEY HOCKEY ACADEMY U15": {"primary": "#1B1464", "accent": "#F15A29", "light": "#EEF0FA"},
    "LANGLEY HOCKEY ACADEMY 18U": {"primary": "#1B1464", "accent": "#F15A29", "light": "#EEF0FA"},
    "LANGLEY HOCKEY ACADEMY": {"primary": "#1B1464", "accent": "#F15A29", "light": "#EEF0FA"},
    "LANGLEY": {"primary": "#1B1464", "accent": "#F15A29", "light": "#EEF0FA"},
    # Edge School
    "EDGE SCHOOL U15 PREP": {"primary": "#111111", "accent": "#C5A059", "light": "#F5F5F5"},
    "EDGE SCHOOL U18 PREP": {"primary": "#111111", "accent": "#C5A059", "light": "#F5F5F5"},
    "EDGE SCHOOL": {"primary": "#111111", "accent": "#C5A059", "light": "#F5F5F5"},
    # NCAA
    "UNIV. OF MICHIGAN": {"primary": "#00274C", "accent": "#FFCB05", "light": "#E8EEF5"},
    "UNIVERSITY OF MICHIGAN": {"primary": "#00274C", "accent": "#FFCB05", "light": "#E8EEF5"},
    "MICHIGAN": {"primary": "#00274C", "accent": "#FFCB05", "light": "#E8EEF5"},
    "PENN STATE": {"primary": "#041E42", "accent": "#FFFFFF", "light": "#E8EDF5"},
}


def _norm_key(team: str) -> str:
    return " ".join((team or "").upper().replace('"', "").split())


@lru_cache(maxsize=256)
def resolve_team_brand(team: str, *, league: str | None = "prospect") -> dict[str, Any]:
    """Return ``{primary, accent, light, logo_url, source}`` for any club name."""
    key = _norm_key(team)
    colors = AMATEUR_TEAM_COLORS.get(key)
    source = "amateur_map"
    if not colors:
        for k, v in AMATEUR_TEAM_COLORS.items():
            if k in key or key in k:
                colors = v
                source = "amateur_fuzzy"
                break
    if not colors:
        colors = get_team_colors(team, league=league)
        source = "team_colors"
        if colors == DEFAULT and key in CHL_TEAM_COLORS:
            colors = CHL_TEAM_COLORS[key]
            source = "chl"
        elif colors == DEFAULT and key in TEAM_COLORS:
            colors = TEAM_COLORS[key]
            source = "nhl"

    logo = get_team_logo(team)
    return {
        "primary": colors["primary"],
        "accent": colors["accent"],
        "light": colors["light"],
        "logo_url": logo,
        "source": source,
        "team": team,
    }


def get_amateur_colors(team: str, *, league: str | None = "prospect") -> dict[str, str]:
    brand = resolve_team_brand(team, league=league)
    return {"primary": brand["primary"], "accent": brand["accent"], "light": brand["light"]}
