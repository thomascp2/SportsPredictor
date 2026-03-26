"""
Game Prediction Backtesting Framework
======================================

Tests different betting strategies against historical games to find
profitable angles. Uses the same feature extraction + model pipeline
but simulates different filtering and selection strategies.

Strategies tested:
    1. Baseline (bet everything)
    2. SHARP-only filter
    3. High-edge filter (edge > threshold)
    4. Home underdog ML
    5. Contrarian (fade public / high implied prob)
    6. Situational (rest, B2B, travel)
    7. Closing line value (CLV) simulation
    8. Kelly criterion sizing
    9. Model confidence threshold sweep
    10. Ensemble agreement filter

Usage:
    python backtest_game_strategies.py --sport nhl
    python backtest_game_strategies.py --sport nba
    python backtest_game_strategies.py --sport all --detailed
"""

import sqlite3
import json
import os
import sys
import math
import argparse
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Tuple
from dataclasses import dataclass, field

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "shared"))

from game_statistical_baseline import GameStatisticalPredictor


# ── Constants ────────────────────────────────────────────────────────────────

JUICE = 0.0476  # Standard -110 vig (~4.76%)
BREAK_EVEN = 0.5238  # Need 52.38% to break even at -110


@dataclass
class BetResult:
    """Single bet outcome for backtesting."""
    game_date: str
    home_team: str
    away_team: str
    bet_type: str       # moneyline, spread, total
    bet_side: str       # home, away, over, under
    line: float
    prediction: str     # WIN/LOSE/OVER/UNDER
    probability: float
    edge: float
    outcome: str        # HIT, MISS, PUSH
    profit: float       # At -110 standard
    strategy: str


@dataclass
class StrategyResult:
    """Summary of a strategy's performance."""
    name: str
    description: str
    total_bets: int = 0
    wins: int = 0
    losses: int = 0
    pushes: int = 0
    profit: float = 0.0
    roi: float = 0.0
    accuracy: float = 0.0
    avg_edge: float = 0.0
    max_drawdown: float = 0.0
    win_streak: int = 0
    loss_streak: int = 0
    bets: List[BetResult] = field(default_factory=list)

    def calculate(self):
        decided = self.wins + self.losses
        self.accuracy = self.wins / decided * 100 if decided > 0 else 0
        self.roi = self.profit / (decided * 100) * 100 if decided > 0 else 0
        if self.bets:
            self.avg_edge = sum(b.edge for b in self.bets) / len(self.bets) * 100

        # Max drawdown + streaks
        running = 0.0
        peak = 0.0
        max_dd = 0.0
        current_streak = 0
        max_win_streak = 0
        max_loss_streak = 0
        for b in self.bets:
            running += b.profit
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd

            if b.outcome == "HIT":
                if current_streak > 0:
                    current_streak += 1
                else:
                    current_streak = 1
                max_win_streak = max(max_win_streak, current_streak)
            elif b.outcome == "MISS":
                if current_streak < 0:
                    current_streak -= 1
                else:
                    current_streak = -1
                max_loss_streak = max(max_loss_streak, abs(current_streak))

        self.max_drawdown = max_dd
        self.win_streak = max_win_streak
        self.loss_streak = max_loss_streak


# ── Data Loading ─────────────────────────────────────────────────────────────

def load_historical_games(sport: str) -> pd.DataFrame:
    """Load all historical games with features and outcomes."""
    db_map = {
        "nhl": os.path.join(PROJECT_ROOT, "nhl", "database", "nhl_predictions_v2.db"),
        "nba": os.path.join(PROJECT_ROOT, "nba", "database", "nba_predictions.db"),
        "mlb": os.path.join(PROJECT_ROOT, "mlb", "database", "mlb_predictions.db"),
    }
    db_path = db_map.get(sport)
    if not db_path or not os.path.exists(db_path):
        return pd.DataFrame()

    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT game_date, home_team, away_team,
               home_win, home_score, away_score, margin, total,
               features_json
        FROM game_training_data
        ORDER BY game_date ASC
    """).fetchall()
    conn.close()

    if not rows:
        return pd.DataFrame()

    records = []
    for r in rows:
        game_date, home, away, home_win, hs, aws, margin, total, feat_json = r
        try:
            features = json.loads(feat_json)
        except (json.JSONDecodeError, TypeError):
            continue

        records.append({
            "game_date": game_date,
            "home_team": home,
            "away_team": away,
            "home_win": home_win,
            "home_score": hs,
            "away_score": aws,
            "margin": margin,
            "total": total,
            **features,
        })

    return pd.DataFrame(records)


# ── Outcome Grading ──────────────────────────────────────────────────────────

def grade_bet(bet_type: str, bet_side: str, line: float,
              prediction: str, margin: int, total: int) -> Tuple[str, float]:
    """Grade a bet and return (outcome, profit at -110)."""
    if bet_type == "moneyline":
        if margin == 0:
            return "PUSH", 0.0
        if bet_side == "home":
            actual = "WIN" if margin > 0 else "LOSE"
        else:
            actual = "WIN" if margin < 0 else "LOSE"
        hit = prediction == actual
        return ("HIT" if hit else "MISS"), (90.91 if hit else -100.0)

    elif bet_type == "spread":
        if bet_side == "home":
            diff = margin - (-line)
        else:
            diff = (-margin) - line
        if diff == 0:
            return "PUSH", 0.0
        hit = diff > 0
        actual = "WIN" if hit else "LOSE"
        return ("HIT" if prediction == actual else "MISS"), (90.91 if prediction == actual else -100.0)

    elif bet_type == "total":
        if total == line:
            return "PUSH", 0.0
        actual = "OVER" if total > line else "UNDER"
        hit = prediction == actual
        return ("HIT" if hit else "MISS"), (90.91 if hit else -100.0)

    return "MISS", -100.0


# ── Strategy Functions ───────────────────────────────────────────────────────

def run_baseline_strategy(df: pd.DataFrame, sport: str,
                          predictor: GameStatisticalPredictor) -> StrategyResult:
    """Strategy 1: Bet everything the model says (no filter)."""
    result = StrategyResult(
        name="Baseline (All Bets)",
        description="Bet every prediction the model generates",
    )

    for _, row in df.iterrows():
        features = {k: v for k, v in row.items()
                    if k.startswith("gf_") and pd.notna(v)}
        preds = predictor.predict_game(features)

        for p in preds:
            outcome, profit = grade_bet(
                p.bet_type, p.bet_side, p.line,
                p.prediction, row["margin"], row["total"]
            )
            bet = BetResult(
                game_date=row["game_date"], home_team=row["home_team"],
                away_team=row["away_team"], bet_type=p.bet_type,
                bet_side=p.bet_side, line=p.line, prediction=p.prediction,
                probability=p.probability, edge=p.edge, outcome=outcome,
                profit=profit, strategy="baseline",
            )
            result.bets.append(bet)
            if outcome == "HIT":
                result.wins += 1
                result.profit += profit
            elif outcome == "MISS":
                result.losses += 1
                result.profit += profit
            else:
                result.pushes += 1
            result.total_bets += 1

    result.calculate()
    return result


def run_sharp_only_strategy(df: pd.DataFrame, sport: str,
                             predictor: GameStatisticalPredictor) -> StrategyResult:
    """Strategy 2: Only bet SHARP tier (edge >= 5%, prob >= 58%)."""
    result = StrategyResult(
        name="SHARP Only",
        description="Only bet when edge >= 5% AND probability >= 58%",
    )

    for _, row in df.iterrows():
        features = {k: v for k, v in row.items()
                    if k.startswith("gf_") and pd.notna(v)}
        preds = predictor.predict_game(features)

        for p in preds:
            if p.confidence_tier != "SHARP":
                continue

            outcome, profit = grade_bet(
                p.bet_type, p.bet_side, p.line,
                p.prediction, row["margin"], row["total"]
            )
            bet = BetResult(
                game_date=row["game_date"], home_team=row["home_team"],
                away_team=row["away_team"], bet_type=p.bet_type,
                bet_side=p.bet_side, line=p.line, prediction=p.prediction,
                probability=p.probability, edge=p.edge, outcome=outcome,
                profit=profit, strategy="sharp_only",
            )
            result.bets.append(bet)
            if outcome == "HIT":
                result.wins += 1
            elif outcome == "MISS":
                result.losses += 1
            else:
                result.pushes += 1
            result.profit += profit
            result.total_bets += 1

    result.calculate()
    return result


def run_high_prob_strategy(df: pd.DataFrame, sport: str,
                            predictor: GameStatisticalPredictor,
                            min_prob: float = 0.62) -> StrategyResult:
    """Strategy 3: High probability filter (prob >= threshold)."""
    result = StrategyResult(
        name=f"High Prob (>={min_prob:.0%})",
        description=f"Only bet when model probability >= {min_prob:.0%}",
    )

    for _, row in df.iterrows():
        features = {k: v for k, v in row.items()
                    if k.startswith("gf_") and pd.notna(v)}
        preds = predictor.predict_game(features)

        for p in preds:
            if p.probability < min_prob:
                continue
            # Skip the complementary side (avoid betting both sides)
            if p.bet_side in ("away", "under"):
                continue

            outcome, profit = grade_bet(
                p.bet_type, p.bet_side, p.line,
                p.prediction, row["margin"], row["total"]
            )
            bet = BetResult(
                game_date=row["game_date"], home_team=row["home_team"],
                away_team=row["away_team"], bet_type=p.bet_type,
                bet_side=p.bet_side, line=p.line, prediction=p.prediction,
                probability=p.probability, edge=p.edge, outcome=outcome,
                profit=profit, strategy=f"high_prob_{min_prob}",
            )
            result.bets.append(bet)
            if outcome == "HIT":
                result.wins += 1
            elif outcome == "MISS":
                result.losses += 1
            else:
                result.pushes += 1
            result.profit += profit
            result.total_bets += 1

    result.calculate()
    return result


def run_home_underdog_strategy(df: pd.DataFrame, sport: str,
                                predictor: GameStatisticalPredictor) -> StrategyResult:
    """Strategy 4: Bet home underdogs with rest advantage.
    Home underdogs with 2+ days rest vs away team on B2B is historically profitable."""
    result = StrategyResult(
        name="Home Underdog + Rest",
        description="Home underdogs (implied prob < 45%) with rest advantage",
    )

    for _, row in df.iterrows():
        features = {k: v for k, v in row.items()
                    if k.startswith("gf_") and pd.notna(v)}

        # Home underdog: implied prob < 45%
        implied = features.get("gf_home_implied_prob", 0.5)
        if implied >= 0.45:
            continue

        # Rest advantage
        rest_adv = features.get("gf_rest_advantage", 0)
        away_b2b = features.get("gf_away_b2b", 0)
        if rest_adv <= 0 and not away_b2b:
            continue

        # Bet home ML
        outcome, profit = grade_bet(
            "moneyline", "home", None,
            "WIN", row["margin"], row["total"]
        )

        # Underdog payout is better than -110
        if implied < 0.5 and outcome == "HIT":
            # Calculate underdog payout
            profit = (1 - implied) / implied * 100  # e.g., 35% implied -> +185.7

        bet = BetResult(
            game_date=row["game_date"], home_team=row["home_team"],
            away_team=row["away_team"], bet_type="moneyline",
            bet_side="home", line=None, prediction="WIN",
            probability=1 - implied, edge=0.0, outcome=outcome,
            profit=profit, strategy="home_underdog_rest",
        )
        result.bets.append(bet)
        if outcome == "HIT":
            result.wins += 1
        elif outcome == "MISS":
            result.losses += 1
        else:
            result.pushes += 1
        result.profit += profit
        result.total_bets += 1

    result.calculate()
    return result


def run_fatigue_fade_strategy(df: pd.DataFrame, sport: str,
                               predictor: GameStatisticalPredictor) -> StrategyResult:
    """Strategy 5: Fade tired teams (B2B, 3-in-4, heavy travel).
    Bet against teams on back-to-backs or 3-in-4 when opponent is rested."""
    result = StrategyResult(
        name="Fatigue Fade",
        description="Bet against B2B/3-in-4 teams when opponent is rested (2+ days)",
    )

    for _, row in df.iterrows():
        features = {k: v for k, v in row.items()
                    if k.startswith("gf_") and pd.notna(v)}

        home_b2b = features.get("gf_home_b2b", 0)
        away_b2b = features.get("gf_away_b2b", 0)
        home_3in4 = features.get("gf_home_3in4", 0)
        away_3in4 = features.get("gf_away_3in4", 0)
        rest_adv = features.get("gf_rest_advantage", 0)

        # Away team fatigued, home rested
        if (away_b2b or away_3in4) and rest_adv >= 1:
            outcome, profit = grade_bet(
                "moneyline", "home", None,
                "WIN", row["margin"], row["total"]
            )
            bet = BetResult(
                game_date=row["game_date"], home_team=row["home_team"],
                away_team=row["away_team"], bet_type="moneyline",
                bet_side="home", line=None, prediction="WIN",
                probability=0.55, edge=0.05, outcome=outcome,
                profit=profit, strategy="fatigue_fade",
            )
            result.bets.append(bet)
            if outcome == "HIT":
                result.wins += 1
            elif outcome == "MISS":
                result.losses += 1
            result.profit += profit
            result.total_bets += 1

        # Home team fatigued, away rested
        elif (home_b2b or home_3in4) and rest_adv <= -1:
            outcome, profit = grade_bet(
                "moneyline", "away", None,
                "WIN", row["margin"], row["total"]
            )
            bet = BetResult(
                game_date=row["game_date"], home_team=row["home_team"],
                away_team=row["away_team"], bet_type="moneyline",
                bet_side="away", line=None, prediction="WIN",
                probability=0.55, edge=0.05, outcome=outcome,
                profit=profit, strategy="fatigue_fade",
            )
            result.bets.append(bet)
            if outcome == "HIT":
                result.wins += 1
            elif outcome == "MISS":
                result.losses += 1
            result.profit += profit
            result.total_bets += 1

    result.calculate()
    return result


def run_totals_weather_strategy(df: pd.DataFrame, sport: str,
                                 predictor: GameStatisticalPredictor) -> StrategyResult:
    """Strategy 6: Totals based on scoring trends.
    Bet under when both teams are low-scoring, over when both are high."""
    result = StrategyResult(
        name="Scoring Trend Totals",
        description="Over when both teams score high, under when both score low",
    )

    for _, row in df.iterrows():
        features = {k: v for k, v in row.items()
                    if k.startswith("gf_") and pd.notna(v)}

        predicted_total = features.get("gf_predicted_total", 0)
        total_line = features.get("gf_total_line", 0)

        if not predicted_total or not total_line:
            continue

        diff = predicted_total - total_line

        # Only bet when model strongly disagrees with line
        if abs(diff) < 1.0:
            continue

        if diff > 0:
            bet_side = "over"
            prediction = "OVER"
        else:
            bet_side = "under"
            prediction = "UNDER"

        outcome, profit = grade_bet(
            "total", bet_side, total_line,
            prediction, row["margin"], row["total"]
        )
        bet = BetResult(
            game_date=row["game_date"], home_team=row["home_team"],
            away_team=row["away_team"], bet_type="total",
            bet_side=bet_side, line=total_line, prediction=prediction,
            probability=0.55, edge=abs(diff)/total_line, outcome=outcome,
            profit=profit, strategy="scoring_trend_totals",
        )
        result.bets.append(bet)
        if outcome == "HIT":
            result.wins += 1
        elif outcome == "MISS":
            result.losses += 1
        result.profit += profit
        result.total_bets += 1

    result.calculate()
    return result


def run_elo_divergence_strategy(df: pd.DataFrame, sport: str,
                                 predictor: GameStatisticalPredictor) -> StrategyResult:
    """Strategy 7: Bet when Elo strongly disagrees with betting line.
    When Elo says one thing and the market says another, trust Elo."""
    result = StrategyResult(
        name="Elo vs Market Divergence",
        description="Bet when Elo win prob diverges from implied prob by 10%+",
    )

    for _, row in df.iterrows():
        features = {k: v for k, v in row.items()
                    if k.startswith("gf_") and pd.notna(v)}

        elo_prob = features.get("gf_elo_home_prob", 0.5)
        implied = features.get("gf_home_implied_prob", 0.5)

        divergence = elo_prob - implied

        # Only bet when Elo strongly disagrees (10%+ divergence)
        if abs(divergence) < 0.10:
            continue

        if divergence > 0:
            # Elo says home is better than market thinks
            bet_side = "home"
        else:
            # Elo says away is better
            bet_side = "away"

        outcome, profit = grade_bet(
            "moneyline", bet_side, None,
            "WIN", row["margin"], row["total"]
        )
        bet = BetResult(
            game_date=row["game_date"], home_team=row["home_team"],
            away_team=row["away_team"], bet_type="moneyline",
            bet_side=bet_side, line=None, prediction="WIN",
            probability=abs(divergence) + 0.5, edge=abs(divergence),
            outcome=outcome, profit=profit, strategy="elo_divergence",
        )
        result.bets.append(bet)
        if outcome == "HIT":
            result.wins += 1
        elif outcome == "MISS":
            result.losses += 1
        result.profit += profit
        result.total_bets += 1

    result.calculate()
    return result


def run_kelly_strategy(df: pd.DataFrame, sport: str,
                        predictor: GameStatisticalPredictor) -> StrategyResult:
    """Strategy 8: Kelly Criterion sizing — only bet positive Kelly.
    Kelly = (bp - q) / b where b=payout, p=win prob, q=1-p.
    Positive Kelly means mathematical edge exists."""
    result = StrategyResult(
        name="Kelly Criterion Filter",
        description="Only bet when Kelly fraction > 0 (mathematical edge at -110)",
    )

    for _, row in df.iterrows():
        features = {k: v for k, v in row.items()
                    if k.startswith("gf_") and pd.notna(v)}
        preds = predictor.predict_game(features)

        for p in preds:
            # Skip complementary side
            if p.bet_side in ("away", "under"):
                continue

            # Kelly at -110: b = 0.9091, kelly = (0.9091*p - (1-p)) / 0.9091
            b = 0.9091
            kelly = (b * p.probability - (1 - p.probability)) / b

            if kelly <= 0:
                continue  # No mathematical edge

            outcome, profit = grade_bet(
                p.bet_type, p.bet_side, p.line,
                p.prediction, row["margin"], row["total"]
            )
            bet = BetResult(
                game_date=row["game_date"], home_team=row["home_team"],
                away_team=row["away_team"], bet_type=p.bet_type,
                bet_side=p.bet_side, line=p.line, prediction=p.prediction,
                probability=p.probability, edge=p.edge, outcome=outcome,
                profit=profit, strategy="kelly",
            )
            result.bets.append(bet)
            if outcome == "HIT":
                result.wins += 1
            elif outcome == "MISS":
                result.losses += 1
            result.profit += profit
            result.total_bets += 1

    result.calculate()
    return result


def run_moneyline_only_strategy(df: pd.DataFrame, sport: str,
                                 predictor: GameStatisticalPredictor,
                                 min_prob: float = 0.58) -> StrategyResult:
    """Strategy 9: Moneyline only with probability threshold.
    Moneylines are the simplest bet — just pick the winner."""
    result = StrategyResult(
        name=f"ML Only (>={min_prob:.0%})",
        description=f"Moneyline bets only when prob >= {min_prob:.0%}",
    )

    for _, row in df.iterrows():
        features = {k: v for k, v in row.items()
                    if k.startswith("gf_") and pd.notna(v)}
        preds = predictor.predict_game(features)

        for p in preds:
            if p.bet_type != "moneyline":
                continue
            if p.bet_side == "away":
                continue
            if p.probability < min_prob:
                continue

            # Determine which side to bet
            if p.probability >= min_prob:
                side = "home"
                pred = "WIN"
            else:
                continue

            outcome, profit = grade_bet(
                "moneyline", side, None,
                pred, row["margin"], row["total"]
            )
            bet = BetResult(
                game_date=row["game_date"], home_team=row["home_team"],
                away_team=row["away_team"], bet_type="moneyline",
                bet_side=side, line=None, prediction=pred,
                probability=p.probability, edge=p.edge, outcome=outcome,
                profit=profit, strategy=f"ml_only_{min_prob}",
            )
            result.bets.append(bet)
            if outcome == "HIT":
                result.wins += 1
            elif outcome == "MISS":
                result.losses += 1
            result.profit += profit
            result.total_bets += 1

    result.calculate()
    return result


def run_under_bias_strategy(df: pd.DataFrame, sport: str,
                             predictor: GameStatisticalPredictor) -> StrategyResult:
    """Strategy 10: Under bias — historically unders hit more in certain sports.
    Bet under when model agrees AND total line is above league average."""
    params = {"nhl": 6.0, "nba": 224.0, "mlb": 9.0}
    avg_total = params.get(sport, 6.0)

    result = StrategyResult(
        name="Under Bias",
        description=f"Bet under when line > league avg ({avg_total}) and model agrees",
    )

    for _, row in df.iterrows():
        features = {k: v for k, v in row.items()
                    if k.startswith("gf_") and pd.notna(v)}

        total_line = features.get("gf_total_line", 0)
        predicted_total = features.get("gf_predicted_total", avg_total)

        if not total_line:
            continue

        # Line is above average AND model predicts under
        if total_line <= avg_total:
            continue
        if predicted_total >= total_line:
            continue

        outcome, profit = grade_bet(
            "total", "under", total_line,
            "UNDER", row["margin"], row["total"]
        )
        bet = BetResult(
            game_date=row["game_date"], home_team=row["home_team"],
            away_team=row["away_team"], bet_type="total",
            bet_side="under", line=total_line, prediction="UNDER",
            probability=0.55, edge=0.05, outcome=outcome,
            profit=profit, strategy="under_bias",
        )
        result.bets.append(bet)
        if outcome == "HIT":
            result.wins += 1
        elif outcome == "MISS":
            result.losses += 1
        result.profit += profit
        result.total_bets += 1

    result.calculate()
    return result


# ── Main Runner ──────────────────────────────────────────────────────────────

def backtest_sport(sport: str, detailed: bool = False) -> List[StrategyResult]:
    """Run all strategies against historical data for a sport."""
    print(f"\n{'='*70}")
    print(f"  BACKTESTING {sport.upper()} GAME STRATEGIES")
    print(f"{'='*70}")

    df = load_historical_games(sport)
    if df.empty:
        print(f"  No historical data for {sport}")
        return []

    print(f"  Games loaded: {len(df)}")
    print(f"  Date range:   {df['game_date'].min()} to {df['game_date'].max()}")
    print(f"  Home win rate: {df['home_win'].mean():.1%}")
    print(f"  Avg margin:   {df['margin'].mean():+.1f}")
    print(f"  Avg total:    {df['total'].mean():.1f}")

    predictor = GameStatisticalPredictor(sport)

    # Run all strategies
    strategies = []

    print(f"\n  Running strategies...")

    s = run_baseline_strategy(df, sport, predictor)
    strategies.append(s)
    print(f"    [1/10] {s.name}: {s.accuracy:.1f}% ({s.wins}W-{s.losses}L) P&L: ${s.profit:+,.0f}")

    s = run_sharp_only_strategy(df, sport, predictor)
    strategies.append(s)
    print(f"    [2/10] {s.name}: {s.accuracy:.1f}% ({s.wins}W-{s.losses}L) P&L: ${s.profit:+,.0f}")

    for prob_thresh in [0.58, 0.62, 0.65]:
        s = run_high_prob_strategy(df, sport, predictor, min_prob=prob_thresh)
        strategies.append(s)
        print(f"    [3/10] {s.name}: {s.accuracy:.1f}% ({s.wins}W-{s.losses}L) P&L: ${s.profit:+,.0f}")

    s = run_home_underdog_strategy(df, sport, predictor)
    strategies.append(s)
    print(f"    [4/10] {s.name}: {s.accuracy:.1f}% ({s.wins}W-{s.losses}L) P&L: ${s.profit:+,.0f}")

    s = run_fatigue_fade_strategy(df, sport, predictor)
    strategies.append(s)
    print(f"    [5/10] {s.name}: {s.accuracy:.1f}% ({s.wins}W-{s.losses}L) P&L: ${s.profit:+,.0f}")

    s = run_totals_weather_strategy(df, sport, predictor)
    strategies.append(s)
    print(f"    [6/10] {s.name}: {s.accuracy:.1f}% ({s.wins}W-{s.losses}L) P&L: ${s.profit:+,.0f}")

    s = run_elo_divergence_strategy(df, sport, predictor)
    strategies.append(s)
    print(f"    [7/10] {s.name}: {s.accuracy:.1f}% ({s.wins}W-{s.losses}L) P&L: ${s.profit:+,.0f}")

    s = run_kelly_strategy(df, sport, predictor)
    strategies.append(s)
    print(f"    [8/10] {s.name}: {s.accuracy:.1f}% ({s.wins}W-{s.losses}L) P&L: ${s.profit:+,.0f}")

    for prob_thresh in [0.55, 0.58, 0.62]:
        s = run_moneyline_only_strategy(df, sport, predictor, min_prob=prob_thresh)
        strategies.append(s)
        print(f"    [9/10] {s.name}: {s.accuracy:.1f}% ({s.wins}W-{s.losses}L) P&L: ${s.profit:+,.0f}")

    s = run_under_bias_strategy(df, sport, predictor)
    strategies.append(s)
    print(f"    [10/10] {s.name}: {s.accuracy:.1f}% ({s.wins}W-{s.losses}L) P&L: ${s.profit:+,.0f}")

    # ── Results Summary ──────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  {sport.upper()} BACKTEST RESULTS — Ranked by ROI")
    print(f"{'='*70}")
    print(f"  {'Strategy':<30} {'Bets':>5} {'W-L':>8} {'Acc':>6} {'ROI':>7} {'P&L':>10} {'MaxDD':>8}")
    print(f"  {'-'*70}")

    # Sort by ROI
    ranked = sorted(strategies, key=lambda x: x.roi, reverse=True)
    for s in ranked:
        if s.total_bets == 0:
            continue
        wl = f"{s.wins}-{s.losses}"
        roi_color = "+" if s.roi > 0 else ""
        print(f"  {s.name:<30} {s.total_bets:>5} {wl:>8} {s.accuracy:>5.1f}% "
              f"{roi_color}{s.roi:>5.1f}% ${s.profit:>+9,.0f} ${s.max_drawdown:>7,.0f}")

    # Highlight profitable strategies
    profitable = [s for s in ranked if s.roi > 0 and s.total_bets >= 10]
    if profitable:
        print(f"\n  PROFITABLE STRATEGIES ({len(profitable)}):")
        for s in profitable:
            print(f"    -> {s.name}: {s.roi:+.1f}% ROI, {s.accuracy:.1f}% acc, "
                  f"{s.total_bets} bets, ${s.profit:+,.0f}")
    else:
        print(f"\n  No strategy with 10+ bets was profitable.")
        # Show least unprofitable
        least_bad = [s for s in ranked if s.total_bets >= 10][:3]
        if least_bad:
            print(f"  Closest to profitable:")
            for s in least_bad:
                print(f"    -> {s.name}: {s.roi:+.1f}% ROI, {s.accuracy:.1f}% acc")

    if detailed:
        print(f"\n  --- Detailed Bet Log (Top Strategy) ---")
        if ranked and ranked[0].bets:
            top = ranked[0]
            print(f"  Strategy: {top.name}")
            for b in top.bets[:30]:
                print(f"    {b.game_date} {b.away_team}@{b.home_team} "
                      f"{b.bet_type} {b.bet_side} -> {b.outcome} "
                      f"${b.profit:+.0f} (prob={b.probability:.1%})")

    return strategies


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest Game Strategies")
    parser.add_argument("--sport", choices=["nhl", "nba", "mlb", "all"],
                        default="all")
    parser.add_argument("--detailed", action="store_true",
                        help="Show individual bet details for top strategy")
    args = parser.parse_args()

    sports = ["nhl", "nba", "mlb"] if args.sport == "all" else [args.sport]

    all_results = {}
    for sport in sports:
        results = backtest_sport(sport, detailed=args.detailed)
        all_results[sport] = results

    # Cross-sport comparison
    if len(all_results) > 1:
        print(f"\n{'='*70}")
        print(f"  CROSS-SPORT STRATEGY COMPARISON")
        print(f"{'='*70}")
        for sport, results in all_results.items():
            profitable = [s for s in results if s.roi > 0 and s.total_bets >= 5]
            print(f"\n  {sport.upper()}: {len(profitable)} profitable strategies")
            for s in profitable[:3]:
                print(f"    {s.name}: {s.roi:+.1f}% ROI ({s.wins}W-{s.losses}L)")
