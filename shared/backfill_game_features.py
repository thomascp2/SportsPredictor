"""
Backfill Game Features — Reconstruct features for historical games.

This enables IMMEDIATE ML training without waiting months for data.
NHL has 1,100+ games and NBA has 1,350+ games already in the database.

For each historical game:
    1. Reconstruct features that were available BEFORE game start
    2. Record the actual outcome (who won, margin, total)
    3. Save to a training-ready CSV/SQLite table

Usage:
    python backfill_game_features.py --sport nhl
    python backfill_game_features.py --sport nba
    python backfill_game_features.py --sport mlb
    python backfill_game_features.py --sport all
"""

import sqlite3
import json
import os
import sys
import argparse
from datetime import datetime
from typing import Dict, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "shared"))

# ── Backfill Schema ──────────────────────────────────────────────────────────

TRAINING_DATA_SCHEMA = """
CREATE TABLE IF NOT EXISTS game_training_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date TEXT NOT NULL,
    game_id TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,

    -- Outcomes (labels for ML)
    home_win INTEGER,              -- 1 = home won, 0 = away won
    home_score INTEGER,
    away_score INTEGER,
    margin INTEGER,                -- home_score - away_score
    total INTEGER,                 -- home_score + away_score

    -- All features as JSON (keeps schema flexible)
    features_json TEXT NOT NULL,

    -- Feature count for validation
    feature_count INTEGER,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(game_date, home_team, away_team)
)
"""


def backfill_sport(sport: str, min_games_before: int = 10):
    """
    Backfill features for all historical games for a sport.

    Args:
        sport: 'nhl', 'nba', or 'mlb'
        min_games_before: Skip games where teams have fewer than this many
                         prior games (features would be meaningless)
    """
    sport = sport.lower()

    # DB paths
    db_map = {
        "nhl": os.path.join(PROJECT_ROOT, "nhl", "database", "nhl_predictions_v2.db"),
        "nba": os.path.join(PROJECT_ROOT, "nba", "database", "nba_predictions.db"),
        "mlb": os.path.join(PROJECT_ROOT, "mlb", "database", "mlb_predictions.db"),
    }

    db_path = db_map.get(sport)
    if not db_path or not os.path.exists(db_path):
        print(f"[BACKFILL] Database not found for {sport}: {db_path}")
        return 0

    # Load the appropriate feature extractor
    try:
        if sport == "nhl":
            sys.path.insert(0, os.path.join(PROJECT_ROOT, "nhl", "features"))
            sys.path.insert(0, os.path.join(PROJECT_ROOT, "nhl", "scripts"))
            from game_features import NHLGameFeatureExtractor
            extractor = NHLGameFeatureExtractor(db_path)
        elif sport == "nba":
            sys.path.insert(0, os.path.join(PROJECT_ROOT, "nba", "features"))
            sys.path.insert(0, os.path.join(PROJECT_ROOT, "nba", "scripts"))
            from game_features import NBAGameFeatureExtractor
            extractor = NBAGameFeatureExtractor(db_path)
        elif sport == "mlb":
            sys.path.insert(0, os.path.join(PROJECT_ROOT, "mlb", "features"))
            sys.path.insert(0, os.path.join(PROJECT_ROOT, "mlb", "scripts"))
            from game_features import MLBGameFeatureExtractor
            extractor = MLBGameFeatureExtractor(db_path)
        else:
            print(f"[BACKFILL] Unknown sport: {sport}")
            return 0
    except ImportError as e:
        print(f"[BACKFILL] Could not import feature extractor for {sport}: {e}")
        return 0

    # Get all completed games
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Ensure training data table exists
    conn.execute(TRAINING_DATA_SCHEMA)
    conn.commit()

    # Get games with scores — check if venue column exists
    col_names = [r[1] for r in conn.execute("PRAGMA table_info(games)").fetchall()]
    has_venue = "venue" in col_names

    if has_venue:
        games = conn.execute("""
            SELECT game_id, game_date, home_team, away_team,
                   home_score, away_score, venue
            FROM games
            WHERE home_score IS NOT NULL AND away_score IS NOT NULL
            ORDER BY game_date ASC
        """).fetchall()
    else:
        games = conn.execute("""
            SELECT game_id, game_date, home_team, away_team,
                   home_score, away_score
            FROM games
            WHERE home_score IS NOT NULL AND away_score IS NOT NULL
            ORDER BY game_date ASC
        """).fetchall()

    # Track team game counts for the min_games filter
    team_games_count: Dict[str, int] = {}

    # Check what's already backfilled
    existing = set()
    for r in conn.execute("SELECT game_date, home_team FROM game_training_data").fetchall():
        existing.add((r[0], r[1]))

    processed = 0
    skipped_min_games = 0
    skipped_existing = 0
    errors = 0

    print(f"[BACKFILL] {sport.upper()}: Processing {len(games)} historical games...")

    for i, game in enumerate(games):
        gd = game["game_date"]
        home = game["home_team"]
        away = game["away_team"]

        # Skip if already backfilled
        if (gd, home) in existing:
            skipped_existing += 1
            continue

        # Track game counts
        team_games_count[home] = team_games_count.get(home, 0) + 1
        team_games_count[away] = team_games_count.get(away, 0) + 1

        # Skip early-season games where stats are meaningless
        if (team_games_count.get(home, 0) < min_games_before or
            team_games_count.get(away, 0) < min_games_before):
            skipped_min_games += 1
            continue

        # Extract features
        try:
            venue = game["venue"] if has_venue and "venue" in game.keys() else None
            features = extractor.extract(gd, home, away, venue)

            # Calculate outcomes
            home_score = game["home_score"]
            away_score = game["away_score"]
            home_win = 1 if home_score > away_score else 0
            margin = home_score - away_score
            total = home_score + away_score

            # Insert
            conn.execute("""
                INSERT OR REPLACE INTO game_training_data
                (game_date, game_id, home_team, away_team,
                 home_win, home_score, away_score, margin, total,
                 features_json, feature_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                gd, game["game_id"], home, away,
                home_win, home_score, away_score, margin, total,
                json.dumps(features), len(features),
            ))

            processed += 1

            # Commit every 100 games
            if processed % 100 == 0:
                conn.commit()
                print(f"  ... {processed} games backfilled ({i+1}/{len(games)})")

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  [ERROR] {gd} {home} vs {away}: {e}")

    conn.commit()

    # Summary
    total_rows = conn.execute("SELECT COUNT(*) FROM game_training_data").fetchone()[0]
    conn.close()

    print(f"\n[BACKFILL] {sport.upper()} Results:")
    print(f"  Processed:        {processed}")
    print(f"  Skipped (exists): {skipped_existing}")
    print(f"  Skipped (min gp): {skipped_min_games}")
    print(f"  Errors:           {errors}")
    print(f"  Total in table:   {total_rows}")

    return processed


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill Game Features")
    parser.add_argument("--sport", choices=["nhl", "nba", "mlb", "all"], required=True)
    parser.add_argument("--min-games", type=int, default=10,
                        help="Min team games before backfilling (default: 10)")
    args = parser.parse_args()

    sports = ["nhl", "nba", "mlb"] if args.sport == "all" else [args.sport]

    for s in sports:
        print(f"\n{'='*60}")
        print(f"  Backfilling {s.upper()} Game Features")
        print(f"{'='*60}")
        backfill_sport(s, min_games_before=args.min_games)
