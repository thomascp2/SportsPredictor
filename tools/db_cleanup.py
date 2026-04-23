"""
Database Cleanup — Fix Data Contamination
==========================================
Fixes four known contamination issues in all sport DBs:

  1. Impossible combo: demon/goblin + UNDER  → outcome = VOID, flagged
  2. DNP inflation:    actual_value = 0      → outcome = VOID (was HIT/MISS)
  3. Profit backfill:  rows with NULL profit  → computed from odds_type
  4. Logic violations: OVER HIT but actual < line, UNDER HIT but actual > line → corrected

Safe to re-run — uses UPDATE, never DELETE.
Prints before/after counts per sport.

Usage:
    python tools/db_cleanup.py [--dry-run]
"""

from __future__ import annotations
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from shared.pp_rules_validator import correct_outcome

SPORTS = {
    "NHL": ROOT / "nhl" / "database" / "nhl_predictions_v2.db",
    "NBA": ROOT / "nba" / "database" / "nba_predictions.db",
    "MLB": ROOT / "mlb" / "database" / "mlb_predictions.db",
}

_SEP = "-" * 70


def _count(cursor: sqlite3.Cursor, sql: str, params: tuple = ()) -> int:
    cursor.execute(sql, params)
    return cursor.fetchone()[0]


def _fix_impossible_combos(cursor: sqlite3.Cursor, dry_run: bool) -> dict:
    """demon+UNDER and goblin+UNDER are impossible on PrizePicks."""
    before = _count(cursor, """
        SELECT COUNT(*) FROM prediction_outcomes
        WHERE LOWER(odds_type) IN ('demon','goblin')
          AND LOWER(prediction) = 'under'
          AND outcome NOT IN ('VOID','IMPOSSIBLE')
    """)
    if not dry_run and before:
        cursor.execute("""
            UPDATE prediction_outcomes
            SET outcome = 'VOID',
                data_quality_flag = 'IMPOSSIBLE_COMBO'
            WHERE LOWER(odds_type) IN ('demon','goblin')
              AND LOWER(prediction) = 'under'
              AND outcome NOT IN ('VOID','IMPOSSIBLE')
        """)
    return {"label": "Impossible combos (demon/goblin + UNDER)", "before": before, "fixed": before if not dry_run else 0}


def _fix_dnp_inflation(cursor: sqlite3.Cursor, dry_run: bool) -> dict:
    """Players who recorded 0 must be VOID, not HIT/MISS."""
    before = _count(cursor, """
        SELECT COUNT(*) FROM prediction_outcomes
        WHERE (actual_value IS NULL OR actual_value = 0)
          AND outcome IN ('HIT','MISS')
    """)
    if not dry_run and before:
        cursor.execute("""
            UPDATE prediction_outcomes
            SET outcome = 'VOID',
                data_quality_flag = 'DNP_INFLATION'
            WHERE (actual_value IS NULL OR actual_value = 0)
              AND outcome IN ('HIT','MISS')
        """)
    return {"label": "DNP inflation (actual=0 graded HIT/MISS)", "before": before, "fixed": before if not dry_run else 0}


def _fix_logic_violations(cursor: sqlite3.Cursor, dry_run: bool) -> dict:
    """Fix rows where outcome contradicts actual vs line direction."""
    before = _count(cursor, """
        SELECT COUNT(*) FROM prediction_outcomes
        WHERE actual_value IS NOT NULL AND actual_value > 0
          AND line IS NOT NULL
          AND outcome IN ('HIT','MISS')
          AND ((LOWER(prediction) = 'over'  AND outcome = 'HIT'  AND actual_value <  line)
            OR (LOWER(prediction) = 'over'  AND outcome = 'MISS' AND actual_value >  line)
            OR (LOWER(prediction) = 'under' AND outcome = 'HIT'  AND actual_value >  line)
            OR (LOWER(prediction) = 'under' AND outcome = 'MISS' AND actual_value <  line))
    """)
    if not dry_run and before:
        # Fetch violating rows and correct them individually
        cursor.execute("""
            SELECT rowid, odds_type, prediction, actual_value, line
            FROM prediction_outcomes
            WHERE actual_value IS NOT NULL AND actual_value > 0
              AND line IS NOT NULL
              AND outcome IN ('HIT','MISS')
              AND ((LOWER(prediction) = 'over'  AND outcome = 'HIT'  AND actual_value <  line)
                OR (LOWER(prediction) = 'over'  AND outcome = 'MISS' AND actual_value >  line)
                OR (LOWER(prediction) = 'under' AND outcome = 'HIT'  AND actual_value >  line)
                OR (LOWER(prediction) = 'under' AND outcome = 'MISS' AND actual_value <  line))
        """)
        rows = cursor.fetchall()
        for rowid, odds_type, prediction, actual_value, line in rows:
            correct = correct_outcome(odds_type or "standard", prediction or "over", actual_value, line)
            cursor.execute(
                "UPDATE prediction_outcomes SET outcome = ?, data_quality_flag = 'LOGIC_VIOLATION_CORRECTED' WHERE rowid = ?",
                (correct, rowid),
            )
    return {"label": "Logic violations (outcome contradicts actual vs line)", "before": before, "fixed": before if not dry_run else 0}


def _fix_smart_pick_sync(cursor: sqlite3.Cursor, dry_run: bool) -> dict:
    """
    Sync is_smart_pick from predictions → prediction_outcomes.
    This fixes rows graded before pp-sync ran (pp-sync sets is_smart_pick in predictions
    after grading already wrote is_smart_pick=0 into outcomes).
    """
    before = _count(cursor, """
        SELECT COUNT(*) FROM prediction_outcomes o
        JOIN predictions p ON o.prediction_id = p.id
        WHERE p.is_smart_pick = 1 AND o.is_smart_pick = 0
    """)
    if not dry_run and before:
        cursor.execute("""
            UPDATE prediction_outcomes
            SET is_smart_pick = 1
            WHERE prediction_id IN (
                SELECT p.id FROM predictions p
                JOIN prediction_outcomes o ON o.prediction_id = p.id
                WHERE p.is_smart_pick = 1 AND o.is_smart_pick = 0
            )
        """)
    return {"label": "is_smart_pick backfill (graded before pp-sync)", "before": before, "fixed": before if not dry_run else 0}


def _fix_profit_backfill(cursor: sqlite3.Cursor, dry_run: bool) -> dict:
    """Rows with NULL profit — compute from odds_type and outcome."""
    before = _count(cursor, """
        SELECT COUNT(*) FROM prediction_outcomes
        WHERE profit IS NULL AND outcome IN ('HIT','MISS')
    """)
    if not dry_run and before:
        cursor.execute("""
            UPDATE prediction_outcomes
            SET profit = CASE outcome
                WHEN 'HIT' THEN
                    CASE LOWER(odds_type)
                        WHEN 'goblin' THEN 31.25
                        WHEN 'demon'  THEN 120.0
                        ELSE 90.91
                    END
                ELSE -100.0
            END
            WHERE profit IS NULL AND outcome IN ('HIT','MISS')
        """)
    return {"label": "NULL profit backfill", "before": before, "fixed": before if not dry_run else 0}


def _ensure_quality_column(cursor: sqlite3.Cursor) -> None:
    try:
        cursor.execute("ALTER TABLE prediction_outcomes ADD COLUMN data_quality_flag TEXT")
    except Exception:
        pass


def _smart_pick_rate(cursor: sqlite3.Cursor) -> str:
    total = _count(cursor, "SELECT COUNT(*) FROM prediction_outcomes")
    smart = _count(cursor, "SELECT COUNT(*) FROM prediction_outcomes WHERE is_smart_pick = 1")
    return f"{smart}/{total} ({smart/total*100:.1f}%)" if total else "0/0"


def _true_win_rate(cursor: sqlite3.Cursor) -> str:
    """Win rate excluding VOID/DNP/IMPOSSIBLE records."""
    total = _count(cursor, """
        SELECT COUNT(*) FROM prediction_outcomes
        WHERE outcome IN ('HIT','MISS')
          AND (data_quality_flag IS NULL OR data_quality_flag = 'LOGIC_VIOLATION_CORRECTED')
    """)
    hits = _count(cursor, """
        SELECT COUNT(*) FROM prediction_outcomes
        WHERE outcome = 'HIT'
          AND (data_quality_flag IS NULL OR data_quality_flag = 'LOGIC_VIOLATION_CORRECTED')
    """)
    return f"{hits}/{total} ({hits/total*100:.1f}%)" if total else "0/0"


def _smart_win_rate(cursor: sqlite3.Cursor) -> str:
    total = _count(cursor, """
        SELECT COUNT(*) FROM prediction_outcomes
        WHERE is_smart_pick = 1 AND outcome IN ('HIT','MISS')
          AND (data_quality_flag IS NULL OR data_quality_flag = 'LOGIC_VIOLATION_CORRECTED')
    """)
    hits = _count(cursor, """
        SELECT COUNT(*) FROM prediction_outcomes
        WHERE is_smart_pick = 1 AND outcome = 'HIT'
          AND (data_quality_flag IS NULL OR data_quality_flag = 'LOGIC_VIOLATION_CORRECTED')
    """)
    return f"{hits}/{total} ({hits/total*100:.1f}%)" if total else "0/0"


def clean_sport(sport: str, db_path: Path, dry_run: bool) -> None:
    if not db_path.exists():
        print(f"  [SKIP] {sport}: DB not found at {db_path}")
        return

    print(f"\n{'='*70}")
    print(f"  {sport} — {db_path.name}")
    print(_SEP)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    _ensure_quality_column(cursor)

    fixes = [
        _fix_impossible_combos(cursor, dry_run),
        _fix_dnp_inflation(cursor, dry_run),
        _fix_logic_violations(cursor, dry_run),
        _fix_profit_backfill(cursor, dry_run),
        _fix_smart_pick_sync(cursor, dry_run),
    ]

    if not dry_run:
        conn.commit()

    total_fixed = sum(f["fixed"] for f in fixes)

    for f in fixes:
        status = "DRY-RUN" if dry_run else ("FIXED" if f["fixed"] else "CLEAN")
        print(f"  [{status:7s}] {f['label']}: {f['before']} rows")

    print(_SEP)
    print(f"  Total contaminated rows: {sum(f['before'] for f in fixes)}")
    if not dry_run:
        print(f"  Total fixed:             {total_fixed}")
    print(f"  Smart pick rate:         {_smart_pick_rate(cursor)}")
    print(f"  All-predictions win rate (clean): {_true_win_rate(cursor)}")
    print(f"  Smart-pick win rate     (clean): {_smart_win_rate(cursor)}")

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix data contamination in sport DBs.")
    parser.add_argument("--dry-run", action="store_true", help="Report issues without modifying any data.")
    parser.add_argument("--sport", choices=["NHL", "NBA", "MLB", "all"], default="all")
    args = parser.parse_args()

    dry_label = " [DRY RUN - no changes written]" if args.dry_run else ""
    print(f"\nDB Cleanup Tool{dry_label}")
    print("=" * 70)

    targets = {k: v for k, v in SPORTS.items() if args.sport == "all" or k == args.sport}
    for sport, path in targets.items():
        clean_sport(sport, path, args.dry_run)

    print(f"\n{'='*70}")
    if args.dry_run:
        print("Dry run complete. Re-run without --dry-run to apply fixes.")
    else:
        print("Cleanup complete. Run with --dry-run to audit remaining issues.")


if __name__ == "__main__":
    main()
