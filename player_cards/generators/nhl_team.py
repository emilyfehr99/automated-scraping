"""NHL team cards → player_cards/output/nhl/teams/"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KIND = "nhl_team"


def generate(
    name: str,
    team: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from player_cards.card_kinds import default_output_path, stamp_card_kind
    from player_cards.team_profile import build_team_card_profile
    from player_cards.team_renderer import generate_team_card_png

    tri = (team or name or "").upper()
    kwargs.pop("kind", None)
    kwargs.pop("amateur_club", None)
    kwargs.pop("undrafted", None)
    kwargs.pop("a3z_season", None)
    kwargs.pop("pbp_source", None)
    kwargs.pop("max_pbp_downloads", None)
    kwargs.pop("refresh_pbp", None)
    kwargs.pop("use_store", None)
    save_json = bool(kwargs.pop("save_json", False))
    output_png = kwargs.pop("output_png", None)
    instat_season_id = kwargs.pop("instat_season_id", None) or 36
    kwargs.pop("league", None)

    profile = build_team_card_profile(tri, instat_season_id=instat_season_id)
    stamp_card_kind(profile, KIND)
    png_path = Path(output_png) if output_png else default_output_path(KIND, tri, team=tri)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    generate_team_card_png(profile, png_path)
    result: dict[str, Any] = {
        "png": str(png_path),
        "profile": profile,
        "sources": profile.get("sources") or {},
        "card_kind": KIND,
    }
    if save_json:
        json_path = png_path.with_suffix(".json")
        json_path.write_text(json.dumps(profile, indent=2, default=str), encoding="utf-8")
        result["json"] = str(json_path)
    return result


def default_png(name: str, team: str | None = None) -> Path:
    from player_cards.card_kinds import default_output_path

    tri = (team or name or "team").upper()
    return default_output_path(KIND, tri, team=tri)
