"""
Opponent strength features.

Computes rolling opponent wRC+ and wOBA for hitters, and rolling opponent
wOBA for pitchers, using FanGraphs season-level team aggregates weighted
by plate appearances.
"""

from datetime import date

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import SETTINGS


def _team_aggregates(fg: pd.DataFrame, wrc_col: str = "wRC+", woba_col: str = "wOBA") -> pd.DataFrame:
    """
    Aggregate FanGraphs data to team level, weighted by PA where available.

    Returns a DataFrame with columns: Team, team_wrc_plus, team_woba.
    """
    if fg.empty:
        return pd.DataFrame(columns=["Team", "team_wrc_plus", "team_woba"])

    weight_col = "PA" if "PA" in fg.columns else None
    rows = []
    for team, group in fg.groupby("Team"):
        if weight_col and group[weight_col].sum() > 0:
            w = group[weight_col].fillna(0)
            wrc = np.average(group[wrc_col].fillna(100), weights=w) if wrc_col in group.columns else 100.0
            woba = np.average(group[woba_col].fillna(0.320), weights=w) if woba_col in group.columns else 0.320
        else:
            wrc = group[wrc_col].mean() if wrc_col in group.columns else 100.0
            woba = group[woba_col].mean() if woba_col in group.columns else 0.320
        rows.append({"Team": team, "team_wrc_plus": wrc, "team_woba": woba})

    return pd.DataFrame(rows)


def add_hitter_opponent_strength(
    hitter_silver: pd.DataFrame,
    fg_hitting: pd.DataFrame,
) -> pd.DataFrame:
    """
    Append rolling opponent wRC+ (7d) and wOBA (14d) to the hitter aggregate.

    The hitter's opponent is inferred from the schedule: if the batter's team
    is the home_team, the opponent is the away_team, and vice versa.
    Because team membership is not stored per batter here, we use away_team
    as a proxy for the opposing lineup (hitter faces the away team's pitchers
    when at home, and vice versa).  A full pipeline would join via roster data.

    Parameters
    ----------
    hitter_silver:
        Output of aggregate_hitters_for_date() merged across dates;
        must include: batter, game_date, home_team, away_team.
    fg_hitting:
        FanGraphs hitting data with Team column.

    Returns
    -------
    hitter_silver with opp_wrc_plus_7d and opp_woba_14d columns appended.
    """
    if hitter_silver.empty:
        return hitter_silver

    team_stats = _team_aggregates(fg_hitting)
    if team_stats.empty:
        logger.warning("opponent_strength: no team aggregates available — skipping")
        hitter_silver["opp_wrc_plus_7d"] = np.nan
        hitter_silver["opp_woba_14d"] = np.nan
        return hitter_silver

    df = hitter_silver.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])

    opp_col = "away_team" if "away_team" in df.columns else None
    if opp_col:
        df = df.merge(
            team_stats.rename(columns={
                "Team": opp_col,
                "team_wrc_plus": "opp_wrc_plus",
                "team_woba": "opp_woba",
            }),
            on=opp_col,
            how="left",
        )
    else:
        df["opp_wrc_plus"] = np.nan
        df["opp_woba"] = np.nan

    df = df.sort_values(["batter", "game_date"])
    windows = SETTINGS.rolling_windows

    df["opp_wrc_plus_7d"] = (
        df.groupby("batter")["opp_wrc_plus"]
        .transform(lambda s: s.rolling(windows["ev_7d"], min_periods=1).mean())
    )
    df["opp_woba_14d"] = (
        df.groupby("batter")["opp_woba"]
        .transform(lambda s: s.rolling(windows["xwoba_14d"], min_periods=1).mean())
    )

    df["game_date"] = df["game_date"].dt.date
    drop_cols = [c for c in ["opp_wrc_plus", "opp_woba"] if c in df.columns]
    df = df.drop(columns=drop_cols)

    logger.info(f"Opponent strength appended for {df['batter'].nunique()} hitters")
    return df


def add_pitcher_opponent_strength(
    pitcher_silver: pd.DataFrame,
    fg_hitting: pd.DataFrame,
) -> pd.DataFrame:
    """
    Append rolling opponent wOBA (14d) to the pitcher aggregate.

    Parameters
    ----------
    pitcher_silver:
        Output of aggregate_pitchers_for_date() merged across dates.
    fg_hitting:
        FanGraphs hitting data with Team column (opponents' offense).

    Returns
    -------
    pitcher_silver with opponent_strength column appended.
    """
    if pitcher_silver.empty:
        return pitcher_silver

    team_stats = _team_aggregates(fg_hitting)
    if team_stats.empty:
        logger.warning("opponent_strength: no team aggregates for pitchers — skipping")
        pitcher_silver["opponent_strength"] = np.nan
        return pitcher_silver

    df = pitcher_silver.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])

    opp_col = "away_team" if "away_team" in df.columns else None
    if opp_col:
        df = df.merge(
            team_stats.rename(columns={"Team": opp_col, "team_woba": "opp_woba"})[
                [opp_col, "opp_woba"]
            ],
            on=opp_col,
            how="left",
        )
    else:
        df["opp_woba"] = np.nan

    df = df.sort_values(["pitcher", "game_date"])
    windows = SETTINGS.rolling_windows

    df["opponent_strength"] = (
        df.groupby("pitcher")["opp_woba"]
        .transform(lambda s: s.rolling(windows["xwoba_14d"], min_periods=1).mean())
    )

    df["game_date"] = df["game_date"].dt.date
    if "opp_woba" in df.columns:
        df = df.drop(columns=["opp_woba"])

    logger.info(f"Opponent strength appended for {df['pitcher'].nunique()} pitchers")
    return df
