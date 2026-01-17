"""
Opponent Feature Extractor
==========================

Extracts defensive features for the OPPONENT team.

Key insight: It's not just about how good the PLAYER is,
it's also about how good the DEFENSE is!

Example:
  McDavid vs Arizona (worst defense) → easier matchup
  McDavid vs Boston (best defense) → harder matchup

CRITICAL: All features must use data from BEFORE game_date (temporal safety).

Author: NHL Prediction System V2
Date: 2025-11-13
"""

import sqlite3
import logging
from typing import Dict, Optional
from datetime import datetime
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class OpponentFeatureExtractor:
    """
    Extracts defensive features for opponent teams.
    
    These features help the model understand defensive matchup difficulty.
    Answers the question: "How hard is it to score against THIS team?"
    """
    
    def __init__(self, db_path: str):
        """
        Initialize opponent feature extractor.
        
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
    
    def extract_opponent_features(self,
                                  opponent_team: str,
                                  game_date: str,
                                  prop_type: str = 'points') -> Dict[str, float]:
        """
        Extract defensive features for opponent team.
        
        This analyzes how the opponent performs DEFENSIVELY by looking at
        stats from opposing players when they play AGAINST this team.
        
        Args:
            opponent_team: Opponent team abbreviation (e.g., 'BOS', 'ARI')
            game_date: Game date (YYYY-MM-DD) - prediction date
            prop_type: 'points' or 'shots'
            
        Returns:
            Dict of opponent defensive features (all floats)
            
        Note:
            Uses ONLY data from BEFORE game_date (temporal safety)
        """
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        
        # Get stats of players who played AGAINST this opponent team
        # (This tells us how good the opponent's DEFENSE is)
        cursor.execute("""
            SELECT 
                pgl.game_date,
                pgl.points,
                pgl.shots_on_goal,
                pgl.scored_1plus_points
            FROM player_game_logs pgl
            INNER JOIN games g 
                ON pgl.game_date = g.game_date
            WHERE 
                -- Player's team is NOT the opponent (they're playing AGAINST opponent)
                pgl.team != ?
                -- Game involves the opponent team (either home or away)
                AND (g.home_team = ? OR g.away_team = ?)
                -- Opponent team was in the game
                AND (pgl.team = g.home_team OR pgl.team = g.away_team)
                -- Only use games before prediction date (temporal safety)
                AND pgl.game_date < ?
            ORDER BY pgl.game_date DESC
            LIMIT 200
        """, (opponent_team, opponent_team, opponent_team, game_date))
        
        opponent_games = cursor.fetchall()
        
        if len(opponent_games) < 20:
            # Not enough data - return league averages
            logger.warning(f"Insufficient opponent data for {opponent_team} (only {len(opponent_games)} games)")
            return self._get_default_opponent_features(prop_type)
        
        # Extract opponent defensive stats
        features = {}
        
        if prop_type == 'points':
            # How many points does this opponent ALLOW per player?
            points_allowed = [float(g['points']) for g in opponent_games]
            scoring_pct_allowed = [float(g['scored_1plus_points']) for g in opponent_games]
            
            # Average points allowed (L10 and L5)
            features['opp_points_allowed_l10'] = float(np.mean(points_allowed[:10])) if len(points_allowed) >= 10 else float(np.mean(points_allowed))
            features['opp_points_allowed_l5'] = float(np.mean(points_allowed[:5])) if len(points_allowed) >= 5 else float(np.mean(points_allowed))
            
            # What % of players score against this opponent?
            features['opp_scoring_pct_allowed'] = float(np.mean(scoring_pct_allowed[:20]))
            
            # How consistent is their defense? (lower std = more consistent)
            features['opp_points_std'] = float(np.std(points_allowed[:10])) if len(points_allowed) >= 10 else 0.5
            
            # Is their defense getting better or worse?
            features['opp_defensive_trend'] = self._calc_defensive_trend(points_allowed[:10])
            
        else:  # shots
            # How many shots does this opponent ALLOW per player?
            shots_allowed = [float(g['shots_on_goal']) for g in opponent_games]
            
            # Average shots allowed (L10 and L5)
            features['opp_shots_allowed_l10'] = float(np.mean(shots_allowed[:10])) if len(shots_allowed) >= 10 else float(np.mean(shots_allowed))
            features['opp_shots_allowed_l5'] = float(np.mean(shots_allowed[:5])) if len(shots_allowed) >= 5 else float(np.mean(shots_allowed))
            
            # How consistent is their shot suppression?
            features['opp_shots_std'] = float(np.std(shots_allowed[:10])) if len(shots_allowed) >= 10 else 1.2
            
            # Defensive trend
            features['opp_shots_trend'] = self._calc_defensive_trend(shots_allowed[:10])
            
            # Overall defensive consistency (same as std, but named differently)
            features['opp_defensive_consistency'] = float(np.std(shots_allowed[:10])) if len(shots_allowed) >= 10 else 1.2
        
        return features
    
    def _calc_defensive_trend(self, values: list) -> float:
        """
        Calculate defensive trend using simple linear regression.
        
        Positive trend = defense getting worse (allowing MORE)
        Negative trend = defense getting better (allowing LESS)
        
        Args:
            values: List of points/shots allowed (most recent first)
            
        Returns:
            Trend coefficient normalized to -1 to +1
        """
        if len(values) < 3:
            return 0.0
        
        # Reverse so oldest is first for regression
        values_reversed = values[::-1]
        x = np.arange(len(values_reversed))
        
        # Calculate slope
        x_mean = np.mean(x)
        y_mean = np.mean(values_reversed)
        
        numerator = np.sum((x - x_mean) * (values_reversed - y_mean))
        denominator = np.sum((x - x_mean) ** 2)
        
        if denominator == 0:
            return 0.0
        
        slope = numerator / denominator
        
        # Normalize to -1 to +1 range using tanh
        # Typical slope range is -0.3 to +0.3 per game
        normalized_trend = np.tanh(slope / 0.3)
        
        return float(normalized_trend)
    
    def _get_default_opponent_features(self, prop_type: str) -> Dict[str, float]:
        """
        Return default opponent features when insufficient data.
        
        Uses league averages.
        
        Args:
            prop_type: 'points' or 'shots'
            
        Returns:
            Dictionary of default opponent features
        """
        
        if prop_type == 'points':
            # League average defensive stats
            return {
                'opp_points_allowed_l10': 0.65,  # Avg points allowed per player
                'opp_points_allowed_l5': 0.65,
                'opp_scoring_pct_allowed': 0.35,  # % of players who score
                'opp_points_std': 0.5,  # Defensive consistency
                'opp_defensive_trend': 0.0  # No trend
            }
        else:  # shots
            # League average shot suppression stats
            return {
                'opp_shots_allowed_l10': 2.5,  # Avg shots allowed per player
                'opp_shots_allowed_l5': 2.5,
                'opp_shots_std': 1.2,  # Shot suppression consistency
                'opp_shots_trend': 0.0,  # No trend
                'opp_defensive_consistency': 1.2
            }


def test_opponent_features():
    """
    Test opponent feature extraction on known good/bad defenses.
    
    Should see Arizona (weak defense) allow MORE than Boston (strong defense).
    """
    logger.info("="*80)
    logger.info("TESTING OPPONENT FEATURE EXTRACTION")
    logger.info("="*80)
    logger.info("")
    
    db_path = r"C:\Users\thoma\NHL-Model-Rebuild-V2\database\nhl_predictions_v2.db"
    
    extractor = OpponentFeatureExtractor(db_path)
    extractor.connect()
    
    # Test on multiple teams to see defensive variation
    test_teams = [
        ('ARI', 'Arizona (expected: weak defense)'),
        ('BOS', 'Boston (expected: strong defense)'),
        ('TOR', 'Toronto (expected: mid defense)'),
    ]
    
    for team_abbr, team_desc in test_teams:
        logger.info(f"\nTesting: {team_desc}")
        logger.info("-"*80)
        
        # Points defense
        points_features = extractor.extract_opponent_features(
            opponent_team=team_abbr,
            game_date='2025-11-13',
            prop_type='points'
        )
        
        logger.info("Points Defense:")
        for key, value in points_features.items():
            logger.info(f"  {key:30s}: {value:.3f}")
        
        logger.info("")
        
        # Shots defense  
        shots_features = extractor.extract_opponent_features(
            opponent_team=team_abbr,
            game_date='2025-11-13',
            prop_type='shots'
        )
        
        logger.info("Shots Defense:")
        for key, value in shots_features.items():
            logger.info(f"  {key:30s}: {value:.3f}")
        
        logger.info("")
    
    logger.info("="*80)
    logger.info("COMPARISON")
    logger.info("="*80)
    logger.info("")
    logger.info("Expected pattern:")
    logger.info("  Weak defense (ARI) → allows MORE points/shots")
    logger.info("  Strong defense (BOS) → allows FEWER points/shots")
    logger.info("")
    logger.info("If the numbers follow this pattern, opponent features are working!")
    logger.info("")
    
    extractor.close()


if __name__ == "__main__":
    test_opponent_features()
