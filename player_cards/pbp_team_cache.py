"""In-memory cache of team PBP CSVs — avoids re-reading ~90 files per player."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .disk_cache import pbp_files_fingerprint

logger = logging.getLogger(__name__)

_frames: dict[str, list[tuple[Path, pd.DataFrame]]] = {}


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    if "player" not in df.columns and "Player" in df.columns:
        df = df.rename(columns={"Player": "player", "Team": "team", "Action": "action"})
    return df


def warm_team_pbp(files: list[Path]) -> str | None:
    """Load all team PBP CSVs into memory. Returns fingerprint."""
    if not files:
        return None
    fp = pbp_files_fingerprint(files)
    if fp in _frames:
        return fp
    loaded: list[tuple[Path, pd.DataFrame]] = []
    for path in files:
        try:
            df = _normalize_df(pd.read_csv(path))
            loaded.append((path, df))
        except Exception as exc:
            logger.warning("Skip PBP file %s: %s", path.name, exc)
    _frames[fp] = loaded
    logger.info("Warmed %s PBP games in memory (fp=%s)", len(loaded), fp)
    return fp


def get_team_frames(files: list[Path]) -> list[tuple[Path, pd.DataFrame]]:
    fp = warm_team_pbp(files)
    if not fp:
        return []
    return _frames.get(fp, [])


def get_frame(path: Path, files: list[Path]) -> pd.DataFrame | None:
    for p, df in get_team_frames(files):
        if p == path or p.name == path.name:
            return df
    try:
        return _normalize_df(pd.read_csv(path))
    except Exception:
        return None
