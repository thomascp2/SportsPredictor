"""
Shared pytest fixtures for ml_training tests.

Provides:
- synthetic_training_df: 200-row DataFrame with game_date, target, and feature columns
- feature_cols: List of feature column names matching synthetic_training_df
- in_memory_game_logs_db: In-memory SQLite DB with player_game_logs data for Test Player
"""

import sqlite3
import numpy as np
import pandas as pd
import pytest
from datetime import date, timedelta


@pytest.fixture
def synthetic_training_df():
    """
    200-row synthetic DataFrame for ML pipeline tests.

    Columns:
        game_date: str YYYY-MM-DD, sequential from 2026-01-01, sorted ascending
        target: int (0/1, roughly 50/50)
        f_last5_avg: float
        f_last10_avg: float
        f_opp_avg: float
    """
    np.random.seed(42)
    n = 200
    start = date(2026, 1, 1)
    dates = [(start + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(n)]
    target = (np.random.rand(n) > 0.5).astype(int)
    f_last5_avg = np.random.normal(20.0, 5.0, n)
    f_last10_avg = np.random.normal(19.5, 4.5, n)
    f_opp_avg = np.random.normal(21.0, 6.0, n)
    df = pd.DataFrame({
        'game_date': dates,
        'target': target,
        'f_last5_avg': f_last5_avg,
        'f_last10_avg': f_last10_avg,
        'f_opp_avg': f_opp_avg,
    })
    return df.sort_values('game_date').reset_index(drop=True)


@pytest.fixture
def feature_cols():
    """Feature column names matching synthetic_training_df."""
    return ['f_last5_avg', 'f_last10_avg', 'f_opp_avg']


@pytest.fixture
def in_memory_game_logs_db():
    """
    In-memory SQLite DB with player_game_logs table.

    Seeded with 15 rows for 'Test Player' on team 'TST',
    dates 2026-01-01 through 2026-01-15.
    Points: [20, 22, 18, 25, 19, 21, 23, 17, 24, 20, 22, 18, 26, 21, 19]

    scope='function' so each test gets a fresh copy.
    """
    conn = sqlite3.connect(':memory:')
    conn.execute("""
        CREATE TABLE player_game_logs (
            player_name TEXT,
            game_date   TEXT,
            team        TEXT,
            points      REAL,
            rebounds    REAL,
            assists     REAL,
            minutes     REAL,
            home_away   TEXT
        )
    """)

    points_values = [20, 22, 18, 25, 19, 21, 23, 17, 24, 20, 22, 18, 26, 21, 19]
    start = date(2026, 1, 1)
    rows = [
        (
            'Test Player',
            (start + timedelta(days=i)).strftime('%Y-%m-%d'),
            'TST',
            float(points_values[i]),
            5.0,
            3.0,
            30.0,
            'home' if i % 2 == 0 else 'away',
        )
        for i in range(15)
    ]
    conn.executemany(
        "INSERT INTO player_game_logs VALUES (?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    yield conn
    conn.close()
