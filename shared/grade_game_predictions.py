"""
Grade Game Predictions — Shared grading logic for all sports.

Compares game predictions against actual final scores to determine
HIT/MISS outcomes. Used by each sport's grade_game_predictions.py script.

Flow:
    1. Load ungraded predictions for a given date
    2. Fetch final scores from the games table
    3. Determine outcome for each bet type (moneyline/spread/total)
    4. Save to game_prediction_outcomes table
    5. Print accuracy summary

Usage:
    from shared.grade_game_predictions import GamePredictionGrader

    grader = GamePredictionGrader(sport="nhl", db_path="nhl/database/...")
    results = grader.grade_date("2026-03-24")
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class GamePredictionGrader:
    """Grade game predictions against final scores."""

    def __init__(self, sport: str, db_path: str):
        self.sport = sport.lower()
        self.db_path = db_path

    def grade_date(self, game_date: str, force: bool = False) -> Dict:
        """
        Grade all predictions for a given date.

        Args:
            game_date: Date to grade (YYYY-MM-DD)
            force: Re-grade even if outcomes exist

        Returns:
            Summary dict with counts and accuracy
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get predictions for this date
        if force:
            # Delete existing outcomes first, then re-grade all
            conn.execute("""
                DELETE FROM game_prediction_outcomes
                WHERE game_date = ?
            """, (game_date,))
            conn.commit()

            predictions = conn.execute("""
                SELECT * FROM game_predictions
                WHERE game_date = ?
            """, (game_date,)).fetchall()
        else:
            # Only get predictions that haven't been graded yet
            predictions = conn.execute("""
                SELECT gp.* FROM game_predictions gp
                LEFT JOIN game_prediction_outcomes gpo
                    ON gp.id = gpo.prediction_id
                WHERE gp.game_date = ?
                  AND gpo.id IS NULL
            """, (game_date,)).fetchall()

        if not predictions:
            conn.close()
            return {
                "graded": 0,
                "message": f"No ungraded predictions for {game_date}",
            }

        # Get final scores
        scores = self._get_final_scores(conn, game_date)

        if not scores:
            conn.close()
            return {
                "graded": 0,
                "message": f"No final scores available for {game_date}",
            }

        # Grade each prediction
        graded = 0
        hits = 0
        misses = 0
        pushes = 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for pred in predictions:
            home = pred["home_team"]
            away = pred["away_team"]
            pred_id = pred["id"]

            # Find matching score
            score_key = f"{home}_vs_{away}"
            if score_key not in scores:
                continue

            score = scores[score_key]
            home_score = score["home_score"]
            away_score = score["away_score"]
            margin = home_score - away_score  # Positive = home won
            total_score = home_score + away_score

            # Determine outcome
            outcome = self._grade_prediction(
                pred["bet_type"],
                pred["bet_side"],
                pred["line"],
                pred["prediction"],
                margin,
                total_score,
            )

            if outcome == "HIT":
                hits += 1
            elif outcome == "MISS":
                misses += 1
            else:
                pushes += 1

            # Calculate profit (flat $100 unit)
            profit = 0.0
            odds = pred["odds_american"]
            if outcome == "HIT" and odds:
                if odds > 0:
                    # Plus odds: +150 means you bet 100 to win 150
                    profit = float(odds)
                else:
                    # Minus odds: -110 means you bet 110 to win 100.
                    # Normalized to a $100 base bet:
                    # Profit = 100 / (abs(odds) / 100)
                    profit = 100.0 / (abs(odds) / 100.0)
            elif outcome == "MISS":
                # Standard $100 unit loss. 
                # Note: Technically minus odds risk more than $100 to win $100,
                # but for simplicity in tracking P&L we often use $100 risked.
                # Here we stick to "To Win $100" logic for minus odds.
                profit = -100.0
            # PUSH = 0

            # Save to outcomes table (uses prediction_id FK)
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO game_prediction_outcomes
                    (prediction_id, game_date,
                     bet_type, bet_side, line,
                     prediction, home_score, away_score,
                     actual_margin, actual_total,
                     outcome, model_version, confidence_tier,
                     odds_american, profit, graded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pred_id, pred["game_date"],
                    pred["bet_type"], pred["bet_side"], pred["line"],
                    pred["prediction"], home_score, away_score,
                    margin, total_score,
                    outcome, pred["model_version"], pred["confidence_tier"],
                    odds, round(profit, 2), now,
                ))
                graded += 1
            except Exception as e:
                print(f"  [WARN] Could not save outcome: {e}")

        conn.commit()
        conn.close()

        # Summary
        total = hits + misses
        accuracy = hits / total * 100 if total > 0 else 0

        return {
            "graded": graded,
            "hits": hits,
            "misses": misses,
            "pushes": pushes,
            "accuracy": round(accuracy, 1),
            "game_date": game_date,
        }

    def _save_closing_odds(self, conn, game_date: str, odds_list: List[Dict]):
        """Save closing odds to the game_predictions table for CLV analysis."""
        for odds in odds_list:
            home = odds["home_team"]
            away = odds["away_team"]
            
            # Update closing line/odds for this game's predictions
            # Note: We update ALL predictions for this game (ML, Spread, Total)
            # The closing_line we save depends on the bet_type.
            
            # 1. Update Moneyline closing odds
            conn.execute("""
                UPDATE game_predictions
                SET closing_odds_american = CASE 
                    WHEN bet_side = 'home' THEN ? 
                    ELSE ? 
                END
                WHERE game_date = ? AND home_team = ? AND away_team = ? AND bet_type = 'moneyline'
            """, (odds.get("home_ml"), odds.get("away_ml"), game_date, home, away))

            # 2. Update Spread closing line
            conn.execute("""
                UPDATE game_predictions
                SET closing_line = ?,
                    closing_odds_american = -110 -- Standard spread juice if not provided
                WHERE game_date = ? AND home_team = ? AND away_team = ? AND bet_type = 'spread'
            """, (odds.get("spread"), game_date, home, away))

            # 3. Update Total closing line
            conn.execute("""
                UPDATE game_predictions
                SET closing_line = ?,
                    closing_odds_american = -110 -- Standard total juice if not provided
                WHERE game_date = ? AND home_team = ? AND away_team = ? AND bet_type = 'total'
            """, (odds.get("over_under"), game_date, home, away))

        conn.commit()

    def _get_final_scores(self, conn, game_date: str) -> Dict:
        """
        Get final scores for all games on a date.

        Returns dict keyed by "{home}_vs_{away}" with home_score, away_score.
        """
        scores = {}

        # Try games table first
        try:
            games = conn.execute("""
                SELECT home_team, away_team, home_score, away_score
                FROM games
                WHERE game_date = ?
                  AND home_score IS NOT NULL
                  AND away_score IS NOT NULL
            """, (game_date,)).fetchall()

            for g in games:
                key = f"{g['home_team']}_vs_{g['away_team']}"
                scores[key] = {
                    "home_score": g["home_score"],
                    "away_score": g["away_score"],
                }
        except Exception:
            pass

        # Also check game_context table (MLB)
        if not scores:
            try:
                games = conn.execute("""
                    SELECT home_team, away_team, home_score, away_score
                    FROM game_context
                    WHERE game_date = ?
                      AND home_score IS NOT NULL
                      AND away_score IS NOT NULL
                """, (game_date,)).fetchall()

                for g in games:
                    key = f"{g['home_team']}_vs_{g['away_team']}"
                    scores[key] = {
                        "home_score": g["home_score"],
                        "away_score": g["away_score"],
                    }
            except Exception:
                pass

        return scores

    def _grade_prediction(self, bet_type: str, bet_side: str,
                          line: float, prediction: str,
                          margin: int, total_score: int) -> str:
        """
        Grade a single prediction.

        Returns 'HIT', 'MISS', or 'PUSH'
        """
        if bet_type == "moneyline":
            if margin == 0:
                return "PUSH"
            if bet_side == "home":
                actual = "WIN" if margin > 0 else "LOSE"
            else:
                actual = "WIN" if margin < 0 else "LOSE"
            return "HIT" if prediction == actual else "MISS"

        elif bet_type == "spread":
            if line is None:
                return "MISS"
            if bet_side == "home":
                covers = margin > (-line)
                pushes = margin == (-line)
            else:
                covers = margin < line
                pushes = margin == line
            if pushes:
                return "PUSH"
            actual = "WIN" if covers else "LOSE"
            return "HIT" if prediction == actual else "MISS"

        elif bet_type == "total":
            if line is None:
                return "MISS"
            if total_score == line:
                return "PUSH"
            actual = "OVER" if total_score > line else "UNDER"
            return "HIT" if prediction == actual else "MISS"

        return "MISS"

    def get_performance_summary(self, days: int = 30) -> Dict:
        """Get accuracy summary over recent days."""
        conn = sqlite3.connect(self.db_path)

        rows = conn.execute("""
            SELECT bet_type, confidence_tier, outcome,
                   COUNT(*) as cnt
            FROM game_prediction_outcomes
            WHERE graded_at >= date('now', ?)
              AND outcome IN ('HIT', 'MISS')
            GROUP BY bet_type, confidence_tier, outcome
        """, (f"-{days} days",)).fetchall()

        conn.close()

        summary = {}
        for row in rows:
            bt = row[0]
            tier = row[1]
            outcome = row[2]
            cnt = row[3]

            key = f"{bt}_{tier}"
            if key not in summary:
                summary[key] = {"hits": 0, "misses": 0}

            if outcome == "HIT":
                summary[key]["hits"] = cnt
            else:
                summary[key]["misses"] = cnt

        for key, v in summary.items():
            total = v["hits"] + v["misses"]
            v["total"] = total
            v["accuracy"] = round(v["hits"] / total * 100, 1) if total > 0 else 0

        return summary
