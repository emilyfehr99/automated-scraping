"""Roster position / goalie helpers for metric filtering."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOALIE_ROSTER_FILE = ROOT / "data" / "goalie_roster.json"


def norm_tokens(name: str) -> list[str]:
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("'", "").replace("-", " ")
    return [t for t in s.split() if t]


def is_defense(position: str | None) -> bool:
    p = str(position or "").upper().strip()
    if not p:
        return False
    if p in ("G", "GK", "GOALIE"):
        return False
    return p == "D" or p.startswith("D") or p in ("LD", "RD", "DEF", "DEFENSE")


def is_goalie_position(position: str | None) -> bool:
    p = str(position or "").upper().strip()
    return p in ("G", "GK", "GOALIE")


def load_goalie_name_set() -> set[str]:
    names: set[str] = set()
    if not GOALIE_ROSTER_FILE.exists():
        return names
    with open(GOALIE_ROSTER_FILE) as f:
        data = json.load(f)
    for team_names in data.values():
        for n in team_names:
            names.add(str(n))
            parts = str(n).split()
            if len(parts) >= 2:
                names.add(f"{parts[-1]} {' '.join(parts[:-1])}")
    return names


def is_goalie_player(player: str, position: str | None, goalie_names: set[str] | None = None) -> bool:
    if is_goalie_position(position):
        return True
    goalie_names = goalie_names if goalie_names is not None else load_goalie_name_set()
    if player in goalie_names:
        return True
    parts = str(player).split()
    if len(parts) >= 2:
        flipped = f"{' '.join(parts[1:])} {parts[0]}"
        if flipped in goalie_names:
            return True
    return False


def ht_to_instat(name: str) -> str:
    parts = str(name or "").strip().split()
    if len(parts) < 2:
        return str(name or "")
    return f"{parts[-1]} {' '.join(parts[:-1])}"


def build_position_by_instat(rosters: dict[str, list[dict]]) -> dict[str, str]:
    """Map INstat PBP player string -> HockeyTech position."""
    out: dict[str, str] = {}
    for players in rosters.values():
        for p in players:
            ht = str(p.get("name") or "")
            pos = str(p.get("position") or "")
            if not ht:
                continue
            out[ht_to_instat(ht)] = pos
            out[ht] = pos
    return out


def defense_mask_for_pdf(
    pdf,
    position_by_instat: dict[str, str] | None,
    goalie_names: set[str] | None = None,
):
    """Boolean mask: rows attributable to defensemen (excludes goalies + forwards)."""
    if "player" not in pdf.columns:
        return pdf.index.to_series().map(lambda _: False)
    goalie_names = goalie_names if goalie_names is not None else load_goalie_name_set()

    def row_ok(player: str) -> bool:
        pos = (position_by_instat or {}).get(str(player), "")
        if is_goalie_player(str(player), pos, goalie_names):
            return False
        return is_defense(pos)

    return pdf["player"].map(row_ok)
