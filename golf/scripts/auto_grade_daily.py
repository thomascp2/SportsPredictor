"""
Golf Auto-Grader
==================

Grades completed round score and make-cut predictions by fetching
actual results from the ESPN Golf API and comparing to stored predictions.

Grading logic:
  - round_score UNDER: HIT if actual_score < line, MISS if actual_score >= line
  - round_score OVER:  HIT if actual_score > line, MISS if actual_score <= line
  - make_cut UNDER:    HIT if player made the cut (made_cut = 1), MISS otherwise
  - make_cut OVER:     HIT if player missed the cut (made_cut = 0), MISS otherwise

Round-grading timing:
  - Rounds 1–3: grade the morning after the round completes (~8 AM)
  - Round 4 / make_cut: grade Sunday morning (cut was determined after Round 2;
    we grade make_cut on Saturday morning after the cut is official)

Usage:
    # Grade predictions for yesterday
    python auto_grade_daily.py

    # Grade a specific date
    python auto_grade_daily.py 2024-04-12
"""

import sys
import os
import sqlite3
import argparse
import logging
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from golf_config import DB_PATH, init_database
from espn_golf_api import ESPNGolfApi

logging.basicConfig(level=logging.INFO, format="[GOLF] %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ============================================================================
# Core grading functions
# ============================================================================

def grade_round_score(prediction: str, line: float, actual_score: int) -> str:
    """Grade a round_score prediction. Returns 'HIT' or 'MISS'."""
    if prediction == "UNDER":
        return "HIT" if actual_score < line else "MISS"
    else:  # OVER
        return "HIT" if actual_score > line else "MISS"


def grade_make_cut(prediction: str, made_cut: bool) -> str:
    """
    Grade a make_cut prediction.
    UNDER = player makes cut (survives to weekend).
    OVER  = player misses cut.
    """
    if prediction == "UNDER":
        return "HIT" if made_cut else "MISS"
    else:
        return "HIT" if not made_cut else "MISS"


# ============================================================================
# Main grading pipeline
# ============================================================================

def run_grading(target_date: str):
    """
    Grade all ungraded predictions for target_date.

    Fetches actual round scores from ESPN and grades each prediction.

    Returns:
        dict: {'graded': int, 'hits': int, 'misses': int, 'skipped': int}
    """
    logger.info(f"Golf grading pipeline — {target_date}")

    init_database()

    # Find ungraded predictions for this date
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # Ensure profit column exists (idempotent migration)
    try:
        conn.execute("ALTER TABLE prediction_outcomes ADD COLUMN profit REAL")
        conn.commit()
    except Exception:
        pass  # Column already exists

    try:
        ungraded = conn.execute(
            """
            SELECT p.id, p.player_name, p.prop_type, p.line,
                   p.prediction, p.round_number, p.tournament_name
            FROM predictions p
            LEFT JOIN prediction_outcomes o ON p.id = o.prediction_id
            WHERE p.game_date = ? AND o.id IS NULL
            """,
            (target_date,),
        ).fetchall()

        if not ungraded:
            logger.info(f"No ungraded predictions found for {target_date}")
            return {"graded": 0, "hits": 0, "misses": 0, "skipped": 0}

        logger.info(f"Found {len(ungraded)} ungraded predictions for {target_date}")

        # Group by round_number to minimize ESPN API calls
        rounds_needed = set()
        for pred in ungraded:
            if pred["round_number"]:
                rounds_needed.add(pred["round_number"])

        # Get the event for this date
        api = ESPNGolfApi()
        event = api.get_tournament_by_date(target_date)
        if not event:
            logger.warning(f"No ESPN tournament data found for {target_date}. Cannot grade.")
            return {"graded": 0, "hits": 0, "misses": 0, "skipped": len(ungraded)}

        event_id = event["event_id"]
        current_round = event.get("current_round", 0)
        logger.info(f"Grading against: {event['name']} (ID: {event_id}) | current_round={current_round}")

        # Fetch full leaderboard (has all rounds + cut status)
        leaderboard = api.get_leaderboard(event_id)
        if not leaderboard:
            logger.warning("Empty leaderboard — cannot grade.")
            return {"graded": 0, "hits": 0, "misses": 0, "skipped": len(ungraded)}

        # Build player lookup: player_name -> leaderboard entry
        player_lookup = {}
        for entry in leaderboard:
            name = entry.get("player_name", "")
            if name:
                player_lookup[name.lower()] = entry

        graded = 0
        hits = 0
        misses = 0
        skipped = 0

        for pred in ungraded:
            player_name = pred["player_name"]
            prop_type   = pred["prop_type"]
            line        = pred["line"]
            prediction  = pred["prediction"]
            round_num   = pred["round_number"]

            # Look up player in leaderboard
            entry = player_lookup.get(player_name.lower())
            if not entry:
                # Try last-name match
                last_name = player_name.split()[-1].lower()
                matches = [v for k, v in player_lookup.items() if k.split()[-1] == last_name]
                entry = matches[0] if len(matches) == 1 else None

            if not entry:
                logger.debug(f"Player not found in leaderboard: {player_name}")
                skipped += 1
                continue

            actual_value = None
            outcome = None

            if prop_type == "round_score":
                if round_num is None:
                    skipped += 1
                    continue
                # Find the specific round score
                round_data = next(
                    (r for r in entry.get("rounds", []) if r["round"] == round_num),
                    None,
                )
                if round_data is None or round_data.get("score") is None:
                    logger.debug(f"No score for {player_name} Round {round_num} (may still be playing)")
                    skipped += 1
                    continue
                actual_value = round_data["score"]
                # Guard against partial-round scores: ESPN sets status=STATUS_IN_PROGRESS
                # for players currently on the course and returns their live cumulative
                # hole-by-hole total as the round score (e.g. 35 after 9 holes).
                # Past rounds (round_num < current_round) are always final regardless
                # of player status, so we only apply this guard to the active round.
                player_status = entry.get("status", "")
                if player_status == "STATUS_IN_PROGRESS" and round_num == current_round:
                    logger.debug(
                        f"Skipping {player_name} R{round_num}: status=STATUS_IN_PROGRESS (round still live)"
                    )
                    skipped += 1
                    continue
                outcome = grade_round_score(prediction, line, actual_value)

            elif prop_type == "make_cut":
                made_cut = entry.get("made_cut")
                if made_cut is None:
                    logger.debug(f"Cut not yet determined for {player_name}")
                    skipped += 1
                    continue
                actual_value = 1.0 if made_cut else 0.0
                outcome = grade_make_cut(prediction, made_cut)

            else:
                skipped += 1
                continue

            # Save outcome
            profit = 90.91 if outcome == "HIT" else -100.0
            conn.execute(
                """
                INSERT INTO prediction_outcomes
                    (prediction_id, game_date, player_name, prop_type,
                     line, actual_value, prediction, outcome, profit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (pred["id"], target_date, player_name, prop_type,
                 line, actual_value, prediction, outcome, profit),
            )

            graded += 1
            if outcome == "HIT":
                hits += 1
            else:
                misses += 1

        # Backfill profit for any existing rows that are missing it
        conn.execute("""
            UPDATE prediction_outcomes
            SET profit = CASE outcome WHEN 'HIT' THEN 90.91 ELSE -100.0 END
            WHERE profit IS NULL AND outcome IN ('HIT', 'MISS')
        """)

        conn.commit()

        accuracy = hits / graded * 100 if graded > 0 else 0
        logger.info(
            f"Graded {graded} predictions: {hits} HIT, {misses} MISS "
            f"({accuracy:.1f}% accuracy) | {skipped} skipped"
        )
        return {"graded": graded, "hits": hits, "misses": misses, "skipped": skipped}

    finally:
        conn.close()


def also_store_round_logs(target_date: str):
    """
    Opportunistically save round scores to player_round_logs when grading.
    This keeps historical data current for ongoing predictions.
    """
    api = ESPNGolfApi()
    event = api.get_tournament_by_date(target_date)
    if not event:
        return

    leaderboard = api.get_leaderboard(event["event_id"])
    if not leaderboard:
        return

    current_round = event.get("current_round", 0)
    season = int(target_date[:4])
    conn = sqlite3.connect(DB_PATH)
    try:
        for entry in leaderboard:
            player_name = entry.get("player_name", "")
            if not player_name:
                continue
            player_status = entry.get("status", "")
            made_cut_val = 1 if entry.get("made_cut") is True else (0 if entry.get("made_cut") is False else None)
            for round_data in entry.get("rounds", []):
                round_num = round_data.get("round")
                score = round_data.get("score")
                if not round_num or score is None:
                    continue
                # Skip the current active round for players still on the course
                if player_status == "STATUS_IN_PROGRESS" and round_num == current_round:
                    continue
                # Compute approximate round date (Thu=R1, Fri=R2, Sat=R3, Sun=R4)
                from datetime import date as d_date
                event_start = d_date.fromisoformat(event["start_date"])
                round_date = (event_start + __import__("datetime").timedelta(days=round_num - 1)).isoformat()
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO player_round_logs
                            (player_name, tournament_name, tournament_id, course_name,
                             round_number, round_score, game_date, season, made_cut,
                             finish_position)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            player_name, event["name"], event["event_id"],
                            event.get("course_name", ""), round_num, score,
                            round_date, season,
                            made_cut_val if round_num >= 3 else None,
                            entry.get("position"),
                        ),
                    )
                except sqlite3.IntegrityError:
                    pass  # UNIQUE constraint — already exists
        conn.commit()
        logger.info(f"Round logs updated from {event['name']} leaderboard")
    finally:
        conn.close()


# ============================================================================
# Entry point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Grade completed golf round predictions")
    parser.add_argument(
        "date",
        nargs="?",
        default=(__import__("datetime").date.today() - __import__("datetime").timedelta(days=1)).isoformat(),
        help="Date to grade (YYYY-MM-DD). Defaults to yesterday.",
    )
    args = parser.parse_args()

    # Also update round logs during grading pass
    also_store_round_logs(args.date)

    result = run_grading(args.date)

    print(f"\n[GOLF] Grading results for {args.date}:")
    print(f"  Graded  : {result['graded']}")
    print(f"  Hits    : {result['hits']}")
    print(f"  Misses  : {result['misses']}")
    print(f"  Skipped : {result['skipped']}")
    if result["graded"] > 0:
        acc = result["hits"] / result["graded"] * 100
        print(f"  Accuracy: {acc:.1f}%")


if __name__ == "__main__":
    main()
