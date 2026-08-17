"""Discover and load InStat PBP CSVs for research (by team, date, game id, league)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from .instat_source import discover_team_pbp_files
from .leagues import LEAGUES, player_cards_work_root
from .pbp_team_cache import get_team_frames, warm_team_pbp

_PBP_NAME = re.compile(
    r"^game_(?:(?P<game_date>\d{4}-\d{2}-\d{2})_)?(?P<match_id>\d+)_pbp\.csv$",
    re.I,
)

_FULL_TO_ABBREV: dict[str, tuple[str, str]] = {}
for _league_key, _cfg in LEAGUES.items():
    for _tri, _full in _cfg.teams.items():
        _FULL_TO_ABBREV[_full.lower()] = (_tri, _league_key)


@dataclass(frozen=True)
class GameRecord:
    path: Path
    match_id: str
    game_date: date | None
    team: str | None
    team_full: str | None
    league: str | None
    bytes: int

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "match_id": self.match_id,
            "game_date": self.game_date.isoformat() if self.game_date else None,
            "team": self.team,
            "team_full": self.team_full,
            "league": self.league,
            "bytes": self.bytes,
        }


def parse_pbp_path(path: Path) -> tuple[str, date | None]:
    m = _PBP_NAME.match(path.name)
    if not m:
        mid = re.search(r"(\d+)_pbp\.csv$", path.name, re.I)
        return (mid.group(1) if mid else path.stem, None)
    gd = m.group("game_date")
    return m.group("match_id"), date.fromisoformat(gd) if gd else None


def _team_from_path(path: Path, work_root: Path) -> tuple[str | None, str | None, str | None]:
    try:
        rel = path.relative_to(work_root)
    except ValueError:
        return None, None, None
    parts = rel.parts
    if not parts:
        return None, None, None
    if parts[0].upper() == "PWHL" and len(parts) >= 2:
        full = parts[1]
        tri, league = _FULL_TO_ABBREV.get(full.lower(), (None, "pwhl"))
        return tri, full, league or "pwhl"
    full = parts[0]
    tri, league = _FULL_TO_ABBREV.get(full.lower(), (None, "nhl"))
    return tri, full, league or "nhl"


def catalog_games(*, work_root: Path | None = None) -> list[GameRecord]:
    """Index every `*_pbp.csv` under PLAYER_CARDS_WORK_ROOT."""
    root = work_root or player_cards_work_root()
    rows: list[GameRecord] = []
    if not root.is_dir():
        return rows
    for path in sorted(root.glob("**/Instat_API_Downloads/*_pbp.csv")):
        if not path.is_file():
            continue
        match_id, game_date = parse_pbp_path(path)
        tri, full, league = _team_from_path(path, root)
        rows.append(
            GameRecord(
                path=path,
                match_id=match_id,
                game_date=game_date,
                team=tri,
                team_full=full,
                league=league,
                bytes=path.stat().st_size,
            )
        )
    return rows


def _parse_iso(d: str | date | None) -> date | None:
    if d is None:
        return None
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d).strip())


def filter_games(
    games: Iterable[GameRecord],
    *,
    league: str | None = None,
    team: str | None = None,
    game_date: str | date | None = None,
    date_from: str | date | None = None,
    date_to: str | date | None = None,
    match_ids: Iterable[str | int] | None = None,
) -> list[GameRecord]:
    """Filter catalog rows. Team filter matches home-folder team (each CSV is one team's feed)."""
    tri = team.upper() if team else None
    lg = league.lower() if league else None
    target_date = _parse_iso(game_date)
    d0 = _parse_iso(date_from)
    d1 = _parse_iso(date_to)
    id_set = {str(x) for x in match_ids} if match_ids is not None else None

    out: list[GameRecord] = []
    for g in games:
        if lg and (g.league or "").lower() != lg:
            continue
        if tri and (g.team or "").upper() != tri:
            continue
        if id_set is not None and g.match_id not in id_set:
            continue
        if target_date and g.game_date != target_date:
            continue
        if d0 and (g.game_date is None or g.game_date < d0):
            continue
        if d1 and (g.game_date is None or g.game_date > d1):
            continue
        out.append(g)
    return out


def dedupe_by_match_id(games: Iterable[GameRecord]) -> list[GameRecord]:
    """One file per InStat match_id (largest file wins — both teams' feeds share an id)."""
    best: dict[str, GameRecord] = {}
    for g in games:
        prev = best.get(g.match_id)
        if prev is None or g.bytes > prev.bytes:
            best[g.match_id] = g
    return sorted(best.values(), key=lambda r: (r.game_date or date.min, r.match_id))


def resolve_files(
    *,
    league: str | None = None,
    team: str | None = None,
    game_date: str | date | None = None,
    date_from: str | date | None = None,
    date_to: str | date | None = None,
    match_ids: Iterable[str | int] | None = None,
    dedupe: bool = True,
    work_root: Path | None = None,
) -> list[Path]:
    """Return PBP file paths matching filters."""
    if team and not (game_date or date_from or date_to or match_ids):
        files = discover_team_pbp_files(team)
        if league:
            lg = league.lower()
            files = [f for f in files if _team_from_path(f, work_root or player_cards_work_root())[2] == lg]
        return sorted(files)

    games = catalog_games(work_root=work_root)
    hits = filter_games(
        games,
        league=league,
        team=team,
        game_date=game_date,
        date_from=date_from,
        date_to=date_to,
        match_ids=match_ids,
    )
    if dedupe:
        hits = dedupe_by_match_id(hits)
    return [g.path for g in hits]


def load_dataframe(
    files: list[Path] | None = None,
    *,
    league: str | None = None,
    team: str | None = None,
    game_date: str | date | None = None,
    date_from: str | date | None = None,
    date_to: str | date | None = None,
    match_ids: Iterable[str | int] | None = None,
    dedupe_games: bool = True,
) -> pd.DataFrame:
    """Load filtered PBP into one DataFrame with game_id + source_file columns."""
    paths = files or resolve_files(
        league=league,
        team=team,
        game_date=game_date,
        date_from=date_from,
        date_to=date_to,
        match_ids=match_ids,
        dedupe=dedupe_games,
    )
    if not paths:
        return pd.DataFrame()

    warm_team_pbp(paths)
    parts: list[pd.DataFrame] = []
    for path, df in get_team_frames(paths):
        if df.empty:
            continue
        chunk = df.copy()
        mid, gd = parse_pbp_path(path)
        chunk["game_id"] = mid
        chunk["game_date"] = gd.isoformat() if gd else None
        chunk["source_file"] = path.name
        parts.append(chunk)

    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    sort_cols = [c for c in ("game_date", "game_id", "half", "start") if c in out.columns]
    if sort_cols:
        out = out.sort_values(sort_cols)
    return out.reset_index(drop=True)


def summary(*, work_root: Path | None = None) -> dict:
    games = catalog_games(work_root=work_root)
    unique = dedupe_by_match_id(games)
    by_league: dict[str, int] = {}
    by_team: dict[str, int] = {}
    dated = sum(1 for g in unique if g.game_date)
    for g in games:
        by_league[g.league or "?"] = by_league.get(g.league or "?", 0) + 1
        key = f"{g.league}/{g.team}" if g.team else "?"
        by_team[key] = by_team.get(key, 0) + 1
    dates = sorted({g.game_date for g in unique if g.game_date})
    return {
        "work_root": str(work_root or player_cards_work_root()),
        "file_rows": len(games),
        "unique_games": len(unique),
        "dated_games": dated,
        "date_min": dates[0].isoformat() if dates else None,
        "date_max": dates[-1].isoformat() if dates else None,
        "by_league_files": by_league,
        "by_team_files": dict(sorted(by_team.items())),
    }
