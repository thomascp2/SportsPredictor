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
import unicodedata
from datetime import datetime, timedelta
import sys
import os
import json

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from nba_config import (
    DB_PATH, DISCORD_WEBHOOK_URL, CORE_PROPS,
    STARTERS_COUNT, SIGNIFICANT_BENCH_COUNT, EXPLORATION_PLAYERS_PER_TEAM,
    DATA_COLLECTION_START, DATA_COLLECTION_END, BLOWOUT_SPREAD_THRESHOLD
)
from data_fetchers.nba_stats_api import NBAStatsAPI
from statistical_predictions import NBAStatisticalPredictor
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__))))
from espn_nba_api import ESPNNBAApi

# Pre-game intel (Grok-powered injury/availability sweep)
_SHARED = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'shared')
sys.path.append(_SHARED)
try:
    from pregame_intel import PreGameIntel
    INTEL_AVAILABLE = True
except ImportError:
    INTEL_AVAILABLE = False


class NBADailyPredictor:
    """Daily prediction generator for NBA games."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.api = NBAStatsAPI()
        self.espn_api = ESPNNBAApi()
        self.predictor = NBAStatisticalPredictor()
        self.intel = PreGameIntel() if INTEL_AVAILABLE else None

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

        # Fetch and save betting lines from ESPN (spread, total, moneylines).
        # This is a separate call because games come from NBA Stats API which
        # has no odds. ESPN scoreboard has both game info and odds.
        game_lines = self._fetch_and_save_game_lines(conn, target_date)

        # Pre-game intel: fetch injury/availability from Grok (once, cached)
        skipped_intel = 0
        if self.intel:
            matchups = [f"{g['away_team']} vs {g['home_team']}" for g in games]
            self.intel.fetch('nba', target_date, matchups)

        # Generate predictions for each game
        total_predictions = 0
        skipped_blowouts = 0
        all_probabilities = []

        for game in games:
            home = game['home_team']
            away = game['away_team']
            print(f"\n{away} @ {home}")

            # Blowout filter: skip entire game if spread is lopsided.
            # Garbage time destroys prop accuracy for both teams.
            abs_spread = game_lines.get(game['game_id'], {}).get('abs_spread')
            if abs_spread is not None and abs_spread >= BLOWOUT_SPREAD_THRESHOLD:
                print(f"   [SKIP] Blowout risk — spread {abs_spread:.1f} >= {BLOWOUT_SPREAD_THRESHOLD}. Skipping.")
                skipped_blowouts += 1
                continue

            # Get players for both teams
            for team, opponent, home_away in [
                (home, away, 'H'),
                (away, home, 'A')
            ]:
                players = self._get_team_players(conn, team, players_per_team, target_date)

                for player_name in players:
                    # Intel filter: skip confirmed OUT players entirely
                    if self.intel and self.intel.is_player_out(player_name, 'nba', target_date):
                        print(f"   [INTEL] {player_name} — OUT (skipping all props)")
                        skipped_intel += 1
                        continue

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
        if skipped_blowouts:
            print(f"[SKIP] Blowout games skipped: {skipped_blowouts} (spread >= {BLOWOUT_SPREAD_THRESHOLD})")
        if skipped_intel:
            print(f"[INTEL] Players skipped (OUT): {skipped_intel}")
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
        """Save games to database and ensure game_lines table exists."""
        cursor = conn.cursor()

        # Create game_lines table if this is the first run after the schema update
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_lines (
                game_id      TEXT NOT NULL,
                game_date    TEXT NOT NULL,
                home_team    TEXT,
                away_team    TEXT,
                spread       REAL,    -- positive = home favored, negative = away favored
                abs_spread   REAL,    -- absolute value of spread (used for blowout filter)
                over_under   REAL,    -- game total
                home_moneyline INTEGER,
                away_moneyline INTEGER,
                odds_details TEXT,
                odds_provider TEXT,
                fetched_at   TEXT,
                PRIMARY KEY (game_id)
            )
        """)

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

    def _fetch_and_save_game_lines(self, conn, game_date):
        """
        Fetch betting lines from ESPN scoreboard and save to game_lines table.

        Matches ESPN games to DB games by team abbreviation, handling known
        ESPN/NBA-Stats-API abbreviation mismatches (via TEAM_ALIASES).

        Returns:
            dict: {game_id: {'spread': float, 'abs_spread': float, 'over_under': float}}
                  Only contains entries where odds were available.
        """
        result = {}
        try:
            espn_games = self.espn_api.get_scoreboard(game_date)
        except Exception as e:
            print(f"   [ODDS] ESPN fetch failed: {e} — skipping lines")
            return result

        if not espn_games:
            print("   [ODDS] No ESPN games returned — lines unavailable")
            return result

        # Build a lookup: (home_abbr, away_abbr) → game_id from the DB games table
        cursor = conn.cursor()
        cursor.execute(
            "SELECT game_id, home_team, away_team FROM games WHERE game_date = ?",
            (game_date,)
        )
        db_games = {(r[1], r[2]): r[0] for r in cursor.fetchall()}

        lines_saved = 0
        for eg in espn_games:
            espn_home = eg.get('home_team', '')
            espn_away = eg.get('away_team', '')

            # Try direct match first, then aliases
            game_id = db_games.get((espn_home, espn_away))
            if not game_id:
                # Try resolving ESPN aliases to NBA Stats API abbreviations
                h = self.TEAM_ALIASES.get(espn_home, espn_home)
                a = self.TEAM_ALIASES.get(espn_away, espn_away)
                game_id = db_games.get((h, a)) or db_games.get((espn_home, a)) or db_games.get((h, espn_away))

            if not game_id:
                continue  # Couldn't match this ESPN game to a DB game

            spread = eg.get('spread')
            over_under = eg.get('over_under')
            abs_spread = abs(spread) if spread is not None else None

            cursor.execute("""
                INSERT OR REPLACE INTO game_lines
                (game_id, game_date, home_team, away_team,
                 spread, abs_spread, over_under,
                 home_moneyline, away_moneyline,
                 odds_details, odds_provider, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                game_id, game_date, espn_home, espn_away,
                spread, abs_spread, over_under,
                eg.get('home_moneyline'), eg.get('away_moneyline'),
                eg.get('odds_details', ''), eg.get('odds_provider', ''),
                datetime.now().isoformat()
            ))

            if abs_spread is not None:
                result[game_id] = {'spread': spread, 'abs_spread': abs_spread, 'over_under': over_under}
                lines_saved += 1

        conn.commit()
        print(f"   [ODDS] Saved lines for {lines_saved}/{len(espn_games)} games"
              + (f" ({len(espn_games) - lines_saved} unmatched)" if lines_saved < len(espn_games) else ""))
        return result

    # ESPN uses different abbreviations than NBA Stats API (which populates the games table).
    TEAM_ALIASES = {
        'WAS': 'WSH', 'WSH': 'WAS',
        'NYK': 'NY',  'NY':  'NYK',
        'SAS': 'SA',  'SA':  'SAS',
        'NOP': 'NO',  'NO':  'NOP',
        'GSW': 'GS',  'GS':  'GSW',
        'UTA': 'UTAH','UTAH':'UTA',
    }

    def _get_team_players(self, conn, team, count, game_date):
        """
        Get top N players for a team based on recent performance.

        Only includes players whose MOST RECENT game was for this team (or its alias).
        - Handles traded players: KD's most recent logs are HOU, so he won't appear in PHX.
        - Handles abbreviation mismatches: WAS (games table) ↔ WSH (ESPN game logs).

        Args:
            conn: Database connection
            team (str): Team tricode
            count (int): Number of players to return
            game_date (str): Game date (for temporal safety)

        Returns:
            list: Player names
        """
        cursor = conn.cursor()

        alias = self.TEAM_ALIASES.get(team)
        team_variants = [team, alias] if alias else [team]
        placeholders = ','.join(['?' for _ in team_variants])

        cursor.execute(f"""
            WITH current_teams AS (
                SELECT player_name, team AS current_team
                FROM (
                    SELECT player_name, team,
                           ROW_NUMBER() OVER (PARTITION BY player_name ORDER BY game_date DESC) AS rn
                    FROM player_game_logs
                    WHERE game_date < ?
                ) ranked
                WHERE rn = 1
            )
            SELECT pgl.player_name, AVG(pgl.minutes) AS avg_minutes, COUNT(*) AS games
            FROM player_game_logs pgl
            JOIN current_teams ct ON pgl.player_name = ct.player_name
                AND ct.current_team IN ({placeholders})
            WHERE pgl.team IN ({placeholders})
              AND pgl.game_date < ?
            GROUP BY pgl.player_name
            HAVING games >= 3
            ORDER BY avg_minutes DESC
            LIMIT ?
        """, (game_date, *team_variants, *team_variants, game_date, count))

        players = [row[0] for row in cursor.fetchall()]

        # If not enough players in database, return what we have
        if len(players) < count:
            print(f"      [WARN]  Only {len(players)} players found for {team} (expected {count}, may have traded players filtered out)")

        return players

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Strip diacritics at write time so DB always stores ASCII names."""
        return ''.join(
            c for c in unicodedata.normalize('NFD', name)
            if unicodedata.category(c) != 'Mn'
        )

    def _save_prediction(self, conn, game_id, game_date, player_name, team, opponent,
                        home_away, prop_type, line, result):
        """Save prediction to database."""
        player_name = self._normalize_name(player_name)
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
