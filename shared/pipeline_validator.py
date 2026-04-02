"""
Pipeline Completion Validator
==============================
Verifies that prediction/grading pipelines produced expected outputs.

Usage:
    from pipeline_validator import validate_predictions, validate_grading

    success, msg = validate_predictions("nba", "2026-03-26")
    if not success:
        logger.error(msg)
        send_alert(msg)
"""

import sqlite3
from datetime import datetime
from pathlib import Path

# Database paths
_DB_PATHS = {
    "nhl": str(Path(__file__).parent.parent / "nhl" / "database" / "nhl_predictions_v2.db"),
    "nba": str(Path(__file__).parent.parent / "nba" / "database" / "nba_predictions.db"),
    "mlb": str(Path(__file__).parent.parent / "mlb" / "database" / "mlb_predictions.db"),
}

# Minimum expected predictions per sport (sanity check)
_MIN_PREDICTIONS = {
    "nhl": 15,   # At least 15 player props if any games
    "nba": 20,   # At least 20 if games exist
    "mlb": 20,
}


def validate_predictions(sport: str, game_date: str) -> tuple:
    """
    Validate that predictions were generated for a date.

    Returns:
        (success: bool, message: str)
    """
    db_path = _DB_PATHS.get(sport)
    if not db_path or not Path(db_path).exists():
        return (False, f"Database not found: {db_path}")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM predictions WHERE game_date = ?",
            (game_date,)
        )
        count = cursor.fetchone()[0]
        conn.close()

        min_expected = _MIN_PREDICTIONS.get(sport, 10)

        if count == 0:
            return (False, f"[{sport.upper()}] ZERO predictions for {game_date} — pipeline may have failed")
        elif count < min_expected:
            return (False, f"[{sport.upper()}] Only {count} predictions for {game_date} (expected >= {min_expected}) — partial failure?")
        else:
            return (True, f"[{sport.upper()}] {count} predictions for {game_date} — OK")

    except Exception as e:
        return (False, f"[{sport.upper()}] Validation error: {e}")


def validate_grading(sport: str, game_date: str) -> tuple:
    """
    Validate that grading completed for a date.

    Returns:
        (success: bool, message: str, stats: dict)
    """
    db_path = _DB_PATHS.get(sport)
    if not db_path or not Path(db_path).exists():
        return (False, f"Database not found: {db_path}", {})

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check prediction_outcomes table
        cursor.execute(
            "SELECT COUNT(*), SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) FROM prediction_outcomes WHERE game_date = ?",
            (game_date,)
        )
        row = cursor.fetchone()
        graded = row[0] or 0
        hits = row[1] or 0

        # Check how many predictions exist for this date
        cursor.execute(
            "SELECT COUNT(*) FROM predictions WHERE game_date = ?",
            (game_date,)
        )
        total_preds = cursor.fetchone()[0]

        conn.close()

        stats = {
            "total_predictions": total_preds,
            "graded": graded,
            "hits": hits,
            "accuracy": round(hits / graded * 100, 1) if graded > 0 else 0,
            "grade_rate": round(graded / total_preds * 100, 1) if total_preds > 0 else 0,
        }

        if total_preds == 0:
            return (True, f"[{sport.upper()}] No predictions for {game_date} — nothing to grade", stats)
        elif graded == 0:
            return (False, f"[{sport.upper()}] {total_preds} predictions but ZERO graded for {game_date}", stats)
        elif stats["grade_rate"] < 50:
            return (False, f"[{sport.upper()}] Only {stats['grade_rate']}% graded ({graded}/{total_preds}) for {game_date}", stats)
        else:
            return (True, f"[{sport.upper()}] Graded {graded}/{total_preds} ({stats['grade_rate']}%), accuracy {stats['accuracy']}%", stats)

    except Exception as e:
        return (False, f"[{sport.upper()}] Grading validation error: {e}", {})


def daily_health_check() -> dict:
    """
    Run a comprehensive health check across all sports.

    Returns dict with status per sport.
    """
    from datetime import timedelta

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    results = {}
    for sport in ["nhl", "nba", "mlb"]:
        pred_ok, pred_msg = validate_predictions(sport, today)
        grade_ok, grade_msg, grade_stats = validate_grading(sport, yesterday)

        results[sport] = {
            "predictions_today": {"ok": pred_ok, "message": pred_msg},
            "grading_yesterday": {"ok": grade_ok, "message": grade_msg, "stats": grade_stats},
        }

    return results


if __name__ == "__main__":
    """Run health check from CLI."""
    results = daily_health_check()
    print("\n" + "=" * 60)
    print("  DAILY PIPELINE HEALTH CHECK")
    print("=" * 60)

    for sport, data in results.items():
        print(f"\n  {sport.upper()}:")
        pred = data["predictions_today"]
        grade = data["grading_yesterday"]

        status_p = "OK" if pred["ok"] else "FAIL"
        status_g = "OK" if grade["ok"] else "FAIL"

        print(f"    Predictions: [{status_p}] {pred['message']}")
        print(f"    Grading:     [{status_g}] {grade['message']}")

    print()
