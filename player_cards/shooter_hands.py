"""League-wide shooter handedness map, built from NHL team rosters.

Needed to classify a shot as off-wing/on-wing (shooter's hand vs. which side
of the ice the shot came from) using real NHL data — not a manually-curated
lookup like the Clarkson/PWHL pipelines use.
"""

from __future__ import annotations

import httpx

from .leagues import NHL_INSTAT_TEAM_IDS


def _norm(name: str) -> str:
    return " ".join(str(name or "").lower().replace(".", "").split())


def fetch_league_shooter_hands(season: str = "20252026") -> dict[str, str]:
    """Normalized full name -> 'R'/'L', for every skater on a 2025-26 NHL roster."""
    out: dict[str, str] = {}
    with httpx.Client(headers={"User-Agent": "PlayerCards/1.0"}, timeout=12.0) as client:
        for team in NHL_INSTAT_TEAM_IDS:
            try:
                resp = client.get(f"https://api-web.nhle.com/v1/roster/{team}/{season}")
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                continue
            for group in ("forwards", "defensemen"):
                for p in data.get(group, []):
                    first = (p.get("firstName") or {}).get("default", "")
                    last = (p.get("lastName") or {}).get("default", "")
                    hand = str(p.get("shootsCatches") or "").strip().upper()
                    if hand in ("R", "L") and first and last:
                        out[_norm(f"{first} {last}")] = hand
    return out
