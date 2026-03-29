"""
Golf Player Feature Extractor
================================

Extracts per-player features for round scoring and make-cut predictions.
All features use the canonical f_ prefix per shared/canonical_schema.py.

Feature groups:
  1. Recent scoring form     — last 5/10 rounds avg, std dev, trend
  2. Traditional stat proxies — GIR, driving, scrambling, putting (SG proxies)
  3. Make-cut form           — recent cut rate, top-10 rate, activity
  4. Context                 — world ranking, days rest, round number, is_major

Temporal safety: all database queries use game_date < target_date to prevent
look-ahead bias. Season stats are filtered to the season prior to target_date
or the current season through the event start.

Usage:
    extractor = PlayerFeatureExtractor(db_path, pga_stats_scraper)
    features = extractor.extract(
        player_name="Scottie Scheffler",
        prop_type="round_score",
        line=70.5,
        target_date="2025-04-10",
        round_number=1,
        world_ranking=1,
        season=2025,
    )
    # Returns dict of {f_feature_name: float}
"""

import sqlite3
import statistics
import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# League-average defaults used when insufficient player data exists
# (based on PGA Tour averages across 2020–2024)
LEAGUE_AVERAGES = {
    "scoring_avg":       71.2,
    "scoring_std":        2.8,
    "gir_pct":           65.0,
    "driving_distance":  295.0,
    "driving_accuracy":  62.0,
    "scrambling_pct":    59.0,
    "putting_avg":        1.73,
    "birdie_avg":          3.8,
    "made_cut_rate":      0.65,
    "top10_rate":         0.15,
}


class PlayerFeatureExtractor:
    """
    Extracts player-level features from player_round_logs and PGA seasonal stats.
    """

    def __init__(self, db_path: str, pga_scraper=None):
        """
        Args:
            db_path: Path to golf_predictions.db
            pga_scraper: Optional PGAStatsScraper instance for seasonal stats.
                         If None, traditional stats will use league averages.
        """
        self.db_path = db_path
        self.pga_scraper = pga_scraper

    def extract(
        self,
        player_name: str,
        prop_type: str,
        line: float,
        target_date: str,
        round_number: int = 1,
        world_ranking: Optional[int] = None,
        season: Optional[int] = None,
        is_major: bool = False,
        days_rest: Optional[int] = None,
        field_strength_avg_rank: Optional[float] = None,
    ) -> dict:
        """
        Extract all features for a player prediction.

        Args:
            player_name: Full player name
            prop_type: 'round_score' or 'make_cut'
            line: The betting line (e.g., 70.5 for round_score, 0.5 for make_cut)
            target_date: Date of the round being predicted (YYYY-MM-DD)
            round_number: 1–4 (which round of the tournament)
            world_ranking: Official World Golf Ranking at time of event
            season: PGA Tour season year for fetching seasonal stats
            is_major: Whether this is a major championship
            days_rest: Days since player's last tournament round
            field_strength_avg_rank: Average OWGR of field (tournament quality)

        Returns:
            dict: {f_feature_name: float, ...}
            Never raises — returns safe defaults on any error.
        """
        try:
            return self._extract_safe(
                player_name, prop_type, line, target_date,
                round_number, world_ranking, season,
                is_major, days_rest, field_strength_avg_rank,
            )
        except Exception as e:
            logger.error(f"Feature extraction failed for {player_name}: {e}")
            return self._default_features(prop_type, line, round_number, world_ranking)

    # ------------------------------------------------------------------
    # Internal extraction
    # ------------------------------------------------------------------

    def _extract_safe(
        self, player_name, prop_type, line, target_date,
        round_number, world_ranking, season,
        is_major, days_rest, field_strength_avg_rank,
    ) -> dict:
        features = {}

        # --- 1. Recent scoring form ---
        recent_rounds = self._get_recent_rounds(player_name, target_date, n=20)
        scores = [r["round_score"] for r in recent_rounds if r["round_score"] is not None]
        l5_scores  = scores[:5]
        l10_scores = scores[:10]

        features["f_scoring_avg_l5_rounds"]  = _safe_mean(l5_scores,  LEAGUE_AVERAGES["scoring_avg"])
        features["f_scoring_avg_l10_rounds"] = _safe_mean(l10_scores, LEAGUE_AVERAGES["scoring_avg"])
        features["f_scoring_std_l10_rounds"] = _safe_std(l10_scores,  LEAGUE_AVERAGES["scoring_std"])
        features["f_rounds_played_l90d"]     = float(self._count_rounds_last_n_days(player_name, target_date, 90))

        # Trend: is player scoring better (lower) recently?
        if len(l10_scores) >= 5:
            first_half_avg = sum(l10_scores[5:]) / max(len(l10_scores[5:]), 1)
            second_half_avg = sum(l10_scores[:5]) / max(len(l10_scores[:5]), 1)
            features["f_scoring_trend"] = first_half_avg - second_half_avg  # positive = improving
        else:
            features["f_scoring_trend"] = 0.0

        # --- 2. Over/under line hit rates (for round_score) ---
        if prop_type == "round_score" and scores:
            features["f_season_success_rate"] = sum(1 for s in scores if s < line) / len(scores)
            features["f_l5_success_rate"]  = sum(1 for s in l5_scores  if s < line) / max(len(l5_scores), 1)
            features["f_l10_success_rate"] = sum(1 for s in l10_scores if s < line) / max(len(l10_scores), 1)
        else:
            features["f_season_success_rate"] = 0.5
            features["f_l5_success_rate"]  = 0.5
            features["f_l10_success_rate"] = 0.5

        # --- 3. Make-cut form ---
        cut_events = self._get_recent_events(player_name, target_date, n=15)
        made_cuts = [e["made_cut"] for e in cut_events if e["made_cut"] is not None]
        top10s    = [e["finish_position"] for e in cut_events
                     if e["finish_position"] is not None and e["finish_position"] <= 10]

        features["f_made_cut_rate_l10"] = sum(made_cuts[:10]) / max(len(made_cuts[:10]), 1) if made_cuts else LEAGUE_AVERAGES["made_cut_rate"]
        features["f_top10_rate_l10"]    = len(top10s) / max(len(cut_events[:10]), 1) if cut_events else LEAGUE_AVERAGES["top10_rate"]

        # --- 4. Traditional stats (SG proxies) from PGA scraper ---
        if self.pga_scraper and season:
            player_stats = self.pga_scraper.get_stats_for_player(player_name, season)
        else:
            player_stats = {}

        features["f_gir_pct_season"]          = player_stats.get("gir_pct",          LEAGUE_AVERAGES["gir_pct"])
        features["f_driving_distance_season"] = player_stats.get("driving_distance",  LEAGUE_AVERAGES["driving_distance"])
        features["f_driving_accuracy_season"] = player_stats.get("driving_accuracy",  LEAGUE_AVERAGES["driving_accuracy"])
        features["f_scrambling_pct_season"]   = player_stats.get("scrambling_pct",    LEAGUE_AVERAGES["scrambling_pct"])
        features["f_putting_avg_season"]      = player_stats.get("putting_avg",       LEAGUE_AVERAGES["putting_avg"])
        features["f_birdie_avg_season"]       = player_stats.get("birdie_avg",        LEAGUE_AVERAGES["birdie_avg"])

        # Use true SG if available (DataGolf upgrade path)
        for sg_stat in ("sg_total", "sg_ott", "sg_approach", "sg_arg", "sg_putting"):
            if sg_stat in player_stats:
                features[f"f_{sg_stat}_season"] = player_stats[sg_stat]

        # --- 5. Context features ---
        features["f_world_ranking"]           = float(world_ranking) if world_ranking else 250.0
        features["f_round_number"]            = float(round_number)
        features["f_is_major"]                = 1.0 if is_major else 0.0
        features["f_days_rest"]               = float(days_rest) if days_rest is not None else 7.0
        features["f_field_strength_avg_rank"] = float(field_strength_avg_rank) if field_strength_avg_rank else 150.0
        features["f_line"]                    = float(line)

        # --- 6. Data quality flag ---
        features["f_insufficient_data"] = 1.0 if len(scores) < 10 else 0.0

        return features

    # ------------------------------------------------------------------
    # Database queries
    # ------------------------------------------------------------------

    def _get_recent_rounds(self, player_name: str, before_date: str, n: int = 20):
        """Fetch the N most recent rounds for a player before target_date."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT round_score, score_vs_par, game_date, round_number,
                       tournament_id, made_cut
                FROM player_round_logs
                WHERE player_name = ?
                  AND game_date < ?
                  AND round_score IS NOT NULL
                ORDER BY game_date DESC, round_number DESC
                LIMIT ?
                """,
                (player_name, before_date, n),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _get_recent_events(self, player_name: str, before_date: str, n: int = 15):
        """
        Fetch recent tournament-level outcomes (one row per event).
        Uses the final round entry per tournament to get made_cut + finish_position.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT tournament_id, MAX(game_date) as last_round_date,
                       made_cut, MIN(finish_position) as finish_position
                FROM player_round_logs
                WHERE player_name = ?
                  AND game_date < ?
                GROUP BY tournament_id
                ORDER BY last_round_date DESC
                LIMIT ?
                """,
                (player_name, before_date, n),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _count_rounds_last_n_days(self, player_name: str, before_date: str, days: int):
        """Count rounds played in the last N days."""
        cutoff = (date.fromisoformat(before_date) - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute(
                """
                SELECT COUNT(*) FROM player_round_logs
                WHERE player_name = ? AND game_date >= ? AND game_date < ?
                """,
                (player_name, cutoff, before_date),
            ).fetchone()[0]
            return count
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Default fallback features
    # ------------------------------------------------------------------

    def _default_features(self, prop_type, line, round_number, world_ranking):
        """Return league-average features when extraction fails."""
        return {
            "f_scoring_avg_l5_rounds":      LEAGUE_AVERAGES["scoring_avg"],
            "f_scoring_avg_l10_rounds":     LEAGUE_AVERAGES["scoring_avg"],
            "f_scoring_std_l10_rounds":     LEAGUE_AVERAGES["scoring_std"],
            "f_rounds_played_l90d":         12.0,
            "f_scoring_trend":              0.0,
            "f_season_success_rate":        0.5,
            "f_l5_success_rate":            0.5,
            "f_l10_success_rate":           0.5,
            "f_made_cut_rate_l10":          LEAGUE_AVERAGES["made_cut_rate"],
            "f_top10_rate_l10":             LEAGUE_AVERAGES["top10_rate"],
            "f_gir_pct_season":             LEAGUE_AVERAGES["gir_pct"],
            "f_driving_distance_season":    LEAGUE_AVERAGES["driving_distance"],
            "f_driving_accuracy_season":    LEAGUE_AVERAGES["driving_accuracy"],
            "f_scrambling_pct_season":      LEAGUE_AVERAGES["scrambling_pct"],
            "f_putting_avg_season":         LEAGUE_AVERAGES["putting_avg"],
            "f_birdie_avg_season":          LEAGUE_AVERAGES["birdie_avg"],
            "f_world_ranking":              float(world_ranking) if world_ranking else 250.0,
            "f_round_number":               float(round_number),
            "f_is_major":                   0.0,
            "f_days_rest":                  7.0,
            "f_field_strength_avg_rank":    150.0,
            "f_line":                       float(line),
            "f_insufficient_data":          1.0,
        }


# ------------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------------

def _safe_mean(values: list, default: float) -> float:
    return sum(values) / len(values) if values else default


def _safe_std(values: list, default: float) -> float:
    if len(values) >= 2:
        try:
            return statistics.stdev(values)
        except statistics.StatisticsError:
            pass
    return default
