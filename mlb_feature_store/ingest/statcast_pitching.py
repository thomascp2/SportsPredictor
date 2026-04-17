"""
Statcast pitching ingestion.

Pulls pitch-level Statcast data, extracts pitcher-centric columns, and
saves each day's pitcher view as a Parquet file under data/raw/statcast/
with a _pitching suffix so it is distinct from the hitter files.
"""

from datetime import date
from pathlib import Path

import pandas as pd
from loguru import logger
from pybaseball import statcast

from config.settings import PATHS, SETTINGS


def _parquet_path(game_date: date) -> Path:
    return PATHS.raw_statcast / f"{game_date.isoformat()}_pitching.parquet"


def _compute_whiff_rate(df: pd.DataFrame) -> pd.Series:
    """
    Whiff rate = swinging strikes / total swing events.
    Uses the 'description' column from Statcast.
    """
    if "description" not in df.columns:
        return pd.Series(dtype=float)

    swings = df["description"].str.contains("swing|foul", case=False, na=False)
    whiffs = df["description"].str.contains("swinging_strike", case=False, na=False)

    swing_counts = swings.groupby(df["pitcher"]).sum()
    whiff_counts = whiffs.groupby(df["pitcher"]).sum()
    return (whiff_counts / swing_counts.replace(0, pd.NA)).rename("whiff_rate")


def ingest_statcast_pitching(start: date, end: date, force: bool = False) -> list[Path]:
    """
    Pull Statcast pitching data for [start, end] and persist to Parquet.

    Parameters
    ----------
    start:
        First date to ingest (inclusive).
    end:
        Last date to ingest (inclusive).
    force:
        Overwrite existing files when True.

    Returns
    -------
    List of Parquet paths written.
    """
    PATHS.raw_statcast.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    start_str = start.isoformat()
    end_str = end.isoformat()

    logger.info(f"Fetching Statcast pitching data {start_str} -> {end_str}")
    try:
        raw: pd.DataFrame = statcast(start_dt=start_str, end_dt=end_str)
    except Exception as exc:
        logger.error(f"pybaseball.statcast() failed: {exc}")
        raise

    if raw.empty:
        logger.warning(f"No Statcast data returned for {start_str} to {end_str}")
        return []

    raw["game_date"] = pd.to_datetime(raw["game_date"]).dt.date

    for game_date, group in raw.groupby("game_date"):
        path = _parquet_path(game_date)
        if path.exists() and not force:
            logger.debug(f"Skipping pitching {game_date} — file exists")
            continue

        available = [c for c in SETTINGS.pitching_columns if c in group.columns]
        pitcher_df = group[available].copy()

        # Attach whiff rate per pitcher for this day
        whiff = _compute_whiff_rate(group)
        if not whiff.empty:
            pitcher_df = pitcher_df.merge(
                whiff.reset_index(), on="pitcher", how="left"
            )

        pitcher_df.reset_index(drop=True).to_parquet(path, index=False)
        logger.info(f"Saved {len(pitcher_df):,} pitching rows for {game_date} -> {path.name}")
        written.append(path)

    return written


def load_statcast_pitching(game_date: date) -> pd.DataFrame:
    """Load a single day's Statcast pitching Parquet. Returns empty if missing."""
    path = _parquet_path(game_date)
    if not path.exists():
        logger.warning(f"No Statcast pitching file for {game_date}")
        return pd.DataFrame(columns=SETTINGS.pitching_columns)
    return pd.read_parquet(path)
