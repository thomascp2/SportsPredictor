"""
NBA Game-Level Feature Extractor
=================================

Extracts ~45 features for full-game predictions (moneyline, spread, total).
All features use data available BEFORE game start (temporal safety).

NBA-specific focus: Pace is critical for totals, rest matters more than
any other sport (back-to-backs swing win rates 2-4%).

Sources:
    - team_rolling_stats table (from team_stats_collector.py)
    - games table (schedule, recent results)
    - player_game_logs table (star player availability detection)
    - elo_ratings JSON (from shared/elo_engine.py)
    - arena_data.py (travel distance, timezone, altitude)
    - game_lines table (odds-derived features)

Returns ~45 features per game.
"""

import sqlite3
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, Optional

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
    "gf_home_ppg": 112.0,
    "gf_away_ppg": 112.0,
    "gf_home_papg": 112.0,
    "gf_away_papg": 112.0,
    "gf_home_point_diff": 0.0,
    "gf_away_point_diff": 0.0,

    # Efficiency (NBA-specific — critical for game prediction)
    "gf_home_off_rtg": 110.0,
    "gf_away_off_rtg": 110.0,
    "gf_home_def_rtg": 110.0,
    "gf_away_def_rtg": 110.0,
    "gf_home_net_rtg": 0.0,
    "gf_away_net_rtg": 0.0,
    "gf_home_pace": 100.0,
    "gf_away_pace": 100.0,
    "gf_pace_product": 100.0,     # Estimated game pace (both teams)

    # Shooting
    "gf_home_fg_pct": 0.460,
    "gf_away_fg_pct": 0.460,
    "gf_home_3pt_pg": 12.0,
    "gf_away_3pt_pg": 12.0,
    "gf_home_ft_pct": 0.780,
    "gf_away_ft_pct": 0.780,

    # Other
    "gf_home_ast_pg": 25.0,
    "gf_away_ast_pg": 25.0,
    "gf_home_tov_pg": 14.0,
    "gf_away_tov_pg": 14.0,
    "gf_home_reb_pg": 44.0,
    "gf_away_reb_pg": 44.0,

    # Elo (raw ratings + derived)
    "gf_home_elo": 1500.0,
    "gf_away_elo": 1500.0,
    "gf_elo_diff": 0.0,
    "gf_elo_home_prob": 0.575,

    # Rest / Travel (NBA rest is HUGE — 2-4% swing)
    "gf_home_days_rest": 2,
    "gf_away_days_rest": 2,
    "gf_home_b2b": 0,
    "gf_away_b2b": 0,
    "gf_home_3in4": 0,
    "gf_away_3in4": 0,
    "gf_rest_advantage": 0,
    "gf_travel_miles": 0.0,
    "gf_timezone_diff": 0,

    # Streaks
    "gf_home_streak": 0,
    "gf_away_streak": 0,

    # Odds-derived
    "gf_spread": 0.0,
    "gf_total_line": 224.0,
    "gf_home_implied_prob": 0.50,
    "gf_over_odds_american": -110,
    "gf_under_odds_american": -110,
    "gf_home_spread_odds_american": -110,
    "gf_away_spread_odds_american": -110,

    # Context
    "gf_is_divisional": 0,
    "gf_home_home_win_pct": 0.600,
    "gf_away_away_win_pct": 0.400,
    "gf_altitude_diff": 0,

    # Momentum (L5 point diff vs season point diff — positive = trending up)
    "gf_home_momentum": 0.0,
    "gf_away_momentum": 0.0,
    # L5 scoring (recent form for totals model)
    "gf_home_l5_ppg": 112.0,
    "gf_away_l5_ppg": 112.0,
    "gf_home_l5_papg": 112.0,
    "gf_away_l5_papg": 112.0,

    # Derived predictions
    "gf_predicted_total": 224.0,
    "gf_predicted_margin": 0.0,
}


class NBAGameFeatureExtractor:
    """Extract game-level features for NBA full-game predictions."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(SPORT_DIR, "database", "nba_predictions.db")
        self.db_path = db_path

    def extract(self, game_date: str, home_team: str, away_team: str,
                venue: str = None) -> Dict:
        """Extract all game features. Returns dict with ~45 gf_* features."""
        features = dict(DEFAULT_FEATURES)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Run each feature group independently so one failure doesn't kill the rest
        for method_name, method in [
            ("team_stats", lambda: self._add_team_stats(conn, features, home_team, away_team, game_date)),
            ("elo", lambda: self._add_elo_features(features, home_team, away_team)),
            ("rest_travel", lambda: self._add_rest_travel(conn, features, home_team, away_team, game_date)),
            ("streaks", lambda: self._add_streaks(conn, features, home_team, away_team, game_date)),
            ("odds", lambda: self._add_odds_features(conn, features, home_team, away_team, game_date)),
            ("context", lambda: self._add_context(features, home_team, away_team)),
        ]:
            try:
                method()
            except Exception as e:
                print(f"[NBA Features] {method_name} error: {e}")

        # Always calculate derived features from whatever loaded
        try:
            features["gf_pace_product"] = round(
                (features["gf_home_pace"] * features["gf_away_pace"]) / 100.0, 1
            )
            home_ppg = features["gf_home_ppg"]
            away_ppg = features["gf_away_ppg"]
            home_papg = features["gf_home_papg"]
            away_papg = features["gf_away_papg"]
            features["gf_predicted_total"] = round((home_ppg + away_papg + away_ppg + home_papg) / 2, 1)
            features["gf_predicted_margin"] = round(
                features["gf_home_point_diff"] - features["gf_away_point_diff"], 1
            )
        except Exception as e:
            print(f"[NBA Features] derived calc error: {e}")

        conn.close()

        return features

    def _add_team_stats(self, conn, features, home, away, game_date):
        """Add team rolling stats."""
        for team, prefix in [(home, "home"), (away, "away")]:
            row = conn.execute("""
                SELECT * FROM team_rolling_stats
                WHERE team = ? AND window = 'season' AND as_of_date <= ?
                ORDER BY as_of_date DESC LIMIT 1
            """, (team, game_date)).fetchone()

            if row:
                features[f"gf_{prefix}_win_pct"] = row["win_pct"] or 0.5
                features[f"gf_{prefix}_ppg"] = row["points_per_game"] or 112.0
                features[f"gf_{prefix}_papg"] = row["points_allowed_per_game"] or 112.0
                features[f"gf_{prefix}_point_diff"] = row["point_diff_avg"] or 0.0
                features[f"gf_{prefix}_fg_pct"] = row["fg_pct"] or 0.46
                features[f"gf_{prefix}_3pt_pg"] = row["threes_per_game"] or 12.0
                features[f"gf_{prefix}_ast_pg"] = row["assists_per_game"] or 25.0
                features[f"gf_{prefix}_tov_pg"] = row["turnovers_per_game"] or 14.0
                features[f"gf_{prefix}_reb_pg"] = row["rebounds_per_game"] or 44.0

                # ft_pct may not exist — compute from ftm/fta if available
                try:
                    if row["fta_per_game"] and row["fta_per_game"] > 0:
                        features[f"gf_{prefix}_ft_pct"] = round(row["ftm_per_game"] / row["fta_per_game"], 3)
                except (KeyError, TypeError):
                    pass
                if row["pace_estimate"] is not None:
                    features[f"gf_{prefix}_pace"] = row["pace_estimate"]
                if row["off_rating_estimate"] is not None:
                    features[f"gf_{prefix}_off_rtg"] = row["off_rating_estimate"]
                if row["def_rating_estimate"] is not None:
                    features[f"gf_{prefix}_def_rtg"] = row["def_rating_estimate"]
                if row["net_rating_estimate"] is not None:
                    features[f"gf_{prefix}_net_rtg"] = row["net_rating_estimate"]

                split_col = "home_win_pct" if prefix == "home" else "away_win_pct"
                feat_key = f"gf_{prefix}_{'home' if prefix == 'home' else 'away'}_win_pct"
                if row[split_col] is not None:
                    features[feat_key] = row[split_col]

            # L10 recent form
            row10 = conn.execute("""
                SELECT win_pct FROM team_rolling_stats
                WHERE team = ? AND window = 'L10' AND as_of_date <= ?
                ORDER BY as_of_date DESC LIMIT 1
            """, (team, game_date)).fetchone()

            if row10:
                features[f"gf_{prefix}_l10_win_pct"] = row10["win_pct"] or 0.5

            # L5 recent form — momentum + recent scoring for totals model
            season_ppg = features.get(f"gf_{prefix}_ppg", 112.0)
            season_diff = features.get(f"gf_{prefix}_point_diff", 0.0)
            row5 = conn.execute("""
                SELECT points_per_game, points_allowed_per_game, point_diff_avg
                FROM team_rolling_stats
                WHERE team = ? AND window = 'L5' AND as_of_date <= ?
                ORDER BY as_of_date DESC LIMIT 1
            """, (team, game_date)).fetchone()

            if row5:
                l5_ppg = row5["points_per_game"] or season_ppg
                l5_papg = row5["points_allowed_per_game"] or features.get(f"gf_{prefix}_papg", 112.0)
                l5_diff = row5["point_diff_avg"] or 0.0
                features[f"gf_{prefix}_l5_ppg"] = l5_ppg
                features[f"gf_{prefix}_l5_papg"] = l5_papg
                # Momentum = recent point diff minus season point diff
                features[f"gf_{prefix}_momentum"] = round(l5_diff - season_diff, 2)

    def _add_elo_features(self, features, home, away):
        """Add Elo ratings."""
        try:
            from elo_engine import EloEngine
            elo = EloEngine(sport="nba")
            if elo.load():
                features["gf_home_elo"] = elo.get_rating(home) or 1500.0
                features["gf_away_elo"] = elo.get_rating(away) or 1500.0
                features["gf_elo_diff"] = elo.get_elo_diff(home, away)
                features["gf_elo_home_prob"] = elo.predict_home_win(home, away)
        except Exception:
            pass

    def _add_rest_travel(self, conn, features, home, away, game_date):
        """Add rest, B2B, 3-in-4, and travel features."""
        for team, prefix in [(home, "home"), (away, "away")]:
            # Last game
            rows = conn.execute("""
                SELECT game_date FROM games
                WHERE (home_team = ? OR away_team = ?) AND game_date < ?
                  AND home_score IS NOT NULL
                ORDER BY game_date DESC LIMIT 3
            """, (team, team, game_date)).fetchall()

            if rows:
                last_date = datetime.strptime(rows[0]["game_date"], "%Y-%m-%d")
                current = datetime.strptime(game_date, "%Y-%m-%d")
                days_rest = (current - last_date).days
                features[f"gf_{prefix}_days_rest"] = days_rest
                features[f"gf_{prefix}_b2b"] = 1 if days_rest <= 1 else 0

                # 3 games in 4 nights
                if len(rows) >= 3:
                    third_date = datetime.strptime(rows[2]["game_date"], "%Y-%m-%d")
                    span = (current - third_date).days
                    features[f"gf_{prefix}_3in4"] = 1 if span <= 4 else 0

        features["gf_rest_advantage"] = (
            features["gf_home_days_rest"] - features["gf_away_days_rest"]
        )

        # Travel distance
        try:
            from arena_data import get_travel_distance, get_timezone_diff, get_altitude
            dist = get_travel_distance(away, home)
            if dist:
                features["gf_travel_miles"] = dist
            tz = get_timezone_diff(away, home)
            if tz is not None:
                features["gf_timezone_diff"] = abs(tz)
            alt_home = get_altitude(home) or 0
            alt_away = get_altitude(away) or 0
            features["gf_altitude_diff"] = alt_home - alt_away
        except ImportError:
            pass

    def _add_streaks(self, conn, features, home, away, game_date):
        """Calculate current win/loss streak."""
        for team, prefix in [(home, "home"), (away, "away")]:
            rows = conn.execute("""
                SELECT home_team, home_score, away_score FROM games
                WHERE (home_team = ? OR away_team = ?) AND game_date < ?
                  AND home_score IS NOT NULL
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
        """Add odds from game_lines table. Handles team abbreviation variants."""
        # Try exact match first, then try all known abbreviation variants
        row = conn.execute("""
            SELECT spread, over_under, home_moneyline, away_moneyline,
                   over_odds, under_odds, home_spread_odds, away_spread_odds
            FROM game_lines
            WHERE home_team = ? AND away_team = ? AND game_date = ?
            LIMIT 1
        """, (home, away, game_date)).fetchone()

        # Fallback: search by date and partial match (handles NY/NYK mismatches)
        if not row:
            rows = conn.execute("""
                SELECT home_team, away_team, spread, over_under,
                       home_moneyline, away_moneyline,
                       over_odds, under_odds, home_spread_odds, away_spread_odds
                FROM game_lines
                WHERE game_date = ?
            """, (game_date,)).fetchall()

            # Try to match using first 2-3 chars
            for r in rows:
                h = r["home_team"] or ""
                a = r["away_team"] or ""
                if (h.startswith(home[:2]) or home.startswith(h[:2])) and \
                   (a.startswith(away[:2]) or away.startswith(a[:2])):
                    row = r
                    break

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
        """Add contextual features."""
        # NBA divisions (2025-26)
        divisions = {
            "Atlantic": ["BOS", "BKN", "NYK", "PHI", "TOR"],
            "Central": ["CHI", "CLE", "DET", "IND", "MIL"],
            "Southeast": ["ATL", "CHA", "MIA", "ORL", "WAS"],
            "Northwest": ["DEN", "MIN", "OKC", "POR", "UTA"],
            "Pacific": ["GSW", "LAC", "LAL", "PHX", "SAC"],
            "Southwest": ["DAL", "HOU", "MEM", "NOP", "SAS"],
        }

        home_div = away_div = None
        for div, teams in divisions.items():
            if home in teams:
                home_div = div
            if away in teams:
                away_div = div

        features["gf_is_divisional"] = 1 if (home_div and home_div == away_div) else 0

    def feature_names(self) -> list:
        return sorted(DEFAULT_FEATURES.keys())

    def feature_count(self) -> int:
        return len(DEFAULT_FEATURES)


if __name__ == "__main__":
    extractor = NBAGameFeatureExtractor()
    features = extractor.extract("2025-11-15", "BOS", "LAL")
    print(f"\nNBA Game Features ({len(features)} total):")
    print("-" * 50)
    for k, v in sorted(features.items()):
        print(f"  {k:<35} {v}")
