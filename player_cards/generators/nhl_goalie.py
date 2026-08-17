"""NHL goalie cards → player_cards/output/nhl/goalies/"""

from __future__ import annotations

from pathlib import Path
from typing import Any

KIND = "nhl_goalie"


def generate(
    name: str,
    team: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from player_cards.card_kinds import default_output_path, stamp_card_kind
    from player_cards.goalie_profile import generate_goalie_card

    kwargs.pop("kind", None)
    kwargs.pop("league", None)
    kwargs.pop("amateur_club", None)
    kwargs.pop("undrafted", None)
    kwargs.pop("a3z_season", None)
    kwargs.pop("pbp_source", None)
    kwargs.pop("max_pbp_downloads", None)
    kwargs.pop("refresh_pbp", None)
    kwargs.pop("use_store", None)
    output_png = kwargs.pop("output_png", None)
    if not output_png:
        output_png = default_output_path(KIND, name, team=team)
    result = generate_goalie_card(name, team, output_png=output_png, **kwargs)
    stamp_card_kind(result.get("profile"), KIND)
    result["card_kind"] = KIND
    return result


def default_png(name: str, team: str | None = None) -> Path:
    from player_cards.card_kinds import default_output_path

    return default_output_path(KIND, name, team=team)
