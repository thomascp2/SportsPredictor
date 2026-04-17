"""
FanGraphs pitching metrics ingestion.

Fetches season-level advanced pitching metrics via pybaseball's
pitching_stats() wrapper (FanGraphs JSON endpoint, no auth).
Stores one Parquet per season under data/raw/fangraphs/.
"""

from pathlib import Path

import pandas as pd
from loguru import logger
from pybaseball import pitching_stats

from config.settings import PATHS


_KEEP_COLS = [
    "IDfg",
    "Name",
    "Team",
    "Season",
    "WAR",
    "ERA",
    "FIP",
    "xFIP",
    "SIERA",
    "K%",
    "BB%",
    "K-BB%",
    "BABIP",
    "LOB%",
    "HR/FB",
    "GB%",
    "LD%",
    "FB%",
    "Soft%",
    "Hard%",
    "WPA",
    "RE24",
    "IP",
    "G",
    "GS",
]


def _parquet_path(season: int) -> Path:
    return PATHS.raw_fangraphs / f"pitching_{season}.parquet"


def ingest_fangraphs_pitching(season: int, force: bool = False) -> Path | None:
    """
    Download FanGraphs pitching stats for a season and persist to Parquet.

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
        logger.info(f"FanGraphs pitching {season}: file already exists — skipping.")
        return None

    logger.info(f"Fetching FanGraphs pitching data for {season}")
    try:
        raw: pd.DataFrame = pitching_stats(season, qual=0)
    except Exception as exc:
        logger.warning(f"pitching_stats({season}) failed (FanGraphs unavailable): {exc} — continuing without FanGraphs pitching data")
        return None

    if raw.empty:
        logger.warning(f"FanGraphs returned no pitching data for {season}")
        return None

    raw["Season"] = season
    available = [c for c in _KEEP_COLS if c in raw.columns]
    missing = set(_KEEP_COLS) - set(available)
    if missing:
        logger.warning(f"FanGraphs pitching — missing columns: {missing}")

    df = raw[available].copy()
    df.to_parquet(path, index=False)
    logger.info(f"Saved {len(df):,} FanGraphs pitching rows for {season} -> {path.name}")
    return path


def load_fangraphs_pitching(season: int) -> pd.DataFrame:
    """Load FanGraphs pitching data for a season. Returns empty if missing."""
    path = _parquet_path(season)
    if not path.exists():
        logger.warning(f"No FanGraphs pitching file for {season}")
        return pd.DataFrame(columns=_KEEP_COLS)
    return pd.read_parquet(path)
