"""
Game Prediction Engine — Shared prediction logic for all sports.

Combines statistical baseline + ML models to generate game predictions.
Uses backtest-proven profitable filters to surface only actionable plays.

Profitable strategies (from backtesting):
    1. Elo vs Market Divergence (10%+ gap) — 70% NHL, 67% NBA
    2. High Probability Moneyline (>=62%) — 86% NHL, 65% NBA
    3. SHARP tier (edge >=5%, prob >=58%) — 70% both sports
    4. Kelly positive filter — 60% NHL, 52% NBA

Flow:
    1. Extract features for each game
    2. Run statistical baseline -> get probabilities
    3. Run ML model (if available) -> get probabilities
    4. Blend results (60% ML / 40% statistical when ML available)
    5. Calculate edge vs odds-implied probability
    6. Tag profitable signals (Elo divergence, high prob, Kelly+)
    7. Assign confidence tier (PRIME / SHARP / LEAN / PASS)
    8. Save to game_predictions table

Usage:
    from shared.game_prediction_engine import GamePredictionEngine

    engine = GamePredictionEngine(sport="nhl", db_path="nhl/database/...")
    results = engine.predict_and_save(games_today)
"""

import sqlite3
import json
import os
import sys
import joblib
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "shared"))

from game_statistical_baseline import GameStatisticalPredictor
from game_prediction_schema import ensure_game_tables


# ── Backtest-proven thresholds ───────────────────────────────────────────────

# Elo divergence: bet when Elo disagrees with market by this much
ELO_DIVERGENCE_THRESHOLD = 0.10  # 10%

# Probability thresholds from backtest sweep
PROB_THRESHOLDS = {
    "prime": 0.62,    # 86% NHL, 65% NBA — best ROI
    "sharp": 0.58,    # 70% NHL, 58% NBA — good volume+ROI balance
    "lean":  0.53,    # Marginal edge
}

# Kelly criterion at -110: need prob > 52.38% for positive Kelly
KELLY_BREAKEVEN = 0.5238


class GamePredictionEngine:
    """Generate and save game predictions for any sport."""

    def __init__(self, sport: str, db_path: str, feature_extractor=None):
        self.sport = sport.lower()
        self.db_path = db_path
        self.extractor = feature_extractor
        self.stat_predictor = GameStatisticalPredictor(self.sport)
        self.ml_models = {}  # {bet_type: (model, scaler, metadata)}
        self._load_ml_models()

    def _load_ml_models(self):
        """Load trained ML models from model registry."""
        registry_dir = os.path.join(PROJECT_ROOT, "ml_training", "model_registry",
                                     f"{self.sport}_games")
        if not os.path.exists(registry_dir):
            return

        for bet_type in ["moneyline", "spread", "total"]:
            bet_dir = os.path.join(registry_dir, bet_type)
            if not os.path.exists(bet_dir):
                continue

            # Find latest model via latest*.txt files
            latest_files = [f for f in os.listdir(bet_dir) if f.startswith("latest")]
            for lf in latest_files:
                try:
                    with open(os.path.join(bet_dir, lf)) as f:
                        timestamp = f.read().strip()

                    # Determine line suffix
                    line_part = lf.replace("latest", "").replace(".txt", "")

                    model_file = os.path.join(bet_dir, f"model{line_part}_{timestamp}.joblib")
                    scaler_file = os.path.join(bet_dir, f"scaler{line_part}_{timestamp}.joblib")
                    meta_file = os.path.join(bet_dir, f"metadata{line_part}_{timestamp}.json")

                    if os.path.exists(model_file) and os.path.exists(scaler_file):
                        model = joblib.load(model_file)
                        scaler = joblib.load(scaler_file)
                        meta = {}
                        if os.path.exists(meta_file):
                            with open(meta_file) as f:
                                meta = json.load(f)

                        key = bet_type if not line_part else f"{bet_type}{line_part}"
                        self.ml_models[key] = (model, scaler, meta)
                        print(f"  [ML] Loaded {self.sport} {key} model "
                              f"(acc={meta.get('test_accuracy', 'N/A')})")
                except Exception as e:
                    print(f"  [ML] Could not load {bet_type}: {e}")

    # ── Signal Detection ─────────────────────────────────────────────────

    def _detect_signals(self, features: Dict, bet_type: str, bet_side: str,
                        final_prob: float, edge: float) -> List[str]:
        """
        Detect which backtest-proven profitable signals apply.

        Returns list of signal tags: ['elo_divergence', 'high_prob', 'kelly_positive', ...]
        """
        signals = []

        elo_prob = features.get("gf_elo_home_prob", 0.5)
        implied = features.get("gf_home_implied_prob", 0.5)

        # Adjust for side
        if bet_side == "away":
            elo_prob = 1.0 - elo_prob
            implied = 1.0 - implied

        # Signal 1: Elo vs Market Divergence
        # Backtest: NHL 70.5% / +34.6% ROI, NBA 67.2% / +28.2% ROI
        elo_divergence = elo_prob - implied
        if bet_type == "moneyline" and abs(elo_divergence) >= ELO_DIVERGENCE_THRESHOLD:
            # Only signal when Elo favors the side we're betting
            if (bet_side == "home" and elo_divergence > 0) or \
               (bet_side == "away" and elo_divergence > 0):
                signals.append("elo_divergence")

        # Signal 2: High Probability
        # Backtest: >=62% -> NHL 85.7%, NBA 65.4%
        if final_prob >= PROB_THRESHOLDS["prime"]:
            signals.append("high_prob_prime")
        elif final_prob >= PROB_THRESHOLDS["sharp"]:
            signals.append("high_prob_sharp")

        # Signal 3: Kelly Criterion Positive
        # Backtest: NHL 60.1% / +14.8% ROI
        b = 0.9091  # payout at -110
        kelly = (b * final_prob - (1 - final_prob)) / b
        if kelly > 0:
            signals.append("kelly_positive")
            if kelly > 0.05:
                signals.append("kelly_strong")

        # Signal 4: Strong Edge
        if abs(edge) >= 0.05 and final_prob >= 0.58:
            signals.append("sharp_edge")

        # Signal 5: Rest / Fatigue advantage (only for moneyline)
        if bet_type == "moneyline":
            rest_adv = features.get("gf_rest_advantage", 0)
            away_b2b = features.get("gf_away_b2b", 0)
            home_b2b = features.get("gf_home_b2b", 0)

            if bet_side == "home" and away_b2b and not home_b2b and rest_adv >= 1:
                signals.append("fatigue_edge")
            elif bet_side == "away" and home_b2b and not away_b2b and rest_adv <= -1:
                signals.append("fatigue_edge")

        return signals

    def _assign_tier(self, signals: List[str], edge: float,
                     prob: float) -> str:
        """
        Assign confidence tier based on backtest-proven signals.

        PRIME:  Multiple profitable signals align (best ROI in backtest)
        SHARP:  At least one strong profitable signal
        LEAN:   Kelly positive but no other strong signal
        PASS:   No profitable signal detected
        """
        strong_signals = {"elo_divergence", "high_prob_prime", "sharp_edge"}
        hit_strong = strong_signals.intersection(signals)

        if len(hit_strong) >= 2:
            return "PRIME"
        elif len(hit_strong) >= 1:
            return "SHARP"
        elif "high_prob_sharp" in signals or "kelly_strong" in signals:
            return "LEAN"
        elif "kelly_positive" in signals and prob >= 0.55:
            return "LEAN"
        else:
            return "PASS"

    # ── Prediction Generation ────────────────────────────────────────────

    def predict_game(self, game_date: str, home_team: str, away_team: str,
                     venue: str = None, **kwargs) -> List[Dict]:
        """
        Generate all predictions for a single game.

        Returns list of prediction dicts ready for database insertion.
        """
        # 1. Extract features
        if self.extractor:
            features = self.extractor.extract(game_date, home_team, away_team, venue, **kwargs)
        else:
            features = {}

        # 2. Statistical baseline predictions
        stat_preds = self.stat_predictor.predict_game(features)

        # 3. Try ML enhancement
        predictions = []
        batch_id = f"{self.sport}_{game_date}_{datetime.now().strftime('%H%M%S')}"

        # Get Elo snapshot
        home_elo = features.get("gf_home_elo", None)
        away_elo = features.get("gf_away_elo", None)
        elo_diff = features.get("gf_elo_diff", 0)
        elo_prob = features.get("gf_elo_home_prob", 0.5)

        for sp in stat_preds:
            # Skip moneyline for NBA (user wants ML only for NHL/MLB)
            if sp.bet_type == "moneyline" and self.sport == "nba":
                continue

            # Check if we have an ML model for this bet type
            ml_prob = None
            model_type = "statistical"

            ml_key = sp.bet_type
            if sp.line and sp.bet_type in ["spread", "total"]:
                ml_key = f"{sp.bet_type}_{sp.line}"

            if ml_key in self.ml_models or sp.bet_type in self.ml_models:
                key = ml_key if ml_key in self.ml_models else sp.bet_type
                model, scaler, meta = self.ml_models[key]

                try:
                    feat_names = meta.get("feature_names", [])
                    if feat_names:
                        X = pd.DataFrame([features])[feat_names]
                        X = X.fillna(X.median() if len(X) > 1 else 0)
                        X_scaled = scaler.transform(X)

                        raw_prob = model.predict_proba(X_scaled)[0]

                        # For home/over bets, we want P(class=1)
                        if sp.bet_side in ["home", "over"]:
                            ml_prob = float(raw_prob[1])
                        else:
                            ml_prob = float(raw_prob[0])

                        model_type = f"ensemble_{meta.get('best_model', 'ml')}"
                except Exception as e:
                    pass  # Fall back to statistical only

            # Blend ML + statistical (60/40 when ML available)
            if ml_prob is not None:
                final_prob = 0.60 * ml_prob + 0.40 * sp.probability
                model_type = model_type
            else:
                final_prob = sp.probability

            # Recalculate edge
            implied = features.get("gf_home_implied_prob", 0.50)
            if sp.bet_side == "away":
                implied = 1.0 - implied
            elif sp.bet_side in ["over", "under"]:
                implied = 0.50  # Assume -110 both sides for totals

            edge = final_prob - implied

            # Determine prediction direction
            if sp.bet_type == "moneyline":
                prediction = "WIN" if final_prob > 0.5 else "LOSE"
            elif sp.bet_type == "spread":
                prediction = "WIN" if final_prob > 0.5 else "LOSE"
            elif sp.bet_type == "total":
                prediction = "OVER" if (sp.bet_side == "over" and final_prob > 0.5) else "UNDER"
                if sp.bet_side == "under":
                    prediction = "UNDER" if final_prob > 0.5 else "OVER"

            # Detect backtest-proven signals
            signals = self._detect_signals(
                features, sp.bet_type, sp.bet_side, final_prob, edge
            )

            # Assign tier based on signal strength
            tier = self._assign_tier(signals, abs(edge), final_prob)

            # Convert American odds for storage
            odds_american = None
            if sp.bet_side == "home" and features.get("gf_home_implied_prob"):
                ip = features["gf_home_implied_prob"]
                if ip > 0.5:
                    odds_american = int(-ip / (1 - ip) * 100)
                else:
                    odds_american = int((1 - ip) / ip * 100)

            predictions.append({
                "game_date": game_date,
                "home_team": home_team,
                "away_team": away_team,
                "venue": venue,
                "bet_type": sp.bet_type,
                "bet_side": sp.bet_side,
                "line": sp.line,
                "prediction": prediction,
                "probability": round(final_prob, 4),
                "edge": round(edge, 4),
                "confidence_tier": tier,
                "odds_american": odds_american,
                "implied_probability": round(implied, 4),
                "model_version": f"v2_{model_type}",
                "model_type": model_type,
                "features_json": json.dumps({
                    **features,
                    "_signals": signals,
                    "_signal_count": len(signals),
                }),
                "home_elo": home_elo,
                "away_elo": away_elo,
                "elo_diff": elo_diff,
                "elo_win_prob": elo_prob,
                "prediction_batch_id": batch_id,
            })

        return predictions

    def save_predictions(self, predictions: List[Dict]) -> int:
        """Save predictions to game_predictions table. Returns count saved."""
        conn = sqlite3.connect(self.db_path)
        ensure_game_tables(conn)

        saved = 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for p in predictions:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO game_predictions
                    (game_date, home_team, away_team, venue,
                     bet_type, bet_side, line, prediction,
                     probability, edge, confidence_tier,
                     odds_american, implied_probability,
                     model_version, model_type, features_json,
                     home_elo, away_elo, elo_diff, elo_win_prob,
                     prediction_batch_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p["game_date"], p["home_team"], p["away_team"], p["venue"],
                    p["bet_type"], p["bet_side"], p["line"], p["prediction"],
                    p["probability"], p["edge"], p["confidence_tier"],
                    p["odds_american"], p["implied_probability"],
                    p["model_version"], p["model_type"], p["features_json"],
                    p["home_elo"], p["away_elo"], p["elo_diff"], p["elo_win_prob"],
                    p["prediction_batch_id"], now,
                ))
                saved += 1
            except Exception as e:
                print(f"  [WARN] Could not save prediction: {e}")

        conn.commit()
        conn.close()
        return saved

    def predict_and_save(self, games: List[Dict]) -> Dict:
        """
        Generate and save predictions for a list of games.

        Returns summary dict with counts, top plays, and signal breakdown.
        """
        all_preds = []
        actionable_plays = []  # PRIME + SHARP only

        for game in games:
            preds = self.predict_game(
                game["game_date"],
                game["home_team"],
                game["away_team"],
                game.get("venue"),
            )
            all_preds.extend(preds)

            for p in preds:
                if p["confidence_tier"] in ("PRIME", "SHARP"):
                    actionable_plays.append(p)

        saved = self.save_predictions(all_preds)

        # Count signal types
        signal_counts = {}
        for p in all_preds:
            try:
                feat = json.loads(p["features_json"])
                for sig in feat.get("_signals", []):
                    signal_counts[sig] = signal_counts.get(sig, 0) + 1
            except Exception:
                pass

        # Tier breakdown
        tier_counts = {}
        for p in all_preds:
            t = p["confidence_tier"]
            tier_counts[t] = tier_counts.get(t, 0) + 1

        return {
            "total_predictions": len(all_preds),
            "saved": saved,
            "games": len(games),
            "actionable_plays": len(actionable_plays),
            "tier_breakdown": tier_counts,
            "signal_counts": signal_counts,
            "sharp_plays": len(actionable_plays),  # backward compat
            "sharp_details": [
                f"[{p['confidence_tier']}] {p['home_team']} vs {p['away_team']}: "
                f"{p['bet_type']} {p['bet_side']} ({p['prediction']}) "
                f"prob={p['probability']:.1%} edge={p['edge']:+.1%}"
                for p in sorted(actionable_plays,
                                key=lambda x: (0 if x["confidence_tier"] == "PRIME" else 1,
                                               -abs(x["edge"])))
            ],
        }
