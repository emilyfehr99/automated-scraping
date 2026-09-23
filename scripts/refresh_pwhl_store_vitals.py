#!/usr/bin/env python3
"""Patch PWHL card-store bios with enriched vitals (fast — no PBP recompute)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from player_cards.card_store import load_stored_profile, open_store
from player_cards.leagues import list_teams
from player_cards.pwhl_vitals import resolve_ht_vitals


def patch_team(store, tri: str, *, season: str = "2025-26") -> dict:
    updated = 0
    for entry in store.list_team_players(tri, league="pwhl", season=season):
        prof = load_stored_profile(entry["name"], team=tri, season=season, league="pwhl")
        if not prof:
            continue
        bio = prof.get("bio") or {}
        patch = resolve_ht_vitals(str(bio.get("name") or entry["name"]), tri, bio)
        new_bio = {**bio}
        for key, val in patch.items():
            if val is not None and val != "":
                new_bio[key] = val
        if new_bio == bio:
            continue
        prof["bio"] = new_bio
        row = store._conn.execute(
            "SELECT pbp_fingerprint FROM player_profiles WHERE league='pwhl' AND season=? AND team=? AND name=?",
            (season, tri, entry["name"]),
        ).fetchone()
        fp = row["pbp_fingerprint"] if row else None
        store.upsert_profile(prof, season=season, pbp_fingerprint=fp)
        updated += 1
    return {"team": tri, "updated": updated}


def main() -> int:
    teams = [t.strip().upper() for t in sys.argv[1:]] if len(sys.argv) > 1 else list_teams("pwhl")
    results = []
    with open_store() as store:
        for tri in teams:
            results.append(patch_team(store, tri))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
