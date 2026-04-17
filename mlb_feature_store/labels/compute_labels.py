"""
Prop outcome label computation.

Derives per-game actual stat values for hitters and pitchers from
raw Statcast pitch-level data. Stores actual values (not binary HIT/MISS)
so any line threshold can be applied at training or prediction time.

Hitter props (from events column):
    hits           — single + double + triple + home_run
    total_bases    — 1*S + 2*D + 3*T + 4*HR
    home_runs      — home_run events

Pitcher props (requires pitcher column in hitting parquets):
    strikeouts     — strikeout events
    walks          — walk + intent_walk events
    outs_recorded  — total outs, counting double-play events as 2

NOTE: RBI, Runs Scored, and HRR (Hits+Runs+RBIs) are not derivable from
pitch-level data. They require game-level box score ingestion (future work).
"""

from datetime import date

import pandas as pd
from loguru import logger

from ingest.statcast_hitting import load_statcast_hitting


# Total base value per hit event
_TOTAL_BASES: dict[str, int] = {
    "single": 1,
    "double": 2,
    "triple": 3,
    "home_run": 4,
}

# Out count per terminal event (from pitcher's perspective)
# Double-play variants credit the pitcher with 2 outs
_PITCHER_OUTS: dict[str, int] = {
    "strikeout": 1,
    "field_out": 1,
    "force_out": 1,
    "fielders_choice": 1,
    "fielders_choice_out": 1,
    "sac_fly": 1,
    "sac_bunt": 1,
    "double_play": 2,
    "grounded_into_double_play": 2,
}


def compute_hitter_labels(game_date: date) -> pd.DataFrame:
    """
    Compute per-game actual values for all hitters on a given date.

    Parameters
    ----------
    game_date:
        The game date to compute labels for.

    Returns
    -------
    DataFrame with columns:
        player_id, game_date, hits, total_bases, home_runs

    One row per batter who appeared in a game that day.
    Returns empty DataFrame if no data is available.
    """
    raw = load_statcast_hitting(game_date)
    if raw.empty or "events" not in raw.columns:
        return pd.DataFrame()

    # Terminal plate appearance events only (non-null events)
    events = raw.dropna(subset=["events", "batter"]).copy()

    events["is_hit"] = events["events"].isin(_TOTAL_BASES).astype(int)
    events["tb"] = events["events"].map(_TOTAL_BASES).fillna(0).astype(int)
    events["is_hr"] = (events["events"] == "home_run").astype(int)

    agg = (
        events.groupby("batter")
        .agg(
            hits=("is_hit", "sum"),
            total_bases=("tb", "sum"),
            home_runs=("is_hr", "sum"),
        )
        .reset_index()
    )

    agg = agg.rename(columns={"batter": "player_id"})
    agg["player_id"] = agg["player_id"].astype(str)
    agg["game_date"] = game_date

    result = agg[["player_id", "game_date", "hits", "total_bases", "home_runs"]]
    logger.info(f"Hitter labels: {len(result)} players for {game_date}")
    return result


def compute_pitcher_labels(game_date: date) -> pd.DataFrame:
    """
    Compute per-game actual values for all pitchers on a given date.

    Requires the 'pitcher' column in the hitting Parquet (added to
    statcast_columns in settings.py). If the column is absent (legacy
    parquets from before the schema update), returns an empty DataFrame
    and logs a warning.

    Parameters
    ----------
    game_date:
        The game date to compute labels for.

    Returns
    -------
    DataFrame with columns:
        player_id, game_date, strikeouts, walks, outs_recorded

    One row per pitcher who threw at least one pitch that day.
    Returns empty DataFrame if no data or pitcher column missing.
    """
    raw = load_statcast_hitting(game_date)
    if raw.empty or "events" not in raw.columns:
        return pd.DataFrame()

    if "pitcher" not in raw.columns:
        logger.warning(
            f"pitcher column missing for {game_date} — re-fetch hitting data with: "
            f"python backfill.py --start {game_date} --end {game_date} --force"
        )
        return pd.DataFrame()

    events = raw.dropna(subset=["events", "pitcher"]).copy()

    events["is_k"] = (events["events"] == "strikeout").astype(int)
    events["is_bb"] = events["events"].isin(["walk", "intent_walk"]).astype(int)
    events["outs"] = events["events"].map(_PITCHER_OUTS).fillna(0).astype(int)

    agg = (
        events.groupby("pitcher")
        .agg(
            strikeouts=("is_k", "sum"),
            walks=("is_bb", "sum"),
            outs_recorded=("outs", "sum"),
        )
        .reset_index()
    )

    agg = agg.rename(columns={"pitcher": "player_id"})
    agg["player_id"] = agg["player_id"].astype(str)
    agg["game_date"] = game_date

    result = agg[["player_id", "game_date", "strikeouts", "walks", "outs_recorded"]]
    logger.info(f"Pitcher labels: {len(result)} pitchers for {game_date}")
    return result


def compute_labels_for_date(game_date: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Convenience wrapper — compute both hitter and pitcher labels for a date.

    Returns
    -------
    (hitter_labels_df, pitcher_labels_df)
    """
    return compute_hitter_labels(game_date), compute_pitcher_labels(game_date)
