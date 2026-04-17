"""
NHL Game-Level Feature Extractor
=================================

Extracts ~40 features for full-game predictions (moneyline, spread, total).
All features use data available BEFORE game start (temporal safety).

Feature prefixes:
    gf_home_*  — home team metrics
    gf_away_*  — away team metrics
    gf_*       — matchup/context features

Sources:
    - team_rolling_stats table (from team_stats_collector.py)
    - games table (schedule, recent results)
    - goalie_stats table (starting goalie quality)
    - elo_ratings JSON (from shared/elo_engine.py)
    - arena_data.py (travel distance, timezone, altitude)
    - game_lines table (odds-derived features)

Returns ~42 features per game.
"""

import sqlite3
import os
import sys
import json
import math
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SPORT_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SPORT_DIR)

sys.path.insert(0, os.path.join(SPORT_DIR, "scripts"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "shared"))

# ── Default feature values (neutral priors) ───────────────────────────────────

DEFAULT_FEATURES = {
    # Team strength
    "gf_home_win_pct": 0.500,
    "gf_away_win_pct": 0.500,
    "gf_home_l10_win_pct": 0.500,
    "gf_away_l10_win_pct": 0.500,
    "gf_home_gf_avg": 3.0,
    "gf_away_gf_avg": 3.0,
    "gf_home_ga_avg": 3.0,
    "gf_away_ga_avg": 3.0,
    "gf_home_goal_diff": 0.0,
    "gf_away_goal_diff": 0.0,

    # Special teams
    "gf_home_pp_pct": 0.20,
    "gf_away_pp_pct": 0.20,
    "gf_home_pk_pct": 0.80,
    "gf_away_pk_pct": 0.80,

    # Physicality
    "gf_home_hits_avg": 20.0,
    "gf_away_hits_avg": 20.0,
    "gf_home_blocks_avg": 12.0,
    "gf_away_blocks_avg": 12.0,

    # Goalie
    "gf_home_goalie_sv_pct": 0.910,
    "gf_away_goalie_sv_pct": 0.910,
    "gf_home_goalie_gaa": 2.80,
    "gf_away_goalie_gaa": 2.80,

    # Elo (raw ratings + derived)
    "gf_home_elo": 1500.0,
    "gf_away_elo": 1500.0,
    "gf_elo_diff": 0.0,
    "gf_elo_home_prob": 0.55,

    # Rest / Travel
    "gf_home_days_rest": 2,
    "gf_away_days_rest": 2,
    "gf_home_b2b": 0,
    "gf_away_b2b": 0,
    "gf_rest_advantage": 0,
    "gf_travel_miles": 0.0,
    "gf_timezone_diff": 0,

    # Streaks
    "gf_home_streak": 0,
    "gf_away_streak": 0,

    # Odds-derived
    "gf_spread": 0.0,
    "gf_total_line": 6.0,
    "gf_home_implied_prob": 0.50,
    "gf_over_odds_american": -110,
    "gf_under_odds_american": -110,
    "gf_home_spread_odds_american": -110,
    "gf_away_spread_odds_american": -110,

    # Context
    "gf_is_divisional": 0,
    "gf_home_home_win_pct": 0.550,
    "gf_away_away_win_pct": 0.450,
    "gf_altitude_diff": 0,

    # Momentum (L5 goal diff vs season goal diff — positive = trending up)
    "gf_home_momentum": 0.0,
    "gf_away_momentum": 0.0,
    # L5 scoring (recent form for totals model)
    "gf_home_l5_gf_avg": 3.0,
    "gf_away_l5_gf_avg": 3.0,
    "gf_home_l5_ga_avg": 3.0,
    "gf_away_l5_ga_avg": 3.0,

    # Combined predictions
    "gf_predicted_total": 6.0,
    "gf_predicted_margin": 0.0,
}


class NHLGameFeatureExtractor:
    """Extract game-level features for NHL full-game predictions."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(SPORT_DIR, "database", "nhl_predictions_v2.db")
        self.db_path = db_path

    def extract(self, game_date: str, home_team: str, away_team: str,
                venue: str = None) -> Dict:
        """
        Extract all game features. Returns dict with ~42 gf_* features.
        All data is from BEFORE game_date (temporal safety).
        """
        features = dict(DEFAULT_FEATURES)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            # 1. Team rolling stats
            self._add_team_stats(conn, features, home_team, away_team, game_date)

            # 2. Goalie stats
            self._add_goalie_stats(conn, features, home_team, away_team)

            # 3. Elo ratings
            self._add_elo_features(features, home_team, away_team)

            # 4. Rest & travel
            self._add_rest_travel(conn, features, home_team, away_team, game_date)

            # 5. Streaks
            self._add_streaks(conn, features, home_team, away_team, game_date)

            # 6. Odds-derived
            self._add_odds_features(conn, features, home_team, away_team, game_date)

            # 7. Context
            self._add_context(features, home_team, away_team)

            # 8. Derived predictions
            home_gf = features["gf_home_gf_avg"]
            away_gf = features["gf_away_gf_avg"]
            home_ga = features["gf_home_ga_avg"]
            away_ga = features["gf_away_ga_avg"]
            features["gf_predicted_total"] = round((home_gf + away_ga + away_gf + home_ga) / 2, 2)
            features["gf_predicted_margin"] = round(
                (home_gf - home_ga) - (away_gf - away_ga), 2
            )

        except Exception as e:
            print(f"[NHL Features] Error extracting features: {e}")
        finally:
            conn.close()

        return features

    def _add_team_stats(self, conn, features, home, away, game_date):
        """Add team rolling stats from team_rolling_stats table."""
        for team, prefix in [(home, "home"), (away, "away")]:
            # Season stats
            row = conn.execute("""
                SELECT * FROM team_rolling_stats
                WHERE team = ? AND window = 'season' AND as_of_date <= ?
                ORDER BY as_of_date DESC LIMIT 1
            """, (team, game_date)).fetchone()

            season_gf_avg = 3.0
            season_goal_diff = 0.0
            if row:
                season_gf_avg = row["goals_for_avg"] or 3.0
                season_goal_diff = row["goal_diff_avg"] or 0.0
                features[f"gf_{prefix}_win_pct"] = row["win_pct"] or 0.5
                features[f"gf_{prefix}_gf_avg"] = season_gf_avg
                features[f"gf_{prefix}_ga_avg"] = row["goals_against_avg"] or 3.0
                features[f"gf_{prefix}_goal_diff"] = season_goal_diff
                features[f"gf_{prefix}_hits_avg"] = row["avg_hits_per_game"] or 20.0
                features[f"gf_{prefix}_blocks_avg"] = row["avg_blocks_per_game"] or 12.0
                features[f"gf_{prefix}_home_win_pct" if prefix == "home" else f"gf_{prefix}_away_win_pct"] = (
                    row["home_win_pct"] if prefix == "home" else row["away_win_pct"]
                ) or 0.5

                if row["pp_pct"] is not None:
                    features[f"gf_{prefix}_pp_pct"] = row["pp_pct"]
                if row["pk_pct"] is not None:
                    features[f"gf_{prefix}_pk_pct"] = row["pk_pct"]

            # L10 stats
            row10 = conn.execute("""
                SELECT win_pct FROM team_rolling_stats
                WHERE team = ? AND window = 'L10' AND as_of_date <= ?
                ORDER BY as_of_date DESC LIMIT 1
            """, (team, game_date)).fetchone()

            if row10:
                features[f"gf_{prefix}_l10_win_pct"] = row10["win_pct"] or 0.5

            # L5 stats — used for momentum and recent totals form
            row5 = conn.execute("""
                SELECT goals_for_avg, goals_against_avg, goal_diff_avg
                FROM team_rolling_stats
                WHERE team = ? AND window = 'L5' AND as_of_date <= ?
                ORDER BY as_of_date DESC LIMIT 1
            """, (team, game_date)).fetchone()

            if row5:
                l5_gf = row5["goals_for_avg"] or season_gf_avg
                l5_ga = row5["goals_against_avg"] or features.get(f"gf_{prefix}_ga_avg", 3.0)
                l5_diff = row5["goal_diff_avg"] or 0.0
                features[f"gf_{prefix}_l5_gf_avg"] = l5_gf
                features[f"gf_{prefix}_l5_ga_avg"] = l5_ga
                # Momentum = recent goal diff minus season goal diff (positive = heating up)
                features[f"gf_{prefix}_momentum"] = round(l5_diff - season_goal_diff, 3)

    def _add_goalie_stats(self, conn, features, home, away):
        """Add starting goalie quality from goalie_stats table."""
        for team, prefix in [(home, "home"), (away, "away")]:
            row = conn.execute("""
                SELECT save_percentage, goals_against_avg
                FROM goalie_stats
                WHERE team = ? AND games_started > 5
                ORDER BY games_started DESC LIMIT 1
            """, (team,)).fetchone()

            if row:
                features[f"gf_{prefix}_goalie_sv_pct"] = row["save_percentage"] or 0.910
                features[f"gf_{prefix}_goalie_gaa"] = row["goals_against_avg"] or 2.80

    def _add_elo_features(self, features, home, away):
        """Add Elo rating features."""
        try:
            from elo_engine import EloEngine
            elo = EloEngine(sport="nhl")
            if elo.load():
                features["gf_home_elo"] = elo.get_rating(home) or 1500.0
                features["gf_away_elo"] = elo.get_rating(away) or 1500.0
                features["gf_elo_diff"] = elo.get_elo_diff(home, away)
                features["gf_elo_home_prob"] = elo.predict_home_win(home, away)
        except Exception:
            pass  # Use defaults

    def _add_rest_travel(self, conn, features, home, away, game_date):
        """Add rest days, back-to-back flags, and travel distance."""
        for team, prefix in [(home, "home"), (away, "away")]:
            row = conn.execute("""
                SELECT game_date FROM games
                WHERE (home_team = ? OR away_team = ?) AND game_date < ?
                  AND game_state = 'FINAL'
                ORDER BY game_date DESC LIMIT 1
            """, (team, team, game_date)).fetchone()

            if row:
                last_date = datetime.strptime(row["game_date"], "%Y-%m-%d")
                current = datetime.strptime(game_date, "%Y-%m-%d")
                days_rest = (current - last_date).days
                features[f"gf_{prefix}_days_rest"] = days_rest
                features[f"gf_{prefix}_b2b"] = 1 if days_rest <= 1 else 0

        features["gf_rest_advantage"] = (
            features["gf_home_days_rest"] - features["gf_away_days_rest"]
        )

        # Travel distance (away team only)
        try:
            from arena_data import get_travel_distance, get_timezone_diff, get_altitude
            dist = get_travel_distance(away, home)
            if dist:
                features["gf_travel_miles"] = dist
            tz = get_timezone_diff(away, home)
            if tz is not None:
                features["gf_timezone_diff"] = abs(tz)

            # Altitude difference
            alt_home = get_altitude(home) or 0
            alt_away = get_altitude(away) or 0
            features["gf_altitude_diff"] = alt_home - alt_away
        except ImportError:
            pass

    def _add_streaks(self, conn, features, home, away, game_date):
        """Calculate current win/loss streak for each team."""
        for team, prefix in [(home, "home"), (away, "away")]:
            rows = conn.execute("""
                SELECT home_team, home_score, away_score FROM games
                WHERE (home_team = ? OR away_team = ?) AND game_date < ?
                  AND game_state = 'FINAL'
                ORDER BY game_date DESC LIMIT 10
            """, (team, team, game_date)).fetchall()

            streak = 0
            for r in rows:
                is_home = r["home_team"] == team
                won = (is_home and r["home_score"] > r["away_score"]) or \
                      (not is_home and r["away_score"] > r["home_score"])
                if streak == 0:
                    streak = 1 if won else -1
                elif (streak > 0 and won) or (streak < 0 and not won):
                    streak += 1 if won else -1
                else:
                    break

            features[f"gf_{prefix}_streak"] = streak

    def _add_odds_features(self, conn, features, home, away, game_date):
        """Add odds-derived features from game_lines table."""
        row = conn.execute("""
            SELECT spread, over_under, home_moneyline, away_moneyline,
                   over_odds, under_odds, home_spread_odds, away_spread_odds
            FROM game_lines
            WHERE home_team = ? AND away_team = ?
              AND game_date = ?
            LIMIT 1
        """, (home, away, game_date)).fetchone()

        if row:
            if row["spread"] is not None:
                features["gf_spread"] = row["spread"]
            if row["over_under"] is not None:
                features["gf_total_line"] = row["over_under"]
            if row["home_moneyline"] is not None:
                ml = row["home_moneyline"]
                if ml < 0:
                    features["gf_home_implied_prob"] = round(abs(ml) / (abs(ml) + 100), 4)
                else:
                    features["gf_home_implied_prob"] = round(100 / (ml + 100), 4)
            if row["over_odds"] is not None:
                features["gf_over_odds_american"] = row["over_odds"]
            if row["under_odds"] is not None:
                features["gf_under_odds_american"] = row["under_odds"]
            if row["home_spread_odds"] is not None:
                features["gf_home_spread_odds_american"] = row["home_spread_odds"]
            if row["away_spread_odds"] is not None:
                features["gf_away_spread_odds_american"] = row["away_spread_odds"]

    def _add_context(self, features, home, away):
        """Add contextual features (divisional, etc)."""
        # NHL divisions (2025-26)
        divisions = {
            "Atlantic": ["BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR"],
            "Metropolitan": ["CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"],
            "Central": ["ARI", "CHI", "COL", "DAL", "MIN", "NSH", "STL", "WPG", "UTA"],
            "Pacific": ["ANA", "CGY", "EDM", "LAK", "SJS", "SEA", "VAN", "VGK"],
        }

        home_div = away_div = None
        for div, teams in divisions.items():
            if home in teams:
                home_div = div
            if away in teams:
                away_div = div

        features["gf_is_divisional"] = 1 if (home_div and home_div == away_div) else 0

    def feature_names(self) -> list:
        """Return ordered list of feature names."""
        return sorted(DEFAULT_FEATURES.keys())

    def feature_count(self) -> int:
        """Return total number of features."""
        return len(DEFAULT_FEATURES)


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    extractor = NHLGameFeatureExtractor()
    features = extractor.extract("2025-10-15", "BOS", "NYR")
    print(f"\nNHL Game Features ({len(features)} total):")
    print("-" * 50)
    for k, v in sorted(features.items()):
        print(f"  {k:<35} {v}")
