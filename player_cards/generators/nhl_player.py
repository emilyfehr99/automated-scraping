"""NHL skater cards → player_cards/output/nhl/players/"""

from __future__ import annotations

from pathlib import Path
from typing import Any

KIND = "nhl_player"


def generate(
    name: str,
    team: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from player_cards.nhl_bio import fetch_nhl_bio

    pos = kwargs.get("position")
    if not pos:
        try:
            bio = fetch_nhl_bio(name, team=team)
            pos = bio.get("position")
        except Exception:
            pos = None
    if str(pos or "").strip().upper() in {"G", "GOALIE", "GOALTENDER"}:
        from . import nhl_goalie

        return nhl_goalie.generate(name, team=team, **kwargs)

    from player_cards.profile import generate_player_card

    kwargs.pop("kind", None)
    kwargs.setdefault("league", "nhl")
    kwargs.setdefault("undrafted", False)
    return generate_player_card(name, team, kind=KIND, **kwargs)



def default_png(name: str, team: str | None = None) -> Path:
    from player_cards.card_kinds import default_output_path

    return default_output_path(KIND, name, team=team)
