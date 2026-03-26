"""
NHL Game Predictions — Generate moneyline, spread, and total predictions.

Fetches today's NHL schedule, extracts features, and runs the shared
GamePredictionEngine to produce predictions for all games.

Usage:
    python generate_game_predictions.py              # Today's games
    python generate_game_predictions.py 2026-03-25   # Specific date
    python generate_game_predictions.py --force      # Re-predict even if exists
"""

import sqlite3
import json
import os
import sys
import argparse
from datetime import datetime, timedelta

# Path setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NHL_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(NHL_DIR)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "shared"))
sys.path.insert(0, os.path.join(NHL_DIR, "features"))

from v2_config import DB_PATH
from game_prediction_engine import GamePredictionEngine

try:
    from game_features import NHLGameFeatureExtractor
except ImportError:
    NHLGameFeatureExtractor = None


def fetch_todays_games(db_path: str, game_date: str) -> list:
    """
    Get today's NHL games from the database or NHL API.

    Returns list of dicts: {game_date, home_team, away_team, venue}
    """
    import urllib.request

    # First check database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    games = conn.execute("""
        SELECT game_id, game_date, home_team, away_team
        FROM games
        WHERE game_date = ?
    """, (game_date,)).fetchall()

    if games:
        conn.close()
        return [
            {
                "game_date": g["game_date"],
                "home_team": g["home_team"],
                "away_team": g["away_team"],
                "venue": None,
                "game_id": g["game_id"],
            }
            for g in games
        ]

    # If no games in DB, fetch from NHL API
    print(f"  [NHL] No games in DB for {game_date}, fetching from NHL API...")
    try:
        url = f"https://api-web.nhle.com/v1/schedule/{game_date}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        fetched_games = []
        for week in data.get("gameWeek", []):
            if week.get("date") != game_date:
                continue
            for game in week.get("games", []):
                away = game.get("awayTeam", {}).get("abbrev", "")
                home = game.get("homeTeam", {}).get("abbrev", "")
                venue = game.get("venue", {}).get("default", None)
                game_id = f"{game_date}_{away}_{home}"

                if away and home:
                    # Save to games table
                    try:
                        conn.execute("""
                            INSERT OR IGNORE INTO games
                            (game_id, game_date, away_team, home_team, season)
                            VALUES (?, ?, ?, ?, ?)
                        """, (game_id, game_date, away, home, "2025-26"))
                    except Exception:
                        pass

                    fetched_games.append({
                        "game_date": game_date,
                        "home_team": home,
                        "away_team": away,
                        "venue": venue,
                        "game_id": game_id,
                    })

        conn.commit()
        conn.close()
        return fetched_games

    except Exception as e:
        print(f"  [NHL] API fetch failed: {e}")
        conn.close()
        return []


def already_predicted(db_path: str, game_date: str) -> bool:
    """Check if game predictions already exist for this date."""
    conn = sqlite3.connect(db_path)
    count = conn.execute("""
        SELECT COUNT(*) FROM game_predictions
        WHERE game_date = ?
    """, (game_date,)).fetchone()[0]
    conn.close()
    return count > 0


def main():
    parser = argparse.ArgumentParser(description="NHL Game Predictions")
    parser.add_argument("date", nargs="?",
                        default=datetime.now().strftime("%Y-%m-%d"),
                        help="Game date (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true",
                        help="Re-predict even if predictions exist")
    args = parser.parse_args()

    game_date = args.date
    print(f"\n{'='*60}")
    print(f"  NHL Game Predictions - {game_date}")
    print(f"{'='*60}")

    # Check for existing predictions
    if not args.force and already_predicted(DB_PATH, game_date):
        print(f"  [SKIP] Predictions already exist for {game_date}. Use --force to overwrite.")
        return

    # Fetch games
    games = fetch_todays_games(DB_PATH, game_date)
    if not games:
        print(f"  [NHL] No games found for {game_date}")
        return

    print(f"  [NHL] Found {len(games)} games")
    for g in games:
        print(f"    {g['away_team']} @ {g['home_team']}")

    # Initialize feature extractor
    extractor = None
    if NHLGameFeatureExtractor:
        try:
            extractor = NHLGameFeatureExtractor(DB_PATH)
            print(f"  [NHL] Feature extractor loaded")
        except Exception as e:
            print(f"  [WARN] Could not init feature extractor: {e}")

    # Initialize engine
    engine = GamePredictionEngine(
        sport="nhl",
        db_path=DB_PATH,
        feature_extractor=extractor,
    )

    # Generate and save predictions
    results = engine.predict_and_save(games)

    # Print summary
    print(f"\n  --- Results ---")
    print(f"  Games:       {results['games']}")
    print(f"  Predictions: {results['total_predictions']}")
    print(f"  Saved:       {results['saved']}")
    print(f"  SHARP plays: {results['sharp_plays']}")

    if results["sharp_details"]:
        print(f"\n  --- SHARP Plays ---")
        for detail in results["sharp_details"]:
            print(f"    * {detail}")

    print(f"\n  Done!")


if __name__ == "__main__":
    main()
