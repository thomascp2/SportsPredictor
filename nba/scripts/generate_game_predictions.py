"""
NBA Game Predictions — Generate moneyline, spread, and total predictions.

Fetches today's NBA schedule, extracts features, and runs the shared
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
from datetime import datetime

# Path setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NBA_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(NBA_DIR)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "data_fetchers"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "shared"))
sys.path.insert(0, os.path.join(NBA_DIR, "features"))

from nba_config import DB_PATH
from game_prediction_engine import GamePredictionEngine
from game_discord_notifications import send_game_predictions_alert
from fetch_game_odds import fetch_and_save_odds, normalize_team

try:
    from game_features import NBAGameFeatureExtractor
except ImportError:
    NBAGameFeatureExtractor = None


def fetch_todays_games(db_path: str, game_date: str) -> list:
    """
    Get today's NBA games from the database or NBA Stats API.

    Returns list of dicts: {game_date, home_team, away_team, venue}
    """
    # Check database first
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

    # Fetch from NBA Stats API
    print(f"  [NBA] No games in DB for {game_date}, fetching from NBA API...")
    try:
        from nba_stats_api import NBAStatsAPI
        api = NBAStatsAPI(db_path)
        scoreboard = api.get_scoreboard(game_date)

        if not scoreboard:
            conn.close()
            return []

        fetched_games = []
        for game in scoreboard:
            home = game.get("home_team", "")
            away = game.get("away_team", "")
            game_id = game.get("game_id", f"{game_date}_{away}_{home}")

            if home and away:
                # Save to games table
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO games
                        (game_id, game_date, home_team, away_team, season, status)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (game_id, game_date, home, away, "2025-26", "scheduled"))
                except Exception:
                    pass

                fetched_games.append({
                    "game_date": game_date,
                    "home_team": home,
                    "away_team": away,
                    "venue": None,
                    "game_id": game_id,
                })

        conn.commit()
        conn.close()
        return fetched_games

    except Exception as e:
        print(f"  [NBA] API fetch failed: {e}")

    # Fallback: try ESPN
    try:
        import urllib.request
        espn_date = game_date.replace("-", "")
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={espn_date}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        fetched_games = []
        for event in data.get("events", []):
            competition = event.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])
            if len(competitors) < 2:
                continue

            home_comp = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away_comp = next((c for c in competitors if c.get("homeAway") == "away"), None)

            if home_comp and away_comp:
                home = home_comp.get("team", {}).get("abbreviation", "")
                away = away_comp.get("team", {}).get("abbreviation", "")
                venue = competition.get("venue", {}).get("fullName", None)
                game_id = event.get("id", f"{game_date}_{away}_{home}")

                # Save to games table
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO games
                        (game_id, game_date, home_team, away_team, season, status)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (game_id, game_date, home, away, "2025-26", "scheduled"))
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
        print(f"  [NBA] ESPN fallback failed: {e}")
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
    parser = argparse.ArgumentParser(description="NBA Game Predictions")
    parser.add_argument("date", nargs="?",
                        default=datetime.now().strftime("%Y-%m-%d"),
                        help="Game date (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true",
                        help="Re-predict even if predictions exist")
    args = parser.parse_args()

    game_date = args.date
    print(f"\n{'='*60}")
    print(f"  NBA Game Predictions - {game_date}")
    print(f"{'='*60}")

    # Check for existing predictions
    if not args.force and already_predicted(DB_PATH, game_date):
        print(f"  [SKIP] Predictions already exist for {game_date}. Use --force to overwrite.")
        return

    # Step 0: Fetch real odds from ESPN and save to game_lines table
    print(f"\n  Step 0: Fetching real sportsbook lines...")
    odds_data = fetch_and_save_odds("nba", DB_PATH, game_date)

    # Fetch games
    games = fetch_todays_games(DB_PATH, game_date)
    if not games:
        print(f"  [NBA] No games found for {game_date}")
        return

    # Normalize team abbreviations to match our database
    for g in games:
        g["home_team"] = normalize_team("nba", g["home_team"])
        g["away_team"] = normalize_team("nba", g["away_team"])

    print(f"  [NBA] Found {len(games)} games")
    for g in games:
        print(f"    {g['away_team']} @ {g['home_team']}")

    # Initialize feature extractor
    extractor = None
    if NBAGameFeatureExtractor:
        try:
            extractor = NBAGameFeatureExtractor(DB_PATH)
            print(f"  [NBA] Feature extractor loaded")
        except Exception as e:
            print(f"  [WARN] Could not init feature extractor: {e}")

    # Initialize engine
    engine = GamePredictionEngine(
        sport="nba",
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

    # Send Discord notification
    try:
        send_game_predictions_alert("nba", results)
        print(f"  [DISCORD] Notification sent")
    except Exception as e:
        print(f"  [DISCORD] Failed: {e}")

    print(f"\n  Done!")


if __name__ == "__main__":
    main()
