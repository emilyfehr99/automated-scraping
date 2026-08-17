"""In-memory cache of team PBP CSVs — avoids re-reading ~90 files per player."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .disk_cache import pbp_files_fingerprint
from .instat_source import is_pbp_game_csv

logger = logging.getLogger(__name__)

_frames: dict[str, list[tuple[Path, pd.DataFrame]]] = {}


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    import numpy as np
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    if "player" not in df.columns and "Player" in df.columns:
        df = df.rename(columns={"Player": "player", "Team": "team", "Action": "action"})
    if "pos_x" in df.columns:
        df["pos_x"] = pd.to_numeric(df["pos_x"], errors="coerce")
    else:
        df["pos_x"] = np.nan
    if "pos_y" in df.columns:
        df["pos_y"] = pd.to_numeric(df["pos_y"], errors="coerce")
    else:
        df["pos_y"] = np.nan
    if "start" in df.columns:
        df = df.sort_values(["half", "start"]).reset_index(drop=True)
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
        if not is_pbp_game_csv(path):
            continue
        try:
            df = _normalize_df(pd.read_csv(path))
            if "player" not in df.columns or "action" not in df.columns:
                logger.warning("Skip non-PBP CSV %s (missing player/action)", path.name)
                continue
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
