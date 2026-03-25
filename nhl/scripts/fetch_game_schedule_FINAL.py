"""
Fetch NHL Game Schedule - PROPERLY FIXED
Only saves games that match the target date
"""

import sqlite3
import requests
import sys
from datetime import datetime
from v2_config import DB_PATH

def fetch_game_schedule(target_date: str, force_refresh: bool = False):
    """
    Fetch NHL games for a specific date and save to database
    
    Args:
        target_date: Date in YYYY-MM-DD format
        force_refresh: If True, delete existing games for date first
    """
    print("=" * 80)
    print("NHL GAME SCHEDULE FETCHER - FIXED (FILTERS BY DATE)")
    print("=" * 80)
    print()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if games already exist for this date
    cursor.execute("SELECT COUNT(*) FROM games WHERE game_date = ?", (target_date,))
    existing_count = cursor.fetchone()[0]
    
    if existing_count > 0:
        print(f"[WARN]  Found {existing_count} existing games for {target_date}")
        if force_refresh:
            print("   Force refresh enabled - deleting old games...")
            cursor.execute("DELETE FROM games WHERE game_date = ?", (target_date,))
            conn.commit()
            print("   [OK] Old games deleted")
        else:
            print("   Skipping fetch (games already exist)")
            print("   Use --force flag to refresh: python script.py 2025-11-06 --force")
            conn.close()
            return True
    print()
    
    # Fetch from NHL API
    url = f"https://api-web.nhle.com/v1/schedule/{target_date}"
    
    print(f"Fetching NHL games for {target_date}...")
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[ERROR] Error fetching schedule: {e}")
        conn.close()
        return False
    
    # Parse games - ONLY for the target date!
    games = []
    games_found_total = 0
    
    if 'gameWeek' in data:
        for day in data['gameWeek']:
            if 'games' in day and 'date' in day:
                day_date = day['date']  # e.g., "2025-11-06"
                
                # COUNT all games (for reporting)
                games_found_total += len(day['games'])
                
                # ONLY process games matching target date
                if day_date == target_date:
                    print(f"   Found {len(day['games'])} games on {day_date}")
                    
                    for game in day['games']:
                        away_team = game['awayTeam']['abbrev']
                        home_team = game['homeTeam']['abbrev']
                        
                        # Create unique game_id
                        game_id = f"{target_date}_{away_team}_{home_team}"
                        
                        games.append({
                            'game_id': game_id,
                            'game_date': target_date,
                            'away_team': away_team,
                            'home_team': home_team,
                            'season': '2025-2026',
                            'created_at': datetime.now().isoformat(),
                            'updated_at': datetime.now().isoformat()
                        })
                else:
                    print(f"   Skipping {len(day['games'])} games on {day_date} (not target date)")
    
    print()
    print(f"API returned {games_found_total} games total (across week)")
    print(f"Filtered to {len(games)} games on {target_date}")
    print()
    
    if not games:
        print(f"[OK] No NHL games scheduled for {target_date} (off day or break)")
        print("   Prediction pipeline will skip today.")
        conn.close()
        return True  # Not an error - just an off day
    
    print(f"[OK] Games on {target_date}:")
    for game in games:
        print(f"  {game['away_team']} @ {game['home_team']}")
    print()
    
    # Save to database with REPLACE strategy
    print("Saving to database...")
    saved_count = 0
    error_count = 0
    
    for game in games:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO games 
                (game_id, game_date, away_team, home_team, season, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                game['game_id'],
                game['game_date'],
                game['away_team'],
                game['home_team'],
                game['season'],
                game['created_at'],
                game['updated_at']
            ))
            saved_count += 1
        except Exception as e:
            print(f"   [WARN]  Failed to save {game['away_team']} @ {game['home_team']}: {e}")
            error_count += 1
    
    conn.commit()
    
    # Verify
    cursor.execute("SELECT COUNT(*) FROM games WHERE game_date = ?", (target_date,))
    final_count = cursor.fetchone()[0]
    
    conn.close()
    
    print()
    print(f"[OK] Saved {saved_count} games")
    if error_count > 0:
        print(f"[WARN]  {error_count} errors")
    print(f"[OK] Total games in database for {target_date}: {final_count}")
    print()
    
    if final_count <= 16:
        print("[OK] Game count looks correct (max 16 games per day for 32 teams)")
    else:
        print(f"[WARN]  WARNING: {final_count} games seems high (max should be 16)")
    
    print()
    print("[OK] Ready for prediction generation!")
    print(f"   Run: python generate_tomorrows_picks_fixed.py {target_date}")
    print()
    
    return saved_count > 0


if __name__ == "__main__":
    # Parse arguments
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        # Default to tomorrow
        from datetime import timedelta
        target_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Check for force flag
    force_refresh = '--force' in sys.argv or '-f' in sys.argv
    
    success = fetch_game_schedule(target_date, force_refresh)
    sys.exit(0 if success else 1)
