"""
MLB schedule ingestion.

Uses pybaseball's schedule_and_record() to pull the game schedule for a
given team and season, then saves it to data/raw/schedule/.

For a league-wide daily schedule, iterates over all 30 teams and deduplicates.
"""

from datetime import date
from pathlib import Path

import pandas as pd
from loguru import logger
from pybaseball import schedule_and_record

from config.settings import PATHS


MLB_TEAMS: list[str] = [
    "ARI", "ATL", "BAL", "BOS", "CHC", "CHW", "CIN", "CLE", "COL", "DET",
    "HOU", "KCR", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "OAK",
    "PHI", "PIT", "SDP", "SEA", "SFG", "STL", "TBR", "TEX", "TOR", "WSN",
]


def _parquet_path(season: int) -> Path:
    return PATHS.raw_schedule / f"schedule_{season}.parquet"


def ingest_schedule(season: int, force: bool = False) -> Path | None:
    """
    Pull the full-season schedule for all 30 MLB teams and persist to Parquet.

    Parameters
    ----------
    season:
        MLB season year.
    force:
        Overwrite existing file when True.

    Returns
    -------
    Path to the written Parquet, or None if skipped.
    """
    PATHS.raw_schedule.mkdir(parents=True, exist_ok=True)
    path = _parquet_path(season)

    if path.exists() and not force:
        logger.info(f"Schedule {season}: file already exists — skipping.")
        return None

    frames: list[pd.DataFrame] = []
    for team in MLB_TEAMS:
        try:
            df = schedule_and_record(season, team)
            df["team"] = team
            frames.append(df)
        except Exception as exc:
            logger.warning(f"schedule_and_record({season}, {team}) failed: {exc}")

    if not frames:
        logger.error(f"Could not retrieve any schedule data for {season}")
        return None

    schedule = pd.concat(frames, ignore_index=True)

    # Normalize date column
    if "Date" in schedule.columns:
        schedule["game_date"] = pd.to_datetime(
            schedule["Date"].astype(str) + f" {season}", format="%b %d %Y", errors="coerce"
        ).dt.date

    schedule.to_parquet(path, index=False)
    logger.info(f"Saved {len(schedule):,} schedule rows for {season} -> {path.name}")
    return path


def load_schedule(season: int) -> pd.DataFrame:
    """Load schedule Parquet for a season. Returns empty if missing."""
    path = _parquet_path(season)
    if not path.exists():
        logger.warning(f"No schedule file for {season}")
        return pd.DataFrame()
    return pd.read_parquet(path)


def games_on_date(game_date: date, season: int) -> pd.DataFrame:
    """Return rows from the schedule matching a specific date."""
    df = load_schedule(season)
    if df.empty or "game_date" not in df.columns:
        return pd.DataFrame()
    return df[df["game_date"] == game_date].reset_index(drop=True)
