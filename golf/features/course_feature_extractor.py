"""
Golf Course Feature Extractor
================================

Extracts course-specific features for a player at a given tournament.
Course fit is one of the most predictive signals in golf modeling:
  - Bomber courses (long driving distance rewarded) vs. accuracy courses
  - Player's historical scoring at this specific course
  - Course scoring difficulty vs. the player's average

All features use canonical f_ prefix per shared/canonical_schema.py.

Usage:
    extractor = CourseFeatureExtractor(db_path)
    features = extractor.extract(
        player_name="Rory McIlroy",
        tournament_id="401353232",
        course_name="Augusta National Golf Club",
        target_date="2025-04-10",
        par=72,
    )
    # Returns dict {f_feature_name: float}
"""

import sqlite3
import statistics
import logging
from datetime import date

logger = logging.getLogger(__name__)

# Fallback defaults based on PGA Tour course averages
COURSE_DEFAULTS = {
    "course_history_avg_score": 71.2,
    "course_history_rounds": 0.0,
    "course_scoring_difficulty": 0.0,  # vs. player's overall avg
    "course_top10_rate": 0.10,
    "course_made_cut_rate": 0.65,
}


class CourseFeatureExtractor:
    """
    Extracts player-specific course history features from player_round_logs.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def extract(
        self,
        player_name: str,
        tournament_id: str,
        course_name: str,
        target_date: str,
        par: int = 72,
        player_scoring_avg: float = None,
    ) -> dict:
        """
        Extract course history features for a player.

        Args:
            player_name: Full player name
            tournament_id: ESPN event ID used to group rounds at this course
            course_name: Name of the course (for logging)
            target_date: Date of prediction (YYYY-MM-DD) — only use history before this date
            par: Course par (default 72)
            player_scoring_avg: Player's overall scoring average (for relative difficulty).
                                 If None, computed from database.

        Returns:
            dict: {f_feature_name: float}
        """
        try:
            return self._extract_safe(
                player_name, tournament_id, course_name,
                target_date, par, player_scoring_avg,
            )
        except Exception as e:
            logger.error(f"Course feature extraction failed for {player_name} at {course_name}: {e}")
            return self._default_features()

    def _extract_safe(
        self, player_name, tournament_id, course_name,
        target_date, par, player_scoring_avg,
    ) -> dict:
        features = {}

        # --- Player history at this specific course ---
        course_rounds = self._get_course_history(player_name, tournament_id, target_date)
        course_scores = [r["round_score"] for r in course_rounds if r["round_score"] is not None]
        course_events = self._get_course_event_history(player_name, tournament_id, target_date)

        features["f_course_history_rounds"] = float(len(course_scores))
        features["f_course_history_avg_score"] = (
            sum(course_scores) / len(course_scores) if course_scores
            else COURSE_DEFAULTS["course_history_avg_score"]
        )
        features["f_course_history_std_score"] = (
            statistics.stdev(course_scores) if len(course_scores) >= 2
            else 2.8  # league avg std
        )

        # Score vs par at this course
        vs_par_scores = [r["score_vs_par"] for r in course_rounds if r["score_vs_par"] is not None]
        features["f_course_avg_vs_par"] = (
            sum(vs_par_scores) / len(vs_par_scores) if vs_par_scores else 0.0
        )

        # --- Cut and finish history at this course ---
        made_cuts = [e["made_cut"] for e in course_events if e["made_cut"] is not None]
        top10s = [e for e in course_events if e.get("finish_position") and e["finish_position"] <= 10]
        features["f_course_made_cut_rate"]  = sum(made_cuts) / max(len(made_cuts), 1) if made_cuts else COURSE_DEFAULTS["course_made_cut_rate"]
        features["f_course_top10_rate"]     = len(top10s) / max(len(course_events), 1) if course_events else COURSE_DEFAULTS["course_top10_rate"]
        features["f_course_events_played"]  = float(len(course_events))

        # --- Course difficulty relative to player's overall average ---
        if player_scoring_avg is None:
            player_scoring_avg = self._get_player_overall_avg(player_name, target_date)
        if course_scores and player_scoring_avg:
            course_avg = sum(course_scores) / len(course_scores)
            features["f_course_scoring_difficulty"] = course_avg - player_scoring_avg
        else:
            features["f_course_scoring_difficulty"] = COURSE_DEFAULTS["course_scoring_difficulty"]

        # --- Course fit proxy: driving distance vs. course requirements ---
        # Augusta National (~7,510 yards) penalizes short hitters more than
        # accuracy courses. We encode course par as a rough proxy — lower par
        # (70-71) courses tend to be tighter, demanding more precision.
        features["f_course_par"] = float(par)

        # --- Has the player played this course before? ---
        features["f_course_is_debut"] = 1.0 if len(course_rounds) == 0 else 0.0

        return features

    # ------------------------------------------------------------------
    # Database queries
    # ------------------------------------------------------------------

    def _get_course_history(self, player_name: str, tournament_id: str, before_date: str):
        """Get all rounds this player has played at this course (same tournament_id)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT round_score, score_vs_par, game_date, round_number
                FROM player_round_logs
                WHERE player_name = ?
                  AND tournament_id = ?
                  AND game_date < ?
                ORDER BY game_date DESC
                """,
                (player_name, tournament_id, before_date),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _get_course_event_history(self, player_name: str, tournament_id: str, before_date: str):
        """Get one row per past appearance at this tournament (final-round data)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT tournament_id, MAX(game_date) as last_round_date,
                       made_cut, MIN(finish_position) as finish_position
                FROM player_round_logs
                WHERE player_name = ?
                  AND tournament_id = ?
                  AND game_date < ?
                GROUP BY season
                ORDER BY last_round_date DESC
                """,
                (player_name, tournament_id, before_date),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _get_player_overall_avg(self, player_name: str, before_date: str):
        """Compute player's overall scoring average from all rounds before target_date."""
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT AVG(round_score)
                FROM player_round_logs
                WHERE player_name = ? AND game_date < ? AND round_score IS NOT NULL
                """,
                (player_name, before_date),
            ).fetchone()
            return float(row[0]) if row and row[0] else 71.2
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------

    def _default_features(self) -> dict:
        return {
            "f_course_history_rounds":       0.0,
            "f_course_history_avg_score":    COURSE_DEFAULTS["course_history_avg_score"],
            "f_course_history_std_score":    2.8,
            "f_course_avg_vs_par":           0.0,
            "f_course_made_cut_rate":        COURSE_DEFAULTS["course_made_cut_rate"],
            "f_course_top10_rate":           COURSE_DEFAULTS["course_top10_rate"],
            "f_course_events_played":        0.0,
            "f_course_scoring_difficulty":   COURSE_DEFAULTS["course_scoring_difficulty"],
            "f_course_par":                  72.0,
            "f_course_is_debut":             1.0,
        }
