"""
NBA Auto-Grader with Multi-API Support
=======================================

Uses ESPN API as primary source (fast, reliable)
Falls back to NBA Stats API if ESPN fails

This solves the API lag issue permanently.
"""

import sqlite3
from datetime import datetime, timedelta
from fuzzywuzzy import fuzz
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from nba_config import DB_PATH, DISCORD_WEBHOOK_URL
from espn_nba_api import ESPNNBAApi


class MultiAPIGrader:
    """Grader that uses multiple API sources for reliability."""
    
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.espn_api = ESPNNBAApi()
        self.nba_api = None  # Lazy load if needed
    
    def grade_yesterday(self, target_date=None):
        """Grade predictions using ESPN API (primary) or NBA Stats API (fallback)."""
        
        if target_date is None:
            target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        print(f"\n[NBA] AUTO-GRADER (Multi-API)")
        print(f"Grading date: {target_date}")
        print("=" * 60)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Ensure profit column exists (idempotent migration)
        try:
            cursor.execute("ALTER TABLE prediction_outcomes ADD COLUMN profit REAL")
            conn.commit()
        except Exception:
            pass  # Column already exists

        # Get predictions to grade
        cursor.execute("""
            SELECT id, game_id, player_name, prop_type, line, prediction, probability, odds_type
            FROM predictions
            WHERE game_date = ?
              AND id NOT IN (SELECT prediction_id FROM prediction_outcomes)
        """, (target_date,))
        
        predictions = cursor.fetchall()
        print(f"[STATS] Found {len(predictions)} predictions to grade\n")
        
        if len(predictions) == 0:
            print("[OK] No predictions to grade")
            conn.close()
            return
        
        # Try ESPN API first
        print("[SYNC] Attempting ESPN API (primary)...")
        games, all_player_stats = self._try_espn_api(target_date)
        
        # If ESPN failed or returned no data, try NBA Stats API
        if len(all_player_stats) == 0:
            print("\n[WARN]  ESPN API returned no data")
            print("[SYNC] Falling back to NBA Stats API...")
            games, all_player_stats = self._try_nba_stats_api(target_date)
        
        if len(all_player_stats) == 0:
            print("\n[FAIL] BOTH APIs FAILED")
            print("   No player stats available from either source")
            print("\n[TIP] Try again later or check if games were actually played")
            conn.close()
            return
        
        print(f"\n[DATA] Total player stats loaded: {len(all_player_stats)}\n")
        
        # Grade predictions
        graded_count = 0
        hit_count = 0
        ungraded = []
        
        print(f"Grading predictions...")
        
        for pred in predictions:
            pred_id, game_id, player_name, prop_type, line, prediction, probability, odds_type = pred
            
            match_result = self._find_player_stats(player_name, all_player_stats)
            
            if match_result is None:
                ungraded.append((player_name, "No match found"))
                continue
            
            player_stats, match_tier, match_score = match_result

            # Skip DNP players
            if player_stats.get('minutes', 1) == 0:
                ungraded.append((player_name, "DNP (0 minutes played)"))
                continue

            actual_value = self._get_stat_value(player_stats, prop_type)

            if actual_value is None:
                ungraded.append((player_name, f"Unknown prop type: {prop_type}"))
                continue

            if prediction == 'OVER':
                outcome = 'HIT' if actual_value > line else 'MISS'
            else:
                outcome = 'HIT' if actual_value <= line else 'MISS'

            # Calculate profit based on odds_type ($100 unit)
            if outcome == 'HIT':
                if odds_type == 'goblin':
                    profit = 31.25  # -320 odds
                elif odds_type == 'demon':
                    profit = 120.0  # +120 odds
                else:
                    profit = 90.91  # -110 odds
            else:
                profit = -100.0

            cursor.execute("""
                INSERT INTO prediction_outcomes
                (prediction_id, game_id, game_date, player_name, prop_type, line,
                 prediction, actual_value, outcome, match_tier, match_score, profit, odds_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pred_id, game_id, target_date, player_name, prop_type, line,
                prediction, actual_value, outcome, match_tier, match_score, profit, odds_type
            ))
            
            graded_count += 1
            if outcome == 'HIT':
                hit_count += 1
        
        # Backfill profit for any existing rows that are missing it
        cursor.execute("""
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

        # Save player logs
        logs_saved = self._save_player_game_logs(conn, all_player_stats, target_date)

        conn.commit()
        
        accuracy = (hit_count / graded_count * 100) if graded_count > 0 else 0
        
        print("\n" + "=" * 60)
        print(f"[OK] GRADING COMPLETE")
        print(f"[STATS] Results: {hit_count}/{graded_count} ({accuracy:.1f}%)")
        print(f"Saved {logs_saved} player logs to database")
        
        if ungraded:
            print(f"\n[WARN]  Ungraded: {len(ungraded)} predictions")
            for player, reason in ungraded[:5]:
                # Handle Unicode characters that can't be encoded in Windows console
                safe_player = player.encode('ascii', 'replace').decode('ascii')
                print(f"   - {safe_player}: {reason}")
        
        conn.close()
        
        if DISCORD_WEBHOOK_URL:
            self._send_discord_notification(target_date, graded_count, hit_count, accuracy, logs_saved)
        
        return {
            'graded': graded_count,
            'hits': hit_count,
            'accuracy': accuracy,
            'logs_saved': logs_saved
        }
    
    def _try_espn_api(self, game_date):
        """Try fetching data from ESPN API."""
        try:
            games = self.espn_api.get_scoreboard(game_date)
            print(f"   [OK] Found {len(games)} games")
            
            all_player_stats = []
            final_count = 0
            
            for game in games:
                if game['status'] == 'Final':
                    final_count += 1
                    print(f"   Loading: {game['away_team']} @ {game['home_team']}")
                    
                    boxscore = self.espn_api.get_boxscore(game['espn_game_id'])
                    if boxscore:
                        # Add game_id field for compatibility
                        for player in boxscore:
                            player['game_id'] = game['game_id']
                        all_player_stats.extend(boxscore)
                        print(f"      > {len(boxscore)} players")
            
            print(f"\n   [OK] ESPN API: {final_count} final games, {len(all_player_stats)} players")
            return games, all_player_stats
            
        except Exception as e:
            print(f"   [FAIL] ESPN API error: {e}")
            return [], []
    
    def _try_nba_stats_api(self, game_date):
        """Try fetching data from NBA Stats API (fallback)."""
        try:
            # Lazy load NBA Stats API
            if self.nba_api is None:
                from data_fetchers.nba_stats_api import NBAStatsAPI
                self.nba_api = NBAStatsAPI()
            
            games = self.nba_api.get_scoreboard(game_date)
            print(f"   [OK] Found {len(games)} games")
            
            all_player_stats = []
            final_count = 0
            
            for game in games:
                if game['status'] == 'Final':
                    final_count += 1
                    print(f"   Loading: {game['away_team']} @ {game['home_team']}")
                    
                    boxscore = self.nba_api.get_boxscore_traditional(game['game_id'])
                    all_player_stats.extend(boxscore)
                    print(f"      > {len(boxscore)} players")
            
            print(f"\n   [OK] NBA Stats API: {final_count} final games, {len(all_player_stats)} players")
            return games, all_player_stats
            
        except Exception as e:
            print(f"   [FAIL] NBA Stats API error: {e}")
            return [], []
    
    def _find_player_stats(self, player_name, all_stats):
        """Find player using fuzzy matching."""
        best_match = None
        best_score = 0
        best_tier = 5
        
        for stats in all_stats:
            actual_name = stats['player_name']
            
            if player_name.lower() == actual_name.lower():
                return (stats, 1, 100)
            
            score = fuzz.ratio(player_name.lower(), actual_name.lower())
            if score > best_score:
                best_score = score
                best_match = stats
                best_tier = 2
        
        if best_score >= 80:
            return (best_match, best_tier, best_score)
        
        return None
    
    @staticmethod
    def _get_stat_value(stats, prop_type):
        """Extract stat value for a given prop type."""
        stat_map = {
            'points': 'points',
            'rebounds': 'rebounds',
            'assists': 'assists',
            'threes': 'threes_made',
            'steals': 'steals',
            'blocked_shots': 'blocks',
            'turnovers': 'turnovers',
            'stocks': lambda s: s.get('steals', 0) + s.get('blocks', 0),
            'pra': lambda s: s.get('points', 0) + s.get('rebounds', 0) + s.get('assists', 0),
            'pts_rebs': lambda s: s.get('points', 0) + s.get('rebounds', 0),
            'pts_asts': lambda s: s.get('points', 0) + s.get('assists', 0),
            'rebs_asts': lambda s: s.get('rebounds', 0) + s.get('assists', 0),
            'blks_stls': lambda s: s.get('blocks', 0) + s.get('steals', 0),
            # PrizePicks fantasy: PTS + 1.2*REB + 1.5*AST + 2*STL + 2*BLK - TOV
            'fantasy': lambda s: (s.get('points', 0) + 1.2 * s.get('rebounds', 0) +
                                  1.5 * s.get('assists', 0) + 2.0 * s.get('steals', 0) +
                                  2.0 * s.get('blocks', 0) - s.get('turnovers', 0)),
            'minutes': 'minutes',
        }

        mapper = stat_map.get(prop_type)

        if mapper is None:
            return None  # Unknown prop type - do not grade
        elif callable(mapper):
            return mapper(stats)
        else:
            return stats.get(mapper, 0)
    
    def _save_player_game_logs(self, conn, all_stats, game_date):
        """Save player logs to database."""
        cursor = conn.cursor()
        saved_count = 0
        
        for stats in all_stats:
            pra = stats['points'] + stats['rebounds'] + stats['assists']
            stocks = stats['steals'] + stats['blocks']
            
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO player_game_logs
                    (game_id, game_date, player_name, team, opponent, home_away,
                     minutes, points, rebounds, assists, steals, blocks, turnovers,
                     threes_made, fga, fgm, fta, ftm, plus_minus, pra, stocks)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    stats['game_id'], game_date, stats['player_name'], stats['team'],
                    '', 'H',
                    stats['minutes'], stats['points'], stats['rebounds'], stats['assists'],
                    stats['steals'], stats['blocks'], stats['turnovers'],
                    stats['threes_made'], stats['fga'], stats['fgm'],
                    stats['fta'], stats['ftm'], stats['plus_minus'],
                    pra, stocks
                ))
                saved_count += 1
            except:
                pass
        
        return saved_count
    
    def _send_discord_notification(self, date, graded, hits, accuracy, logs_saved):
        """Send Discord notification."""
        try:
            import requests
            
            message = f"""
[NBA] **NBA Auto-Grader Report** (Multi-API)
[DATE] Date: {date}

[STATS] **Results:**
- Graded: {graded}
- Hits: {hits}
- Accuracy: {accuracy:.1f}%

**Continuous Learning:**
- Player logs saved: {logs_saved}

[OK] GRADING COMPLETE
            """
            
            payload = {"content": message}
            requests.post(DISCORD_WEBHOOK_URL, json=payload)
        except:
            pass


if __name__ == "__main__":
    grader = MultiAPIGrader()
    
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        target_date = None
    
    grader.grade_yesterday(target_date)
