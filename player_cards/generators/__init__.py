"""One folder, separate generators per card kind.

Call ``generate_card(...)`` from the CLI/API. Each kind lives in its own
module and writes to its own output tree under ``player_cards/output/``.
"""

from __future__ import annotations

from typing import Any

from player_cards.card_kinds import CARD_KINDS, detect_card_kind, kind_to_league

from . import junior_player, nhl_goalie, nhl_player, nhl_prospect, nhl_team, pwhl_player

GENERATORS = {
    "nhl_player": nhl_player,
    "nhl_goalie": nhl_goalie,
    "nhl_prospect": nhl_prospect,
    "nhl_team": nhl_team,
    "pwhl_player": pwhl_player,
    "junior_player": junior_player,
}


def generate_card(
    name: str,
    team: str | None = None,
    *,
    kind: str | None = None,
    league: str | None = None,
    amateur_club: str | None = None,
    undrafted: bool | None = None,
    team_card: bool = False,
    position: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Dispatch to the generator for this card kind. Kinds never share output dirs."""
    card_kind = detect_card_kind(
        name,
        kind=kind,
        league=league,
        team=team,
        amateur_club=amateur_club,
        undrafted=undrafted,
        team_card=team_card,
        position=position,
    )
    mod = GENERATORS[card_kind]
    kwargs.setdefault("league", league or kind_to_league(card_kind))
    return mod.generate(
        name,
        team=team,
        amateur_club=amateur_club,
        undrafted=undrafted,
        **kwargs,
    )


def assert_generators_complete() -> None:
    missing = [k for k in CARD_KINDS if k not in GENERATORS]
    extra = [k for k in GENERATORS if k not in CARD_KINDS]
    if missing or extra:
        raise RuntimeError(f"generator/kind mismatch missing={missing} extra={extra}")


assert_generators_complete()
