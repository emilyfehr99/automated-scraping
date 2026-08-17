"""PWHL skater cards → player_cards/output/pwhl/players/"""

from __future__ import annotations

from pathlib import Path
from typing import Any

KIND = "pwhl_player"


def generate(
    name: str,
    team: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from player_cards.profile import generate_player_card

    kwargs.pop("kind", None)
    kwargs.setdefault("league", "pwhl")
    kwargs.setdefault("undrafted", False)
    kwargs.setdefault("pbp_source", "api")
    return generate_player_card(name, team, kind=KIND, **kwargs)


def default_png(name: str, team: str | None = None) -> Path:
    from player_cards.card_kinds import default_output_path

    return default_output_path(KIND, name, team=team)
