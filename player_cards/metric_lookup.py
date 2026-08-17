"""Resolve display metrics across A3Z and PBP section layouts."""

from __future__ import annotations

from typing import Any

# Pillar / highlight keys → ordered fallbacks (first match wins).
METRIC_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "successful_entries_per_60": ("successful_entries_per_60", "entries_w_passing_play_per_60"),
    "entries_w_chance_per_60": ("entries_w_chance_per_60", "carries_w_chances_per_60"),
    "zone_exits_per_60": ("zone_exits_per_60", "exits"),
    "exits": ("zone_exits_per_60", "exits"),
    "forechecking": ("forecheck_pressures_per_60", "forechecking"),
    "carries_per_60": ("carries_per_60", "carries_1_per_60"),
    "defense": ("defense", "entry_defense"),
    "defense_composite": ("defense", "entry_defense", "dz_retrievals_per_60"),
}


def metric_lookup(sections: dict[str, Any], key: str) -> dict[str, Any] | None:
    """Find a metric by key, trying A3Z/PBP aliases when the primary key is absent."""
    keys = METRIC_KEY_ALIASES.get(key, (key,))
    for alias in keys:
        for items in sections.values():
            if not isinstance(items, list):
                continue
            for m in items:
                if isinstance(m, dict) and m.get("key") == alias:
                    return m
    return None
