"""
Continuous Feature Extractor for Shots Predictions
===================================================

Extracts features for CONTINUOUS modeling (how many shots?).
Different from binary features - focuses on volume, consistency, trends.

Key differences from binary extractor:
- Uses averages and standard deviations (not success rates)
- Tracks trends (increasing/decreasing)
- Models shot volume distribution (not yes/no outcome)

CRITICAL: All features must use data from BEFORE game_date (temporal safety).

Author: NHL Prediction System V2
Date: 2025-11-04
"""

import sqlite3
import logging
from typing import Dict, Optional, Tuple, List
from datetime import datetime
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class ContinuousFeatureExtractor:
    """
    Extracts continuous features for Shots predictions.
    
    Features focus on shot volume, consistency, and trends.
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
        self.conn.row_factory = sqlite3.Row
        
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
        Extract continuous features for a player's game.
        
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
            
        # Get player's shot history (BEFORE game_date)
        games = self._get_shot_history(player_name, team, game_date)
        
        if not games:
            logger.warning(f"No shot history for {player_name} before {game_date}")
            return self._get_default_features(is_home)
            
        # Extract shot features
        features = {}
        
        # AVERAGES (3 features)
        features['sog_season'] = self._calc_average(games, window=None)
        features['sog_l10'] = self._calc_average(games, window=10)
        features['sog_l5'] = self._calc_average(games, window=5)
        
        # CONSISTENCY (2 features)
        features['sog_std_season'] = self._calc_std_dev(games, window=None)
        features['sog_std_l10'] = self._calc_std_dev(games, window=10)
        
        # TREND (1 feature)
        features['sog_trend'] = self._calc_trend(games)
        
        # ICE TIME (1 feature) - if available
        features['avg_toi_minutes'] = self._calc_avg_toi(games)
        
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
        
    def _get_shot_history(self,
                          player_name: str,
                          team: str,
                          cutoff_date: str) -> List[Dict]:
        """
        Get player's shot history BEFORE cutoff_date.
        
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
                shots_on_goal,
                toi_seconds,
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
        
    def _calc_average(self, games: List[Dict], window: Optional[int] = None) -> float:
        """
        Calculate average shots per game.
        
        Args:
            games: List of game dictionaries
            window: Number of recent games (None = all games)
            
        Returns:
            Average SOG per game
        """
        if not games:
            return 2.5  # League average default
            
        # Apply window
        if window:
            games_subset = games[:window]
        else:
            games_subset = games
            
        if not games_subset:
            return 2.5
            
        shots = [g['shots_on_goal'] for g in games_subset]
        return float(np.mean(shots))
        
    def _calc_std_dev(self, games: List[Dict], window: Optional[int] = None) -> float:
        """
        Calculate standard deviation of shots (consistency measure).
        
        Args:
            games: List of game dictionaries
            window: Number of recent games (None = all games)
            
        Returns:
            Standard deviation of SOG
        """
        if not games:
            return 1.2  # Default std dev
            
        # Apply window
        if window:
            games_subset = games[:window]
        else:
            games_subset = games
            
        if len(games_subset) < 2:
            return 1.2
            
        shots = [g['shots_on_goal'] for g in games_subset]
        return max(float(np.std(shots)), 0.5)  # Minimum 0.5 std dev
        
    def _calc_trend(self, games: List[Dict]) -> float:
        """
        Calculate shot trend (increasing/decreasing).
        
        Uses linear regression on recent games.
        Positive = increasing, Negative = decreasing
        
        Args:
            games: List of game dictionaries (most recent first)
            
        Returns:
            Trend coefficient (-1 to +1 normalized)
        """
        if len(games) < 3:
            return 0.0  # Not enough data for trend
            
        # Use last 10 games for trend
        recent_games = games[:10]
        shots = [g['shots_on_goal'] for g in recent_games]
        
        # Reverse so oldest is first for regression
        shots = shots[::-1]
        
        # Simple linear regression
        x = np.arange(len(shots))
        
        # Calculate slope
        x_mean = np.mean(x)
        y_mean = np.mean(shots)
        
        numerator = np.sum((x - x_mean) * (shots - y_mean))
        denominator = np.sum((x - x_mean) ** 2)
        
        if denominator == 0:
            return 0.0
            
        slope = numerator / denominator
        
        # Normalize to -1 to +1 range
        # Typical slope range is -0.5 to +0.5 per game
        normalized_trend = np.tanh(slope / 0.3)
        
        return float(normalized_trend)
        
    def _calc_avg_toi(self, games: List[Dict]) -> float:
        """
        Calculate average time on ice in minutes.
        
        Args:
            games: List of game dictionaries
            
        Returns:
            Average TOI in minutes
        """
        if not games:
            return 15.0  # Default ~15 minutes
            
        toi_values = []
        for game in games:
            if game['toi_seconds'] is not None:
                toi_minutes = game['toi_seconds'] / 60.0
                toi_values.append(toi_minutes)
        
        if not toi_values:
            return 15.0
            
        return float(np.mean(toi_values))
        
    def _validate_temporal_safety(self,
                                  games: List[Dict],
                                  game_date: str) -> Tuple[bool, Optional[str]]:
        """
        Validate that all games are from BEFORE game_date.
        
        Args:
            games: List of game dictionaries
            game_date: Prediction date (should be > all game dates)
            
        Returns:
            (is_safe, violation_date)
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
        league_avg_sog = 2.5  # League average from verify_data
        league_std = 1.2
        
        return {
            'sog_season': league_avg_sog,
            'sog_l10': league_avg_sog,
            'sog_l5': league_avg_sog,
            'sog_std_season': league_std,
            'sog_std_l10': league_std,
            'sog_trend': 0.0,
            'avg_toi_minutes': 15.0,
            'is_home': 1.0 if is_home else 0.0,
            'games_played': 0.0,
            'insufficient_data': 1.0
        }


def test_feature_extraction():
    """
    Test feature extraction on sample players.
    Verifies temporal safety and feature correctness.
    """
    logger.info("="*80)
    logger.info("TESTING CONTINUOUS FEATURE EXTRACTOR")
    logger.info("="*80)
    
    db_path = r"C:\Users\thoma\NHL-Model-Rebuild-V2\database\nhl_predictions_v2.db"
    
    extractor = ContinuousFeatureExtractor(db_path)
    extractor.connect()
    
    # Get 3 sample players from October 15
    cursor = extractor.conn.cursor()
    cursor.execute("""
        SELECT DISTINCT player_name, team, opponent, is_home
        FROM player_game_logs
        WHERE game_date = '2025-10-15'
        ORDER BY RANDOM()
        LIMIT 3
    """)
    
    test_cases = cursor.fetchall()
    
    logger.info(f"\nTesting {len(test_cases)} players from 2025-10-15")
    logger.info("")
    
    for idx, (player, team, opponent, is_home) in enumerate(test_cases, 1):
        logger.info("="*80)
        logger.info(f"TEST {idx}: {player} ({team} vs {opponent})")
        logger.info("="*80)
        logger.info(f"Location: {'HOME' if is_home else 'AWAY'}")
        logger.info("")
        
        try:
            # Extract features
            features = extractor.extract_features(
                player_name=player,
                team=team,
                game_date='2025-10-15',
                opponent=opponent,
                is_home=bool(is_home)
            )
            
            logger.info("Features extracted successfully:")
            logger.info("-"*80)
            
            # Show key features
            logger.info(f"  SOG Season Avg: {features['sog_season']:.2f}")
            logger.info(f"  SOG L10 Avg: {features['sog_l10']:.2f}")
            logger.info(f"  SOG L5 Avg: {features['sog_l5']:.2f}")
            logger.info(f"  Season Std Dev: {features['sog_std_season']:.2f}")
            logger.info(f"  L10 Std Dev: {features['sog_std_l10']:.2f}")
            logger.info(f"  Trend: {features['sog_trend']:+.2f} "
                       f"({'Increasing' if features['sog_trend'] > 0.1 else 'Decreasing' if features['sog_trend'] < -0.1 else 'Stable'})")
            logger.info(f"  Avg TOI: {features['avg_toi_minutes']:.1f} minutes")
            logger.info(f"  Games Played: {features['games_played']:.0f}")
            logger.info(f"  Insufficient Data: {features['insufficient_data']:.0f}")
            
            # Validation
            logger.info("")
            logger.info("VALIDATION:")
            
            # Check temporal safety
            games = extractor._get_shot_history(player, team, '2025-10-15')
            is_safe, violation = extractor._validate_temporal_safety(games, '2025-10-15')
            
            if is_safe:
                logger.info(f"  PASS: Temporal safety (used {len(games)} games)")
            else:
                logger.error(f"  FAIL: Data leakage on {violation}")
            
            # Check feature ranges
            all_valid = True
            
            # Averages should be reasonable (0-10 SOG)
            for key in ['sog_season', 'sog_l10', 'sog_l5']:
                if not (0 <= features[key] <= 10):
                    logger.error(f"  FAIL: {key} = {features[key]} (should be 0-10)")
                    all_valid = False
            
            # Std dev should be reasonable (0-5)
            for key in ['sog_std_season', 'sog_std_l10']:
                if not (0 <= features[key] <= 5):
                    logger.error(f"  FAIL: {key} = {features[key]} (should be 0-5)")
                    all_valid = False
            
            # Trend should be -1 to +1
            if not (-1 <= features['sog_trend'] <= 1):
                logger.error(f"  FAIL: sog_trend = {features['sog_trend']} (should be -1 to +1)")
                all_valid = False
            
            if all_valid:
                logger.info("  PASS: All feature ranges valid")
            
            # Check insufficient data flag
            if features['insufficient_data'] == 1.0:
                logger.warning(f"  WARNING: <5 games ({features['games_played']:.0f} games)")
            else:
                logger.info(f"  PASS: Sufficient data ({features['games_played']:.0f} games)")
            
        except Exception as e:
            logger.error(f"Feature extraction failed: {e}")
            import traceback
            traceback.print_exc()
        
        logger.info("")
    
    logger.info("="*80)
    logger.info("TEST COMPLETE")
    logger.info("="*80)
    
    extractor.close()


if __name__ == "__main__":
    test_feature_extraction()
