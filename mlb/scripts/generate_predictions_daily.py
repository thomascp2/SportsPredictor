"""
MLB Daily Prediction Generator
================================

Main prediction pipeline. Generates OVER/UNDER predictions for all
PrizePicks MLB player props on a given date.

Pipeline:
  1. Fetch today's schedule (starters, lineups, game context)
  2. For each game:
     a. Pitcher props (both starters, if not TBD)
     b. Batter props (all batters in lineup/projected roster)
  3. Save all predictions to database

Handles:
  - TBD starters: pitcher props skipped
  - Lineup availability: uses confirmed lineup or historical proxy
  - Doubleheaders: processed as separate games naturally
  - Postponements: skipped

Usage:
    python generate_predictions_daily.py 2026-04-15
    python generate_predictions_daily.py  # defaults to today
"""

import sys
import json
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'features'))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'ml_training'))

from mlb_config import (
    DB_PATH, BACKUPS_DIR, CORE_PROPS, PITCHER_PROPS, BATTER_PROPS,
    get_player_type, get_db_connection, initialize_database,
    mlb_has_games, MIN_PITCHER_STARTS_FOR_PREDICTION, MIN_BATTER_GAMES_FOR_PREDICTION,
    is_over_only_line, MODEL_TYPE,
)
from fetch_game_schedule import GameScheduleFetcher
from statistical_predictions import MLBStatisticalEngine

# ML Model Integration (optional — falls back to statistical if no models trained yet)
try:
    from production_predictor import ProductionPredictor
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
from pitcher_feature_extractor import PitcherFeatureExtractor
from batter_feature_extractor import BatterFeatureExtractor
from opponent_feature_extractor import OpponentFeatureExtractor
from game_context_extractor import GameContextExtractor


class MLBDailyPredictor:
    """
    Orchestrates the full daily prediction pipeline for MLB.

    Generates predictions for all prop types and saves to the DB.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        initialize_database(self.db_path)

        # Sub-components
        self.schedule_fetcher = GameScheduleFetcher(self.db_path)
        self.stat_engine      = MLBStatisticalEngine()
        self.pitcher_feats    = PitcherFeatureExtractor(self.db_path)
        self.batter_feats     = BatterFeatureExtractor(self.db_path)
        self.opponent_feats   = OpponentFeatureExtractor(self.db_path)
        self.context_feats    = GameContextExtractor(self.db_path)

        # ML predictor — only active when MODEL_TYPE != "statistical_only"
        self.ml_predictor = None
        if ML_AVAILABLE and MODEL_TYPE != "statistical_only":
            try:
                registry_dir = Path(__file__).parent.parent.parent / 'ml_training' / 'model_registry'
                self.ml_predictor = ProductionPredictor(str(registry_dir))
                mlb_models = self.ml_predictor.list_available_models('mlb')
                if mlb_models:
                    print(f"[ML] {len(mlb_models)} MLB ML models loaded")
                else:
                    print("[ML] No MLB models in registry — using statistical predictor")
                    self.ml_predictor = None
            except Exception as e:
                print(f"[ML] Could not load ML predictor: {e}")
                self.ml_predictor = None

    def generate_predictions(self, target_date: str) -> Dict:
        """
        Run the full prediction pipeline for a given date.

        Args:
            target_date: Date in YYYY-MM-DD format

        Returns:
            Summary dict with counts and stats
        """
        print(f"\n{'='*60}")
        print(f"[MLB] Generating predictions for {target_date}")
        print(f"{'='*60}")

        if not mlb_has_games(target_date):
            print(f"[MLB] No games expected on {target_date} (off-season check).")
            return {'status': 'no_games', 'predictions': 0}

        # Create batch ID for this run
        batch_id = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Step 1: Fetch schedule and game context
        games = self.schedule_fetcher.fetch_and_save(target_date)
        if not games:
            print(f"[MLB] No games found for {target_date}")
            return {'status': 'no_games', 'predictions': 0}

        print(f"[MLB] Processing {len(games)} games...")

        # Track results
        predictions_saved = 0
        skipped_tbd = 0
        skipped_data = 0
        errors = 0

        conn = get_db_connection(self.db_path)

        try:
            for game in games:
                if game.status == 'postponed':
                    print(f"[MLB] Skipping postponed: {game.away_team} @ {game.home_team}")
                    continue

                # Get game context features
                ctx_features = self.context_feats.extract(
                    game_id=str(game.game_id),
                    home_team=game.home_team,
                    away_team=game.away_team,
                    venue=game.venue,
                    day_night=game.day_night,
                )

                print(f"\n[MLB] {game.away_team} @ {game.home_team} "
                      f"(O/U: {ctx_features.get('ctx_game_total', 'N/A')})")

                # --- Generate pitcher props ---
                for side, pitcher_name, pitcher_id, team, opponent in [
                    ('home', game.home_starter, game.home_starter_id,
                     game.home_team, game.away_team),
                    ('away', game.away_starter, game.away_starter_id,
                     game.away_team, game.home_team),
                ]:
                    if not pitcher_name or pitcher_name == 'TBD':
                        print(f"  [MLB] Skipping {team} pitcher props (TBD starter)")
                        skipped_tbd += 1
                        continue

                    saved, skipped, errs = self._generate_pitcher_predictions(
                        conn, pitcher_name, pitcher_id, team, opponent, side,
                        game, ctx_features, batch_id, target_date
                    )
                    predictions_saved += saved
                    skipped_data += skipped
                    errors += errs

                # --- Generate batter props ---
                # Get projected lineups for both teams
                home_lineup = game.home_lineup or []
                away_lineup = game.away_lineup or []

                for side, lineup, team, opponent, starter_name, starter_id in [
                    ('home', home_lineup, game.home_team, game.away_team,
                     game.away_starter, game.away_starter_id),
                    ('away', away_lineup, game.away_team, game.home_team,
                     game.home_starter, game.home_starter_id),
                ]:
                    # If lineup not available, use historical starters
                    if not lineup:
                        lineup = self._get_proxy_lineup(conn, team, target_date, side,
                                                         str(game.game_id), game.venue,
                                                         opponent)

                    for batter_info in lineup:
                        saved, skipped, errs = self._generate_batter_predictions(
                            conn, batter_info, team, opponent, side,
                            starter_name, starter_id,
                            game, ctx_features, batch_id, target_date
                        )
                        predictions_saved += saved
                        skipped_data += skipped
                        errors += errs

            conn.commit()

        except Exception as e:
            print(f"[MLB] Critical error: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

        summary = {
            'status': 'success',
            'date': target_date,
            'batch_id': batch_id,
            'predictions': predictions_saved,
            'games': len(games),
            'skipped_tbd': skipped_tbd,
            'skipped_data': skipped_data,
            'errors': errors,
        }

        print(f"\n[MLB] Prediction Summary:")
        print(f"  Predictions saved: {predictions_saved}")
        print(f"  Skipped (TBD starter): {skipped_tbd}")
        print(f"  Skipped (insufficient data): {skipped_data}")
        print(f"  Errors: {errors}")

        return summary

    # =========================================================================
    # Pitcher predictions
    # =========================================================================

    def _generate_pitcher_predictions(self, conn, pitcher_name: str, pitcher_id: Optional[int],
                                       team: str, opponent: str, home_away: str,
                                       game, ctx_features: Dict, batch_id: str,
                                       target_date: str) -> tuple:
        """Generate all pitcher prop predictions for a starting pitcher."""
        saved = skipped = errors = 0

        print(f"  [P] {pitcher_name} ({team} vs {opponent})")

        # Extract pitcher features
        pf = self.pitcher_feats.extract(
            player_name=pitcher_name,
            team=team,
            target_date=target_date,
            home_away=home_away,
            player_id=pitcher_id,
        )

        if pf.get('f_insufficient_data') == 1 and pf.get('f_starts_counted', 0) == 0:
            print(f"     No data for {pitcher_name} — skipping pitcher props")
            skipped += 5  # 5 prop types
            return saved, skipped, errors

        # Extract opponent features (opposing team's plate discipline)
        opp_features = self.opponent_feats.extract_team_offense(
            opponent_team=opponent,
            target_date=target_date,
            pitcher_hand='R',  # Default; could look up from player_id
        )

        # Generate prediction for each pitcher prop type
        for prop_type, lines in CORE_PROPS.items():
            if prop_type not in PITCHER_PROPS:
                continue

            for line in lines:
                try:
                    pred = self.stat_engine.predict(
                        player_name=pitcher_name,
                        prop_type=prop_type,
                        line=line,
                        pitcher_features=pf,
                        context_features=ctx_features,
                        opponent_features=opp_features,
                    )

                    if not pred:
                        continue

                    # ML ensemble blend if a trained model exists for this combo
                    if (self.ml_predictor and
                            self.ml_predictor.is_model_available('mlb', prop_type, line)):
                        pred = self.ml_predictor.predict_ensemble(
                            'mlb', prop_type, line,
                            pred.get('features', {}), pred
                        )

                    # Goblin/demon lines only allow OVER on PrizePicks — skip UNDER
                    if pred['prediction'] == 'UNDER' and is_over_only_line(prop_type, line):
                        continue

                    self._save_prediction(conn, pred, target_date, str(game.game_id),
                                          team, opponent, home_away, 'pitcher', batch_id)
                    saved += 1

                except Exception as e:
                    print(f"     Error: {pitcher_name} {prop_type} {line}: {e}")
                    errors += 1

        return saved, skipped, errors

    # =========================================================================
    # Batter predictions
    # =========================================================================

    def _generate_batter_predictions(self, conn, batter_info: Dict, team: str,
                                      opponent: str, home_away: str,
                                      starter_name: Optional[str], starter_id: Optional[int],
                                      game, ctx_features: Dict, batch_id: str,
                                      target_date: str) -> tuple:
        """Generate all batter prop predictions for a single batter."""
        saved = skipped = errors = 0

        player_name = batter_info.get('name') or batter_info.get('player_name', '')
        player_id = batter_info.get('id') or batter_info.get('player_id')
        batting_order = batter_info.get('batting_order', 5) or 5

        if not player_name:
            return saved, skipped, errors

        # Determine opposing pitcher handedness (default R if unknown)
        pitcher_hand = 'R'  # Could look up from starter_id via API

        # Extract opposing pitcher features
        opp_features = self.opponent_feats.extract_pitcher_matchup(
            pitcher_name=starter_name or 'TBD',
            pitcher_id=starter_id,
            target_date=target_date,
            batter_hand='R',  # Default; from player_id lookup if available
            pitcher_is_home=(home_away == 'away'),  # Pitcher is home if batter is away
        )

        # Generate predictions for each batter prop type
        for prop_type, lines in CORE_PROPS.items():
            if prop_type not in BATTER_PROPS:
                continue

            for line in lines:
                try:
                    # Extract batter features (prop-specific)
                    bf = self.batter_feats.extract(
                        player_name=player_name,
                        team=team,
                        prop_type=prop_type,
                        line=line,
                        target_date=target_date,
                        opposing_pitcher_hand=pitcher_hand,
                        home_away=home_away,
                        batting_order=batting_order,
                    )

                    if bf.get('f_insufficient_data') == 1 and bf.get('f_games_played', 0) == 0:
                        skipped += 1
                        continue

                    pred = self.stat_engine.predict(
                        player_name=player_name,
                        prop_type=prop_type,
                        line=line,
                        batter_features=bf,
                        context_features=ctx_features,
                        opponent_features=opp_features,
                    )

                    if not pred:
                        continue

                    # ML ensemble blend if a trained model exists for this combo
                    if (self.ml_predictor and
                            self.ml_predictor.is_model_available('mlb', prop_type, line)):
                        pred = self.ml_predictor.predict_ensemble(
                            'mlb', prop_type, line,
                            pred.get('features', {}), pred
                        )

                    # Goblin/demon lines only allow OVER on PrizePicks — skip UNDER
                    if pred['prediction'] == 'UNDER' and is_over_only_line(prop_type, line):
                        continue

                    self._save_prediction(conn, pred, target_date, str(game.game_id),
                                          team, opponent, home_away, 'batter', batch_id)
                    saved += 1

                except Exception as e:
                    print(f"     Error: {player_name} {prop_type} {line}: {e}")
                    errors += 1

        return saved, skipped, errors

    # =========================================================================
    # DB helpers
    # =========================================================================

    def _save_prediction(self, conn: sqlite3.Connection, pred: Dict, game_date: str,
                          game_id: str, team: str, opponent: str, home_away: str,
                          player_type: str, batch_id: str) -> None:
        """Insert a single prediction into the database."""
        conn.execute('''
            INSERT INTO predictions (
                game_date, game_id, player_name, team, opponent,
                home_away, player_type, prop_type, line,
                prediction, probability, confidence_tier, expected_value,
                features_json, model_version, prediction_batch_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            game_date,
            game_id,
            pred['player_name'],
            team,
            opponent,
            home_away,
            player_type,
            pred['prop_type'],
            pred['line'],
            pred['prediction'],
            pred['probability'],
            pred['confidence_tier'],
            pred.get('expected_value'),
            json.dumps(pred.get('features', {})),
            pred.get('model_version', ''),
            batch_id,
            datetime.now().isoformat(),
        ))

    def _get_proxy_lineup(self, conn: sqlite3.Connection, team: str, target_date: str,
                           home_away: str, game_id: str, venue: str,
                           opponent: str) -> List[Dict]:
        """
        Get a proxy lineup from historical starters when official lineup not yet posted.

        Returns list of dicts compatible with batter_info format.
        """
        cursor = conn.execute('''
            SELECT
                player_name,
                AVG(COALESCE(batting_order, 5)) as avg_order,
                COUNT(*) as games
            FROM player_game_logs
            WHERE team = ?
              AND player_type = 'batter'
              AND game_date < ?
            GROUP BY player_name
            HAVING COUNT(*) >= 3
            ORDER BY avg_order ASC, games DESC
            LIMIT 9
        ''', (team, target_date))

        rows = cursor.fetchall()
        lineup = []
        for i, row in enumerate(rows, start=1):
            lineup.append({
                'name': row['player_name'],
                'id': None,
                'batting_order': i,
                'lineup_confirmed': False,
            })

        return lineup


# ============================================================================
# Database backup utility
# ============================================================================

def backup_database(db_path: str = None, backups_dir: str = None) -> Optional[str]:
    """
    Create a timestamped backup of the database before running predictions.

    Args:
        db_path: Source database path
        backups_dir: Directory to store backups

    Returns:
        Path to backup file, or None on failure
    """
    db_path = db_path or DB_PATH
    backups_dir = backups_dir or BACKUPS_DIR

    if not Path(db_path).exists():
        return None

    Path(backups_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = str(Path(backups_dir) / f"mlb_predictions_{timestamp}.db")

    try:
        shutil.copy2(db_path, backup_path)
        print(f"[MLB] Database backed up to: {backup_path}")

        # Clean up old backups (keep last 30 days)
        _cleanup_old_backups(backups_dir, keep_days=30)

        return backup_path
    except Exception as e:
        print(f"[MLB] Backup failed: {e}")
        return None


def _cleanup_old_backups(backups_dir: str, keep_days: int = 30) -> None:
    """Remove backup files older than keep_days."""
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=keep_days)
    for f in Path(backups_dir).glob('mlb_predictions_*.db'):
        if f.stat().st_mtime < cutoff.timestamp():
            try:
                f.unlink()
            except Exception:
                pass


# ============================================================================
# Standalone entry point
# ============================================================================

def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime('%Y-%m-%d')

    print(f"[MLB] Starting prediction pipeline for {target_date}")

    # Backup DB before running
    backup_database()

    predictor = MLBDailyPredictor()
    summary = predictor.generate_predictions(target_date)

    print(f"\n[MLB] Done: {summary}")
    return 0 if summary.get('status') == 'success' else 1


if __name__ == '__main__':
    sys.exit(main())
