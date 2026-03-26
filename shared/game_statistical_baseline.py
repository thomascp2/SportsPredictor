"""
Game Statistical Baseline — Day 1 predictions without ML training.

Generates moneyline, spread, and total predictions using:
    - Team scoring averages + defense
    - Elo ratings + home advantage
    - Odds-implied probabilities (when available)
    - Normal distribution for spread/total probability

This is the BASELINE that ML models must beat. If XGBoost can't beat
calibrated statistical predictions, it should not be deployed.

Usage:
    from shared.game_statistical_baseline import GameStatisticalPredictor

    pred = GameStatisticalPredictor(sport="nhl")
    result = pred.predict_game(features_dict)
    # Returns: {moneyline, spread, total} predictions with probabilities
"""

import math
from typing import Dict, Optional
from dataclasses import dataclass


# ── Sport-specific parameters ─────────────────────────────────────────────────

SPORT_PARAMS = {
    "nhl": {
        "avg_total": 6.0,
        "margin_stdev": 2.5,      # Std dev of goal margin
        "total_stdev": 2.2,       # Std dev of total goals
        "home_advantage": 0.035,  # ~3.5% home win boost
        "elo_weight": 0.40,       # How much to trust Elo vs stats
        "stats_weight": 0.35,
        "odds_weight": 0.25,
    },
    "nba": {
        "avg_total": 224.0,
        "margin_stdev": 11.8,
        "total_stdev": 18.5,
        "home_advantage": 0.045,  # NBA has strongest home court
        "elo_weight": 0.35,
        "stats_weight": 0.35,
        "odds_weight": 0.30,
    },
    "mlb": {
        "avg_total": 9.0,
        "margin_stdev": 3.8,
        "total_stdev": 3.2,
        "home_advantage": 0.025,  # MLB home field weakest
        "elo_weight": 0.30,
        "stats_weight": 0.35,
        "odds_weight": 0.35,      # MLB lines are very efficient
    },
}


@dataclass
class GamePrediction:
    """A single game prediction."""
    bet_type: str         # 'moneyline', 'spread', 'total'
    bet_side: str         # 'home', 'away', 'over', 'under'
    line: float           # spread or total value
    prediction: str       # 'WIN'/'LOSE' or 'OVER'/'UNDER'
    probability: float    # calibrated probability
    edge: float           # predicted prob minus implied
    confidence_tier: str  # 'SHARP', 'LEAN', 'PASS'
    model_type: str       # 'statistical'

    def to_dict(self):
        return {
            "bet_type": self.bet_type,
            "bet_side": self.bet_side,
            "line": self.line,
            "prediction": self.prediction,
            "probability": round(self.probability, 4),
            "edge": round(self.edge, 4),
            "confidence_tier": self.confidence_tier,
            "model_type": self.model_type,
        }


def _normal_cdf(x):
    """Standard normal CDF using error function approximation."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


class GameStatisticalPredictor:
    """Generate baseline game predictions using statistics."""

    def __init__(self, sport: str):
        self.sport = sport.lower()
        if self.sport not in SPORT_PARAMS:
            raise ValueError(f"Unknown sport: {sport}")
        self.params = SPORT_PARAMS[self.sport]

    def predict_game(self, features: Dict) -> list:
        """
        Generate moneyline, spread, and total predictions from features.

        Args:
            features: Dict of gf_* features from game feature extractor

        Returns:
            List of GamePrediction objects (up to 6: home ML, away ML,
            home spread, away spread, over total, under total)
        """
        predictions = []

        # Estimate home win probability from multiple signals
        home_win_prob = self._estimate_home_win_prob(features)

        # Estimate expected total
        expected_total = self._estimate_total(features)

        # Estimate expected margin (positive = home wins by)
        expected_margin = self._estimate_margin(features, home_win_prob)

        # Get odds-implied probabilities for edge calculation
        implied_prob = features.get("gf_home_implied_prob", 0.50)
        spread = features.get("gf_spread", 0.0)
        total_line = features.get("gf_total_line", self.params["avg_total"])

        # ── Moneyline predictions ─────────────────────────────────────────
        # Home win
        home_edge = home_win_prob - implied_prob
        predictions.append(GamePrediction(
            bet_type="moneyline",
            bet_side="home",
            line=None,
            prediction="WIN" if home_win_prob > 0.5 else "LOSE",
            probability=home_win_prob,
            edge=home_edge,
            confidence_tier=self._tier(abs(home_edge), home_win_prob),
            model_type="statistical",
        ))

        # Away win
        away_win_prob = 1.0 - home_win_prob
        away_implied = 1.0 - implied_prob
        away_edge = away_win_prob - away_implied
        predictions.append(GamePrediction(
            bet_type="moneyline",
            bet_side="away",
            line=None,
            prediction="WIN" if away_win_prob > 0.5 else "LOSE",
            probability=away_win_prob,
            edge=away_edge,
            confidence_tier=self._tier(abs(away_edge), away_win_prob),
            model_type="statistical",
        ))

        # ── Spread predictions ────────────────────────────────────────────
        # P(home covers spread) = P(home_margin > -spread)
        # If spread = -3.5 (home favored), need home to win by > 3.5
        if spread != 0:
            spread_prob = _normal_cdf(
                (expected_margin - (-spread)) / self.params["margin_stdev"]
            )
            spread_edge = spread_prob - 0.50  # Assume -110 both sides
            predictions.append(GamePrediction(
                bet_type="spread",
                bet_side="home",
                line=spread,
                prediction="WIN" if spread_prob > 0.5 else "LOSE",
                probability=spread_prob,
                edge=spread_edge,
                confidence_tier=self._tier(abs(spread_edge), spread_prob),
                model_type="statistical",
            ))

            predictions.append(GamePrediction(
                bet_type="spread",
                bet_side="away",
                line=-spread,
                prediction="WIN" if (1 - spread_prob) > 0.5 else "LOSE",
                probability=1 - spread_prob,
                edge=-(spread_edge),
                confidence_tier=self._tier(abs(spread_edge), 1 - spread_prob),
                model_type="statistical",
            ))

        # ── Total predictions ─────────────────────────────────────────────
        over_prob = 1.0 - _normal_cdf(
            (total_line - expected_total) / self.params["total_stdev"]
        )
        over_edge = over_prob - 0.50
        predictions.append(GamePrediction(
            bet_type="total",
            bet_side="over",
            line=total_line,
            prediction="OVER" if over_prob > 0.5 else "UNDER",
            probability=over_prob,
            edge=over_edge,
            confidence_tier=self._tier(abs(over_edge), over_prob),
            model_type="statistical",
        ))

        under_prob = 1.0 - over_prob
        predictions.append(GamePrediction(
            bet_type="total",
            bet_side="under",
            line=total_line,
            prediction="UNDER" if under_prob > 0.5 else "OVER",
            probability=under_prob,
            edge=-over_edge,
            confidence_tier=self._tier(abs(over_edge), under_prob),
            model_type="statistical",
        ))

        return predictions

    def _estimate_home_win_prob(self, f: Dict) -> float:
        """
        Blend Elo, team stats, and odds into a home win probability.
        Uses configurable weights per sport.
        """
        w = self.params

        # Signal 1: Elo-based probability
        elo_prob = f.get("gf_elo_home_prob", 0.55)

        # Signal 2: Stats-based (scoring differential comparison)
        home_diff = f.get("gf_home_goal_diff", f.get("gf_home_point_diff", f.get("gf_home_run_diff", 0)))
        away_diff = f.get("gf_away_goal_diff", f.get("gf_away_point_diff", f.get("gf_away_run_diff", 0)))
        diff_advantage = home_diff - away_diff

        # Convert differential advantage to probability using logistic function
        # Scale factor calibrated per sport
        if self.sport == "nhl":
            stats_prob = 1.0 / (1.0 + math.exp(-diff_advantage * 0.5))
        elif self.sport == "nba":
            stats_prob = 1.0 / (1.0 + math.exp(-diff_advantage * 0.08))
        else:  # mlb
            stats_prob = 1.0 / (1.0 + math.exp(-diff_advantage * 0.3))

        # Signal 3: Odds-implied probability
        odds_prob = f.get("gf_home_implied_prob", 0.50)

        # Blend
        blended = (
            w["elo_weight"] * elo_prob +
            w["stats_weight"] * stats_prob +
            w["odds_weight"] * odds_prob
        )

        # Apply home advantage boost
        blended += w["home_advantage"]

        # Apply rest adjustment (NBA B2B = big swing)
        rest_adv = f.get("gf_rest_advantage", 0)
        if rest_adv > 0:
            blended += 0.015 * min(rest_adv, 3)  # Cap at +4.5%
        elif rest_adv < 0:
            blended -= 0.015 * min(abs(rest_adv), 3)

        # B2B penalty
        if f.get("gf_away_b2b", 0) and not f.get("gf_home_b2b", 0):
            blended += 0.025  # Away team on B2B, home is rested
        elif f.get("gf_home_b2b", 0) and not f.get("gf_away_b2b", 0):
            blended -= 0.025

        # Clamp to reasonable range
        return max(0.15, min(0.85, blended))

    def _estimate_total(self, f: Dict) -> float:
        """Estimate expected total score for the game."""
        predicted = f.get("gf_predicted_total", self.params["avg_total"])

        # Adjust for park/weather (MLB)
        if self.sport == "mlb":
            park_runs = f.get("gf_park_runs_factor", 1.0)
            predicted *= park_runs

            # Temperature effect (warmer = more runs)
            temp = f.get("gf_temperature", 72)
            if temp > 85:
                predicted *= 1.03
            elif temp < 50:
                predicted *= 0.97

            # Wind effect
            wind = f.get("gf_wind_effect", 0)
            predicted *= (1 + wind * 0.05)

        # Adjust for pace (NBA)
        if self.sport == "nba":
            pace = f.get("gf_pace_product", 100)
            if pace > 0:
                predicted *= (pace / 100.0)

        return predicted

    def _estimate_margin(self, f: Dict, home_win_prob: float) -> float:
        """Estimate expected scoring margin from win probability."""
        # Convert probability to margin using normal distribution inverse
        # P(home wins) = Phi(margin / stdev) → margin = stdev * Phi_inv(P)
        if home_win_prob <= 0.01 or home_win_prob >= 0.99:
            home_win_prob = max(0.01, min(0.99, home_win_prob))

        # Approximate inverse normal CDF (Beasley-Springer-Moro)
        p = home_win_prob
        if p < 0.5:
            t = math.sqrt(-2 * math.log(p))
            z = -(t - (2.515517 + 0.802853*t + 0.010328*t*t) /
                  (1 + 1.432788*t + 0.189269*t*t + 0.001308*t*t*t))
        else:
            t = math.sqrt(-2 * math.log(1 - p))
            z = t - (2.515517 + 0.802853*t + 0.010328*t*t) / \
                (1 + 1.432788*t + 0.189269*t*t + 0.001308*t*t*t)

        return round(z * self.params["margin_stdev"], 2)

    def _tier(self, edge: float, prob: float) -> str:
        """Assign confidence tier based on edge and probability."""
        if edge >= 0.05 and prob >= 0.58:
            return "SHARP"
        elif edge >= 0.02 and prob >= 0.53:
            return "LEAN"
        else:
            return "PASS"


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import os

    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, PROJECT_ROOT)

    # Test with each sport
    for sport in ["nhl", "nba", "mlb"]:
        pred = GameStatisticalPredictor(sport)

        # Simulate a game where home team is favored
        test_features = dict(SPORT_PARAMS[sport])  # Get defaults
        if sport == "nhl":
            from nhl.features.game_features import NHLGameFeatureExtractor, DEFAULT_FEATURES
        elif sport == "nba":
            from nba.features.game_features import NBAGameFeatureExtractor, DEFAULT_FEATURES
        else:
            from mlb.features.game_features import MLBGameFeatureExtractor, DEFAULT_FEATURES

        features = dict(DEFAULT_FEATURES)
        # Make home team slightly better
        if "gf_home_goal_diff" in features:
            features["gf_home_goal_diff"] = 0.5
            features["gf_away_goal_diff"] = -0.3
        elif "gf_home_point_diff" in features:
            features["gf_home_point_diff"] = 5.0
            features["gf_away_point_diff"] = -2.0
        elif "gf_home_run_diff" in features:
            features["gf_home_run_diff"] = 0.5
            features["gf_away_run_diff"] = -0.3

        features["gf_elo_home_prob"] = 0.60
        features["gf_home_implied_prob"] = 0.58
        features["gf_spread"] = -2.5 if sport == "nhl" else (-5.5 if sport == "nba" else -1.5)

        results = pred.predict_game(features)

        print(f"\n{'='*60}")
        print(f"  {sport.upper()} Statistical Baseline — Sample Game")
        print(f"{'='*60}")
        for r in results:
            marker = "*" if r.confidence_tier == "SHARP" else (" " if r.confidence_tier == "LEAN" else ".")
            print(f"  {marker} {r.bet_type:<12} {r.bet_side:<6} "
                  f"line={str(r.line or ''):>6} -> {r.prediction:<6} "
                  f"prob={r.probability:.1%} edge={r.edge:+.1%} [{r.confidence_tier}]")
