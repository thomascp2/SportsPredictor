"""
Elo Rating Engine — Sport-agnostic rating system for game predictions.

Maintains team ratings that update after each game result. Elo difference
is one of the strongest single predictors for game outcomes (~55-60% alone).

Usage:
    from shared.elo_engine import EloEngine

    elo = EloEngine(sport="nhl")
    elo.load()                              # Load saved ratings
    elo.update("BOS", "NYR", 4, 2)          # Update after game
    diff = elo.get_elo_diff("BOS", "NYR")   # Feature for ML
    prob = elo.predict_home_win("NYR", "BOS")  # Win probability
    elo.save()                              # Persist ratings
"""

import json
import os
import math
from datetime import datetime
from typing import Dict, Optional, Tuple

# ── Sport-specific configuration ──────────────────────────────────────────────

SPORT_CONFIG = {
    "nhl": {
        "k_factor": 20,           # Rating adjustment speed
        "home_advantage": 60,     # Home ice advantage in Elo points
        "mov_exponent": 0.8,      # Margin-of-victory dampening
        "default_rating": 1500,
        "season_regression": 0.25, # Regress 25% toward mean between seasons
    },
    "nba": {
        "k_factor": 20,
        "home_advantage": 100,    # NBA has strongest home court advantage
        "mov_exponent": 0.7,      # More dampening — NBA blowouts are common
        "default_rating": 1500,
        "season_regression": 0.25,
    },
    "mlb": {
        "k_factor": 6,            # Lower K — MLB has 162 games (more data, less noise)
        "home_advantage": 24,     # MLB home field advantage is weakest of big 3
        "mov_exponent": 0.6,      # Run differentials can be huge — dampen heavily
        "default_rating": 1500,
        "season_regression": 0.25,
    },
}

# ── Standard team abbreviations per sport ─────────────────────────────────────

NHL_TEAMS = [
    "ANA", "ARI", "BOS", "BUF", "CGY", "CAR", "CHI", "COL", "CBJ", "DAL",
    "DET", "EDM", "FLA", "LAK", "MIN", "MTL", "NSH", "NJD", "NYI", "NYR",
    "OTT", "PHI", "PIT", "SJS", "SEA", "STL", "TBL", "TOR", "UTA", "VAN",
    "VGK", "WPG", "WSH",
]

NBA_TEAMS = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]

MLB_TEAMS = [
    "ARI", "ATL", "BAL", "BOS", "CHC", "CHW", "CIN", "CLE", "COL", "DET",
    "HOU", "KCR", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "OAK",
    "PHI", "PIT", "SDP", "SFG", "SEA", "STL", "TBR", "TEX", "TOR", "WSH",
]

SPORT_TEAMS = {
    "nhl": NHL_TEAMS,
    "nba": NBA_TEAMS,
    "mlb": MLB_TEAMS,
}

# Non-standard abbreviations used in some data sources → canonical form
TEAM_ALIASES = {
    "mlb": {
        "AZ": "ARI",
        "SD": "SDP",
        "SF": "SFG",
        "TB": "TBR",
        "KC": "KCR",
        "CWS": "CHW",
        "ATH": "OAK",
    },
    "nhl": {},
    "nba": {},
}


class EloEngine:
    """Sport-agnostic Elo rating engine with persistence."""

    def __init__(self, sport: str, data_dir: Optional[str] = None):
        if sport not in SPORT_CONFIG:
            raise ValueError(f"Unknown sport: {sport}. Use: {list(SPORT_CONFIG.keys())}")

        self.sport = sport
        self.config = SPORT_CONFIG[sport]
        self.default_rating = self.config["default_rating"]

        # Storage location
        if data_dir is None:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(base, self.sport, "database")
        self.data_dir = data_dir
        self.ratings_file = os.path.join(data_dir, f"elo_ratings_{sport}.json")

        # Initialize ratings
        self.ratings: Dict[str, float] = {}
        self.history: list = []  # Track rating changes
        self.games_processed: int = 0
        self.last_updated: Optional[str] = None
        self.season: Optional[str] = None

        self._init_default_ratings()

    def _init_default_ratings(self):
        """Initialize all teams at default rating."""
        teams = SPORT_TEAMS.get(self.sport, [])
        for team in teams:
            if team not in self.ratings:
                self.ratings[team] = self.default_rating

    # ── Core Elo math ─────────────────────────────────────────────────────────

    def expected_score(self, rating_a: float, rating_b: float) -> float:
        """Calculate expected score (win probability) for team A."""
        return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))

    def margin_of_victory_multiplier(self, margin: int) -> float:
        """
        Scale K-factor by margin of victory.
        Uses log-based dampening to prevent blowouts from over-inflating ratings.
        """
        exp = self.config["mov_exponent"]
        return math.log(max(abs(margin), 1) + 1) ** exp

    def update(self, home_team: str, away_team: str,
               home_score: int, away_score: int,
               game_date: Optional[str] = None) -> Tuple[float, float]:
        """
        Update Elo ratings after a game result.

        Args:
            home_team: Home team abbreviation
            away_team: Away team abbreviation
            home_score: Home team final score
            away_score: Away team final score
            game_date: Optional date string (YYYY-MM-DD)

        Returns:
            Tuple of (new_home_rating, new_away_rating)
        """
        # Ensure teams exist in ratings
        if home_team not in self.ratings:
            self.ratings[home_team] = self.default_rating
        if away_team not in self.ratings:
            self.ratings[away_team] = self.default_rating

        home_rating = self.ratings[home_team]
        away_rating = self.ratings[away_team]

        # Apply home advantage to expected score calculation
        home_adv = self.config["home_advantage"]
        expected_home = self.expected_score(home_rating + home_adv, away_rating)

        # Actual result (1 = home win, 0 = away win, 0.5 = tie/OT loss)
        if home_score > away_score:
            actual_home = 1.0
        elif away_score > home_score:
            actual_home = 0.0
        else:
            actual_home = 0.5  # Ties (NHL OT/SO handled by caller)

        # Margin of victory multiplier
        margin = home_score - away_score
        mov_mult = self.margin_of_victory_multiplier(margin)

        # K-factor with MOV
        k = self.config["k_factor"] * mov_mult

        # Update ratings
        delta = k * (actual_home - expected_home)
        new_home = home_rating + delta
        new_away = away_rating - delta

        self.ratings[home_team] = round(new_home, 1)
        self.ratings[away_team] = round(new_away, 1)
        self.games_processed += 1
        self.last_updated = game_date or datetime.now().strftime("%Y-%m-%d")

        # Track history (keep last 100 updates for debugging)
        if len(self.history) < 100:
            self.history.append({
                "date": self.last_updated,
                "home": home_team,
                "away": away_team,
                "score": f"{home_score}-{away_score}",
                "delta": round(delta, 1),
                "home_elo": self.ratings[home_team],
                "away_elo": self.ratings[away_team],
            })

        return self.ratings[home_team], self.ratings[away_team]

    # ── Feature extraction ────────────────────────────────────────────────────

    def get_rating(self, team: str) -> float:
        """Get current Elo rating for a team."""
        return self.ratings.get(team, self.default_rating)

    def get_elo_diff(self, home_team: str, away_team: str,
                     include_home_advantage: bool = True) -> float:
        """
        Get Elo difference (home - away). Primary feature for ML models.
        Positive = home team is stronger.
        """
        diff = self.get_rating(home_team) - self.get_rating(away_team)
        if include_home_advantage:
            diff += self.config["home_advantage"]
        return round(diff, 1)

    def predict_home_win(self, home_team: str, away_team: str) -> float:
        """
        Predict home team win probability based on Elo ratings.
        Includes home advantage.
        """
        home_r = self.get_rating(home_team) + self.config["home_advantage"]
        away_r = self.get_rating(away_team)
        return round(self.expected_score(home_r, away_r), 4)

    def get_rankings(self, top_n: int = 0) -> list:
        """Get teams sorted by rating. top_n=0 returns all."""
        sorted_teams = sorted(self.ratings.items(), key=lambda x: x[1], reverse=True)
        if top_n > 0:
            sorted_teams = sorted_teams[:top_n]
        return [{"rank": i + 1, "team": t, "rating": r}
                for i, (t, r) in enumerate(sorted_teams)]

    # ── Season management ─────────────────────────────────────────────────────

    def new_season(self, season: str):
        """
        Regress ratings toward mean for a new season.
        Carries forward 75% of deviation from 1500 (configurable).
        """
        regression = self.config["season_regression"]
        mean = self.default_rating

        for team in self.ratings:
            deviation = self.ratings[team] - mean
            self.ratings[team] = round(mean + deviation * (1 - regression), 1)

        self.season = season
        self.games_processed = 0
        self.history = []
        self.last_updated = None

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self):
        """Save ratings to JSON file."""
        os.makedirs(self.data_dir, exist_ok=True)
        data = {
            "sport": self.sport,
            "season": self.season,
            "games_processed": self.games_processed,
            "last_updated": self.last_updated,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "config": self.config,
            "ratings": self.ratings,
            "recent_history": self.history[-20:],  # Last 20 updates
        }
        with open(self.ratings_file, "w") as f:
            json.dump(data, f, indent=2)

    def load(self) -> bool:
        """Load ratings from JSON file. Returns True if loaded successfully."""
        if not os.path.exists(self.ratings_file):
            return False
        try:
            with open(self.ratings_file, "r") as f:
                data = json.load(f)
            self.ratings = data.get("ratings", {})
            self.season = data.get("season")
            self.games_processed = data.get("games_processed", 0)
            self.last_updated = data.get("last_updated")
            self.history = data.get("recent_history", [])
            # Ensure any new teams get default rating
            self._init_default_ratings()
            return True
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[ELO] Warning: Could not load ratings from {self.ratings_file}: {e}")
            return False

    # ── Batch processing ──────────────────────────────────────────────────────

    def process_games_from_db(self, db_path: str, season: Optional[str] = None):
        """
        Process all games from a sport's database to build Elo ratings.
        Games must be in the standard `games` table with:
            game_date, home_team, away_team, home_score, away_score

        Args:
            db_path: Path to SQLite database
            season: Optional season filter (e.g., "2025-2026")
        """
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
            SELECT game_date, home_team, away_team, home_score, away_score
            FROM games
            WHERE home_score IS NOT NULL AND away_score IS NOT NULL
        """
        params = []
        if season:
            query += " AND season = ?"
            params.append(season)
        query += " ORDER BY game_date ASC"

        cursor.execute(query, params)
        games = cursor.fetchall()
        conn.close()

        aliases = TEAM_ALIASES.get(self.sport, {})
        processed = 0
        for game in games:
            home = aliases.get(game["home_team"], game["home_team"])
            away = aliases.get(game["away_team"], game["away_team"])
            self.update(
                home_team=home,
                away_team=away,
                home_score=game["home_score"],
                away_score=game["away_score"],
                game_date=game["game_date"],
            )
            processed += 1

        print(f"[ELO] {self.sport.upper()}: Processed {processed} games, "
              f"{len(self.ratings)} teams rated")
        return processed

    # ── Display ───────────────────────────────────────────────────────────────

    def __repr__(self):
        return (f"EloEngine(sport={self.sport}, teams={len(self.ratings)}, "
                f"games={self.games_processed}, last={self.last_updated})")

    def print_rankings(self, top_n: int = 10):
        """Print formatted rankings table."""
        rankings = self.get_rankings(top_n)
        print(f"\n{'='*40}")
        print(f"  {self.sport.upper()} Elo Rankings")
        if self.last_updated:
            print(f"  As of {self.last_updated}")
        print(f"{'='*40}")
        for r in rankings:
            bar = "+" * int((r["rating"] - 1400) / 10) if r["rating"] > 1400 else ""
            print(f"  {r['rank']:>2}. {r['team']:<5} {r['rating']:>6.1f}  {bar}")
        print(f"{'='*40}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Elo Rating Engine")
    parser.add_argument("--sport", choices=["nhl", "nba", "mlb"], required=True)
    parser.add_argument("--build", action="store_true",
                        help="Build ratings from game history in database")
    parser.add_argument("--season", type=str, default=None,
                        help="Filter to specific season (e.g., 2025-2026)")
    parser.add_argument("--rankings", type=int, default=10,
                        help="Show top N teams (default: 10, 0=all)")
    parser.add_argument("--predict", nargs=2, metavar=("HOME", "AWAY"),
                        help="Predict win probability (e.g., --predict BOS NYR)")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    elo = EloEngine(sport=args.sport)

    if args.build:
        # Determine DB path
        db_map = {
            "nhl": os.path.join(base_dir, "nhl", "database", "nhl_predictions_v2.db"),
            "nba": os.path.join(base_dir, "nba", "database", "nba_predictions.db"),
            "mlb": os.path.join(base_dir, "mlb", "database", "mlb_predictions.db"),
        }
        db_path = db_map[args.sport]
        if not os.path.exists(db_path):
            print(f"[ELO] Database not found: {db_path}")
            return

        elo.process_games_from_db(db_path, season=args.season)
        elo.save()
        print(f"[ELO] Ratings saved to {elo.ratings_file}")
    else:
        if not elo.load():
            print(f"[ELO] No saved ratings found. Run with --build first.")
            return

    if args.predict:
        home, away = args.predict
        prob = elo.predict_home_win(home, away)
        diff = elo.get_elo_diff(home, away)
        print(f"\n  {home} (home) vs {away}")
        print(f"  Elo diff: {diff:+.1f}")
        print(f"  {home} win prob: {prob:.1%}")
        print(f"  {away} win prob: {1 - prob:.1%}\n")

    elo.print_rankings(args.rankings)


if __name__ == "__main__":
    main()
