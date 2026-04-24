"""
MLB Game-Level Feature Extractor
=================================

Extracts ~50 features for full-game predictions (moneyline, spread, total).
MLB-specific: starting pitcher is ~40% of game variance, weather/park effects
are enormous, and bullpen fatigue is a key edge.

Sources:
    - team_rolling_stats table (from team_stats_collector.py)
    - games table (schedule, recent results)
    - game_context table (venue, starters, weather, odds)
    - player_game_logs table (pitcher stats)
    - elo_ratings JSON (from shared/elo_engine.py)
    - park_factors.py (venue effects — already built)
    - weather_client.py (temp, wind, humidity — already built)

Returns ~50 features per game.
"""

import sqlite3
import os
import sys
from datetime import datetime
from typing import Dict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SPORT_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SPORT_DIR)

sys.path.insert(0, os.path.join(SPORT_DIR, "scripts"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "shared"))

# ── Default features ──────────────────────────────────────────────────────────

DEFAULT_FEATURES = {
    # Team strength
    "gf_home_win_pct": 0.500,
    "gf_away_win_pct": 0.500,
    "gf_home_l10_win_pct": 0.500,
    "gf_away_l10_win_pct": 0.500,
    "gf_home_rpg": 4.5,
    "gf_away_rpg": 4.5,
    "gf_home_rapg": 4.5,
    "gf_away_rapg": 4.5,
    "gf_home_run_diff": 0.0,
    "gf_away_run_diff": 0.0,
    "gf_home_pyth_win_pct": 0.500,
    "gf_away_pyth_win_pct": 0.500,

    # Offense
    "gf_home_hr_pg": 1.1,
    "gf_away_hr_pg": 1.1,
    "gf_home_hits_pg": 8.5,
    "gf_away_hits_pg": 8.5,
    "gf_home_k_pg": 8.5,          # Batting strikeouts (higher = worse offense)
    "gf_away_k_pg": 8.5,
    "gf_home_bb_pg": 3.5,
    "gf_away_bb_pg": 3.5,
    "gf_home_sb_pg": 0.7,
    "gf_away_sb_pg": 0.7,

    # Starting pitcher (THE most important MLB feature)
    "gf_home_sp_era": 4.00,
    "gf_away_sp_era": 4.00,
    "gf_home_sp_whip": 1.25,
    "gf_away_sp_whip": 1.25,
    "gf_home_sp_k9": 8.5,
    "gf_away_sp_k9": 8.5,
    "gf_home_sp_innings": 0.0,    # Season IP (proxy for reliability)
    "gf_away_sp_innings": 0.0,

    # Elo (raw ratings + derived)
    "gf_home_elo": 1500.0,
    "gf_away_elo": 1500.0,
    "gf_elo_diff": 0.0,
    "gf_elo_home_prob": 0.535,

    # Rest (less impactful in MLB than NBA/NHL, but bullpen rest matters)
    "gf_home_days_rest": 1,
    "gf_away_days_rest": 1,
    "gf_travel_miles": 0.0,

    # Streaks
    "gf_home_streak": 0,
    "gf_away_streak": 0,

    # Park factors (from existing park_factors.py)
    "gf_park_hr_factor": 1.00,
    "gf_park_runs_factor": 1.00,
    "gf_park_hits_factor": 1.00,
    "gf_is_dome": 0,
    "gf_altitude": 0,

    # Weather
    "gf_temperature": 72.0,
    "gf_wind_speed": 5.0,
    "gf_wind_effect": 0.0,        # -1 to +1 (blowing in vs blowing out)

    # Odds-derived
    "gf_spread": 0.0,
    "gf_total_line": 9.0,
    "gf_home_implied_prob": 0.50,
    "gf_over_odds_american": -110,
    "gf_under_odds_american": -110,
    "gf_home_spread_odds_american": -110,
    "gf_away_spread_odds_american": -110,

    # Context
    "gf_is_divisional": 0,
    "gf_home_home_win_pct": 0.540,
    "gf_away_away_win_pct": 0.460,

    # Derived predictions
    "gf_predicted_total": 9.0,
    "gf_predicted_margin": 0.0,
}


class MLBGameFeatureExtractor:
    """Extract game-level features for MLB full-game predictions."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(SPORT_DIR, "database", "mlb_predictions.db")
        self.db_path = db_path

    def extract(self, game_date: str, home_team: str, away_team: str,
                venue: str = None, home_starter: str = None,
                away_starter: str = None) -> Dict:
        """
        Extract all game features. Returns dict with ~50 gf_* features.

        Args:
            game_date: YYYY-MM-DD
            home_team, away_team: Team abbreviations
            venue: Stadium name (for park factors)
            home_starter, away_starter: Starting pitcher names (optional — auto-looked up from game_context)
        """
        features = dict(DEFAULT_FEATURES)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            # Auto-lookup starters from game_context if not provided
            if not home_starter or not away_starter:
                row = conn.execute("""
                    SELECT home_starter, away_starter
                    FROM game_context
                    WHERE home_team = ? AND away_team = ? AND game_date = ?
                    LIMIT 1
                """, (home_team, away_team, game_date)).fetchone()
                if row:
                    home_starter = home_starter or row["home_starter"]
                    away_starter = away_starter or row["away_starter"]

            self._add_team_stats(conn, features, home_team, away_team, game_date)
            self._add_pitcher_stats(conn, features, home_starter, away_starter, game_date)
            self._add_park_factors(features, venue, home_team)
            self._add_weather(features, venue, game_date)
            self._add_elo_features(features, home_team, away_team)
            self._add_rest(conn, features, home_team, away_team, game_date)
            self._add_streaks(conn, features, home_team, away_team, game_date)
            self._add_odds_features(conn, features, home_team, away_team, game_date)
            self._add_context(features, home_team, away_team)

            # Derived predictions
            home_rpg = features["gf_home_rpg"]
            away_rpg = features["gf_away_rpg"]
            home_rapg = features["gf_home_rapg"]
            away_rapg = features["gf_away_rapg"]
            park_runs = features["gf_park_runs_factor"]

            home_sp_era = features["gf_home_sp_era"]
            away_sp_era = features["gf_away_sp_era"]
            home_sp_ip = features["gf_home_sp_innings"]
            away_sp_ip = features["gf_away_sp_innings"]

            if home_sp_ip > 0 or away_sp_ip > 0:
                # SP ERA adjustment for predicted total.
                #
                # SP_WEIGHT = 0.50 is a reasonable prior for a typical MLB starter
                # (~5-6 innings). It means a SP with ERA half the league average
                # (e.g. 2.00 vs 4.00) reduces expected runs by 25% (not 50%), which
                # is conservative and intentional — the bullpen covers the rest.
                #
                # CALIBRATION NOTE (recalibrate when game_prediction_outcomes has
                # 500+ graded total rows with real SP data):
                #   Run: python mlb/features/game_features.py --calibrate
                #   The calibrate_sp_weight() method will compute the SP_WEIGHT
                #   that minimizes RMSE on historical predicted vs actual totals.
                #   Expected recalibration window: ~Aug 2026 (mid-season with full
                #   starter workloads and enough outcomes to trust the signal).
                #
                # KNOWN LIMITATION: SP_WEIGHT doesn't scale with ace quality.
                # An elite front-line SP (ERA < 2.50, K/9 > 11) likely warrants
                # weight 0.60-0.65. Add a K/9 or FIP-based tier adjustment here
                # once we have enough outcomes to validate the multiplier.
                LEAGUE_AVG_ERA = 4.00
                # SP_WEIGHT calibrated retroactively on 226 graded games (Apr 24 2026).
                # Optimal was 0.20; using 0.25 conservatively pending 500-game threshold.
                # Re-run: python mlb/features/game_features.py --calibrate
                SP_WEIGHT = 0.25

                # Guard: cap ERA inputs to prevent tiny or extreme sample sizes
                # from producing nonsensical adjustment factors.
                # Floor at 1.50 (no active SP is truly sub-1.50 over a full season).
                # Ceiling at 7.00 (above this ERA the SP likely won't finish the game).
                home_sp_era_capped = max(1.50, min(7.00, home_sp_era))
                away_sp_era_capped = max(1.50, min(7.00, away_sp_era))

                away_sp_adj = ((1 - SP_WEIGHT) + SP_WEIGHT * away_sp_era_capped / LEAGUE_AVG_ERA
                               if away_sp_ip > 0 else 1.0)
                home_sp_adj = ((1 - SP_WEIGHT) + SP_WEIGHT * home_sp_era_capped / LEAGUE_AVG_ERA
                               if home_sp_ip > 0 else 1.0)

                # Final safety clamp: adjustment factor must stay in [0.55, 1.45].
                # Prevents edge cases (e.g. 1-inning SP sample) from collapsing or
                # exploding the predicted total.
                away_sp_adj = max(0.55, min(1.45, away_sp_adj))
                home_sp_adj = max(0.55, min(1.45, home_sp_adj))

                home_expected = home_rpg * away_sp_adj
                away_expected = away_rpg * home_sp_adj
                features["gf_predicted_total"] = round((home_expected + away_expected) * park_runs, 1)
            else:
                features["gf_predicted_total"] = round(
                    ((home_rpg + away_rapg + away_rpg + home_rapg) / 2) * park_runs, 1
                )

            features["gf_predicted_margin"] = round(
                (home_rpg - home_rapg) - (away_rpg - away_rapg), 2
            )

        except Exception as e:
            print(f"[MLB Features] Error: {e}")
        finally:
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
                features[f"gf_{prefix}_rpg"] = row["runs_per_game"] or 4.5
                features[f"gf_{prefix}_rapg"] = row["runs_allowed_per_game"] or 4.5
                features[f"gf_{prefix}_run_diff"] = row["run_diff_per_game"] or 0.0
                features[f"gf_{prefix}_pyth_win_pct"] = row["pythagorean_win_pct"] or 0.5

                if row["hits_per_game"] is not None:
                    features[f"gf_{prefix}_hits_pg"] = row["hits_per_game"]
                if row["hr_per_game"] is not None:
                    features[f"gf_{prefix}_hr_pg"] = row["hr_per_game"]
                if row["k_per_game_batting"] is not None:
                    features[f"gf_{prefix}_k_pg"] = row["k_per_game_batting"]
                if row["bb_per_game_batting"] is not None:
                    features[f"gf_{prefix}_bb_pg"] = row["bb_per_game_batting"]
                if row["sb_per_game"] is not None:
                    features[f"gf_{prefix}_sb_pg"] = row["sb_per_game"]

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

    def _add_pitcher_stats(self, conn, features, home_sp, away_sp, game_date):
        """Add starting pitcher stats from player_game_logs."""
        if not home_sp and not away_sp:
            return

        for pitcher, prefix in [(home_sp, "home"), (away_sp, "away")]:
            if not pitcher:
                continue

            rows = conn.execute("""
                SELECT innings_pitched, earned_runs, strikeouts_pitched,
                       walks_allowed, hits_allowed
                FROM player_game_logs
                WHERE player_name = ? AND player_type = 'pitcher' AND game_date < ?
                ORDER BY game_date DESC LIMIT 10
            """, (pitcher, game_date)).fetchall()

            if not rows:
                continue

            total_ip = sum(r["innings_pitched"] or 0 for r in rows)
            total_er = sum(r["earned_runs"] or 0 for r in rows)
            total_k = sum(r["strikeouts_pitched"] or 0 for r in rows)
            total_bb = sum(r["walks_allowed"] or 0 for r in rows)
            total_h = sum(r["hits_allowed"] or 0 for r in rows)

            if total_ip > 0:
                features[f"gf_{prefix}_sp_era"] = round(total_er * 9 / total_ip, 2)
                features[f"gf_{prefix}_sp_whip"] = round((total_bb + total_h) / total_ip, 2)
                features[f"gf_{prefix}_sp_k9"] = round(total_k * 9 / total_ip, 1)
            features[f"gf_{prefix}_sp_innings"] = round(total_ip, 1)

    def _add_park_factors(self, features, venue, home_team):
        """Add park factors from existing park_factors.py."""
        try:
            from park_factors import (get_park_factor, get_park_factor_by_team,
                                      is_dome_or_retractable, get_altitude)

            # Try venue name first, fall back to team
            try:
                features["gf_park_hr_factor"] = get_park_factor(venue, "hr") if venue else get_park_factor_by_team(home_team, "hr")
                features["gf_park_runs_factor"] = get_park_factor(venue, "runs") if venue else get_park_factor_by_team(home_team, "runs")
                features["gf_park_hits_factor"] = get_park_factor(venue, "hits") if venue else get_park_factor_by_team(home_team, "hits")
            except Exception:
                features["gf_park_hr_factor"] = get_park_factor_by_team(home_team, "hr")
                features["gf_park_runs_factor"] = get_park_factor_by_team(home_team, "runs")
                features["gf_park_hits_factor"] = get_park_factor_by_team(home_team, "hits")

            features["gf_is_dome"] = 1 if is_dome_or_retractable(venue or "") else 0

            alt = get_altitude(venue or "") if venue else None
            if alt:
                features["gf_altitude"] = alt

        except ImportError:
            pass  # park_factors not available

    def _add_weather(self, features, venue, game_date):
        """Add weather features from existing weather_client.py."""
        if features["gf_is_dome"]:
            features["gf_temperature"] = 72.0
            features["gf_wind_speed"] = 0.0
            features["gf_wind_effect"] = 0.0
            return

        try:
            from weather_client import get_game_weather
            weather = get_game_weather(venue, game_date)
            if weather:
                features["gf_temperature"] = weather.get("temperature", 72.0)
                features["gf_wind_speed"] = weather.get("wind_speed", 5.0)
                features["gf_wind_effect"] = weather.get("wind_effect", 0.0)
        except (ImportError, Exception):
            pass

    def _add_elo_features(self, features, home, away):
        """Add Elo ratings."""
        try:
            from elo_engine import EloEngine
            elo = EloEngine(sport="mlb")
            if elo.load():
                features["gf_home_elo"] = elo.get_rating(home) or 1500.0
                features["gf_away_elo"] = elo.get_rating(away) or 1500.0
                features["gf_elo_diff"] = elo.get_elo_diff(home, away)
                features["gf_elo_home_prob"] = elo.predict_home_win(home, away)
        except Exception:
            pass

    def _add_rest(self, conn, features, home, away, game_date):
        """Add days rest."""
        for team, prefix in [(home, "home"), (away, "away")]:
            try:
                row = conn.execute("""
                    SELECT game_date FROM games
                    WHERE (home_team = ? OR away_team = ?) AND game_date < ?
                      AND home_score IS NOT NULL
                    ORDER BY game_date DESC LIMIT 1
                """, (team, team, game_date)).fetchone()

                if row:
                    last = datetime.strptime(row["game_date"], "%Y-%m-%d")
                    current = datetime.strptime(game_date, "%Y-%m-%d")
                    features[f"gf_{prefix}_days_rest"] = (current - last).days
            except Exception:
                pass

        # Travel distance
        try:
            from park_factors import PARK_FACTORS, TEAM_TO_PARK
            import math

            home_park = TEAM_TO_PARK.get(home)
            away_park = TEAM_TO_PARK.get(away)

            if home_park and away_park:
                h = PARK_FACTORS[home_park]
                a = PARK_FACTORS[away_park]
                # Haversine
                R = 3959
                lat1, lon1 = math.radians(a["lat"]), math.radians(a["lon"])
                lat2, lon2 = math.radians(h["lat"]), math.radians(h["lon"])
                dlat, dlon = lat2 - lat1, lon2 - lon1
                aa = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
                features["gf_travel_miles"] = round(R * 2 * math.asin(math.sqrt(aa)), 1)
        except (ImportError, KeyError):
            pass

    def _add_streaks(self, conn, features, home, away, game_date):
        """Calculate win/loss streaks."""
        for team, prefix in [(home, "home"), (away, "away")]:
            try:
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
            except Exception:
                pass

    def _add_odds_features(self, conn, features, home, away, game_date):
        """Add odds from game_lines table (primary) or game_context (fallback)."""
        found = False

        # Primary: game_lines table (populated by fetch_game_odds.py)
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

            if "game_lines" in tables:
                row = conn.execute("""
                    SELECT spread, over_under, home_moneyline, home_implied_prob,
                           over_odds, under_odds, home_spread_odds, away_spread_odds
                    FROM game_lines
                    WHERE home_team = ? AND away_team = ? AND game_date = ?
                    LIMIT 1
                """, (home, away, game_date)).fetchone()

                if row:
                    found = True
                    if row["spread"] is not None:
                        features["gf_spread"] = row["spread"]
                    if row["over_under"] is not None:
                        features["gf_total_line"] = row["over_under"]
                    if row["home_implied_prob"] is not None:
                        features["gf_home_implied_prob"] = row["home_implied_prob"]
                    elif row["home_moneyline"] is not None:
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
        except Exception:
            pass

        # Fallback: game_context table
        if not found:
            try:
                row = conn.execute("""
                    SELECT spread, game_total, home_ml
                    FROM game_context
                    WHERE home_team = ? AND away_team = ? AND game_date = ?
                    LIMIT 1
                """, (home, away, game_date)).fetchone()

                if row:
                    if row["spread"] is not None:
                        features["gf_spread"] = row["spread"]
                    if row["game_total"] is not None:
                        features["gf_total_line"] = row["game_total"]
                    if row["home_ml"] is not None:
                        ml = row["home_ml"]
                        if ml < 0:
                            features["gf_home_implied_prob"] = round(abs(ml) / (abs(ml) + 100), 4)
                        else:
                            features["gf_home_implied_prob"] = round(100 / (ml + 100), 4)
            except Exception:
                pass

    def _add_context(self, features, home, away):
        """Add divisional matchup flag."""
        divisions = {
            "AL East": ["BAL", "BOS", "NYY", "TBR", "TOR"],
            "AL Central": ["CHW", "CLE", "DET", "KCR", "MIN"],
            "AL West": ["HOU", "LAA", "OAK", "SEA", "TEX"],
            "NL East": ["ATL", "MIA", "NYM", "PHI", "WSH"],
            "NL Central": ["CHC", "CIN", "MIL", "PIT", "STL"],
            "NL West": ["ARI", "COL", "LAD", "SDP", "SFG"],
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

    def calibrate_sp_weight(self, min_games: int = 500) -> dict:
        """
        Find the SP_WEIGHT that minimizes RMSE on historical total predictions.

        Reads graded outcomes (game_prediction_outcomes) joined with the
        features_json stored at prediction time, then does a grid search over
        SP_WEIGHT in [0.20, 0.80] to find the value that produces the lowest
        root-mean-square error between predicted and actual totals.

        Returns a dict with 'weight', 'rmse', 'games', and 'ready' flag.
        Call this from the CLI: python mlb/features/game_features.py --calibrate

        DATA GATE: Returns ready=False if fewer than min_games graded total
        rows with real SP data exist. Do not update SP_WEIGHT in code until
        ready=True and the improvement over 0.50 baseline is >= 0.1 RMSE.
        """
        import json as _json

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            rows = conn.execute("""
                SELECT gp.features_json, gpo.actual_total
                FROM game_predictions gp
                JOIN game_prediction_outcomes gpo
                    ON gp.id = gpo.prediction_id
                WHERE gp.bet_type = 'total'
                  AND gpo.actual_total IS NOT NULL
                  AND gpo.actual_total > 0
            """).fetchall()
        except Exception as e:
            conn.close()
            return {"ready": False, "reason": str(e), "games": 0}

        conn.close()

        # Keep only rows where at least one SP had real IP data
        games = []
        for r in rows:
            try:
                f = _json.loads(r["features_json"])
                if f.get("gf_home_sp_innings", 0) > 0 or f.get("gf_away_sp_innings", 0) > 0:
                    games.append((f, r["actual_total"]))
            except Exception:
                continue

        if len(games) < min_games:
            # Use --min-games 200 to run with current season data (~226 games available Apr 24)
            return {
                "ready": False,
                "reason": f"Only {len(games)} graded total rows with SP data — need {min_games}",
                "games": len(games),
                "target_date": "~Aug 2026 (mid-season) for 500-game threshold",
            }

        LEAGUE_AVG_ERA = 4.00

        def rmse_for_weight(weight):
            errors = []
            for f, actual in games:
                h_ip = f.get("gf_home_sp_innings", 0)
                a_ip = f.get("gf_away_sp_innings", 0)
                h_era = max(1.50, min(7.00, f.get("gf_home_sp_era", 4.00)))
                a_era = max(1.50, min(7.00, f.get("gf_away_sp_era", 4.00)))
                park = f.get("gf_park_runs_factor", 1.00)

                a_adj = max(0.55, min(1.45, (1 - weight) + weight * a_era / LEAGUE_AVG_ERA)) if a_ip > 0 else 1.0
                h_adj = max(0.55, min(1.45, (1 - weight) + weight * h_era / LEAGUE_AVG_ERA)) if h_ip > 0 else 1.0

                predicted = (f.get("gf_home_rpg", 4.5) * a_adj + f.get("gf_away_rpg", 4.5) * h_adj) * park
                errors.append((predicted - actual) ** 2)
            return (sum(errors) / len(errors)) ** 0.5

        best_weight, best_rmse = 0.50, rmse_for_weight(0.50)
        for w in [round(x * 0.05, 2) for x in range(4, 17)]:  # 0.20 to 0.80
            r = rmse_for_weight(w)
            if r < best_rmse:
                best_rmse, best_weight = r, w

        baseline_rmse = rmse_for_weight(0.50)
        improvement = baseline_rmse - best_rmse

        return {
            "ready": True,
            "weight": best_weight,
            "rmse": round(best_rmse, 4),
            "baseline_rmse": round(baseline_rmse, 4),
            "improvement": round(improvement, 4),
            "games": len(games),
            "update_code": improvement >= 0.10,
            "note": "Update SP_WEIGHT in game_features.py only if improvement >= 0.10 RMSE",
        }


if __name__ == "__main__":
    import argparse as _ap

    parser = _ap.ArgumentParser(description="MLB Game Feature Extractor")
    parser.add_argument("--calibrate", action="store_true",
                        help="Calibrate SP_WEIGHT from graded outcomes")
    parser.add_argument("--min-games", type=int, default=500,
                        help="Minimum graded games required for calibration (default: 500)")
    args = parser.parse_args()

    extractor = MLBGameFeatureExtractor()

    if args.calibrate:
        print("\nCalibrating SP_WEIGHT from historical outcomes...")
        result = extractor.calibrate_sp_weight(min_games=args.min_games)
        if not result["ready"]:
            print(f"  NOT READY: {result['reason']}")
            print(f"  Games with SP data so far: {result['games']}")
            print(f"  Check again: {result.get('target_date', 'when more data is available')}")
        else:
            print(f"  Games used:      {result['games']}")
            print(f"  Optimal weight:  {result['weight']}")
            print(f"  Optimal RMSE:    {result['rmse']}")
            print(f"  Baseline RMSE:   {result['baseline_rmse']} (weight=0.50)")
            print(f"  Improvement:     {result['improvement']:.4f} RMSE")
            if result["update_code"]:
                print(f"\n  ACTION: improvement >= 0.10 — update SP_WEIGHT to {result['weight']} in game_features.py")
            else:
                print(f"\n  HOLD: improvement < 0.10 — keep SP_WEIGHT at 0.50 for now")
    else:
        features = extractor.extract("2026-04-15", "NYY", "BOS",
                                      venue="Yankee Stadium",
                                      home_starter="Gerrit Cole",
                                      away_starter="Brayan Bello")
        print(f"\nMLB Game Features ({len(features)} total):")
        print("-" * 50)
        for k, v in sorted(features.items()):
            print(f"  {k:<35} {v}")
