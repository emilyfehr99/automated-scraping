"""NHL-org drafted prospects → player_cards/output/nhl/prospects/"""

from __future__ import annotations

from pathlib import Path
from typing import Any

KIND = "nhl_prospect"

# 2026 NHL-org prospects used by the batch helper (not junior/undrafted).
BATCH = [
    ("Gavin McKenna", "TOR"),
    ("Ivar Stenberg", "SJS"),
]


def generate(
    name: str,
    team: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from player_cards.profile import generate_player_card

    kwargs.pop("kind", None)
    kwargs.setdefault("league", "prospect")
    kwargs.setdefault("undrafted", False)
    kwargs.setdefault("pbp_source", "api")
    return generate_player_card(name, team, kind=KIND, **kwargs)


def generate_batch(players: list[tuple[str, str]] | None = None) -> list[dict[str, Any]]:
    rows = players or BATCH
    out: list[dict[str, Any]] = []
    for name, tri in rows:
        print(f"→ {name} ({tri}) nhl_prospect")
        out.append(generate(name, team=tri, save_json=True))
    return out


def default_png(name: str, team: str | None = None) -> Path:
    from player_cards.card_kinds import default_output_path

    return default_output_path(KIND, name, team=team)
