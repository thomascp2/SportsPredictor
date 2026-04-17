"""
FanGraphs hitting metrics ingestion.

Fetches season-level advanced hitting metrics via pybaseball's
batting_stats() wrapper (which hits the FanGraphs JSON endpoint).
Stores one Parquet per season under data/raw/fangraphs/.
"""

from pathlib import Path

import pandas as pd
from loguru import logger
from pybaseball import batting_stats

from config.settings import PATHS


# Columns to keep from FanGraphs hitting data
_KEEP_COLS = [
    "IDfg",       # FanGraphs player ID
    "Name",
    "Team",
    "Season",
    "wRC+",
    "WAR",
    "BABIP",
    "wOBA",
    "ISO",
    "K%",
    "BB%",
    "RE24",
    "WPA",
    "PA",
    "G",
]


def _parquet_path(season: int) -> Path:
    return PATHS.raw_fangraphs / f"hitting_{season}.parquet"


def ingest_fangraphs_hitting(season: int, force: bool = False) -> Path | None:
    """
    Download FanGraphs hitting stats for a season and persist to Parquet.

    Parameters
    ----------
    season:
        MLB season year (e.g. 2024).
    force:
        Overwrite existing file when True.

    Returns
    -------
    Path to the written Parquet file, or None if skipped.
    """
    PATHS.raw_fangraphs.mkdir(parents=True, exist_ok=True)
    path = _parquet_path(season)

    if path.exists() and not force:
        logger.info(f"FanGraphs hitting {season}: file already exists — skipping.")
        return None

    logger.info(f"Fetching FanGraphs hitting data for {season}")
    try:
        raw: pd.DataFrame = batting_stats(season, qual=0)
    except Exception as exc:
        logger.warning(f"batting_stats({season}) failed (FanGraphs unavailable): {exc} — continuing without FanGraphs hitting data")
        return None

    if raw.empty:
        logger.warning(f"FanGraphs returned no hitting data for {season}")
        return None

    raw["Season"] = season
    available = [c for c in _KEEP_COLS if c in raw.columns]
    missing = set(_KEEP_COLS) - set(available)
    if missing:
        logger.warning(f"FanGraphs hitting — missing columns: {missing}")

    df = raw[available].copy()
    df.to_parquet(path, index=False)
    logger.info(f"Saved {len(df):,} FanGraphs hitting rows for {season} -> {path.name}")
    return path


def load_fangraphs_hitting(season: int) -> pd.DataFrame:
    """
    Load FanGraphs hitting data for a season.

    Returns an empty DataFrame if the file does not exist.
    """
    path = _parquet_path(season)
    if not path.exists():
        logger.warning(f"No FanGraphs hitting file for {season}")
        return pd.DataFrame(columns=_KEEP_COLS)
    return pd.read_parquet(path)
