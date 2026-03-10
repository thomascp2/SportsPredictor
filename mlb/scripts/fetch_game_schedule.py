"""
MLB Game Schedule Fetcher
=========================

Fetches the daily MLB schedule including:
  - Game IDs, teams, venues, game times
  - Probable starting pitchers (with TBD handling)
  - Projected lineups (when posted, ~3-4 hours before game)
  - Vegas odds (from ESPN API)
  - Weather at game time (from OpenWeatherMap)

Saves all context to the game_context table for use by feature extractors.

MLB-specific complexity handled here:
  - TBD starters: flagged, pitcher props skipped for that team
  - Doubleheaders: two separate game_ids, both processed
  - Postponements: marked, skipped in prediction and grading
  - Lineup availability: ~3h before game; uses historical proxy if not posted

Usage:
    python fetch_game_schedule.py 2026-04-15
    python fetch_game_schedule.py  # defaults to today
"""

import sys
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from mlb_config import DB_PATH, get_db_connection, initialize_database, mlb_has_games
from mlb_stats_api import MLBStatsAPI, GameInfo
from espn_mlb_api import ESPNMLBApi
from weather_client import get_game_weather


class GameScheduleFetcher:
    """
    Fetches and saves the full game context for a given date.

    Combines data from:
      1. MLB Stats API (schedule, starters, lineups)
      2. ESPN API (Vegas moneylines + game totals)
      3. OpenWeatherMap (weather at game time per ballpark)
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self.mlb_api = MLBStatsAPI()
        self.espn_api = ESPNMLBApi()
        initialize_database(self.db_path)

    def fetch_and_save(self, target_date: str) -> List[GameInfo]:
        """
        Fetch all game context for a date and save to DB.

        Args:
            target_date: Date in YYYY-MM-DD format

        Returns:
            List of GameInfo objects for games found
        """
        print(f"\n[Schedule] Fetching MLB schedule for {target_date}...")

        if not mlb_has_games(target_date):
            print(f"[Schedule] {target_date} is outside MLB regular season — skipping")
            return []

        # 1. Fetch schedule + starters + lineups
        games = self.mlb_api.get_schedule(target_date)
        if not games:
            print(f"[Schedule] No games found for {target_date}")
            return []

        print(f"[Schedule] Found {len(games)} games")

        # 2. Fetch Vegas odds for all games
        print(f"[Schedule] Fetching Vegas odds from ESPN...")
        odds_by_matchup = {}
        try:
            odds_by_matchup = self.espn_api.get_all_game_odds(target_date)
        except Exception as e:
            print(f"[Schedule] ESPN odds fetch failed: {e} — proceeding without odds")

        # 3. Save game context to DB
        conn = get_db_connection(self.db_path)
        saved_count = 0

        try:
            for game in games:
                # Skip postponed games
                if game.status == 'postponed':
                    print(f"[Schedule] Skipping postponed: {game.away_team} @ {game.home_team}")
                    continue

                # Get odds for this matchup
                odds_key = (game.away_team, game.home_team)
                # Also try reversed key (ESPN sometimes lists differently)
                odds = odds_by_matchup.get(odds_key) or odds_by_matchup.get(
                    (game.home_team, game.away_team), {}
                )

                # Get weather
                weather = {}
                try:
                    weather = get_game_weather(game.home_team, game.game_time_utc, game.venue)
                except Exception as e:
                    print(f"[Schedule] Weather fetch failed for {game.home_team}: {e}")

                # Save to game_context table
                self._save_game_context(conn, game, odds, weather)
                saved_count += 1

            conn.commit()
            print(f"[Schedule] Saved context for {saved_count} games to DB")

        finally:
            conn.close()

        return games

    def _save_game_context(self, conn: sqlite3.Connection, game: GameInfo,
                            odds: Dict, weather: Dict) -> None:
        """Insert or update game context in the DB."""
        conn.execute('''
            INSERT OR REPLACE INTO game_context (
                game_id, game_date, home_team, away_team, venue,
                home_starter, away_starter, home_starter_id, away_starter_id,
                home_ml, away_ml, game_total,
                temperature, wind_speed, wind_direction, conditions,
                day_night, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(game.game_id),
            game.game_date,
            game.home_team,
            game.away_team,
            game.venue,
            game.home_starter,
            game.away_starter,
            game.home_starter_id,
            game.away_starter_id,
            odds.get('home_ml'),
            odds.get('away_ml'),
            odds.get('game_total'),
            weather.get('temperature'),
            weather.get('wind_speed'),
            weather.get('wind_direction', 'Unknown'),
            weather.get('conditions', 'Unknown'),
            game.day_night,
            game.status,
            datetime.now().isoformat(),
        ))

    def get_games_for_date(self, target_date: str) -> List[Dict]:
        """
        Retrieve saved game context from DB for a given date.

        Args:
            target_date: Date in YYYY-MM-DD format

        Returns:
            List of game context dicts
        """
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.execute(
                'SELECT * FROM game_context WHERE game_date = ? ORDER BY game_id',
                (target_date,)
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_confirmed_starters(self, target_date: str) -> List[Dict]:
        """
        Get all confirmed (non-TBD) starting pitchers for a date.

        Args:
            target_date: Date in YYYY-MM-DD format

        Returns:
            List of dicts with: pitcher_name, team, opponent, home_away, game_id, venue
        """
        games = self.get_games_for_date(target_date)
        starters = []

        for game in games:
            if game['status'] == 'postponed':
                continue

            # Home starter
            if game['home_starter'] and game['home_starter'] != 'TBD':
                starters.append({
                    'pitcher_name': game['home_starter'],
                    'pitcher_id': game['home_starter_id'],
                    'team': game['home_team'],
                    'opponent': game['away_team'],
                    'home_away': 'home',
                    'game_id': game['game_id'],
                    'venue': game['venue'],
                })

            # Away starter
            if game['away_starter'] and game['away_starter'] != 'TBD':
                starters.append({
                    'pitcher_name': game['away_starter'],
                    'pitcher_id': game['away_starter_id'],
                    'team': game['away_team'],
                    'opponent': game['home_team'],
                    'home_away': 'away',
                    'game_id': game['game_id'],
                    'venue': game['venue'],
                })

        return starters

    def get_active_batters(self, target_date: str) -> List[Dict]:
        """
        Get projected batting lineups for all games on a date.

        Uses confirmed lineup data if available; falls back to historical
        most-frequent starters per team (from player_game_logs).

        Args:
            target_date: Date in YYYY-MM-DD format

        Returns:
            List of batter dicts with: player_name, team, opponent, home_away,
                                       batting_order, game_id, venue
        """
        games = self.mlb_api.get_schedule(target_date)
        batters = []

        conn = get_db_connection(self.db_path)
        try:
            for game in games:
                if game.status == 'postponed':
                    continue

                for side, team, opponent, lineup in [
                    ('home', game.home_team, game.away_team, game.home_lineup),
                    ('away', game.away_team, game.home_team, game.away_lineup),
                ]:
                    if lineup:
                        # Confirmed lineup posted
                        for player in lineup:
                            if not player['name']:
                                continue
                            batters.append({
                                'player_name': player['name'],
                                'player_id': player.get('id'),
                                'team': team,
                                'opponent': opponent,
                                'home_away': side,
                                'batting_order': player.get('batting_order', 0),
                                'game_id': str(game.game_id),
                                'venue': game.venue,
                                'lineup_confirmed': True,
                            })
                    else:
                        # Lineup not posted — use historical roster
                        historical = self._get_historical_starters(conn, team, target_date)
                        for order, player_name in enumerate(historical, start=1):
                            batters.append({
                                'player_name': player_name,
                                'player_id': None,
                                'team': team,
                                'opponent': opponent,
                                'home_away': side,
                                'batting_order': order,
                                'game_id': str(game.game_id),
                                'venue': game.venue,
                                'lineup_confirmed': False,
                            })
        finally:
            conn.close()

        return batters

    def _get_historical_starters(self, conn: sqlite3.Connection,
                                  team: str, target_date: str, top_n: int = 9) -> List[str]:
        """
        Get the most frequently starting players for a team in recent games.

        Falls back to any batters in player_game_logs if insufficient data.

        Args:
            conn: DB connection
            team: Team abbreviation
            target_date: Date cutoff (only use games before this)
            top_n: Number of players to return

        Returns:
            List of player names in approximate batting order
        """
        cursor = conn.execute('''
            SELECT player_name, COUNT(*) as games,
                   AVG(COALESCE(batting_order, 5)) as avg_order
            FROM player_game_logs
            WHERE team = ?
              AND player_type = 'batter'
              AND game_date < ?
            GROUP BY player_name
            ORDER BY games DESC, avg_order ASC
            LIMIT ?
        ''', (team, target_date, top_n))

        rows = cursor.fetchall()
        if not rows:
            return []

        # Sort by average batting order
        sorted_players = sorted(rows, key=lambda r: r['avg_order'] or 5)
        return [row['player_name'] for row in sorted_players]


# ============================================================================
# Standalone usage
# ============================================================================

def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime('%Y-%m-%d')

    print(f"[Schedule] Running for date: {target_date}")
    fetcher = GameScheduleFetcher()
    games = fetcher.fetch_and_save(target_date)

    print(f"\n[Schedule] Summary for {target_date}:")
    print(f"  Total games: {len(games)}")

    starters = fetcher.get_confirmed_starters(target_date)
    print(f"  Confirmed starters: {len(starters)}")
    for s in starters:
        print(f"    {s['pitcher_name']} ({s['team']} vs {s['opponent']})")

    saved_games = fetcher.get_games_for_date(target_date)
    print(f"\n  Saved game contexts: {len(saved_games)}")
    for g in saved_games:
        total_str = f"O/U {g['game_total']}" if g['game_total'] else "No line"
        weather_str = f"{g['temperature']}°F {g['wind_speed']}mph {g['wind_direction']}" if g['temperature'] else "No weather"
        print(f"    {g['away_team']} @ {g['home_team']} | {total_str} | {weather_str}")


if __name__ == '__main__':
    main()
