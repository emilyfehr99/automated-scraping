"""Fast player-centric PBP harvest across all Prospects caches.

For dual-roster / heavily-scouted juniors (Schultz, Pue, Dupont), opponent
folders already hold many of their games. Harvesting by player name +
deduping on match id is seconds, not minutes — no InStat session required.
"""

from __future__ import annotations

import csv
import logging
import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from .instat_source import _match_player_name
from .leagues import player_cards_work_root

logger = logging.getLogger(__name__)


def prospects_root() -> Path:
    override = os.getenv("PLAYER_CARDS_WORK_ROOT", "").strip()
    if override:
        return Path(override) / "Prospects"
    return player_cards_work_root() / "Prospects"


def _match_id_from_path(path: Path) -> str | None:
    m = re.search(r"_(\d+)_pbp\.csv$", path.name)
    return m.group(1) if m else None


def _player_needles(player_name: str) -> list[str]:
    """InStat CSVs use both 'First Last' and 'Last First'."""
    parts = [p for p in re.split(r"\s+", player_name.strip()) if p]
    needles = [player_name.strip()]
    if len(parts) >= 2:
        needles.append(f"{parts[-1]} {' '.join(parts[:-1])}")
        needles.append(f"{parts[-1]} {parts[0]}")
    # unique preserve order
    out, seen = [], set()
    for n in needles:
        k = n.lower()
        if k not in seen:
            seen.add(k)
            out.append(n)
    return out


def find_player_pbp_files(
    player_name: str,
    *,
    root: Path | None = None,
) -> dict[str, list[Path]]:
    """Map club name → unique game CSV paths where the player appears."""
    root = root or prospects_root()
    if not root.is_dir():
        return {}

    needles = _player_needles(player_name)
    # ripgrep is far faster than walking every CSV in Python.
    found: set[Path] = set()
    for needle in needles:
        try:
            proc = subprocess.run(
                ["rg", "-l", "--glob", "game_*_pbp.csv", needle, str(root)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception as exc:
            logger.warning("rg harvest failed for %s: %s", needle, exc)
            continue
        for line in proc.stdout.splitlines():
            p = Path(line.strip())
            if p.is_file():
                found.add(p)

    by_team: dict[str, dict[str, Path]] = defaultdict(dict)
    for path in found:
        mid = _match_id_from_path(path) or path.name
        try:
            with path.open(encoding="utf-8", errors="ignore") as fh:
                for row in csv.DictReader(fh):
                    pname = str(row.get("player") or "")
                    team = str(row.get("team") or "").strip()
                    if not team:
                        continue
                    if _match_player_name(pname, player_name):
                        by_team[team][mid] = path
                        break
        except Exception:
            continue

    return {team: sorted(files.values(), key=lambda p: p.name) for team, files in by_team.items()}


def materialize_team_cache(
    team: str,
    files: list[Path],
    *,
    league: str = "prospect",
) -> Path:
    """Hardlink/copy unique harvest files into the canonical Prospects cache dir."""
    from .instat_pbp_fetch import team_pbp_dir

    out = team_pbp_dir(team, league=league)
    out.mkdir(parents=True, exist_ok=True)
    for src in files:
        dest = out / src.name
        if dest.exists():
            continue
        try:
            os.link(src, dest)
        except OSError:
            try:
                dest.symlink_to(src.resolve())
            except OSError:
                shutil.copy2(src, dest)
    return out


def harvest_player_pbp(
    player_name: str,
    *,
    prefer_clubs: list[str] | None = None,
    league: str = "prospect",
    materialize: bool = True,
) -> dict[str, Any]:
    """Fast multi-club PBP assemble for a prospect (< a few seconds on local disk).

    Returns ``{teams: {club: [paths]}, file_groups: [...], all_files: [...],
    games_by_team: {club: n}}``.
    """
    by_team = find_player_pbp_files(player_name)
    if prefer_clubs:
        # Stable order: preferred clubs first, then any extras found.
        ordered: dict[str, list[Path]] = {}
        used = set()
        for club in prefer_clubs:
            # fuzzy match harvest keys
            key = next(
                (
                    t
                    for t in by_team
                    if t.lower() == club.lower()
                    or club.lower() in t.lower()
                    or t.lower() in club.lower()
                ),
                None,
            )
            if key and key not in used:
                ordered[key] = by_team[key]
                used.add(key)
        for t, files in by_team.items():
            if t not in used:
                ordered[t] = files
        by_team = ordered

    if materialize:
        for team, files in list(by_team.items()):
            materialize_team_cache(team, files, league=league)

    file_groups: list[tuple[str, list[Path], int | None]] = []
    all_files: list[Path] = []
    games_by_team: dict[str, int] = {}
    for team, files in by_team.items():
        if not files:
            continue
        file_groups.append((team, files, len(files)))
        all_files.extend(files)
        games_by_team[team] = len(files)

    logger.info(
        "Harvested PBP for %s — %s games across %s clubs: %s",
        player_name,
        len(all_files),
        len(games_by_team),
        games_by_team,
    )
    return {
        "teams": by_team,
        "file_groups": file_groups,
        "all_files": all_files,
        "games_by_team": games_by_team,
        "source": "local_harvest",
    }
