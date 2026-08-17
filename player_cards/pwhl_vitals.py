"""PWHL player vitals — HockeyTech roster + handedness + curated overrides."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

_HANDEDNESS_PATHS = (
    Path.home() / "CascadeProjects/pwhl-analytics/data/shooter_handedness.json",
    Path.home() / "Desktop/pwhl-analytics/data/shooter_handedness.json",
)

_OVERRIDES_PATH = Path(__file__).resolve().parent / "data" / "pwhl_vitals_overrides.json"

_HANDEDNESS_CACHE: dict[str, str] | None = None
_OVERRIDES_CACHE: dict[str, Any] | None = None


def _norm_name_key(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "").strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _name_keys(display_name: str, instat_name: str | None = None) -> list[str]:
    keys: list[str] = []
    for candidate in (display_name, instat_name):
        if not candidate:
            continue
        keys.append(str(candidate).strip().lower())
        parts = candidate.lower().split()
        if len(parts) >= 2:
            keys.append(f"{parts[-1]} {parts[0]}")
    return keys


def _load_handedness() -> dict[str, str]:
    global _HANDEDNESS_CACHE
    if _HANDEDNESS_CACHE is not None:
        return _HANDEDNESS_CACHE
    data: dict[str, str] = {}
    for path in _HANDEDNESS_PATHS:
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update({str(k).lower(): str(v).upper() for k, v in raw.items()})
        except Exception:
            continue
    _HANDEDNESS_CACHE = data
    return data


def _load_overrides() -> dict[str, Any]:
    global _OVERRIDES_CACHE
    if _OVERRIDES_CACHE is not None:
        return _OVERRIDES_CACHE
    if not _OVERRIDES_PATH.is_file():
        _OVERRIDES_CACHE = {"by_ht_player_id": {}, "by_name": {}}
        return _OVERRIDES_CACHE
    try:
        raw = json.loads(_OVERRIDES_PATH.read_text(encoding="utf-8"))
        _OVERRIDES_CACHE = raw if isinstance(raw, dict) else {"by_ht_player_id": {}, "by_name": {}}
    except Exception:
        _OVERRIDES_CACHE = {"by_ht_player_id": {}, "by_name": {}}
    return _OVERRIDES_CACHE


def _lookup_override(
    *,
    ht_player_id: str | None = None,
    display_name: str = "",
    instat_name: str | None = None,
) -> dict[str, Any]:
    data = _load_overrides()
    by_id = data.get("by_ht_player_id") or {}
    by_name = data.get("by_name") or {}
    if ht_player_id and str(ht_player_id) in by_id:
        return dict(by_id[str(ht_player_id)])
    for key in _name_keys(display_name, instat_name):
        if key in by_name:
            return dict(by_name[key])
    return {}


def parse_ht_height(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    m = re.match(r"(\d+)\s*['\-]\s*(\d+)", text)
    if m:
        return f"{m.group(1)}'{m.group(2)}\""
    return text


def parse_ht_shoots(raw: Any) -> str | None:
    s = str(raw or "").strip().upper()
    if s in ("L", "R", "C"):
        return s
    if s.startswith("LEFT"):
        return "L"
    if s.startswith("RIGHT"):
        return "R"
    if s.startswith("CATCH"):
        return "C"
    return None


def _is_goalie(position: str | None) -> bool:
    return str(position or "").strip().upper().startswith("G")


def lookup_handedness(display_name: str, instat_name: str | None = None) -> str | None:
    hands = _load_handedness()
    for candidate in (display_name, instat_name):
        if not candidate:
            continue
        key = _norm_name_key(candidate)
        if key in hands:
            return hands[key]
        parts = candidate.lower().split()
        if len(parts) >= 2:
            for combo in (f"{parts[-1]} {parts[0]}", parts[-1], parts[0]):
                k = _norm_name_key(combo)
                if k in hands:
                    return hands[k]
    return None


def vitals_from_ht_row(row: dict[str, Any]) -> dict[str, Any]:
    height = parse_ht_height(row.get("height") or row.get("h"))
    shoots = parse_ht_shoots(row.get("shoots"))
    jersey = row.get("sweater_number") or row.get("tp_jersey_number") or row.get("jersey_number")
    return {
        "height": height,
        "shoots": shoots,
        "sweater_number": jersey,
    }


def enrich_vitals(
    display_name: str,
    instat_name: str | None,
    row: dict[str, Any] | None,
    *,
    ht_player_id: str | None = None,
    position: str | None = None,
) -> dict[str, Any]:
    vitals = vitals_from_ht_row(row or {})
    pos = position or (row or {}).get("position")
    if not vitals.get("shoots"):
        vitals["shoots"] = lookup_handedness(display_name, instat_name)

    override = _lookup_override(
        ht_player_id=ht_player_id or (str((row or {}).get("player_id")) if row else None),
        display_name=display_name,
        instat_name=instat_name,
    )
    if override.get("height") and not vitals.get("height"):
        vitals["height"] = parse_ht_height(override["height"])
    catch = override.get("catches")
    if catch:
        vitals["shoots"] = str(catch).upper()
    elif override.get("shoots") and not vitals.get("shoots"):
        vitals["shoots"] = parse_ht_shoots(override["shoots"])
    if override.get("position") and not pos:
        vitals["position"] = str(override["position"]).upper()

    if not vitals.get("shoots") and _is_goalie(pos or vitals.get("position")):
        vitals["shoots"] = "C"

    return vitals


def format_shoots_label(bio: dict[str, Any]) -> str:
    """Card copy: goalies show Catches, skaters show Shoots."""
    pos = str(bio.get("position") or "").upper()
    val = bio.get("shoots") or "—"
    if pos.startswith("G"):
        return f"Catches {val}"
    return f"Shoots {val}"


def resolve_ht_vitals(
    name: str,
    tri: str,
    bio: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Look up HockeyTech roster (with cross-team fallback) and enrich vitals."""
    from .leagues import PWHL_HOCKEYTECH_TEAM_IDS
    from .pwhl_photos import _fetch_ht_roster, _find_roster_row, search_pwhl_player

    bio = bio or {}
    tri = tri.upper()
    instat = str(bio.get("instat_name") or name)
    ht: dict[str, Any] | None = None
    ht_team_id = PWHL_HOCKEYTECH_TEAM_IDS.get(tri)
    if ht_team_id:
        ht = _find_roster_row(instat, _fetch_ht_roster(ht_team_id))
    if not ht:
        found = search_pwhl_player(instat)
        if found:
            other_tri = str(found.get("team") or "").upper()
            other_ht_id = PWHL_HOCKEYTECH_TEAM_IDS.get(other_tri)
            if other_ht_id:
                ht = _find_roster_row(str(found.get("name") or instat), _fetch_ht_roster(other_ht_id))
            if not ht:
                ht = {
                    "player_id": found.get("player_id"),
                    "name": found.get("name"),
                    "position": found.get("position"),
                    "sweater_number": found.get("sweater_number"),
                }
    if not ht:
        vitals = enrich_vitals(
            name,
            instat,
            {},
            ht_player_id=str(bio.get("ht_player_id") or ""),
            position=bio.get("position"),
        )
        return {
            "height": vitals.get("height") or bio.get("height"),
            "shoots": vitals.get("shoots") or bio.get("shoots"),
            "sweater_number": vitals.get("sweater_number") or bio.get("sweater_number"),
            "position": vitals.get("position") or bio.get("position"),
            "ht_player_id": bio.get("ht_player_id"),
            "name": bio.get("name") or name,
        }
    vitals = enrich_vitals(
        str(ht.get("name") or name),
        instat,
        ht,
        ht_player_id=str(ht.get("player_id") or bio.get("ht_player_id") or ""),
        position=ht.get("position") or bio.get("position"),
    )
    return {
        "name": ht.get("name") or bio.get("name") or name,
        "ht_player_id": str(ht.get("player_id") or bio.get("ht_player_id") or ""),
        "position": vitals.get("position") or ht.get("position") or bio.get("position"),
        "sweater_number": vitals.get("sweater_number") or ht.get("sweater_number") or bio.get("sweater_number"),
        "height": vitals.get("height") or bio.get("height"),
        "shoots": vitals.get("shoots") or bio.get("shoots"),
    }
