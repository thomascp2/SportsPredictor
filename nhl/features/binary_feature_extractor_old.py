"""
Binary Feature Extractor for Points O0.5 Predictions
=====================================================

Extracts features for BINARY classification (scored or didn't score).
Priority 1 features only - tested and validated before adding more.

CRITICAL: All features must use data from BEFORE game_date (temporal safety).

Author: NHL Prediction System V2
Date: 2025-11-04
"""

import sqlite3
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class BinaryFeatureExtractor:
    """
    Extracts binary features for Points O0.5 predictions.
    
    Features focus on player's scoring patterns, streaks, and momentum.
    All features are computed using only historical data (temporal safety).
    """
    
    def __init__(self, db_path: str):
        """
        Initialize feature extractor.
        
        Args:
            db_path: Path to nhl_predictions_v2.db
        """
        self.db_path = db_path
        self.conn = None
        
    def connect(self):
        """Open database connection"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Access columns by name
        
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            
    def extract_features(self, 
                        player_name: str, 
                        team: str, 
                        game_date: str, 
                        opponent: str,
                        is_home: bool) -> Dict[str, float]:
        """
        Extract binary features for a player's game.
        
        Args:
            player_name: Player's full name
            team: Player's team abbreviation
            game_date: Game date (YYYY-MM-DD) - PREDICTION DATE
            opponent: Opponent team abbreviation
            is_home: True if home game, False if away
            
        Returns:
            Dictionary of features (all floats)
            
        Note:
            Uses ONLY data from BEFORE game_date (temporal safety)
        """
        if not self.conn:
            self.connect()
            
        # Get player's historical games (BEFORE game_date)
        games = self._get_player_history(player_name, team, game_date)
        
        if not games:
            logger.warning(f"No history for {player_name} before {game_date}")
            return self._get_default_features(is_home)
            
        # Extract features
        features = {}
        
        # SUCCESS RATES (5 features)
        features['success_rate_season'] = self._calc_success_rate(games, window=None)
        features['success_rate_l20'] = self._calc_success_rate(games, window=20)
        features['success_rate_l10'] = self._calc_success_rate(games, window=10)
        features['success_rate_l5'] = self._calc_success_rate(games, window=5)
        features['success_rate_l3'] = self._calc_success_rate(games, window=3)
        
        # STREAKS (2 features)
        features['current_streak'] = self._calc_current_streak(games)
        features['max_hot_streak'] = self._calc_max_hot_streak(games)
        
        # MOMENTUM (1 feature)
        features['recent_momentum'] = self._calc_momentum(games)
        
        # CONTEXT (3 features)
        features['is_home'] = 1.0 if is_home else 0.0
        features['games_played'] = float(len(games))
        features['insufficient_data'] = 1.0 if len(games) < 5 else 0.0
        
        # VALIDATE TEMPORAL SAFETY
        is_safe, violation_date = self._validate_temporal_safety(games, game_date)
        if not is_safe:
            logger.error(f"TEMPORAL VIOLATION: Used data from {violation_date} >= {game_date}")
            raise ValueError("Data leakage detected!")
            
        return features
        
    def _get_player_history(self, 
                           player_name: str, 
                           team: str, 
                           cutoff_date: str) -> list:
        """
        Get player's game history BEFORE cutoff_date.
        
        Args:
            player_name: Player name
            team: Team abbreviation
            cutoff_date: Don't include games on or after this date
            
        Returns:
            List of game dictionaries (most recent first)
        """
        cursor = self.conn.cursor()
        
        query = """
            SELECT 
                game_date,
                scored_1plus_points,
                points,
                is_home
            FROM player_game_logs
            WHERE player_name = ?
                AND team = ?
                AND game_date < ?
            ORDER BY game_date DESC
        """
        
        cursor.execute(query, (player_name, team, cutoff_date))
        games = [dict(row) for row in cursor.fetchall()]
        
        return games
        
    def _calc_success_rate(self, games: list, window: Optional[int] = None) -> float:
        """
        Calculate success rate (% of games with 1+ points).
        
        Args:
            games: List of game dictionaries
            window: Number of recent games (None = all games)
            
        Returns:
            Success rate (0.0 to 1.0)
        """
        if not games:
            return 0.5  # Default: 50% if no data
            
        # Apply window
        if window:
            games_subset = games[:window]
        else:
            games_subset = games
            
        if not games_subset:
            return 0.5
            
        # Calculate success rate
        successes = sum(1 for g in games_subset if g['scored_1plus_points'] == 1)
        return successes / len(games_subset)
        
    def _calc_current_streak(self, games: list) -> float:
        """
        Calculate current streak (positive = hot, negative = cold).
        
        Args:
            games: List of game dictionaries (most recent first)
            
        Returns:
            Streak length (positive for scoring streak, negative for cold streak)
            
        Example:
            [1, 1, 1, 0] -> +3 (scored last 3 games)
            [0, 0, 1, 1] -> -2 (scoreless last 2 games)
        """
        if not games:
            return 0.0
            
        streak = 0
        first_result = games[0]['scored_1plus_points']
        
        for game in games:
            if game['scored_1plus_points'] == first_result:
                streak += 1
            else:
                break
                
        # Make negative if cold streak
        if first_result == 0:
            streak = -streak
            
        return float(streak)
        
    def _calc_max_hot_streak(self, games: list) -> float:
        """
        Calculate longest scoring streak this season.
        
        Args:
            games: List of game dictionaries
            
        Returns:
            Max consecutive games with 1+ points
        """
        if not games:
            return 0.0
            
        max_streak = 0
        current_streak = 0
        
        for game in games:
            if game['scored_1plus_points'] == 1:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
                
        return float(max_streak)
        
    def _calc_momentum(self, games: list) -> float:
        """
        Calculate momentum (weighted toward recent games).
        
        Uses exponential weighting: recent games count more.
        
        Args:
            games: List of game dictionaries (most recent first)
            
        Returns:
            Momentum score (0.0 to 1.0)
        """
        if not games:
            return 0.5
            
        # Use last 10 games for momentum
        recent_games = games[:10]
        
        if not recent_games:
            return 0.5
            
        # Exponential weights (most recent = highest weight)
        weights = np.exp(-np.arange(len(recent_games)) / 3.0)
        weights = weights / weights.sum()  # Normalize
        
        # Weighted average of successes
        outcomes = np.array([g['scored_1plus_points'] for g in recent_games])
        momentum = np.sum(outcomes * weights)
        
        return float(momentum)
        
    def _validate_temporal_safety(self, 
                                  games: list, 
                                  game_date: str) -> Tuple[bool, Optional[str]]:
        """
        Validate that all games are from BEFORE game_date.
        
        Args:
            games: List of game dictionaries
            game_date: Prediction date (should be > all game dates)
            
        Returns:
            (is_safe, violation_date)
            - is_safe: True if all games before game_date
            - violation_date: First date >= game_date (if any)
        """
        game_date_obj = datetime.strptime(game_date, '%Y-%m-%d')
        
        for game in games:
            game_date_check = datetime.strptime(game['game_date'], '%Y-%m-%d')
            if game_date_check >= game_date_obj:
                return False, game['game_date']
                
        return True, None
        
    def _get_default_features(self, is_home: bool) -> Dict[str, float]:
        """
        Return default features when player has no history.
        
        Args:
            is_home: Is this a home game?
            
        Returns:
            Dictionary of default features (conservative estimates)
        """
        return {
            'success_rate_season': 0.35,  # League average from verify_data.py
            'success_rate_l20': 0.35,
            'success_rate_l10': 0.35,
            'success_rate_l5': 0.35,
            'success_rate_l3': 0.35,
            'current_streak': 0.0,
            'max_hot_streak': 0.0,
            'recent_momentum': 0.35,
            'is_home': 1.0 if is_home else 0.0,
            'games_played': 0.0,
            'insufficient_data': 1.0  # FLAG: No historical data
        }


def test_feature_extraction():
    """
    Test feature extraction on a sample player from October 2025.
    Verifies temporal safety and feature correctness.
    """
    logger.info("="*80)
    logger.info("TESTING BINARY FEATURE EXTRACTOR")
    logger.info("="*80)
    
    db_path = r"C:\Users\thoma\NHL-Model-Rebuild-V2\database\nhl_predictions_v2.db"
    
    # Test on a game from October 15, 2025
    # Should only use games from Oct 1-14
    extractor = BinaryFeatureExtractor(db_path)
    extractor.connect()
    
    # Get a sample player from database
    cursor = extractor.conn.cursor()
    cursor.execute("""
        SELECT DISTINCT player_name, team, opponent, is_home
        FROM player_game_logs
        WHERE game_date = '2025-10-15'
        LIMIT 1
    """)
    
    row = cursor.fetchone()
    if not row:
        logger.error("No games found for 2025-10-15")
        extractor.close()
        return
        
    player_name = row[0]
    team = row[1]
    opponent = row[2]
    is_home = bool(row[3])
    
    logger.info(f"\nTesting player: {player_name} ({team})")
    logger.info(f"Game: {team} vs {opponent} on 2025-10-15")
    logger.info(f"Location: {'HOME' if is_home else 'AWAY'}")
    logger.info("")
    
    # Extract features
    try:
        features = extractor.extract_features(
            player_name=player_name,
            team=team,
            game_date='2025-10-15',  # Prediction date
            opponent=opponent,
            is_home=is_home
        )
        
        logger.info("Features extracted successfully:")
        logger.info("-"*80)
        
        for feature_name, value in features.items():
            logger.info(f"  {feature_name:30s}: {value:.4f}")
            
        logger.info("")
        logger.info("="*80)
        logger.info("VALIDATION CHECKS")
        logger.info("="*80)
        
        # Check 1: Temporal safety
        logger.info("\n[CHECK 1] Temporal Safety")
        games = extractor._get_player_history(player_name, team, '2025-10-15')
        is_safe, violation = extractor._validate_temporal_safety(games, '2025-10-15')
        
        if is_safe:
            logger.info("  PASS: All data from before 2025-10-15")
            logger.info(f"  Used {len(games)} games from history")
        else:
            logger.error(f"  FAIL: Data leakage detected on {violation}")
            
        # Check 2: Feature ranges
        logger.info("\n[CHECK 2] Feature Value Ranges")
        all_valid = True
        
        # Success rates should be 0-1
        for key in ['success_rate_season', 'success_rate_l20', 'success_rate_l10', 
                    'success_rate_l5', 'success_rate_l3', 'recent_momentum']:
            if not (0.0 <= features[key] <= 1.0):
                logger.error(f"  FAIL: {key} = {features[key]} (should be 0-1)")
                all_valid = False
                
        # Streak should be reasonable (-20 to +20)
        if not (-20 <= features['current_streak'] <= 20):
            logger.error(f"  FAIL: current_streak = {features['current_streak']}")
            all_valid = False
            
        # Games played should be reasonable (0-82)
        if not (0 <= features['games_played'] <= 82):
            logger.error(f"  FAIL: games_played = {features['games_played']}")
            all_valid = False
            
        if all_valid:
            logger.info("  PASS: All features in valid ranges")
            
        # Check 3: Insufficient data flag
        logger.info("\n[CHECK 3] Insufficient Data Handling")
        if features['insufficient_data'] == 1.0:
            logger.warning(f"  WARNING: Player has <5 games ({int(features['games_played'])} games)")
            logger.info("  Using season averages as fallback")
        else:
            logger.info(f"  PASS: Sufficient data ({int(features['games_played'])} games)")
            
        logger.info("")
        logger.info("="*80)
        logger.info("TEST COMPLETE")
        logger.info("="*80)
        
    except Exception as e:
        logger.error(f"Feature extraction failed: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        extractor.close()


if __name__ == "__main__":
    test_feature_extraction()
