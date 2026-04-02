"""
Golf Daily Prediction Generator
==================================

Generates OVER/UNDER predictions for PGA Tour round scoring and make-cut props.
This script is the golf equivalent of nba/scripts/generate_predictions_daily.py.

Pipeline:
  1. Check if a tournament is active today (skip if not)
  2. Get the active tournament and current round from ESPN API
  3. Fetch the player field (all competitors)
  4. For each player x prop_type x line:
     a. Extract player features (form, SG proxies, course history)
     b. Compute OVER/UNDER probability using statistical model
     c. Save prediction to database
  5. Print summary

Statistical model (Learning Mode):
  - round_score UNDER: P(score < line) from normal distribution
    centered on f_scoring_avg_l10_rounds with std f_scoring_std_l10_rounds
  - make_cut UNDER: logistic regression on f_made_cut_rate_l10 + f_world_ranking
    (simple linear combination until ML model is trained)
  - Probabilities are capped at PROBABILITY_CAP to prevent overconfidence

Usage:
    # Predict for today's round
    python generate_predictions_daily.py

    # Predict for a specific date (useful for backtesting)
    python generate_predictions_daily.py 2024-04-11

    # Force re-run even if predictions already exist
    python generate_predictions_daily.py 2024-04-11 --force
"""

import sys
import os
import json
import sqlite3
import argparse
import logging
from datetime import date, datetime
from pathlib import Path
from scipy.stats import norm

# Path setup
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
REPO_ROOT = PROJECT_ROOT.parent

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "features"))

from golf_config import (
    DB_PATH, CORE_PROPS, PROBABILITY_CAP, MIN_PREDICTION_CONFIDENCE,
    MIN_ROUNDS_FOR_PREDICTION, MAJOR_NAMES, DEFAULT_COURSE_PAR,
    has_active_tournament, init_database,
)
from espn_golf_api import ESPNGolfApi
from pga_stats_scraper import PGAStatsScraper
from player_feature_extractor import PlayerFeatureExtractor
from course_feature_extractor import CourseFeatureExtractor

logging.basicConfig(level=logging.INFO, format="[GOLF] %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ============================================================================
# Probability model
# ============================================================================

def compute_round_score_probability(line: float, features: dict) -> tuple[float, str]:
    """
    Compute P(score UNDER line) for a round_score prop.

    Uses a normal distribution centered on the player's recent scoring average
    with their scoring standard deviation.

    Returns:
        (probability_under, 'UNDER' or 'OVER')
    """
    mu  = features.get("f_scoring_avg_l10_rounds", 71.2)
    std = features.get("f_scoring_std_l10_rounds", 2.8)

    # Adjust mu using course difficulty
    course_diff = features.get("f_course_scoring_difficulty", 0.0)
    mu += course_diff * 0.5  # partial weight on course difficulty

    # Adjust for major (harder scoring conditions)
    if features.get("f_is_major", 0) == 1.0:
        mu += 0.5

    # Clamp std to reasonable range
    std = max(1.5, min(std, 5.0))

    # P(gross score < line) — UNDER means scoring better than the line
    # For round_score, UNDER means player shoots LOWER (better) than the line
    p_under = float(norm.cdf(line, loc=mu, scale=std))

    # Cap probability to prevent overconfidence
    p_under = min(p_under, PROBABILITY_CAP)
    p_under = max(p_under, 1.0 - PROBABILITY_CAP)

    prediction = "UNDER" if p_under >= 0.5 else "OVER"
    return p_under, prediction


def compute_make_cut_probability(line: float, features: dict) -> tuple[float, str]:
    """
    Compute P(player makes cut) for a make_cut prop.

    Simple weighted combination:
    - Recent cut rate (strongest signal)
    - World ranking (lower rank = better player)
    - Top-10 rate (activity and quality signal)

    Returns:
        (probability_under, 'UNDER' or 'OVER')
        UNDER means makes cut (score < 0.5 cut line = binary yes/no)
    """
    cut_rate   = features.get("f_made_cut_rate_l10", 0.65)
    top10_rate = features.get("f_top10_rate_l10", 0.15)
    ranking    = features.get("f_world_ranking", 200.0)

    # World ranking contribution: top 50 players make cut ~80% of the time
    ranking_factor = max(0.0, (300.0 - ranking) / 300.0) * 0.20

    # Weighted combination
    p_make_cut = (cut_rate * 0.60) + (top10_rate * 0.20) + ranking_factor + 0.10

    # Course history adjustment
    course_cut_rate = features.get("f_course_made_cut_rate", None)
    if course_cut_rate is not None and features.get("f_course_events_played", 0) >= 2:
        p_make_cut = (p_make_cut * 0.70) + (course_cut_rate * 0.30)

    # Cap
    p_make_cut = min(p_make_cut, PROBABILITY_CAP)
    p_make_cut = max(p_make_cut, 1.0 - PROBABILITY_CAP)

    prediction = "UNDER" if p_make_cut >= 0.5 else "OVER"
    return p_make_cut, prediction


# ============================================================================
# Prediction helpers
# ============================================================================

def already_predicted(conn, game_date: str, player_name: str, prop_type: str, line: float) -> bool:
    """Check if a prediction already exists for this player/prop/line/date."""
    row = conn.execute(
        """
        SELECT id FROM predictions
        WHERE game_date = ? AND player_name = ? AND prop_type = ? AND line = ?
        """,
        (game_date, player_name, prop_type, line),
    ).fetchone()
    return row is not None


def save_prediction(conn, game_date, player_name, tournament_name, prop_type,
                    line, prediction, probability, features, round_number):
    """Insert a prediction row into the database."""
    conn.execute(
        """
        INSERT INTO predictions
            (game_date, player_name, tournament_name, prop_type, line,
             prediction, probability, features_json, round_number, model_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_date, player_name, tournament_name, prop_type,
            line, prediction, probability,
            json.dumps(features), round_number, "statistical",
        ),
    )


def compute_days_rest(player_name: str, target_date: str, db_path: str) -> int:
    """Days since player's last tournament round."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT MAX(game_date) FROM player_round_logs
            WHERE player_name = ? AND game_date < ?
            """,
            (player_name, target_date),
        ).fetchone()
        if row and row[0]:
            last = date.fromisoformat(row[0])
            return (date.fromisoformat(target_date) - last).days
        return 7  # Default: assume 1 week rest
    finally:
        conn.close()


# ============================================================================
# Main pipeline
# ============================================================================

def run_predictions(target_date: str, force: bool = False):
    """
    Run the full golf prediction pipeline for target_date.

    Returns:
        dict: {'generated': int, 'skipped': int, 'tournament': str, 'round': int}
    """
    logger.info(f"Golf prediction pipeline — {target_date}")

    # Step 1: Check for active tournament
    if not has_active_tournament(target_date):
        logger.info(f"No PGA Tour tournament expected on {target_date}. Skipping.")
        return {"generated": 0, "skipped": 0, "tournament": None, "round": None}

    # Step 2: Get tournament info from ESPN
    api = ESPNGolfApi()
    event = api.get_tournament_by_date(target_date)
    if not event:
        logger.warning(f"ESPN returned no tournament for {target_date}. Skipping.")
        return {"generated": 0, "skipped": 0, "tournament": None, "round": None}

    tournament_name = event["name"]
    event_id        = event["event_id"]
    course_name     = event.get("course_name", "Unknown course")
    current_round   = event.get("current_round", 1)
    is_major        = any(m.lower() in tournament_name.lower() for m in MAJOR_NAMES)

    logger.info(f"Tournament: {tournament_name} | Course: {course_name} | Round {current_round}")

    # Step 3: Get player field
    leaderboard = api.get_leaderboard(event_id)
    if not leaderboard:
        logger.warning("Empty leaderboard from ESPN. Skipping.")
        return {"generated": 0, "skipped": 0, "tournament": tournament_name, "round": current_round}

    # Step 4: Initialize DB, extractors, scraper
    init_database()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    season = date.fromisoformat(target_date).year
    pga_scraper = PGAStatsScraper()
    player_extractor = PlayerFeatureExtractor(DB_PATH, pga_scraper)
    course_extractor = CourseFeatureExtractor(DB_PATH)

    # Field strength: average world ranking of players (rough proxy)
    field_rankings = [p.get("world_ranking") or 200 for p in leaderboard if isinstance(p, dict)]
    field_strength = sum(field_rankings) / max(len(field_rankings), 1)

    generated = 0
    skipped = 0

    try:
        for player in leaderboard:
            player_name = player.get("player_name", "")
            if not player_name:
                continue

            # Skip players who missed the cut for round 3+ predictions.
            # The cut is determined after Round 2; STATUS_CUT players have no
            # further rounds, so any round_score predictions for them would
            # never be gradeable and poison the training data.
            if current_round > 2 and player.get("made_cut") is False:
                skipped += 1
                continue

            # For make_cut prop, only generate before/at Round 2
            # (cut happens after Round 2 — no point predicting after it's determined)
            world_ranking = player.get("world_ranking")
            days_rest = compute_days_rest(player_name, target_date, DB_PATH)

            # Extract player features
            player_features = {}
            course_features = {}

            for prop_type, lines in CORE_PROPS.items():
                for line in lines:
                    # Skip make_cut if we're past Round 2
                    if prop_type == "make_cut" and current_round > 2:
                        continue

                    if not force and already_predicted(conn, target_date, player_name, prop_type, line):
                        skipped += 1
                        continue

                    # Extract features (cache per player to avoid repeated DB queries)
                    if not player_features:
                        player_features = player_extractor.extract(
                            player_name=player_name,
                            prop_type=prop_type,
                            line=line,
                            target_date=target_date,
                            round_number=current_round,
                            world_ranking=world_ranking,
                            season=season,
                            is_major=is_major,
                            days_rest=days_rest,
                            field_strength_avg_rank=field_strength,
                        )

                    if not course_features:
                        course_features = course_extractor.extract(
                            player_name=player_name,
                            tournament_id=event_id,
                            course_name=course_name,
                            target_date=target_date,
                            par=DEFAULT_COURSE_PAR,
                            player_scoring_avg=player_features.get("f_scoring_avg_l10_rounds"),
                        )

                    combined_features = {**player_features, **course_features}
                    combined_features["f_line"] = float(line)

                    # Compute probability
                    if prop_type == "round_score":
                        probability, prediction = compute_round_score_probability(line, combined_features)
                    elif prop_type == "make_cut":
                        probability, prediction = compute_make_cut_probability(line, combined_features)
                    else:
                        continue

                    # Skip low-confidence predictions
                    if probability < MIN_PREDICTION_CONFIDENCE and (1 - probability) < MIN_PREDICTION_CONFIDENCE:
                        skipped += 1
                        continue

                    save_prediction(
                        conn, target_date, player_name, tournament_name,
                        prop_type, line, prediction, probability,
                        combined_features,
                        current_round if prop_type == "round_score" else None,
                    )
                    generated += 1

        conn.commit()
    finally:
        conn.close()

    logger.info(
        f"Done — generated {generated} predictions, skipped {skipped} "
        f"| {tournament_name} Round {current_round}"
    )
    return {
        "generated": generated,
        "skipped": skipped,
        "tournament": tournament_name,
        "round": current_round,
    }


# ============================================================================
# Entry point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Generate golf round score predictions")
    parser.add_argument(
        "date",
        nargs="?",
        default=date.today().isoformat(),
        help="Target date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Re-generate predictions even if they already exist",
    )
    args = parser.parse_args()

    result = run_predictions(args.date, force=args.force)

    if result["tournament"]:
        print(f"\n[GOLF] {result['tournament']} — Round {result['round']}")
        print(f"  Predictions generated : {result['generated']}")
        print(f"  Skipped (existing)    : {result['skipped']}")
    else:
        print(f"\n[GOLF] No active tournament on {args.date}")


if __name__ == "__main__":
    main()
