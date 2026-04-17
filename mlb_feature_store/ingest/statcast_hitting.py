"""
Statcast hitting ingestion.

Pulls pitch-level Statcast data for a given date range using pybaseball,
retains only the columns required for hitter feature engineering, and
saves each day's data as a Parquet file under data/raw/statcast/.
"""

from datetime import date
from pathlib import Path

import pandas as pd
from loguru import logger
from pybaseball import statcast

from config.settings import PATHS, SETTINGS


def _parquet_path(game_date: date) -> Path:
    return PATHS.raw_statcast / f"{game_date.isoformat()}.parquet"


def ingest_statcast_hitting(start: date, end: date, force: bool = False) -> list[Path]:
    """
    Pull Statcast hitting data for [start, end] and persist to Parquet.

    Parameters
    ----------
    start:
        First date to ingest (inclusive).
    end:
        Last date to ingest (inclusive).
    force:
        If True, overwrite existing files. Default skips dates already on disk.

    Returns
    -------
    List of Parquet paths written (may be empty if all dates already exist).
    """
    PATHS.raw_statcast.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    start_str = start.isoformat()
    end_str = end.isoformat()

    if not force:
        # Skip entirely if all days in range are already present
        from utils.dates import date_range
        missing = [d for d in date_range(start, end) if not _parquet_path(d).exists()]
        if not missing:
            logger.info("Statcast hitting: all dates in range already ingested — skipping.")
            return []

    logger.info(f"Fetching Statcast hitting data {start_str} -> {end_str}")
    try:
        raw: pd.DataFrame = statcast(start_dt=start_str, end_dt=end_str)
    except Exception as exc:
        logger.error(f"pybaseball.statcast() failed: {exc}")
        raise

    if raw.empty:
        logger.warning(f"No Statcast data returned for {start_str} to {end_str}")
        return []

    raw["game_date"] = pd.to_datetime(raw["game_date"]).dt.date

    available_cols = [c for c in SETTINGS.statcast_columns if c in raw.columns]
    missing_cols = set(SETTINGS.statcast_columns) - set(available_cols)
    if missing_cols:
        logger.warning(f"Statcast columns missing from API response: {missing_cols}")

    df = raw[available_cols].copy()

    for game_date, group in df.groupby("game_date"):
        path = _parquet_path(game_date)
        if path.exists() and not force:
            logger.debug(f"Skipping {game_date} — file exists")
            continue
        group.reset_index(drop=True).to_parquet(path, index=False)
        logger.info(f"Saved {len(group):,} pitches for {game_date} -> {path.name}")
        written.append(path)

    return written


def load_statcast_hitting(game_date: date) -> pd.DataFrame:
    """
    Load a single day's Statcast hitting Parquet file.

    Returns an empty DataFrame if the file does not exist.
    """
    path = _parquet_path(game_date)
    if not path.exists():
        logger.warning(f"No Statcast hitting file for {game_date}")
        return pd.DataFrame(columns=SETTINGS.statcast_columns)
    return pd.read_parquet(path)
