"""
Hitter daily aggregation.

Reads raw Statcast hitting Parquet files and produces a silver-layer
hitter daily aggregate: one row per (batter, game_date) with the
core contact-quality metrics used downstream for rolling features.
"""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import PATHS, SETTINGS
from ingest.statcast_hitting import load_statcast_hitting


def _hard_hit_rate(ev_series: pd.Series) -> float:
    """Fraction of batted balls with EV >= threshold (hard-hit proxy)."""
    valid = ev_series.dropna()
    if valid.empty:
        return np.nan
    return (valid >= SETTINGS.hard_hit_ev_threshold).sum() / len(valid)


def aggregate_hitters_for_date(game_date: date) -> pd.DataFrame:
    """
    Aggregate Statcast pitch-level data to hitter daily metrics for one date.

    Parameters
    ----------
    game_date:
        The game date to aggregate.

    Returns
    -------
    DataFrame with columns:
        batter, game_date, avg_ev, avg_la, xwoba, pa, hard_hit_rate
    """
    raw = load_statcast_hitting(game_date)
    if raw.empty:
        logger.warning(f"aggregate_hitters: no data for {game_date}")
        return pd.DataFrame(
            columns=["batter", "game_date", "avg_ev", "avg_la", "xwoba", "pa", "hard_hit_rate"]
        )

    # Plate appearance proxy: one row per batter per event (null events = balls/strikes, skip)
    batted = raw.dropna(subset=["batter"])

    grouped = batted.groupby("batter")

    agg = pd.DataFrame(
        {
            "avg_ev": grouped["launch_speed"].mean(),
            "avg_la": grouped["launch_angle"].mean(),
            "xwoba": grouped["estimated_woba_using_speedangle"].mean(),
            "pa": grouped["launch_speed"].count(),
            "hard_hit_rate": grouped["launch_speed"].apply(_hard_hit_rate),
        }
    ).reset_index()

    agg["game_date"] = game_date
    agg = agg[["batter", "game_date", "avg_ev", "avg_la", "xwoba", "pa", "hard_hit_rate"]]

    logger.info(f"Aggregated {len(agg)} hitters for {game_date}")
    return agg


def aggregate_hitters_range(start: date, end: date) -> pd.DataFrame:
    """
    Aggregate all dates in [start, end] and return a combined DataFrame.

    Parameters
    ----------
    start:
        First date (inclusive).
    end:
        Last date (inclusive).

    Returns
    -------
    Concatenated daily hitter aggregates sorted by (batter, game_date).
    """
    from utils.dates import date_range

    frames: list[pd.DataFrame] = []
    for d in date_range(start, end):
        frame = aggregate_hitters_for_date(d)
        if not frame.empty:
            frames.append(frame)

    if not frames:
        logger.warning(f"No hitter data aggregated for {start} to {end}")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True).sort_values(
        ["batter", "game_date"]
    )
    return combined


def save_hitters_silver(df: pd.DataFrame, partition_date: date) -> Path:
    """
    Write a daily hitter aggregate to the silver layer as Parquet.

    Parameters
    ----------
    df:
        Output of aggregate_hitters_for_date().
    partition_date:
        Used to name the output file.

    Returns
    -------
    Path to the written file.
    """
    PATHS.silver_hitters.mkdir(parents=True, exist_ok=True)
    path = PATHS.silver_hitters / f"{partition_date.isoformat()}.parquet"
    df.to_parquet(path, index=False)
    logger.info(f"Saved hitter aggregate -> {path.name}")
    return path


def load_hitters_silver(game_date: date) -> pd.DataFrame:
    """Load silver hitter aggregate for a specific date."""
    path = PATHS.silver_hitters / f"{game_date.isoformat()}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)
