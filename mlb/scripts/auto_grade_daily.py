"""
MLB Daily Auto-Grader
======================

Grades yesterday's MLB predictions against actual game results.

Pipeline:
  1. Backup database (before any writes)
  2. Fetch final boxscores from MLB Stats API for target_date
  3. For each game marked 'final' (not postponed/shortened):
     a. Parse pitcher stats (starter only)
     b. Parse batter stats (all players who appeared)
     c. Save game logs to player_game_logs (for future feature extraction)
  4. Match predictions to actual results (with fuzzy name matching)
  5. Save HIT/MISS/VOID outcomes to prediction_outcomes table
  6. Log accuracy metrics by prop type and direction

Special MLB cases:
  - Postponements: mark all predictions as VOID (don't count toward accuracy)
  - Rain-shortened games (< 5 innings official): VOID pitcher/batter props
  - DNP (did not play): mark as VOID
  - Bullpen/opener game: starter may have 0 outs → handle gracefully

Usage:
    python auto_grade_daily.py 2026-04-14
    python auto_grade_daily.py  # defaults to yesterday
"""

import sys
import json
import math
import sqlite3
import shutil
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))
from mlb_config import (
    DB_PATH, BACKUPS_DIR, get_db_connection, initialize_database, CORE_PROPS,
    is_over_only_line,
)
from mlb_stats_api import MLBStatsAPI, PitcherBoxscore, BatterBoxscore
from generate_predictions_daily import backup_database
from shared.pp_rules_validator import validate_prediction, correct_outcome


# ============================================================================
# Stat extraction mapping
# prop_type → function that extracts stat value from PitcherBoxscore/BatterBoxscore
# ============================================================================

PITCHER_STAT_MAP = {
    'strikeouts':    lambda p: p.strikeouts,
    'outs_recorded': lambda p: p.outs_recorded,
    'pitcher_walks': lambda p: p.walks,
    'hits_allowed':  lambda p: p.hits_allowed,
    'earned_runs':   lambda p: p.earned_runs,
}

BATTER_STAT_MAP = {
    'hits':              lambda b: b.hits,
    'singles':           lambda b: max(0, b.hits - b.doubles - b.triples - b.home_runs),
    'doubles':           lambda b: b.doubles,
    'total_bases':       lambda b: b.total_bases,
    'home_runs':         lambda b: b.home_runs,
    'rbis':              lambda b: b.rbis,
    'runs':              lambda b: b.runs,
    'stolen_bases':      lambda b: b.stolen_bases,
    'walks':             lambda b: b.walks,
    'batter_strikeouts': lambda b: b.strikeouts,
    'hrr':               lambda b: b.hrr,
}

# Minimum innings pitched to grade an "official" game (rain rule etc.)
MIN_IP_FOR_OFFICIAL = 4.5   # ~4.5 innings pitched by BOTH teams combined


class MLBGrader:
    """
    Grades MLB predictions against actual game outcomes.

    Uses MLB Stats API boxscores as the authoritative source of truth.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self.api = MLBStatsAPI()
        initialize_database(self.db_path)

    def grade_date(self, target_date: str) -> Dict:
        """
        Grade all predictions for a given date.

        Args:
            target_date: Date in YYYY-MM-DD format (the game date)

        Returns:
            Grading summary dict
        """
        print(f"\n{'='*60}")
        print(f"[MLB Grader] Grading predictions for {target_date}")
        print(f"{'='*60}")

        # Ensure profit and is_smart_pick columns exist (idempotent migration)
        with sqlite3.connect(self.db_path) as _mc:
            for col in [("profit", "REAL"), ("is_smart_pick", "INTEGER DEFAULT 0"), ("odds_type", "TEXT DEFAULT 'standard'")]:
                try:
                    _mc.execute(f"ALTER TABLE prediction_outcomes ADD COLUMN {col[0]} {col[1]}")
                    _mc.commit()
                except Exception:
                    pass  # Column already exists
            # ml_prob_over lives on predictions table (XGBoost P(OVER) for BMA)
            try:
                _mc.execute("ALTER TABLE predictions ADD COLUMN ml_prob_over REAL")
                _mc.commit()
            except Exception:
                pass

        # Backup database first
        backup_database(self.db_path, BACKUPS_DIR)

        # Fetch all games for this date
        games = self.api.get_schedule(target_date)
        if not games:
            print(f"[MLB Grader] No games found for {target_date}")
            return {'graded': 0, 'void': 0, 'errors': 0}

        # Only process final games
        final_games = [g for g in games if g.status == 'final']
        postponed_games = [g for g in games if g.status == 'postponed']

        print(f"[MLB Grader] Total games: {len(games)} | "
              f"Final: {len(final_games)} | Postponed: {len(postponed_games)}")

        graded = void = errors = 0

        conn = get_db_connection(self.db_path)
        try:
            # Handle postponed games — mark all predictions as VOID
            for game in postponed_games:
                voided = self._void_predictions(conn, target_date, str(game.game_id),
                                                 reason='postponed')
                void += voided
                print(f"  [VOID] {game.away_team} @ {game.home_team}: postponed ({voided} voided)")

            # Grade each final game
            for game in final_games:
                game_graded, game_void, game_errors = self._grade_game(
                    conn, game, target_date
                )
                graded += game_graded
                void += game_void
                errors += game_errors

            # Backfill profit for any existing rows that are missing it
            conn.execute("""
                UPDATE prediction_outcomes
                SET profit = CASE outcome 
                    WHEN 'HIT' THEN 
                        CASE odds_type
                            WHEN 'goblin' THEN 31.25
                            WHEN 'demon' THEN 120.0
                            ELSE 90.91
                        END
                    ELSE -100.0 
                END
                WHERE profit IS NULL AND outcome IN ('HIT', 'MISS')
            """)

            conn.commit()

        except Exception as e:
            print(f"[MLB Grader] Critical error: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

        # Print accuracy metrics
        self._print_accuracy_report(target_date)

        # Grade ml_v2_predictions → ml_v2_outcomes (non-fatal)
        try:
            self._grade_v2_predictions(target_date)
        except Exception as e:
            print(f"[V2 Grader] Failed (non-fatal): {e}")

        # Update MAB with today's grading results (non-fatal)
        try:
            self._update_mab(target_date)
        except Exception as e:
            print(f"[MAB] Update failed (non-fatal): {e}")

        summary = {
            'date': target_date,
            'graded': graded,
            'void': void,
            'errors': errors,
            'final_games': len(final_games),
        }
        print(f"\n[MLB Grader] Summary: {summary}")
        return summary

    # =========================================================================
    # V2 outcomes (ml_v2_predictions → ml_v2_outcomes)
    # =========================================================================

    def _grade_v2_predictions(self, target_date: str) -> None:
        """
        Populate ml_v2_outcomes by joining ml_v2_predictions with already-graded
        prediction_outcomes for the same date.

        Does not re-fetch boxscores — piggybacks on the graded prediction_outcomes
        rows written in the main grading pass above.
        """
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row

            # Create table if first run
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ml_v2_outcomes (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    v2_prediction_id INTEGER REFERENCES ml_v2_predictions(id),
                    game_date        DATE,
                    player_name      TEXT,
                    prop_type        TEXT,
                    line             REAL,
                    prediction       TEXT,
                    actual_value     REAL,
                    outcome          TEXT,
                    prob_over        REAL,
                    bma_correct      INTEGER,
                    created_at       TEXT,
                    UNIQUE(v2_prediction_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ml_v2_outcomes_date
                ON ml_v2_outcomes (game_date)
            """)

            # Join ml_v2_predictions with graded prediction_outcomes on (player, prop, line, date)
            rows = conn.execute("""
                SELECT
                    v2.id          AS v2_id,
                    v2.player_name,
                    v2.prop_type,
                    v2.line,
                    v2.prediction  AS v2_prediction,
                    v2.prob_over,
                    po.actual_value,
                    po.outcome
                FROM ml_v2_predictions v2
                JOIN prediction_outcomes po
                  ON  po.game_date  = v2.game_date
                  AND LOWER(po.player_name) = LOWER(v2.player_name)
                  AND po.prop_type  = v2.prop_type
                  AND po.line       = v2.line
                WHERE v2.game_date = ?
                  AND v2.id NOT IN (SELECT v2_prediction_id FROM ml_v2_outcomes
                                    WHERE v2_prediction_id IS NOT NULL)
            """, (target_date,)).fetchall()

            if not rows:
                print(f"[V2 Grader] No ml_v2_predictions to grade for {target_date}")
                return

            written = 0
            for row in rows:
                actual    = row['actual_value']
                outcome   = row['outcome']
                direction = row['v2_prediction']   # 'OVER' or 'UNDER'

                # bma_correct: did BMA direction match actual?
                if outcome in ('HIT', 'MISS') and actual is not None:
                    actual_dir  = 'OVER' if float(actual) > row['line'] else 'UNDER'
                    bma_correct = 1 if direction == actual_dir else 0
                else:
                    bma_correct = None  # VOID — don't count

                conn.execute("""
                    INSERT OR IGNORE INTO ml_v2_outcomes (
                        v2_prediction_id, game_date, player_name, prop_type, line,
                        prediction, actual_value, outcome,
                        prob_over, bma_correct, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row['v2_id'], target_date,
                    row['player_name'], row['prop_type'], row['line'],
                    direction, actual, outcome,
                    row['prob_over'], bma_correct,
                    datetime.now().isoformat(),
                ))
                written += 1

            conn.commit()

        # Summary
        with sqlite3.connect(self.db_path) as conn:
            stats = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(bma_correct) as correct,
                    SUM(CASE WHEN outcome = 'VOID' THEN 1 ELSE 0 END) as voids
                FROM ml_v2_outcomes WHERE game_date = ?
            """, (target_date,)).fetchone()

        total   = stats[0] or 0
        correct = stats[1] or 0
        voids   = stats[2] or 0
        graded  = total - voids
        acc     = f"{correct / graded * 100:.1f}%" if graded > 0 else "n/a"
        print(f"[V2 Grader] {written} rows written | BMA accuracy: {correct}/{graded} = {acc} (VOID: {voids})")

    # =========================================================================
    # MAB update (Thompson Sampling — stat + xgb arms)
    # =========================================================================

    def _update_mab(self, target_date: str) -> None:
        """Update MAB state from today's graded outcomes for stat and xgb arms."""
        _HLSS = Path(__file__).resolve().parents[3] / "hlss"
        if str(_HLSS) not in sys.path:
            sys.path.insert(0, str(_HLSS))
        from ml_training.mab_weighting import ThompsonSamplingMAB

        mab = ThompsonSamplingMAB()
        _STAT_TO_DUCKDB = {"pitcher_walks": "walks"}

        def _norm(name: str) -> str:
            import unicodedata as _ud
            n = _ud.normalize("NFKD", str(name))
            return "".join(c for c in n if not _ud.combining(c)).lower().strip()

        def _p_over_local(predicted_mean: float, line: float):
            try:
                from scipy.stats import poisson
                if predicted_mean <= 0:
                    return None
                return float(1.0 - poisson.cdf(int(line), mu=predicted_mean))
            except ImportError:
                return None

        # Fetch graded outcomes
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            outcomes = [dict(r) for r in conn.execute("""
                SELECT player_name, prop_type, line, prediction, actual_value, outcome
                FROM prediction_outcomes
                WHERE game_date = ? AND outcome IN ('HIT', 'MISS')
            """, (target_date,)).fetchall()]

        if not outcomes:
            print(f"[MAB] No HIT/MISS outcomes for {target_date} — skipping")
            return

        # Stat arm updates
        for row in outcomes:
            mab.update('mlb', row['prop_type'], 'stat',
                       correct=(row['outcome'] == 'HIT'),
                       line=row['line'], game_date=target_date)
        print(f"[MAB] Stat arm: {len(outcomes)} updates")

        # XGBoost arm — load DuckDB ml_predictions
        xgb_updated = 0
        _DUCKDB_PATH = Path(__file__).resolve().parents[2] / "mlb_feature_store" / "data" / "mlb.duckdb"

        if _DUCKDB_PATH.exists():
            try:
                import duckdb
                duck = duckdb.connect(str(_DUCKDB_PATH), read_only=True)

                try:
                    aliases = duck.execute("SELECT fs_name, canonical_name FROM name_aliases").fetchall()
                    alias_map = {_norm(fs): _norm(can) for fs, can in aliases}
                except Exception:
                    alias_map = {}

                ml_rows = duck.execute("""
                    SELECT p.player_name, mp.prop, mp.predicted_value, mp.line
                    FROM ml_predictions mp
                    JOIN players p ON mp.player_id = p.player_id
                    WHERE mp.game_date = ?
                """, [target_date]).fetchall()
                duck.close()

                ml_lookup = {}
                for pname, prop, predicted_value, ml_line in ml_rows:
                    key = (alias_map.get(_norm(pname), _norm(pname)), prop)
                    ml_lookup[key] = (predicted_value, ml_line)

                for row in outcomes:
                    duckdb_prop = _STAT_TO_DUCKDB.get(row['prop_type'], row['prop_type'])
                    ml_entry = ml_lookup.get((_norm(row['player_name']), duckdb_prop))
                    if ml_entry is None:
                        continue

                    predicted_value, _ = ml_entry
                    grade_line = row['line']
                    prob_over = _p_over_local(predicted_value, grade_line)
                    if prob_over is None or row['actual_value'] is None:
                        continue

                    xgb_direction = 'OVER' if prob_over > 0.5 else 'UNDER'
                    actual_direction = 'OVER' if float(row['actual_value']) > grade_line else 'UNDER'
                    mab.update('mlb', row['prop_type'], 'xgb',
                               correct=(xgb_direction == actual_direction),
                               line=grade_line, game_date=target_date)
                    xgb_updated += 1

            except Exception as e:
                print(f"[MAB] XGB arm failed: {e}")
        else:
            print(f"[MAB] DuckDB not found — xgb arm skipped")

        mab.save()
        print(f"[MAB] Saved. Stat: {len(outcomes)}, XGB: {xgb_updated} for {target_date}")

    # =========================================================================
    # Per-game grading
    # =========================================================================

    def _grade_game(self, conn: sqlite3.Connection, game, target_date: str) -> Tuple[int, int, int]:
        """Grade all predictions for a single final game."""
        graded = void = errors = 0

        print(f"\n  [Game] {game.away_team} @ {game.home_team} (ID: {game.game_id})")

        try:
            boxscore = self.api.get_boxscore(game.game_id)
            if not boxscore:
                print(f"  [WARN] No boxscore for game {game.game_id} — skipping")
                return graded, void, errors

            # Check if game was official (≥5 innings)
            if not self._is_game_official(boxscore):
                voided = self._void_predictions(conn, target_date, str(game.game_id),
                                                 reason='shortened')
                print(f"  [VOID] Game shortened (<5 innings) — voided {voided} predictions")
                return graded, voided, errors

            # Parse actual stats from boxscore
            pitchers = self.api.parse_pitcher_stats(boxscore)
            batters  = self.api.parse_batter_stats(boxscore)

            # Save game logs for future feature extraction
            self._save_game_logs(conn, game, pitchers, batters)

            # Grade pitcher predictions
            for pitcher in pitchers:
                if not pitcher.is_starter:
                    continue  # Only grade starters for pitcher props
                p_graded, p_void, p_errs = self._grade_player_predictions(
                    conn, pitcher.player_name, pitcher.team, target_date,
                    str(game.game_id), 'pitcher', pitcher, None
                )
                graded += p_graded
                void += p_void
                errors += p_errs

            # Grade batter predictions
            for batter in batters:
                b_graded, b_void, b_errs = self._grade_player_predictions(
                    conn, batter.player_name, batter.team, target_date,
                    str(game.game_id), 'batter', None, batter
                )
                graded += b_graded
                void += b_void
                errors += b_errs

        except Exception as e:
            print(f"  [ERROR] Game {game.game_id}: {e}")
            errors += 1

        return graded, void, errors

    def _grade_player_predictions(self, conn: sqlite3.Connection, player_name: str,
                                   team: str, target_date: str, game_id: str,
                                   player_type: str, pitcher: Optional[PitcherBoxscore],
                                   batter: Optional[BatterBoxscore]) -> Tuple[int, int, int]:
        """Grade all predictions for a single player on a given date."""
        graded = void = errors = 0

        # Get all predictions for this player on this date
        predictions = self._get_predictions(conn, player_name, team, target_date, player_type)

        if not predictions:
            return graded, void, errors

        # DNP guard: batter in box score with no plate appearances is a ghost entry
        # (projected lineup player who was scratched). Void all their predictions.
        if player_type == 'batter' and batter:
            played = (batter.at_bats > 0 or batter.walks > 0 or batter.runs > 0)
            if not played:
                for pred in predictions:
                    self._save_outcome(conn, pred['id'], target_date, game_id,
                                       player_name, pred['prop_type'], pred['line'],
                                       pred['prediction'], None, 'VOID')
                    void += 1
                return graded, void, errors

        # DNP guard: pitcher with 0 outs recorded didn't pitch
        if player_type == 'pitcher' and pitcher:
            if (pitcher.outs_recorded or 0) == 0:
                for pred in predictions:
                    self._save_outcome(conn, pred['id'], target_date, game_id,
                                       player_name, pred['prop_type'], pred['line'],
                                       pred['prediction'], None, 'VOID')
                    void += 1
                return graded, void, errors

        for pred in predictions:
            prop_type = pred['prop_type']
            line = pred['line']
            prediction = pred['prediction']
            odds_type = pred.get('odds_type', 'standard')

            try:
                # Goblin/demon lines only allow OVER on PrizePicks.
                # If an UNDER prediction somehow exists, void it — not actionable.
                if prediction == 'UNDER' and is_over_only_line(prop_type, line):
                    self._save_outcome(conn, pred['id'], target_date, game_id,
                                       player_name, prop_type, line, prediction,
                                       None, 'VOID')
                    void += 1
                    continue

                # Extract actual stat value
                actual_value = None
                if player_type == 'pitcher' and pitcher:
                    extract_fn = PITCHER_STAT_MAP.get(prop_type)
                    if extract_fn:
                        actual_value = extract_fn(pitcher)
                elif player_type == 'batter' and batter:
                    extract_fn = BATTER_STAT_MAP.get(prop_type)
                    if extract_fn:
                        actual_value = extract_fn(batter)

                # Block impossible combos before grading
                combo_check = validate_prediction(odds_type, prediction)
                if not combo_check:
                    continue  # Silent skip — impossible combo shouldn't exist in predictions

                if actual_value is None:
                    # DNP or unknown prop — void
                    self._save_outcome(conn, pred['id'], target_date, game_id,
                                       player_name, prop_type, line, prediction,
                                       None, 'VOID')
                    void += 1
                    continue

                # Use validator to compute correct outcome (DNP=0→VOID, push handled)
                outcome = correct_outcome(odds_type, prediction, actual_value, line)

                # Profit: HIT/MISS only; PUSH/VOID are 0
                if outcome == 'HIT':
                    if odds_type == 'goblin':
                        profit = 31.25   # -320 odds
                    elif odds_type == 'demon':
                        profit = 120.0   # +120 odds
                    else:
                        profit = 90.91   # -110 odds
                elif outcome == 'MISS':
                    profit = -100.0
                else:
                    profit = 0.0

                self._save_outcome(conn, pred['id'], target_date, game_id,
                                   player_name, prop_type, line, prediction,
                                   actual_value, outcome, profit, odds_type, pred.get('is_smart_pick', 0))
                graded += 1

            except Exception as e:
                print(f"    [ERROR] {player_name} {prop_type} {line}: {e}")
                errors += 1

        return graded, void, errors

    # =========================================================================
    # Fuzzy name matching helpers
    # =========================================================================

    def _get_predictions(self, conn: sqlite3.Connection, player_name: str,
                          team: str, target_date: str, player_type: str) -> List[Dict]:
        """
        Fetch predictions for a player using fuzzy name matching.

        Tries 4 levels of matching:
        1. Exact name match
        2. Case-insensitive match
        3. Last-name match
        4. SequenceMatcher fuzzy (≥85% similarity)
        """
        # Level 1: Exact match
        cursor = conn.execute('''
            SELECT id, player_name, prop_type, line, prediction, probability, is_smart_pick, odds_type
            FROM predictions
            WHERE game_date = ?
              AND team = ?
              AND player_type = ?
              AND player_name = ?
              AND id NOT IN (SELECT prediction_id FROM prediction_outcomes WHERE prediction_id IS NOT NULL)
        ''', (target_date, team, player_type, player_name))
        rows = cursor.fetchall()
        if rows:
            return [dict(r) for r in rows]

        # Level 2: Case-insensitive
        cursor = conn.execute('''
            SELECT id, player_name, prop_type, line, prediction, probability, is_smart_pick, odds_type
            FROM predictions
            WHERE game_date = ?
              AND team = ?
              AND player_type = ?
              AND LOWER(player_name) = LOWER(?)
              AND id NOT IN (SELECT prediction_id FROM prediction_outcomes WHERE prediction_id IS NOT NULL)
        ''', (target_date, team, player_type, player_name))
        rows = cursor.fetchall()
        if rows:
            return [dict(r) for r in rows]

        # Level 3: Last name match
        last_name = player_name.split()[-1] if player_name else ''
        if last_name:
            cursor = conn.execute('''
                SELECT id, player_name, prop_type, line, prediction, probability, is_smart_pick, odds_type
                FROM predictions
                WHERE game_date = ?
                  AND team = ?
                  AND player_type = ?
                  AND player_name LIKE ?
                  AND id NOT IN (SELECT prediction_id FROM prediction_outcomes WHERE prediction_id IS NOT NULL)
            ''', (target_date, team, player_type, f'%{last_name}%'))
            rows = cursor.fetchall()
            if rows:
                return [dict(r) for r in rows]

        # Level 4: Fuzzy match against all ungraded predictions for this team/date
        cursor = conn.execute('''
            SELECT id, player_name, prop_type, line, prediction, probability, is_smart_pick, odds_type
            FROM predictions
            WHERE game_date = ?
              AND team = ?
              AND player_type = ?
              AND id NOT IN (SELECT prediction_id FROM prediction_outcomes WHERE prediction_id IS NOT NULL)
        ''', (target_date, team, player_type))
        all_preds = [dict(r) for r in cursor.fetchall()]

        if not all_preds:
            return []

        # Find best fuzzy match candidate
        name_lower = player_name.lower()
        best_match_name = None
        best_ratio = 0.0

        for pred in all_preds:
            ratio = SequenceMatcher(None, name_lower, pred['player_name'].lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match_name = pred['player_name']

        if best_ratio >= 0.85 and best_match_name:
            return [p for p in all_preds if p['player_name'] == best_match_name]

        return []

    # =========================================================================
    # Game log saving
    # =========================================================================

    def _save_game_logs(self, conn: sqlite3.Connection, game,
                         pitchers: List[PitcherBoxscore],
                         batters: List[BatterBoxscore]) -> None:
        """Save game stats to player_game_logs for future feature extraction."""
        for p in pitchers:
            try:
                # Determine opponent
                if p.team == game.home_team:
                    opponent = game.away_team
                    home_away = 'home'
                    opp_starter = game.away_starter
                else:
                    opponent = game.home_team
                    home_away = 'away'
                    opp_starter = game.home_starter

                conn.execute('''
                    INSERT OR IGNORE INTO player_game_logs (
                        game_id, game_date, player_name, team, opponent,
                        home_away, player_type,
                        innings_pitched, outs_recorded, strikeouts_pitched,
                        walks_allowed, hits_allowed, earned_runs,
                        home_runs_allowed, pitches,
                        opposing_pitcher, venue, game_time, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(game.game_id), game.game_date, p.player_name, p.team, opponent,
                    home_away, 'pitcher',
                    p.innings_pitched, p.outs_recorded, p.strikeouts, p.walks,
                    p.hits_allowed, p.earned_runs, p.home_runs_allowed, p.pitches,
                    opp_starter, game.venue, game.game_time_utc, datetime.now().isoformat()
                ))
            except Exception as e:
                print(f"  [WARN] Failed to save pitcher log {p.player_name}: {e}")

        for b in batters:
            try:
                if b.team == game.home_team:
                    opponent = game.away_team
                    home_away = 'home'
                    opp_pitcher = game.away_starter
                else:
                    opponent = game.home_team
                    home_away = 'away'
                    opp_pitcher = game.home_starter

                conn.execute('''
                    INSERT OR IGNORE INTO player_game_logs (
                        game_id, game_date, player_name, team, opponent,
                        home_away, player_type,
                        at_bats, hits, home_runs, rbis, runs,
                        stolen_bases, walks_drawn, strikeouts_batter,
                        doubles, triples, total_bases, hrr,
                        batting_order, opposing_pitcher, venue, game_time, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(game.game_id), game.game_date, b.player_name, b.team, opponent,
                    home_away, 'batter',
                    b.at_bats, b.hits, b.home_runs, b.rbis, b.runs,
                    b.stolen_bases, b.walks, b.strikeouts, b.doubles, b.triples,
                    b.total_bases, b.hrr, b.batting_order,
                    opp_pitcher, game.venue, game.game_time_utc, datetime.now().isoformat()
                ))
            except Exception as e:
                print(f"  [WARN] Failed to save batter log {b.player_name}: {e}")

    # =========================================================================
    # Outcome saving
    # =========================================================================

    def _save_outcome(self, conn: sqlite3.Connection, prediction_id: int, game_date: str,
                       game_id: str, player_name: str, prop_type: str, line: float,
                       prediction: str, actual_value: Optional[float], outcome: str,
                       profit: float = 0.0, odds_type: str = 'standard', is_smart_pick: int = 0) -> None:
        """Save a single prediction outcome to the prediction_outcomes table."""
        conn.execute('''
            INSERT OR IGNORE INTO prediction_outcomes (
                prediction_id, game_date, game_id, player_name,
                prop_type, line, prediction, actual_value, outcome, created_at, profit, odds_type, is_smart_pick
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            prediction_id, game_date, game_id, player_name,
            prop_type, line, prediction, actual_value, outcome,
            datetime.now().isoformat(), profit, odds_type, is_smart_pick
        ))

    def _void_predictions(self, conn: sqlite3.Connection, game_date: str,
                           game_id: str, reason: str) -> int:
        """Mark all ungraded predictions for a game as VOID."""
        cursor = conn.execute('''
            SELECT id, player_name, prop_type, line, prediction
            FROM predictions
            WHERE game_date = ?
              AND game_id = ?
              AND id NOT IN (SELECT prediction_id FROM prediction_outcomes WHERE prediction_id IS NOT NULL)
        ''', (game_date, game_id))

        preds = cursor.fetchall()
        for pred in preds:
            self._save_outcome(conn, pred['id'], game_date, game_id,
                                pred['player_name'], pred['prop_type'], pred['line'],
                                pred['prediction'], None, 'VOID')

        return len(preds)

    # =========================================================================
    # Game validity check
    # =========================================================================

    def _is_game_official(self, boxscore: Dict) -> bool:
        """
        Check if a game was official (played at least 5 innings).

        For grading purposes, a shortened game where < 5 innings were played
        should be voided (weather, curfew, etc.)

        Args:
            boxscore: Raw boxscore dict from MLB Stats API

        Returns:
            True if game is official and should be graded
        """
        try:
            # Check innings played in linescore
            linescore = boxscore.get('linescore', {})
            current_inning = linescore.get('currentInning', 9)
            game_state = boxscore.get('gameData', {}).get('status', {}).get('detailedState', '')

            # If game completed normally
            if 'Final' in game_state and current_inning >= 5:
                return True

            # If suspended or postponed mid-game
            if 'Suspended' in game_state or current_inning < 5:
                return False

            return True  # Default: assume official
        except Exception:
            return True  # Fail open: don't void games on parsing errors

    # =========================================================================
    # Accuracy reporting
    # =========================================================================

    def _print_accuracy_report(self, target_date: str) -> None:
        """Print grading accuracy summary for the day."""
        conn = get_db_connection(self.db_path)
        try:
            # Overall
            cursor = conn.execute('''
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits,
                    SUM(CASE WHEN outcome = 'MISS' THEN 1 ELSE 0 END) as misses,
                    SUM(CASE WHEN outcome = 'VOID' THEN 1 ELSE 0 END) as voids
                FROM prediction_outcomes
                WHERE game_date = ?
            ''', (target_date,))
            row = cursor.fetchone()

            if not row or not row['total']:
                print("\n[MLB Grader] No outcomes graded yet.")
                return

            graded = row['hits'] + row['misses']
            acc = row['hits'] / graded * 100 if graded > 0 else 0

            print(f"\n[MLB Grader] Accuracy for {target_date}:")
            print(f"  Overall: {row['hits']}/{graded} = {acc:.1f}% (VOID: {row['voids']})")

            # By prop type
            cursor = conn.execute('''
                SELECT
                    po.prop_type,
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'HIT' THEN 1 ELSE 0 END) as hits
                FROM prediction_outcomes po
                WHERE game_date = ?
                  AND outcome IN ('HIT', 'MISS')
                GROUP BY po.prop_type
                ORDER BY po.prop_type
            ''', (target_date,))

            print("\n  By prop type:")
            for row in cursor.fetchall():
                total = row['total']
                hits = row['hits']
                acc = hits / total * 100 if total > 0 else 0
                print(f"    {row['prop_type']:<20}: {hits}/{total} = {acc:.1f}%")

        finally:
            conn.close()


# ============================================================================
# Standalone entry point
# ============================================================================

def main():
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        # Default: grade yesterday's games
        yesterday = datetime.now() - timedelta(days=1)
        target_date = yesterday.strftime('%Y-%m-%d')

    print(f"[MLB Grader] Grading predictions for: {target_date}")

    grader = MLBGrader()
    summary = grader.grade_date(target_date)

    return 0 if summary.get('errors', 0) == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
