"""Card kinds — keep NHL / PWHL / junior pipelines separate and pick smart defaults.

Kinds (do not mix output trees):
  nhl_player     — NHL skater cards
  nhl_goalie     — NHL goalie cards
  nhl_prospect   — NHL-org drafted prospects (still junior/college, branded by NHL club)
  nhl_team       — NHL team cards
  pwhl_player    — PWHL skater cards
  junior_player  — Undrafted / junior dual-roster cards (Pats + Pat Canadians, etc.)

Detection + default output paths live here so every entry point
(`python -m player_cards`, player_cards.generators, API) stays consistent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OUTPUT_ROOT = Path(__file__).resolve().parent / "output"

CARD_KINDS = (
    "nhl_player",
    "nhl_goalie",
    "nhl_prospect",
    "nhl_team",
    "pwhl_player",
    "junior_player",
)


@dataclass(frozen=True)
class CardKindSpec:
    kind: str
    label: str
    league: str  # data league key in leagues.LEAGUES
    output_subdir: str
    description: str


SPECS: dict[str, CardKindSpec] = {
    "nhl_player": CardKindSpec(
        "nhl_player",
        "NHL Player",
        "nhl",
        "nhl/players",
        "NHL skater microstat cards",
    ),
    "nhl_goalie": CardKindSpec(
        "nhl_goalie",
        "NHL Goalie",
        "nhl",
        "nhl/goalies",
        "NHL goalie cards",
    ),
    "nhl_prospect": CardKindSpec(
        "nhl_prospect",
        "NHL Prospect",
        "prospect",
        "nhl/prospects",
        "NHL-org drafted prospects (junior/college) branded by NHL club",
    ),
    "nhl_team": CardKindSpec(
        "nhl_team",
        "NHL Team",
        "nhl",
        "nhl/teams",
        "NHL team roster cards",
    ),
    "pwhl_player": CardKindSpec(
        "pwhl_player",
        "PWHL Player",
        "pwhl",
        "pwhl/players",
        "PWHL skater microstat cards",
    ),
    "junior_player": CardKindSpec(
        "junior_player",
        "Junior / Undrafted",
        "prospect",
        "junior/players",
        "Undrafted junior dual-roster cards (WHL/U18/etc.)",
    ),
}


def normalize_kind(kind: str | None) -> str | None:
    if not kind:
        return None
    k = kind.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "player": "nhl_player",
        "skater": "nhl_player",
        "nhl": "nhl_player",
        "goalie": "nhl_goalie",
        "g": "nhl_goalie",
        "prospect": "nhl_prospect",
        "nhl_org_prospect": "nhl_prospect",
        "org_prospect": "nhl_prospect",
        "team": "nhl_team",
        "pwhl": "pwhl_player",
        "pwhl_skater": "pwhl_player",
        "junior": "junior_player",
        "undrafted": "junior_player",
        "junior_prospect": "junior_player",
        "amateur": "junior_player",
    }
    k = aliases.get(k, k)
    if k not in SPECS:
        raise ValueError(f"Unknown card kind {kind!r}; choose from {', '.join(CARD_KINDS)}")
    return k


def slugify(*parts: str | None) -> str:
    bits: list[str] = []
    for part in parts:
        if not part:
            continue
        s = re.sub(r"[^a-z0-9]+", "-", str(part).strip().lower())
        s = s.strip("-")
        if s:
            bits.append(s)
    return "-".join(bits) or "card"


def detect_card_kind(
    name: str,
    *,
    kind: str | None = None,
    league: str | None = None,
    team: str | None = None,
    amateur_club: str | None = None,
    undrafted: bool | None = None,
    team_card: bool = False,
    position: str | None = None,
) -> str:
    """Infer card kind from flags. Explicit ``kind`` always wins."""
    if kind:
        return normalize_kind(kind)  # type: ignore[return-value]
    if team_card:
        return "nhl_team"

    nhl_tri = bool(team and re.fullmatch(r"[A-Za-z]{3}", team.strip()))
    pos = (position or "").strip().upper()
    if pos in {"G", "GOALIE", "GOALTENDER"}:
        return "nhl_goalie"

    if undrafted is True or (
        amateur_club and not nhl_tri and (league in {None, "prospect"} or undrafted is not False)
    ):
        # Junior / undrafted path — dual-roster SMAAAHL+WHL kids etc.
        if not nhl_tri:
            return "junior_player"

    league_l = (league or "").strip().lower()
    if league_l == "pwhl":
        return "pwhl_player"
    if league_l == "prospect":
        return "nhl_prospect" if nhl_tri else "junior_player"

    if league_l in {"nhl", ""}:
        return "nhl_player"
    return "nhl_player"


def default_output_path(
    kind: str,
    name: str,
    *,
    team: str | None = None,
    amateur_club: str | None = None,
) -> Path:
    """Canonical on-disk path under player_cards/output/<kind>/…"""
    kind = normalize_kind(kind)  # type: ignore[assignment]
    spec = SPECS[kind]
    if kind == "nhl_team":
        tri = (team or name or "team").upper()
        filename = f"{tri.lower()}-team.png"
    elif kind == "nhl_goalie":
        filename = f"{slugify(name, team)}-goalie.png"
    elif kind == "nhl_prospect":
        filename = f"{slugify(name, team or amateur_club)}-prospect.png"
    elif kind == "junior_player":
        club = amateur_club or team
        club_bit = (club or "").split()[0] if club else None
        filename = f"{slugify(name, club_bit)}-junior.png"
    elif kind == "pwhl_player":
        filename = f"{slugify(name, team)}-pwhl.png"
    else:
        filename = f"{slugify(name, team)}.png"
    path = OUTPUT_ROOT / spec.output_subdir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def kind_to_league(kind: str) -> str:
    return SPECS[normalize_kind(kind)].league  # type: ignore[index]


def stamp_card_kind(profile: dict[str, Any] | None, kind: str) -> None:
    if not profile:
        return
    sources = profile.setdefault("sources", {})
    sources["card_kind"] = kind
    sources["card_kind_label"] = SPECS[kind].label
    bio = profile.get("bio")
    if isinstance(bio, dict):
        bio["card_kind"] = kind
