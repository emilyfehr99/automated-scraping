"""Junior / undrafted cards → player_cards/output/junior/players/"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

KIND = "junior_player"

PLAYERS = [
    ("Landon Dupont", "Everett Silvertips"),
    ("Maddox Schultz", "Regina Pats"),
    ("Liam Pue", "Regina Pats"),
]


def generate(
    name: str,
    team: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from player_cards.profile import generate_player_card

    amateur_club = kwargs.pop("amateur_club", None) or team
    kwargs.pop("kind", None)
    kwargs.setdefault("league", "prospect")
    kwargs["undrafted"] = True if kwargs.get("undrafted") is None else kwargs.get("undrafted")
    kwargs.setdefault("pbp_source", "harvest")
    if kwargs.get("use_store") is None:
        kwargs["use_store"] = False
    kwargs.setdefault("a3z_season", "2025-26")
    return generate_player_card(
        name,
        team=None,
        kind=KIND,
        amateur_club=amateur_club,
        **kwargs,
    )


def generate_batch(players: list[tuple[str, str]] | None = None) -> list[dict[str, Any]]:
    from player_cards.card_kinds import default_output_path, slugify
    from player_cards.validate_card import _issues_for_profile

    rows = players or PLAYERS
    legacy_dir = Path(__file__).resolve().parents[1] / "output" / "undrafted"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for name, club in rows:
        out = default_output_path(KIND, name, amateur_club=club)
        club_slug = slugify(club.split()[0])
        legacy = legacy_dir / f"{slugify(name)}-{club_slug}-prospect.png"
        t0 = time.time()
        print(f"→ {name} ({club}) [{out}]")
        res = generate(name, amateur_club=club, output_png=out, save_json=True)
        png = Path(res["png"])
        if png.is_file():
            shutil.copy2(png, legacy)
            j = png.with_suffix(".json")
            if j.is_file():
                shutil.copy2(j, legacy.with_suffix(".json"))
        bio = (res.get("profile") or {}).get("bio") or {}
        sources = res.get("sources") or {}
        pbp = (res.get("profile") or {}).get("pbp") or {}
        elapsed = time.time() - t0
        print(f"  {elapsed:.1f}s  kind={res.get('card_kind')} png={res.get('png')}")
        print(f"  vitals={bio.get('height')} / {bio.get('weight_lbs')} / {bio.get('shoots')}")
        print(f"  ep_totals={bio.get('ep_season_totals')}")
        print(
            f"  pbp_goals={pbp.get('goals')} shot_count={pbp.get('shot_count')} "
            f"gp={pbp.get('games_played')}"
        )
        print(
            f"  pbp_sample={sources.get('pbp_sample_games')} "
            f"season_gp={sources.get('season_gp')}"
        )
        print(f"  games_by_team={sources.get('games_by_team')}")
        print(
            f"  missing_pbp={sources.get('missing_pbp_clubs')} "
            f"incomplete={sources.get('pbp_incomplete_vs_season')}"
        )
        results.append(res)

    junior_dir = Path(__file__).resolve().parents[1] / "output" / "junior" / "players"
    issues: list[str] = []
    for path in list(junior_dir.glob("*-junior.json")) + list(legacy_dir.glob("*-prospect.json")):
        issues.extend(
            _issues_for_profile(json.loads(path.read_text(encoding="utf-8")), name=path.name)
        )
    if issues:
        print("VALIDATE FAIL:")
        for msg in issues:
            print(f"  {msg}")
        raise SystemExit(1)
    print("VALIDATE OK: no mismatches")
    return results


def main() -> None:
    generate_batch()


def default_png(name: str, team: str | None = None, amateur_club: str | None = None) -> Path:
    from player_cards.card_kinds import default_output_path

    return default_output_path(KIND, name, team=team, amateur_club=amateur_club or team)
