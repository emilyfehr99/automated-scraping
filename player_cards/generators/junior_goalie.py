"""Junior / undrafted goalie cards → player_cards/output/junior/goalies/"""

from __future__ import annotations

from pathlib import Path
from typing import Any

KIND = "junior_goalie"


def generate(
    name: str,
    team: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from player_cards.prospect_goalie_profile import generate_prospect_goalie_card

    amateur_club = kwargs.pop("amateur_club", None) or team or ""
    kwargs.pop("kind", None)
    kwargs.pop("league", None)
    kwargs.pop("undrafted", None)
    from player_cards.leagues import DEFAULT_SEASON
    a3z_season = kwargs.pop("a3z_season", DEFAULT_SEASON)
    output_png = kwargs.pop("output_png", None)
    save_json = kwargs.pop("save_json", False)

    if not output_png:
        from player_cards.card_kinds import default_output_path
        output_png = default_output_path(KIND, name, amateur_club=amateur_club)

    return generate_prospect_goalie_card(
        name,
        amateur_club,
        output_png=output_png,
        a3z_season=a3z_season,
        save_json=save_json,
    )


def default_png(name: str, team: str | None = None, amateur_club: str | None = None) -> Path:
    from player_cards.card_kinds import default_output_path
    return default_output_path(KIND, name, amateur_club=amateur_club or team)
