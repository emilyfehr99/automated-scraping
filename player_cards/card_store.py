"""SQLite materialized store for instant player card generation."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from .a3z_source import resolve_a3z_season
from .disk_cache import CACHE_ROOT
from .nhl_bio import _norm

DEFAULT_STORE_PATH = Path(
    os.getenv("PLAYER_CARDS_STORE", str(CACHE_ROOT / "card_store.db"))
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team_builds (
    league TEXT NOT NULL DEFAULT 'nhl',
    team TEXT NOT NULL,
    season TEXT NOT NULL,
    pbp_fingerprint TEXT,
    pbp_dir TEXT,
    match_count INTEGER,
    player_count INTEGER DEFAULT 0,
    built_at REAL,
    PRIMARY KEY (league, team, season)
);

CREATE TABLE IF NOT EXISTS player_profiles (
    league TEXT NOT NULL DEFAULT 'nhl',
    player_id INTEGER NOT NULL,
    season TEXT NOT NULL,
    team TEXT NOT NULL,
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    pbp_fingerprint TEXT,
    built_at REAL NOT NULL,
    PRIMARY KEY (league, player_id, season)
);

CREATE INDEX IF NOT EXISTS idx_player_profiles_name ON player_profiles(league, name_norm);
CREATE INDEX IF NOT EXISTS idx_player_profiles_team_season ON player_profiles(league, team, season);
"""


class CardStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or DEFAULT_STORE_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        for table in ("team_builds", "player_profiles"):
            cols = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if "league" not in cols:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN league TEXT NOT NULL DEFAULT 'nhl'"
                )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> CardStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def upsert_team(
        self,
        team: str,
        season: str,
        *,
        league: str = "nhl",
        pbp_fingerprint: str | None,
        pbp_dir: str | None,
        match_count: int | None,
        player_count: int,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO team_builds(league, team, season, pbp_fingerprint, pbp_dir, match_count, player_count, built_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(league, team, season) DO UPDATE SET
                pbp_fingerprint = excluded.pbp_fingerprint,
                pbp_dir = excluded.pbp_dir,
                match_count = excluded.match_count,
                player_count = excluded.player_count,
                built_at = excluded.built_at
            """,
            (
                league,
                team.upper(),
                season,
                pbp_fingerprint,
                pbp_dir,
                match_count,
                player_count,
                time.time(),
            ),
        )
        self._conn.commit()

    def get_team_fingerprint(self, team: str, season: str, *, league: str = "nhl") -> str | None:
        row = self._conn.execute(
            "SELECT pbp_fingerprint FROM team_builds WHERE league = ? AND team = ? AND season = ?",
            (league, team.upper(), season),
        ).fetchone()
        return str(row["pbp_fingerprint"]) if row and row["pbp_fingerprint"] else None

    def list_teams(self, season: str) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM team_builds WHERE season = ? ORDER BY team",
                (season,),
            )
        )

    def upsert_profile(
        self,
        profile: dict[str, Any],
        *,
        season: str,
        pbp_fingerprint: str | None,
    ) -> None:
        bio = profile.get("bio") or {}
        player_id = bio.get("player_id")
        if not player_id:
            return
        name = str(bio.get("name") or "")
        team = str(bio.get("team") or "").upper()
        league = str(bio.get("league") or profile.get("league") or "nhl")
        self._conn.execute(
            """
            INSERT INTO player_profiles(
                league, player_id, season, team, name, name_norm, profile_json, pbp_fingerprint, built_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(league, player_id, season) DO UPDATE SET
                team = excluded.team,
                name = excluded.name,
                name_norm = excluded.name_norm,
                profile_json = excluded.profile_json,
                pbp_fingerprint = excluded.pbp_fingerprint,
                built_at = excluded.built_at
            """,
            (
                league,
                int(player_id),
                season,
                team,
                name,
                _norm(name),
                json.dumps(profile, default=str),
                pbp_fingerprint,
                time.time(),
            ),
        )
        self._conn.commit()

    def count_players(self, season: str, *, league: str | None = None) -> int:
        if league:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM player_profiles WHERE season = ? AND league = ?",
                (season, league),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM player_profiles WHERE season = ?",
                (season,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def find_profile(
        self,
        player_name: str,
        *,
        team: str | None = None,
        season: str | None = None,
        league: str = "nhl",
    ) -> dict[str, Any] | None:
        season = season or resolve_a3z_season(None, None)
        name_norm = _norm(player_name)
        params: list[Any] = [league, season]
        query = "SELECT * FROM player_profiles WHERE league = ? AND season = ?"
        if team:
            query += " AND team = ?"
            params.append(team.upper())

        rows = list(self._conn.execute(query, params))
        if not rows:
            return None

        def _rank(row: sqlite3.Row) -> tuple[int, int]:
            stored = str(row["name_norm"])
            score = 0
            if stored == name_norm:
                score += 100
            parts = name_norm.split()
            stored_parts = stored.split()
            if parts and stored_parts and parts[-1] == stored_parts[-1]:
                score += 40
            if name_norm in stored or stored in name_norm:
                score += 10
            return (score, -int(row["built_at"]))

        best = max(rows, key=_rank)
        if _rank(best)[0] < 40:
            return None

        team_fp = self.get_team_fingerprint(str(best["team"]), season, league=league)
        row_fp = best["pbp_fingerprint"]
        if team_fp and row_fp and team_fp != row_fp:
            return None

        profile = json.loads(str(best["profile_json"]))
        profile.setdefault("sources", {})
        profile["sources"]["card_store"] = True
        profile["sources"]["store_path"] = str(self.path)
        return profile


def open_store(path: Path | str | None = None) -> CardStore:
    return CardStore(path)


def load_stored_profile(
    player_name: str,
    *,
    team: str | None = None,
    season: str | None = None,
    league: str = "nhl",
    store_path: Path | str | None = None,
) -> dict[str, Any] | None:
    with open_store(store_path) as store:
        return store.find_profile(player_name, team=team, season=season, league=league)
