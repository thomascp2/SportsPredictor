"""
Rest & Rotation Calculator — Schedule-situation features for all sports.

Calculates rest days, back-to-backs, 3-in-4, 4-in-6, road trip length,
and travel fatigue. These are among the highest-value features for game
prediction (2-4% win rate swing in NBA, 1-2% in NHL).

Usage:
    from shared.rest_rotation import RestRotationCalculator

    calc = RestRotationCalculator(db_path, sport="nba")
    features = calc.get_rest_features("BOS", "2026-03-25")
    # Returns: {days_rest, is_b2b, is_3in4, is_4in6, road_trip_game,
    #           road_trip_length, games_in_7_days, travel_miles_7d, ...}
"""

import sqlite3
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, Optional, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RestRotationCalculator:
    """Calculate rest and rotation features for any sport."""

    def __init__(self, db_path: str, sport: str):
        self.db_path = db_path
        self.sport = sport.lower()

        # Load arena/park coordinates for travel calculations
        self._coords = {}
        self._load_coordinates()

    def _load_coordinates(self):
        """Load venue coordinates for travel distance calculation."""
        try:
            if self.sport == "nhl":
                sys.path.insert(0, os.path.join(PROJECT_ROOT, "nhl", "scripts"))
                from arena_data import get_coordinates, TEAM_TO_ARENA
                for team in TEAM_TO_ARENA:
                    c = get_coordinates(team)
                    if c:
                        self._coords[team] = c
            elif self.sport == "nba":
                sys.path.insert(0, os.path.join(PROJECT_ROOT, "nba", "scripts"))
                from arena_data import get_coordinates, TEAM_TO_ARENA
                for team in TEAM_TO_ARENA:
                    c = get_coordinates(team)
                    if c:
                        self._coords[team] = c
            elif self.sport == "mlb":
                sys.path.insert(0, os.path.join(PROJECT_ROOT, "mlb", "scripts"))
                from park_factors import PARK_FACTORS, TEAM_TO_PARK
                for team, park in TEAM_TO_PARK.items():
                    pf = PARK_FACTORS.get(park, {})
                    if "lat" in pf and "lon" in pf:
                        self._coords[team] = (pf["lat"], pf["lon"])
        except ImportError:
            pass

    def get_rest_features(self, team: str, game_date: str) -> Dict:
        """
        Calculate all rest/rotation features for a team on a given date.

        Returns dict with keys:
            days_rest, is_b2b, is_3in4, is_4in6, games_last_7,
            games_last_14, road_trip_game, road_trip_length,
            travel_miles_3d, travel_miles_7d, avg_rest_last_5
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        target = datetime.strptime(game_date, "%Y-%m-%d")
        lookback_start = (target - timedelta(days=14)).strftime("%Y-%m-%d")

        # Get recent games
        recent_games = conn.execute("""
            SELECT game_date,
                   CASE WHEN home_team = ? THEN 1 ELSE 0 END as is_home,
                   CASE WHEN home_team = ? THEN away_team ELSE home_team END as opponent,
                   home_team, away_team
            FROM games
            WHERE (home_team = ? OR away_team = ?)
              AND game_date >= ? AND game_date < ?
              AND home_score IS NOT NULL
            ORDER BY game_date DESC
        """, (team, team, team, team, lookback_start, game_date)).fetchall()

        conn.close()

        features = {
            "days_rest": 3,         # Default if no recent games
            "is_b2b": 0,
            "is_3in4": 0,
            "is_4in6": 0,
            "games_last_7": 0,
            "games_last_14": len(recent_games),
            "road_trip_game": 0,
            "road_trip_length": 0,
            "travel_miles_3d": 0.0,
            "travel_miles_7d": 0.0,
            "avg_rest_last_5": 2.0,
        }

        if not recent_games:
            return features

        # Days since last game
        last_game_date = datetime.strptime(recent_games[0]["game_date"], "%Y-%m-%d")
        features["days_rest"] = (target - last_game_date).days
        features["is_b2b"] = 1 if features["days_rest"] <= 1 else 0

        # Games in windows
        for g in recent_games:
            gd = datetime.strptime(g["game_date"], "%Y-%m-%d")
            days_ago = (target - gd).days
            if days_ago <= 7:
                features["games_last_7"] += 1

        # 3-in-4 nights
        games_in_4 = sum(
            1 for g in recent_games
            if (target - datetime.strptime(g["game_date"], "%Y-%m-%d")).days <= 4
        )
        features["is_3in4"] = 1 if games_in_4 >= 3 else 0

        # 4-in-6 nights
        games_in_6 = sum(
            1 for g in recent_games
            if (target - datetime.strptime(g["game_date"], "%Y-%m-%d")).days <= 6
        )
        features["is_4in6"] = 1 if games_in_6 >= 4 else 0

        # Average rest between last 5 games
        if len(recent_games) >= 2:
            rest_days = []
            for i in range(min(len(recent_games) - 1, 4)):
                d1 = datetime.strptime(recent_games[i]["game_date"], "%Y-%m-%d")
                d2 = datetime.strptime(recent_games[i + 1]["game_date"], "%Y-%m-%d")
                rest_days.append((d1 - d2).days)
            if rest_days:
                features["avg_rest_last_5"] = round(sum(rest_days) / len(rest_days), 1)

        # Road trip detection
        consecutive_away = 0
        for g in recent_games:
            if not g["is_home"]:
                consecutive_away += 1
            else:
                break

        # Check if TODAY's game is also away (caller determines this)
        features["road_trip_length"] = consecutive_away
        features["road_trip_game"] = consecutive_away  # 0 = home, 1+ = Nth road game

        # Travel distance in last 3 and 7 days
        features["travel_miles_3d"] = self._calc_travel_miles(recent_games, target, 3)
        features["travel_miles_7d"] = self._calc_travel_miles(recent_games, target, 7)

        return features

    def _calc_travel_miles(self, games: list, target: datetime, days: int) -> float:
        """Calculate total travel miles in the last N days."""
        import math

        recent = [
            g for g in games
            if (target - datetime.strptime(g["game_date"], "%Y-%m-%d")).days <= days
        ]

        if len(recent) < 2:
            return 0.0

        total_miles = 0.0
        for i in range(len(recent) - 1):
            # Get the venue for each game (opponent's arena if away, home arena if home)
            g_curr = recent[i]
            g_prev = recent[i + 1]

            # Where were they playing?
            loc_curr = g_curr["home_team"] if g_curr["is_home"] else g_curr["away_team"]
            # Actually — the game is AT the home_team's arena
            arena_curr = g_curr["home_team"]
            arena_prev = g_prev["home_team"]

            coords_curr = self._coords.get(arena_curr)
            coords_prev = self._coords.get(arena_prev)

            if coords_curr and coords_prev:
                total_miles += self._haversine(
                    coords_prev[0], coords_prev[1],
                    coords_curr[0], coords_curr[1]
                )

        return round(total_miles, 1)

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2):
        """Distance in miles between two lat/lon points."""
        import math
        R = 3959
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
        return R * 2 * math.asin(math.sqrt(a))

    def get_matchup_rest_comparison(self, home_team: str, away_team: str,
                                     game_date: str) -> Dict:
        """
        Get rest features for BOTH teams and compute differentials.
        This is the feature set most useful for ML models.
        """
        home_rest = self.get_rest_features(home_team, game_date)
        away_rest = self.get_rest_features(away_team, game_date)

        return {
            # Home team
            "home_days_rest": home_rest["days_rest"],
            "home_is_b2b": home_rest["is_b2b"],
            "home_is_3in4": home_rest["is_3in4"],
            "home_games_last_7": home_rest["games_last_7"],
            "home_road_trip": 0,  # Home team is at home

            # Away team
            "away_days_rest": away_rest["days_rest"],
            "away_is_b2b": away_rest["is_b2b"],
            "away_is_3in4": away_rest["is_3in4"],
            "away_is_4in6": away_rest["is_4in6"],
            "away_games_last_7": away_rest["games_last_7"],
            "away_road_trip_game": away_rest["road_trip_game"],
            "away_travel_miles_3d": away_rest["travel_miles_3d"],
            "away_travel_miles_7d": away_rest["travel_miles_7d"],

            # Differentials (positive = home advantage)
            "rest_advantage": home_rest["days_rest"] - away_rest["days_rest"],
            "schedule_density_diff": away_rest["games_last_7"] - home_rest["games_last_7"],
            "fatigue_score_diff": (
                (away_rest["is_b2b"] * 3 + away_rest["is_3in4"] * 2 + away_rest["is_4in6"]) -
                (home_rest["is_b2b"] * 3 + home_rest["is_3in4"] * 2)
            ),
        }


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Rest & Rotation Calculator")
    parser.add_argument("--sport", choices=["nhl", "nba", "mlb"], required=True)
    parser.add_argument("--team", required=True)
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--matchup", help="Away team for matchup comparison")
    args = parser.parse_args()

    db_map = {
        "nhl": os.path.join(PROJECT_ROOT, "nhl", "database", "nhl_predictions_v2.db"),
        "nba": os.path.join(PROJECT_ROOT, "nba", "database", "nba_predictions.db"),
        "mlb": os.path.join(PROJECT_ROOT, "mlb", "database", "mlb_predictions.db"),
    }

    calc = RestRotationCalculator(db_map[args.sport], args.sport)

    if args.matchup:
        features = calc.get_matchup_rest_comparison(args.team, args.matchup, args.date)
        print(f"\n{args.sport.upper()} Matchup Rest: {args.team} (home) vs {args.matchup} (away)")
    else:
        features = calc.get_rest_features(args.team, args.date)
        print(f"\n{args.sport.upper()} Rest Features: {args.team} on {args.date}")

    print("-" * 50)
    for k, v in features.items():
        print(f"  {k:<30} {v}")
