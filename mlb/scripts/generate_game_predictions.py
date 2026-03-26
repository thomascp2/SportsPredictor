"""
MLB Game Predictions — Generate moneyline, spread, and total predictions.

Fetches today's MLB schedule (including probable pitchers, weather, venue),
extracts features, and runs the shared GamePredictionEngine.

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
from datetime import datetime

# Path setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MLB_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(MLB_DIR)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "shared"))
sys.path.insert(0, os.path.join(MLB_DIR, "features"))

from mlb_config import DB_PATH
from game_prediction_engine import GamePredictionEngine

try:
    from game_features import MLBGameFeatureExtractor
except ImportError:
    MLBGameFeatureExtractor = None


def fetch_todays_games(db_path: str, game_date: str) -> list:
    """
    Get today's MLB games from the database or MLB Stats API.

    Returns list of dicts: {game_date, home_team, away_team, venue}
    """
    # Check game_context table first (MLB stores schedule here)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Check if game_context table exists
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    if "game_context" in tables:
        games = conn.execute("""
            SELECT game_id, game_date, home_team, away_team, venue
            FROM game_context
            WHERE game_date = ?
        """, (game_date,)).fetchall()

        if games:
            conn.close()
            return [
                {
                    "game_date": g["game_date"],
                    "home_team": g["home_team"],
                    "away_team": g["away_team"],
                    "venue": g["venue"] if "venue" in g.keys() else None,
                    "game_id": g["game_id"],
                }
                for g in games
            ]

    # Also check games table
    if "games" in tables:
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

    # Fetch from MLB Stats API
    print(f"  [MLB] No games in DB for {game_date}, fetching from MLB API...")
    try:
        import urllib.request
        url = (f"https://statsapi.mlb.com/api/v1/schedule"
               f"?date={game_date}&sportId=1&gameType=R"
               f"&hydrate=probablePitcher,venue,team")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        fetched_games = []
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                teams = game.get("teams", {})
                home_info = teams.get("home", {})
                away_info = teams.get("away", {})

                home = home_info.get("team", {}).get("abbreviation", "")
                away = away_info.get("team", {}).get("abbreviation", "")
                venue = game.get("venue", {}).get("name", "")
                game_id = str(game.get("gamePk", f"{game_date}_{away}_{home}"))

                if home and away:
                    # Save to games table if it exists
                    try:
                        if "games" in tables:
                            conn.execute("""
                                INSERT OR IGNORE INTO games
                                (game_id, game_date, home_team, away_team, season)
                                VALUES (?, ?, ?, ?, ?)
                            """, (game_id, game_date, home, away, "2026"))
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
        print(f"  [MLB] API fetch failed: {e}")
        conn.close()
        return []


def already_predicted(db_path: str, game_date: str) -> bool:
    """Check if game predictions already exist for this date."""
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute("""
            SELECT COUNT(*) FROM game_predictions
            WHERE game_date = ?
        """, (game_date,)).fetchone()[0]
    except Exception:
        count = 0
    conn.close()
    return count > 0


def main():
    parser = argparse.ArgumentParser(description="MLB Game Predictions")
    parser.add_argument("date", nargs="?",
                        default=datetime.now().strftime("%Y-%m-%d"),
                        help="Game date (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true",
                        help="Re-predict even if predictions exist")
    args = parser.parse_args()

    game_date = args.date
    print(f"\n{'='*60}")
    print(f"  MLB Game Predictions - {game_date}")
    print(f"{'='*60}")

    # Check for existing predictions
    if not args.force and already_predicted(DB_PATH, game_date):
        print(f"  [SKIP] Predictions already exist for {game_date}. Use --force to overwrite.")
        return

    # Fetch games
    games = fetch_todays_games(DB_PATH, game_date)
    if not games:
        print(f"  [MLB] No games found for {game_date}")
        return

    print(f"  [MLB] Found {len(games)} games")
    for g in games:
        print(f"    {g['away_team']} @ {g['home_team']}" +
              (f" ({g['venue']})" if g.get('venue') else ""))

    # Initialize feature extractor
    extractor = None
    if MLBGameFeatureExtractor:
        try:
            extractor = MLBGameFeatureExtractor(DB_PATH)
            print(f"  [MLB] Feature extractor loaded")
        except Exception as e:
            print(f"  [WARN] Could not init feature extractor: {e}")

    # Initialize engine
    engine = GamePredictionEngine(
        sport="mlb",
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
