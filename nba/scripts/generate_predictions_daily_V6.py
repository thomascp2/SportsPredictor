"""
NBA Daily Prediction Generator V6 - PrizePicks Line Driven
============================================================

CHANGES IN V6 (Jan 2026):
- Predictions generated ONLY for actual PrizePicks lines
- Fetches PP lines first, then generates predictions for those exact lines
- No more fixed lines (15.5, 20.5, etc.) - uses what PP actually offers
- Ensures every prediction is immediately betable

This version:
1. Fetches fresh PrizePicks lines (if not already fetched today)
2. For each player in scheduled games, finds their PP lines
3. Generates predictions only for those available lines
4. Results in cleaner training data for ML

Based on original generate_predictions_daily.py with PP integration.
"""

import sqlite3
import unicodedata
from datetime import datetime, timedelta
import sys
import os
import json
from pathlib import Path

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from nba_config import (
    DB_PATH, DISCORD_WEBHOOK_URL,
    STARTERS_COUNT, SIGNIFICANT_BENCH_COUNT,
    nba_has_games,
)
from data_fetchers.nba_stats_api import NBAStatsAPI
from espn_nba_api import ESPNNBAApi
from statistical_predictions import NBAStatisticalPredictor

# PrizePicks Integration
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "shared"))
try:
    from prizepicks_client import PrizePicksIngestion
    PP_AVAILABLE = True
except ImportError:
    PP_AVAILABLE = False
    print("WARNING: PrizePicks client not available")

# ML Model Integration
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "ml_training"))
try:
    from production_predictor import ProductionPredictor
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

# ============================================================================
# CONFIGURATION
# ============================================================================

# PrizePicks database path
PP_DB_PATH = Path(__file__).parent.parent.parent / "shared" / "prizepicks_lines.db"

# Supported props (what we can predict)
# Note: Must match internal names from PP_TO_INTERNAL mapping
SUPPORTED_PROPS = ['points', 'rebounds', 'assists', 'threes', 'pra', 'pts_rebs',
                   'pts_asts', 'rebs_asts', 'steals', 'blocked_shots', 'turnovers',
                   'stocks', 'fantasy']

# Map PP prop names to our internal names
PP_TO_INTERNAL = {
    'points': 'points',
    'rebounds': 'rebounds',
    'assists': 'assists',
    'threes': 'threes',
    '3-pt_made': 'threes',
    'pra': 'pra',
    'pts_rebs': 'pts_rebs',
    'pts_asts': 'pts_asts',
    'rebs_asts': 'rebs_asts',
    'steals': 'steals',
    'blocked_shots': 'blocked_shots',
    'turnovers': 'turnovers',
    'blks_stls': 'stocks',
    'blks+stls': 'stocks',
    'fantasy': 'fantasy',
}

# Odds types to include — demon BE ~45%, quality-gated by σ<1.5 in selector
ODDS_TYPES = ['standard', 'goblin', 'demon']

# Fallback lines if PP not available (rarely needed)
FALLBACK_PROPS = {
    'points': [15.5, 20.5, 25.5],
    'rebounds': [7.5, 10.5],
    'assists': [5.5, 7.5],
    'threes': [2.5],
    'pra': [30.5, 35.5, 40.5],
}


class NBADailyPredictorV6:
    """V6: PrizePicks line-driven prediction generator for NBA games."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.api = NBAStatsAPI()
        self.espn_api = ESPNNBAApi()
        self.predictor = NBAStatisticalPredictor()

        # ML predictor — wraps statistical with trained models where available
        self.ml_predictor = None
        if ML_AVAILABLE:
            try:
                registry_dir = Path(__file__).parent.parent.parent / "ml_training" / "model_registry"
                self.ml_predictor = ProductionPredictor(str(registry_dir))
                nba_models = self.ml_predictor.list_available_models('nba')
                if nba_models:
                    print(f"[ML] {len(nba_models)} NBA ML models loaded")
                else:
                    print("[ML] No NBA models in registry — using statistical predictor")
                    self.ml_predictor = None
            except Exception as e:
                print(f"[ML] Could not load ML predictor: {e}")
                self.ml_predictor = None

    def ensure_pp_lines_fetched(self) -> tuple[bool, str]:
        """
        Ensure PrizePicks lines are fetched for today.

        PP lines are fetched daily and represent lines for upcoming games.
        We use TODAY's fetch_date regardless of game date.

        Returns:
            Tuple of (success, fetch_date)
        """
        if not PP_AVAILABLE:
            print("[WARN] PrizePicks client not available")
            return False, None

        today = datetime.now().strftime("%Y-%m-%d")

        conn = sqlite3.connect(PP_DB_PATH)
        cursor = conn.cursor()

        # Check if we have lines for today
        cursor.execute('''
            SELECT COUNT(*) FROM prizepicks_lines
            WHERE fetch_date = ? AND league = 'NBA'
        ''', (today,))
        count = cursor.fetchone()[0]
        conn.close()

        if count > 0:
            print(f"[PP] Found {count} existing NBA lines (fetched {today})")
            return True, today

        # Fetch fresh lines
        print(f"[PP] No lines found for today, fetching fresh...")
        try:
            ingestion = PrizePicksIngestion()
            result = ingestion.run_ingestion(['NBA'])

            lines_fetched = result.get('sports', {}).get('NBA', {}).get('lines_fetched', 0)
            print(f"[PP] Fetched {lines_fetched} NBA lines")
            return lines_fetched > 0, today
        except Exception as e:
            print(f"[PP] Error fetching lines: {e}")
            return False, None

    def get_all_pp_player_lines(self, fetch_date: str) -> dict:
        """
        Get all PrizePicks lines for NBA, organized by player.

        Returns:
            Dict: {player_name: {prop_type: [lines]}}
        """
        if not PP_AVAILABLE:
            return {}

        conn = sqlite3.connect(PP_DB_PATH)
        cursor = conn.cursor()

        placeholders = ','.join(['?' for _ in ODDS_TYPES])
        cursor.execute(f'''
            SELECT player_name, prop_type, line
            FROM prizepicks_lines
            WHERE fetch_date = ?
            AND league = 'NBA'
            AND odds_type IN ({placeholders})
            ORDER BY player_name, prop_type, line
        ''', (fetch_date, *ODDS_TYPES))

        # Organize by player
        player_lines = {}
        for row in cursor.fetchall():
            player, prop, line = row

            # Map PP prop to our internal name
            internal_prop = PP_TO_INTERNAL.get(prop.lower(), prop.lower())

            # Skip props we can't predict (e.g., 'dunks' - no data in DB)
            if internal_prop not in SUPPORTED_PROPS:
                continue

            if player not in player_lines:
                player_lines[player] = {}
            if internal_prop not in player_lines[player]:
                player_lines[player][internal_prop] = []

            player_lines[player][internal_prop].append(line)

        conn.close()
        return player_lines

    def match_player_to_pp(self, player_name: str, pp_player_lines: dict) -> str | None:
        """
        Match our player name to PrizePicks player name using fuzzy matching.

        Args:
            player_name: Our format
            pp_player_lines: Dict from get_all_pp_player_lines

        Returns:
            PP player name if found, None otherwise
        """
        # Exact match first
        if player_name in pp_player_lines:
            return player_name

        # Try lowercase
        player_lower = player_name.lower()
        for pp_name in pp_player_lines.keys():
            if pp_name.lower() == player_lower:
                return pp_name

        # Last name match
        last_name = player_name.split()[-1].lower()
        first_initial = player_name[0].lower() if player_name else ''

        for pp_name in pp_player_lines.keys():
            pp_parts = pp_name.split()
            if len(pp_parts) >= 2:
                pp_last = pp_parts[-1].lower()
                pp_first_initial = pp_parts[0][0].lower() if pp_parts[0] else ''

                if pp_last == last_name and pp_first_initial == first_initial:
                    return pp_name

        return None

    def generate_predictions(self, target_date=None, players_per_team=None, force=False):
        """
        V6: Generate predictions using PrizePicks lines.

        Args:
            target_date (str): Date to predict (YYYY-MM-DD). Defaults to tomorrow.
            players_per_team (int): Number of players per team. Defaults to 8.
            force (bool): Force regeneration even if predictions exist.
        """
        # Determine target date (tomorrow by default)
        if target_date is None:
            target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        # Default to 8 players (5 starters + 3 bench)
        if players_per_team is None:
            players_per_team = STARTERS_COUNT + SIGNIFICANT_BENCH_COUNT

        print()
        print("=" * 70)
        print("  NBA PREDICTION GENERATOR V6 - PrizePicks Line Driven")
        print("=" * 70)
        print(f"  Target date: {target_date}")
        print(f"  Players per team: {players_per_team}")
        print()

        print("MODE: PrizePicks Line Driven")
        print("Only generating predictions for ACTUAL PrizePicks lines")
        print()

        # STEP 0: Check NBA schedule
        print("STEP 0: Checking NBA schedule...")
        has_games, game_count = nba_has_games(target_date)
        if not has_games:
            print(f"[SKIP] No regular season NBA games scheduled for {target_date}")
            if game_count == 0:
                print("       (All-Star break or off day)")
            print("       Skipping prediction generation.")
            print()
            return {'total_predictions': 0, 'no_games': True, 'skipped_schedule': True}
        else:
            count_str = str(game_count) if game_count > 0 else "unknown number of"
            print(f"[OK] {count_str} regular season games on {target_date}")
        print()

        # Check for existing predictions
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM predictions WHERE game_date = ?', (target_date,))
        existing = cursor.fetchone()[0]

        if existing > 0 and not force:
            print(f"[SKIP] {existing} predictions already exist for {target_date}")
            print("       Use --force to regenerate")
            conn.close()
            return {'total_predictions': 0, 'skipped': True}

        if existing > 0 and force:
            cursor.execute('DELETE FROM predictions WHERE game_date = ?', (target_date,))
            conn.commit()
            print(f"[DELETE] Deleted {existing} existing predictions (--force)")
            print()

        # STEP 1: Ensure PP lines are fetched
        print("STEP 1: Checking PrizePicks lines...")
        pp_available, pp_fetch_date = self.ensure_pp_lines_fetched()

        if not pp_available:
            print("[WARN] PrizePicks lines not available, using fallback lines")
            use_pp_lines = False
            pp_player_lines = {}
        else:
            use_pp_lines = True
            pp_player_lines = self.get_all_pp_player_lines(pp_fetch_date)
            print(f"[PP] Found lines for {len(pp_player_lines)} NBA players")
        print()

        # STEP 2: Fetch games (NBA Stats API primary, ESPN fallback)
        print("STEP 2: Fetching game schedule...")
        games = self.api.get_scoreboard(target_date)
        print(f"[GAME] Found {len(games)} games on {target_date} (NBA Stats API)")

        if len(games) == 0:
            print("[WARN] NBA Stats API returned 0 games — trying ESPN API fallback...")
            try:
                espn_games = self.espn_api.get_scoreboard(target_date)
                if espn_games:
                    games = espn_games
                    print(f"[GAME] ESPN fallback: found {len(games)} games on {target_date}")
                else:
                    print("[WARN] ESPN API also returned 0 games — no games scheduled")
            except Exception as e:
                print(f"[WARN] ESPN fallback failed: {e}")

        if len(games) == 0:
            print("[WARN] No games scheduled")
            conn.close()
            return {'total_predictions': 0, 'no_games': True}

        # Save games to database
        self._save_games(conn, games, target_date)
        print()

        # STEP 3: Generate predictions
        print("STEP 3: Generating predictions...")
        print()

        total_predictions = 0
        pp_matched_players = 0
        pp_unmatched_players = 0
        predictions_by_prop = {}
        all_probabilities = []
        skipped_errors = 0

        for game in games:
            print(f"{game['away_team']} @ {game['home_team']}")

            for team, opponent, home_away in [
                (game['home_team'], game['away_team'], 'H'),
                (game['away_team'], game['home_team'], 'A')
            ]:
                players = self._get_team_players(conn, team, players_per_team, target_date)

                for player_name in players:
                    # Find PP lines for this player
                    if use_pp_lines:
                        pp_name = self.match_player_to_pp(player_name, pp_player_lines)

                        if pp_name:
                            pp_matched_players += 1
                            player_pp_lines = pp_player_lines[pp_name]
                        else:
                            # No PP lines = player is injured, not playing today, or on wrong team.
                            # Skip entirely — do NOT fall back to fixed lines. This prevents
                            # generating fake predictions for traded players (e.g. KD as PHX).
                            pp_unmatched_players += 1
                            continue
                    else:
                        player_pp_lines = FALLBACK_PROPS.copy()

                    # Generate predictions for each prop/line combo
                    for prop_type, lines in player_pp_lines.items():
                        for line in lines:
                            try:
                                # Statistical predictor always runs (provides features + fallback)
                                stat_result = self.predictor.predict_prop(
                                    player_name, prop_type, line, target_date,
                                    home_away, opponent
                                )

                                # Use ML ensemble if a trained model exists for this combo
                                if (stat_result and self.ml_predictor and
                                        self.ml_predictor.is_model_available('nba', prop_type, line)):
                                    result = self.ml_predictor.predict_ensemble(
                                        'nba', prop_type, line,
                                        stat_result.get('features', {}),
                                        stat_result
                                    )
                                else:
                                    result = stat_result

                                if result:
                                    # Save prediction
                                    self._save_prediction(
                                        conn, game['game_id'], target_date, player_name,
                                        team, opponent, home_away, prop_type, line, result
                                    )

                                    total_predictions += 1
                                    predictions_by_prop[prop_type] = predictions_by_prop.get(prop_type, 0) + 1
                                    all_probabilities.append(result['probability'])
                            except Exception as e:
                                # Log so we can diagnose systematic failures
                                import sys
                                print(f"[WARN] {player_name} {prop_type} {line}: {e}", file=sys.stderr)
                                skipped_errors += 1

                print(f"   {team}: {len(players)} players")

            print()

        conn.commit()
        conn.close()

        # Summary
        print("=" * 70)
        print(f"  V6: GENERATED {total_predictions} PREDICTIONS")
        print("=" * 70)
        print()

        if use_pp_lines:
            print("PRIZEPICKS MATCHING:")
            print(f"  Players matched to PP: {pp_matched_players}")
            print(f"  Players unmatched (fallback): {pp_unmatched_players}")
            print()

        print("BREAKDOWN BY PROP:")
        for prop, count in sorted(predictions_by_prop.items(), key=lambda x: -x[1]):
            print(f"  {prop}: {count}")
        print()

        # Feature variety check
        unique_probs = len(set([round(p, 2) for p in all_probabilities]))
        print(f"Unique probabilities: {unique_probs}")

        if unique_probs < 10:
            print("[WARN] Low feature variety (< 10 unique probabilities)")
        else:
            print("[OK] Feature variety looks good!")

        if skipped_errors > 0:
            print(f"[WARN] {skipped_errors} predictions skipped due to errors (check stderr)")

        # Discord notification
        if DISCORD_WEBHOOK_URL:
            self._send_discord_notification(target_date, total_predictions, unique_probs)

        return {
            'total_predictions': total_predictions,
            'unique_probabilities': unique_probs,
            'pp_matched': pp_matched_players,
            'pp_unmatched': pp_unmatched_players,
            'skipped_errors': skipped_errors
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

    # ESPN uses different abbreviations than NBA Stats API (which populates the games table).
    # This map lets us search player_game_logs using both the canonical abbrev and its alias.
    TEAM_ALIASES = {
        'WAS': 'WSH', 'WSH': 'WAS',
        'NYK': 'NY',  'NY':  'NYK',
        'SAS': 'SA',  'SA':  'SAS',
        'NOP': 'NO',  'NO':  'NOP',
        'GSW': 'GS',  'GS':  'GSW',
        'UTA': 'UTAH','UTAH':'UTA',
    }

    def _get_team_players(self, conn, team, count, game_date):
        """Get top N players for a team based on recent performance.

        Only includes players whose MOST RECENT game was for this team (or its alias).
        - Handles traded players: KD's most recent logs are HOU, so he won't appear in PHX.
        - Handles abbreviation mismatches: WAS (games table) ↔ WSH (ESPN game logs).
        """
        cursor = conn.cursor()

        # Build list of team abbreviations to accept (canonical + ESPN alias).
        alias = self.TEAM_ALIASES.get(team)
        team_variants = [team, alias] if alias else [team]
        placeholders = ','.join(['?' for _ in team_variants])

        # Only include players whose most recent game (before target date) was for this
        # team (in any variant). This filters out players traded away to other teams.
        # CTE pre-computes each player's current team once (avoids O(n²) correlated subquery).
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

        if len(players) < count:
            print(f"      [WARN] Only {len(players)} players found for {team} (may have traded players filtered out)")

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
                 f_consistency_score, features_json, expected_value)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                result.get('expected_value'),
            ))
        except sqlite3.IntegrityError:
            pass  # Duplicate prediction

    def _send_discord_notification(self, date, total, unique):
        """Send Discord notification."""
        try:
            import requests

            message = f"""
[NBA] **NBA V6 Prediction Generator Report**
Date: {date}

**Generated:**
- Total predictions: {total}
- Unique probabilities: {unique}

{'[OK] PREDICTIONS READY' if unique >= 10 else '[WARN] LOW FEATURE VARIETY'}
            """

            payload = {"content": message}
            requests.post(DISCORD_WEBHOOK_URL, json=payload)
        except:
            pass


# CLI interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='NBA V6: PrizePicks Line Driven Predictions')
    parser.add_argument('date', nargs='?', default=None, help='Target date (YYYY-MM-DD)')
    parser.add_argument('--force', action='store_true', help='Force regeneration')

    args = parser.parse_args()

    import sys as _sys
    generator = NBADailyPredictorV6()
    result = generator.generate_predictions(args.date, force=args.force)

    total = result.get('total_predictions', 0)
    if total > 0:
        print(f"\n[SUCCESS] Generated {total} predictions")
        _sys.exit(0)
    elif result.get('skipped') or result.get('no_games') or result.get('skipped_schedule'):
        # Legitimate skip (off day, existing predictions)
        print("\n[INFO] No new predictions generated (off day or already exists)")
        _sys.exit(0)
    else:
        # Games exist but 0 predictions generated — something went wrong
        print("\n[ERROR] 0 predictions generated despite games being scheduled", file=_sys.stderr)
        _sys.exit(1)
