"""
NBA Daily Prediction Generator (UPDATED - Always 8 Players)
============================================================

Generates predictions for today/tomorrow's NBA games.

UPDATED: Now always uses top 8 players per team (5 starters + 3 bench)
This captures 6th/7th men and provides more betting opportunities.

Features:
1. Auto-detects tomorrow's date
2. Fetches games from NBA Stats API
3. Uses top 8 players per team (ranked by minutes)
4. Extracts features and generates predictions
5. Saves to predictions table
6. Verifies feature variety
7. Discord notification (optional)

Run daily at 10 AM after games are scheduled.
"""

import sqlite3
from datetime import datetime, timedelta
import sys
import os
import json

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from nba_config import (
    DB_PATH, DISCORD_WEBHOOK_URL, CORE_PROPS,
    STARTERS_COUNT, SIGNIFICANT_BENCH_COUNT, EXPLORATION_PLAYERS_PER_TEAM,
    DATA_COLLECTION_START, DATA_COLLECTION_END
)
from data_fetchers.nba_stats_api import NBAStatsAPI
from statistical_predictions import NBAStatisticalPredictor


class NBADailyPredictor:
    """Daily prediction generator for NBA games."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.api = NBAStatsAPI()
        self.predictor = NBAStatisticalPredictor()

    def generate_predictions(self, target_date=None, players_per_team=None):
        """
        Generate predictions for a specific date.

        Args:
            target_date (str): Date to predict (YYYY-MM-DD). Defaults to tomorrow.
            players_per_team (int): Number of players per team. Defaults to 8.
        """
        # Determine target date (tomorrow by default)
        if target_date is None:
            target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        # Default to 8 players (5 starters + 3 bench)
        if players_per_team is None:
            players_per_team = STARTERS_COUNT + SIGNIFICANT_BENCH_COUNT

        print(f"\n[NBA] NBA DAILY PREDICTION GENERATOR")
        print(f" Target date: {target_date}")
        print(f" Players per team: {players_per_team} (5 starters + {players_per_team - 5} bench)")
        print("=" * 60)

        # Fetch games for target date
        games = self.api.get_scoreboard(target_date)
        print(f"[GAME] Found {len(games)} games on {target_date}\n")

        if len(games) == 0:
            print("[WARN]  No games scheduled")
            return

        conn = sqlite3.connect(self.db_path)

        # Save games to database
        self._save_games(conn, games, target_date)

        # Generate predictions for each game
        total_predictions = 0
        all_probabilities = []

        for game in games:
            print(f"\n{game['away_team']} @ {game['home_team']}")

            # Get players for both teams
            for team, opponent, home_away in [
                (game['home_team'], game['away_team'], 'H'),
                (game['away_team'], game['home_team'], 'A')
            ]:
                players = self._get_team_players(conn, team, players_per_team, target_date)

                for player_name in players:
                    # Generate predictions for core props
                    for prop_type, lines in CORE_PROPS.items():
                        for line in lines:
                            result = self.predictor.predict_prop(
                                player_name, prop_type, line, target_date, home_away, opponent
                            )

                            # Save prediction
                            self._save_prediction(
                                conn, game['game_id'], target_date, player_name,
                                team, opponent, home_away, prop_type, line, result
                            )

                            total_predictions += 1
                            all_probabilities.append(result['probability'])

                print(f"   {team}: {len(players)} players")

        conn.commit()

        # Calculate feature variety
        unique_probs = len(set([round(p, 2) for p in all_probabilities]))

        print("\n" + "=" * 60)
        print(f"[OK] PREDICTION GENERATION COMPLETE")
        print(f"[STATS] Total predictions: {total_predictions}")
        print(f" Unique probabilities: {unique_probs}")

        if unique_probs < 10:
            print("[WARN]  WARNING: Low feature variety (< 10 unique probabilities)")
        else:
            print("[OK] Feature variety looks good!")

        conn.close()

        # Discord notification (optional)
        if DISCORD_WEBHOOK_URL:
            self._send_discord_notification(target_date, total_predictions, unique_probs)

        return {
            'total_predictions': total_predictions,
            'unique_probabilities': unique_probs
        }

    def _save_games(self, conn, games, game_date):
        """Save games to database."""
        cursor = conn.cursor()

        for game in games:
            cursor.execute("""
                INSERT OR REPLACE INTO games
                (game_id, game_date, season, home_team, away_team, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                game['game_id'], game_date, '2025-26',
                game['home_team'], game['away_team'], game['status']
            ))

        conn.commit()

    def _get_team_players(self, conn, team, count, game_date):
        """
        Get top N players for a team based on recent performance.

        Args:
            conn: Database connection
            team (str): Team tricode
            count (int): Number of players to return
            game_date (str): Game date (for temporal safety)

        Returns:
            list: Player names
        """
        cursor = conn.cursor()

        # Get players with most recent games for this team
        cursor.execute("""
            SELECT player_name, AVG(minutes) as avg_minutes, COUNT(*) as games
            FROM player_game_logs
            WHERE team = ?
              AND game_date < ?
            GROUP BY player_name
            HAVING games >= 3
            ORDER BY avg_minutes DESC
            LIMIT ?
        """, (team, game_date, count))

        players = [row[0] for row in cursor.fetchall()]

        # If not enough players in database, return what we have
        if len(players) < count:
            print(f"      [WARN]  Only {len(players)} players found for {team} (expected {count})")

        return players

    def _save_prediction(self, conn, game_id, game_date, player_name, team, opponent,
                        home_away, prop_type, line, result):
        """Save prediction to database."""
        cursor = conn.cursor()

        features = result.get('features', {})

        # Serialize all features to JSON (includes opponent defensive features)
        features_json = json.dumps(features)

        try:
            cursor.execute("""
                INSERT INTO predictions
                (game_id, game_date, player_name, team, opponent, home_away,
                 prop_type, line, prediction, probability,
                 f_season_success_rate, f_l20_success_rate, f_l10_success_rate,
                 f_l5_success_rate, f_l3_success_rate, f_current_streak,
                 f_max_streak, f_trend_slope, f_home_away_split, f_games_played,
                 f_insufficient_data, f_season_avg, f_l10_avg, f_l5_avg,
                 f_season_std, f_l10_std, f_trend_acceleration, f_avg_minutes,
                 f_consistency_score, features_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                game_id, game_date, player_name, team, opponent, home_away,
                prop_type, line, result['prediction'], result['probability'],
                features.get('f_season_success_rate', 0),
                features.get('f_l20_success_rate', 0),
                features.get('f_l10_success_rate', 0),
                features.get('f_l5_success_rate', 0),
                features.get('f_l3_success_rate', 0),
                features.get('f_current_streak', 0),
                features.get('f_max_streak', 0),
                features.get('f_trend_slope', 0),
                features.get('f_home_away_split', 0),
                features.get('f_games_played', 0),
                features.get('f_insufficient_data', 0),
                features.get('f_season_avg', 0),
                features.get('f_l10_avg', 0),
                features.get('f_l5_avg', 0),
                features.get('f_season_std', 0),
                features.get('f_l10_std', 0),
                features.get('f_trend_acceleration', 0),
                features.get('f_avg_minutes', 0),
                features.get('f_consistency_score', 0),
                features_json,
            ))
        except sqlite3.IntegrityError:
            pass  # Duplicate prediction

    def _send_discord_notification(self, date, total, unique):
        """Send Discord notification (optional)."""
        try:
            import requests

            message = f"""
[NBA] **NBA Prediction Generator Report**
 Date: {date}

[STATS] **Generated:**
- Total predictions: {total}
- Unique probabilities: {unique}

{'[OK] PREDICTIONS READY' if unique >= 10 else '[WARN] LOW FEATURE VARIETY'}
            """

            payload = {"content": message}
            requests.post(DISCORD_WEBHOOK_URL, json=payload)
        except:
            pass  # Discord is optional


# CLI interface
if __name__ == "__main__":
    generator = NBADailyPredictor()

    # Parse command line arguments
    target_date = None
    players_per_team = None

    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2] == '--force':
        # Force regeneration even if predictions exist
        pass
    
    # Generate with default 8 players
    generator.generate_predictions(target_date, players_per_team)
