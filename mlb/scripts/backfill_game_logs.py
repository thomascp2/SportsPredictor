"""
MLB Player Game Logs Backfill
==============================

Backfills player_game_logs from the 2025 MLB season using the official
MLB Stats API. This gives our prediction model historical data so it can
generate predictions from Day 1 of the 2026 season.

Strategy:
  1. Fetch every completed game from the 2025 regular season (April-September)
  2. For each game, pull the full boxscore
  3. Parse pitcher + batter stats using existing MLBStatsAPI methods
  4. Insert into player_game_logs (same format as daily grading)

The MLB Stats API is free and has no auth. We add polite delays to avoid
hammering it (~0.3s per request).

Usage:
    python backfill_game_logs.py                    # Full 2025 season
    python backfill_game_logs.py --month 9          # September 2025 only
    python backfill_game_logs.py --start 2025-08-01 --end 2025-09-30
    python backfill_game_logs.py --check             # Just show current counts
"""

import sys
import time
import sqlite3
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mlb_config import DB_PATH, get_db_connection, initialize_database
from mlb_stats_api import MLBStatsAPI


# ============================================================================
# Constants
# ============================================================================

SEASON_2025_START = "2025-03-27"   # 2025 Opening Day
SEASON_2025_END   = "2025-09-28"   # 2025 regular season end
REQUEST_DELAY     = 0.3            # Seconds between API calls (be polite)


# ============================================================================
# Backfill Logic
# ============================================================================

class MLBBackfiller:
    """Backfills player_game_logs from historical boxscores."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self.api = MLBStatsAPI()
        self.stats = {
            'dates_processed': 0,
            'games_processed': 0,
            'games_skipped': 0,
            'pitchers_saved': 0,
            'batters_saved': 0,
            'errors': 0,
        }

    def backfill_date_range(self, start_date: str, end_date: str) -> dict:
        """
        Backfill all games between start_date and end_date (inclusive).

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        Returns:
            Stats dict with counts
        """
        initialize_database()
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row

        current = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        total_days = (end - current).days + 1

        print(f"\n{'='*60}")
        print(f"  MLB Game Log Backfill")
        print(f"  Range: {start_date} -> {end_date} ({total_days} days)")
        print(f"  Database: {self.db_path}")
        print(f"{'='*60}\n")

        try:
            while current <= end:
                date_str = current.strftime("%Y-%m-%d")
                self._process_date(conn, date_str)
                self.stats['dates_processed'] += 1

                # Progress update every 7 days
                if self.stats['dates_processed'] % 7 == 0:
                    pct = (self.stats['dates_processed'] / total_days) * 100
                    print(f"\n  --- Progress: {self.stats['dates_processed']}/{total_days} days "
                          f"({pct:.0f}%) | {self.stats['games_processed']} games | "
                          f"{self.stats['pitchers_saved']} pitchers | "
                          f"{self.stats['batters_saved']} batters ---\n")

                current += timedelta(days=1)

        except KeyboardInterrupt:
            print("\n\n[INTERRUPTED] Saving progress...")
            conn.commit()
        finally:
            conn.commit()
            conn.close()

        self._print_summary()
        return self.stats

    def _process_date(self, conn: sqlite3.Connection, date_str: str) -> None:
        """Process all games for a single date."""
        # Check how many games we already have for this date
        existing = conn.execute(
            "SELECT COUNT(DISTINCT game_id) FROM player_game_logs WHERE game_date = ?",
            (date_str,)
        ).fetchone()[0]

        # Fetch schedule
        games = self.api.get_schedule(date_str)
        final_games = [g for g in games if g.status == 'final']

        if not final_games:
            return

        # Skip dates we've already fully processed
        if existing >= len(final_games):
            print(f"  [{date_str}] Already have {existing} games — skipping")
            self.stats['games_skipped'] += existing
            return

        print(f"  [{date_str}] {len(final_games)} final games (have {existing} already)")

        for game in final_games:
            try:
                self._process_game(conn, game, date_str)
                time.sleep(REQUEST_DELAY)
            except Exception as e:
                print(f"    [ERROR] Game {game.game_id}: {e}")
                self.stats['errors'] += 1

        # Commit after each date (safe checkpoint)
        conn.commit()

    def _process_game(self, conn: sqlite3.Connection, game, date_str: str) -> None:
        """Fetch boxscore and save pitcher/batter stats for one game."""
        # Check if we already have this game
        existing = conn.execute(
            "SELECT COUNT(*) FROM player_game_logs WHERE game_id = ?",
            (str(game.game_id),)
        ).fetchone()[0]

        if existing > 0:
            return  # Already have this game

        # Fetch boxscore
        boxscore = self.api.get_boxscore(game.game_id)
        if not boxscore:
            print(f"    [WARN] No boxscore for game {game.game_id}")
            return

        # Parse stats
        pitchers = self.api.parse_pitcher_stats(boxscore)
        batters = self.api.parse_batter_stats(boxscore)

        # Save pitchers
        for p in pitchers:
            try:
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
                        game_id, game_date, player_name, player_id, team, opponent,
                        home_away, player_type,
                        innings_pitched, outs_recorded, strikeouts_pitched,
                        walks_allowed, hits_allowed, earned_runs,
                        home_runs_allowed, pitches,
                        opposing_pitcher, venue, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(game.game_id), date_str, p.player_name, p.player_id,
                    p.team, opponent, home_away, 'pitcher',
                    p.innings_pitched, p.outs_recorded, p.strikeouts, p.walks,
                    p.hits_allowed, p.earned_runs, p.home_runs_allowed, p.pitches,
                    opp_starter, game.venue, datetime.now().isoformat()
                ))
                self.stats['pitchers_saved'] += 1
            except Exception as e:
                print(f"    [WARN] Pitcher {p.player_name}: {e}")

        # Save batters
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
                        game_id, game_date, player_name, player_id, team, opponent,
                        home_away, player_type,
                        at_bats, hits, home_runs, rbis, runs,
                        stolen_bases, walks_drawn, strikeouts_batter,
                        doubles, triples, total_bases, hrr,
                        batting_order, opposing_pitcher, venue, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(game.game_id), date_str, b.player_name, b.player_id,
                    b.team, opponent, home_away, 'batter',
                    b.at_bats, b.hits, b.home_runs, b.rbis, b.runs,
                    b.stolen_bases, b.walks, b.strikeouts, b.doubles, b.triples,
                    b.total_bases, b.hrr, b.batting_order,
                    opp_pitcher, game.venue, datetime.now().isoformat()
                ))
                self.stats['batters_saved'] += 1
            except Exception as e:
                print(f"    [WARN] Batter {b.player_name}: {e}")

        self.stats['games_processed'] += 1
        abbr = f"{game.away_team}@{game.home_team}"
        print(f"    {abbr}: {len(pitchers)}P + {len(batters)}B saved")

        # Also save to games table
        try:
            conn.execute('''
                INSERT OR IGNORE INTO games (game_id, game_date, home_team, away_team, season, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (str(game.game_id), date_str, game.home_team, game.away_team, '2025', 'final'))
        except Exception:
            pass

    def _print_summary(self) -> None:
        """Print final summary."""
        s = self.stats
        print(f"\n{'='*60}")
        print(f"  BACKFILL COMPLETE")
        print(f"{'='*60}")
        print(f"  Dates processed:  {s['dates_processed']}")
        print(f"  Games processed:  {s['games_processed']}")
        print(f"  Games skipped:    {s['games_skipped']} (already in DB)")
        print(f"  Pitchers saved:   {s['pitchers_saved']:,}")
        print(f"  Batters saved:    {s['batters_saved']:,}")
        print(f"  Errors:           {s['errors']}")
        print(f"{'='*60}\n")

    def check_current_data(self) -> None:
        """Print current database stats."""
        initialize_database()
        conn = get_db_connection()

        total = conn.execute("SELECT COUNT(*) FROM player_game_logs").fetchone()[0]
        pitchers = conn.execute(
            "SELECT COUNT(*) FROM player_game_logs WHERE player_type='pitcher'"
        ).fetchone()[0]
        batters = conn.execute(
            "SELECT COUNT(*) FROM player_game_logs WHERE player_type='batter'"
        ).fetchone()[0]
        dates = conn.execute(
            "SELECT COUNT(DISTINCT game_date) FROM player_game_logs"
        ).fetchone()[0]
        games = conn.execute(
            "SELECT COUNT(DISTINCT game_id) FROM player_game_logs"
        ).fetchone()[0]
        unique_players = conn.execute(
            "SELECT COUNT(DISTINCT player_name) FROM player_game_logs"
        ).fetchone()[0]

        # Date range
        date_range = conn.execute(
            "SELECT MIN(game_date), MAX(game_date) FROM player_game_logs"
        ).fetchone()

        # Top players by games
        top_pitchers = conn.execute('''
            SELECT player_name, COUNT(*) as games
            FROM player_game_logs WHERE player_type='pitcher'
            GROUP BY player_name ORDER BY games DESC LIMIT 5
        ''').fetchall()

        top_batters = conn.execute('''
            SELECT player_name, COUNT(*) as games
            FROM player_game_logs WHERE player_type='batter'
            GROUP BY player_name ORDER BY games DESC LIMIT 5
        ''').fetchall()

        conn.close()

        print(f"\n{'='*60}")
        print(f"  MLB Player Game Logs — Current Data")
        print(f"{'='*60}")
        print(f"  Total records:    {total:,}")
        print(f"  Pitcher records:  {pitchers:,}")
        print(f"  Batter records:   {batters:,}")
        print(f"  Unique players:   {unique_players:,}")
        print(f"  Unique games:     {games:,}")
        print(f"  Unique dates:     {dates}")
        if date_range[0]:
            print(f"  Date range:       {date_range[0]} to {date_range[1]}")

        if top_pitchers:
            print(f"\n  Top Pitchers (by games):")
            for name, g in top_pitchers:
                status = "READY" if g >= 3 else f"need {3-g} more"
                print(f"    {name}: {g} games [{status}]")

        if top_batters:
            print(f"\n  Top Batters (by games):")
            for name, g in top_batters:
                status = "READY" if g >= 10 else f"need {10-g} more"
                print(f"    {name}: {g} games [{status}]")

        print(f"{'='*60}\n")

        # Readiness check
        if total == 0:
            print("  [!!] NO DATA — run backfill to populate historical game logs")
        elif pitchers < 500:
            print(f"  [..] Low data — {pitchers} pitcher records. Consider backfilling more months.")
        else:
            print(f"  [OK] Sufficient data for predictions ({total:,} records)")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Backfill MLB player game logs")
    parser.add_argument('--start', help='Start date (YYYY-MM-DD)', default=SEASON_2025_START)
    parser.add_argument('--end', help='End date (YYYY-MM-DD)', default=SEASON_2025_END)
    parser.add_argument('--month', type=int, help='Backfill specific month of 2025 (3-9)')
    parser.add_argument('--check', action='store_true', help='Just show current data counts')
    parser.add_argument('--recent', type=int, help='Backfill last N days only')
    args = parser.parse_args()

    backfiller = MLBBackfiller()

    if args.check:
        backfiller.check_current_data()
        return

    start = args.start
    end = args.end

    if args.month:
        m = args.month
        start = f"2025-{m:02d}-01"
        # End of month
        if m == 9:
            end = "2025-09-28"
        elif m in (4, 6):
            end = f"2025-{m:02d}-30"
        elif m in (3,):
            end = f"2025-{m:02d}-31"  # Only a few days in March
        else:
            end = f"2025-{m:02d}-31"

    if args.recent:
        end_dt = datetime.now() - timedelta(days=1)
        start_dt = end_dt - timedelta(days=args.recent)
        start = start_dt.strftime("%Y-%m-%d")
        end = end_dt.strftime("%Y-%m-%d")

    print(f"\n  Starting backfill: {start} to {end}")
    print(f"  This may take a while (0.3s per API call)...")
    print(f"  Estimated time: ~{((datetime.strptime(end, '%Y-%m-%d') - datetime.strptime(start, '%Y-%m-%d')).days * 5 * 0.3 / 60):.0f} minutes\n")

    backfiller.backfill_date_range(start, end)
    backfiller.check_current_data()


if __name__ == '__main__':
    main()
