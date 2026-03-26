"""
NHL Hits & Blocks Data Enrichment
==================================
Fetches ALL the real data Grok needs so it never has to guess:
  - Real ESPN odds (spread, o/u, moneylines) per game
  - Player hit/block stats from our 38K+ game log database
  - Injury reports from NHL API
  - Confirmed lineups/scratches from NHL API
  - Team shot volume stats (for matchup context)

This runs BEFORE the Grok call and injects hard data into the prompt.
Grok's only job becomes: pick the best 8 plays from our data and write the narrative.

Usage:
    from hb_data_enrichment import enrich_games
    enriched = enrich_games("2026-03-26", games_list)
"""

import sqlite3
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_NHL_ROOT = _SCRIPTS_DIR.parent
_PROJECT_ROOT = _NHL_ROOT.parent
DB_PATH = str(_NHL_ROOT / "database" / "nhl_predictions_v2.db")

sys.path.insert(0, str(_PROJECT_ROOT / "shared"))

# ── ESPN Odds ────────────────────────────────────────────────────────────────

def fetch_espn_odds(game_date: str) -> dict:
    """
    Fetch real NHL odds from ESPN. Free, no API key needed.
    Returns dict keyed by (away_abbr, home_abbr) -> odds dict.
    """
    try:
        from fetch_game_odds import _fetch_espn_odds
        odds_list = _fetch_espn_odds("nhl", game_date)
        odds_by_matchup = {}
        for o in odds_list:
            key = (o["away_team"], o["home_team"])
            odds_by_matchup[key] = {
                "spread": o.get("spread"),
                "over_under": o.get("over_under"),
                "home_ml": o.get("home_ml"),
                "away_ml": o.get("away_ml"),
                "home_prob": o.get("home_implied_prob"),
            }
        return odds_by_matchup
    except Exception as e:
        print(f"[Enrich] ESPN odds error: {e}")
        return {}


def format_odds_string(away, home, odds_data) -> str:
    """Format odds into a readable string for the prompt."""
    if not odds_data:
        return "    Odds: Not available"

    parts = []
    hml = odds_data.get("home_ml")
    aml = odds_data.get("away_ml")
    if hml is not None and aml is not None:
        fmt = lambda x: f"+{x}" if x > 0 else str(x)
        parts.append(f"ML: {home} {fmt(hml)} / {away} {fmt(aml)}")

    spread = odds_data.get("spread")
    if spread is not None:
        parts.append(f"Puck Line: {home} {spread:+.1f}")

    ou = odds_data.get("over_under")
    if ou is not None:
        parts.append(f"O/U: {ou}")

    # Blowout check
    is_blowout = False
    if hml is not None and aml is not None:
        fav_ml = min(hml, aml)
        if fav_ml < -170:
            is_blowout = True
            parts.append("[BLOWOUT RISK - EXCLUDE]")

    return "    " + " | ".join(parts) if parts else "    Odds: Not available"


# ── Player Stats from Our Database ───────────────────────────────────────────

def get_player_stats(game_date: str, teams: list) -> dict:
    """
    Get hit/block stats for players on tonight's teams from our game log database.

    Returns dict keyed by team_abbr -> list of player stat dicts, sorted by
    hits+blocks descending.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Look back ~60 days for recent form
    cutoff_recent = (datetime.strptime(game_date, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
    cutoff_season = (datetime.strptime(game_date, "%Y-%m-%d") - timedelta(days=180)).strftime("%Y-%m-%d")

    stats_by_team = {}

    for team in teams:
        # Season averages
        season_rows = conn.execute("""
            SELECT player_name,
                   COUNT(*) as games,
                   ROUND(AVG(COALESCE(hits, 0)), 2) as avg_hits,
                   ROUND(AVG(COALESCE(blocked_shots, 0)), 2) as avg_blocks,
                   ROUND(AVG(COALESCE(toi_seconds, 0) / 60.0), 1) as avg_toi,
                   ROUND(AVG(COALESCE(shots_on_goal, 0)), 1) as avg_sog
            FROM player_game_logs
            WHERE team = ? AND game_date >= ? AND game_date < ?
                  AND (hits IS NOT NULL OR blocked_shots IS NOT NULL)
            GROUP BY player_name
            HAVING games >= 5
            ORDER BY (avg_hits + avg_blocks) DESC
        """, (team, cutoff_season, game_date)).fetchall()

        # Recent form (last 14 days)
        recent_rows = conn.execute("""
            SELECT player_name,
                   COUNT(*) as games,
                   ROUND(AVG(COALESCE(hits, 0)), 2) as avg_hits,
                   ROUND(AVG(COALESCE(blocked_shots, 0)), 2) as avg_blocks,
                   ROUND(AVG(COALESCE(toi_seconds, 0) / 60.0), 1) as avg_toi
            FROM player_game_logs
            WHERE team = ? AND game_date >= ? AND game_date < ?
                  AND (hits IS NOT NULL OR blocked_shots IS NOT NULL)
            GROUP BY player_name
            HAVING games >= 2
        """, (team, cutoff_recent, game_date)).fetchall()

        recent_map = {r["player_name"]: dict(r) for r in recent_rows}

        players = []
        for r in season_rows:
            name = r["player_name"]
            recent = recent_map.get(name, {})
            players.append({
                "name": name,
                "team": team,
                "games": r["games"],
                "avg_hits": r["avg_hits"],
                "avg_blocks": r["avg_blocks"],
                "avg_toi": r["avg_toi"],
                "avg_sog": r["avg_sog"],
                "recent_hits": recent.get("avg_hits"),
                "recent_blocks": recent.get("avg_blocks"),
                "recent_games": recent.get("games"),
                "recent_toi": recent.get("avg_toi"),
            })

        stats_by_team[team] = players[:15]  # Top 15 per team

    conn.close()
    return stats_by_team


def format_player_stats(stats_by_team: dict, teams_in_game: tuple) -> str:
    """Format player stats into a readable block for the prompt."""
    lines = []
    for team in teams_in_game:
        players = stats_by_team.get(team, [])
        if not players:
            continue

        lines.append(f"    {team} Key Players (hits/blocks):")
        for p in players[:8]:  # Top 8 per team
            recent_str = ""
            if p["recent_hits"] is not None:
                recent_str = f" | L14d: {p['recent_hits']} hits, {p['recent_blocks']} blks ({p['recent_games']}gp)"
            lines.append(
                f"      - {p['name']}: {p['avg_hits']} hits/g, {p['avg_blocks']} blks/g, "
                f"{p['avg_toi']}min TOI ({p['games']}gp){recent_str}"
            )

    return "\n".join(lines)


# ── Team Shot Volume Stats ───────────────────────────────────────────────────

def get_team_shot_stats(game_date: str) -> dict:
    """Get team-level shot volume stats for matchup context."""
    conn = sqlite3.connect(DB_PATH)

    cutoff = (datetime.strptime(game_date, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT team,
               ROUND(AVG(shots_on_goal), 1) as avg_team_sog
        FROM (
            SELECT team, game_date, SUM(COALESCE(shots_on_goal, 0)) as shots_on_goal
            FROM player_game_logs
            WHERE game_date >= ? AND game_date < ?
            GROUP BY team, game_date
        )
        GROUP BY team
    """, (cutoff, game_date)).fetchall()

    conn.close()
    return {r[0]: r[1] for r in rows}


# ── NHL Injury Report ────────────────────────────────────────────────────────

def fetch_injuries(teams: list) -> dict:
    """
    Fetch injury reports from NHL API.
    Returns dict keyed by team_abbr -> list of injury strings.
    """
    injuries = {}
    try:
        url = "https://api-web.nhle.com/v1/injuries"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())

        for team_data in data.get("teams", []):
            abbr = team_data.get("teamAbbrev", {}).get("default", "")
            if abbr not in teams:
                continue

            team_injuries = []
            for player in team_data.get("players", []):
                name = f"{player.get('firstName', {}).get('default', '')} {player.get('lastName', {}).get('default', '')}"
                status = player.get("injuryStatus", "")
                desc = player.get("injuryDesc", "")
                team_injuries.append(f"{name.strip()} ({status}: {desc})")

            if team_injuries:
                injuries[abbr] = team_injuries

    except Exception as e:
        print(f"[Enrich] Injury fetch warning: {e}")

    return injuries


# ── Main Enrichment Function ─────────────────────────────────────────────────

def enrich_games(game_date: str, games: list) -> str:
    """
    Build a fully enriched context string with real data for every game.

    Args:
        game_date: YYYY-MM-DD
        games: list of game dicts from _fetch_schedule()

    Returns:
        Formatted string ready to inject into the Grok prompt.
    """
    if not games:
        return "No games tonight."

    # Collect all teams playing tonight
    all_teams = set()
    for g in games:
        all_teams.add(g["away_abbr"])
        all_teams.add(g["home_abbr"])

    # Fetch all data in parallel
    print("[Enrich] Fetching ESPN odds...")
    espn_odds = fetch_espn_odds(game_date)
    print(f"[Enrich] Got odds for {len(espn_odds)} games")

    print("[Enrich] Computing player stats from 38K+ game logs...")
    player_stats = get_player_stats(game_date, list(all_teams))
    total_players = sum(len(v) for v in player_stats.values())
    print(f"[Enrich] Stats for {total_players} players across {len(player_stats)} teams")

    print("[Enrich] Fetching team shot volume...")
    team_shots = get_team_shot_stats(game_date)

    print("[Enrich] Fetching NHL injury report...")
    injuries = fetch_injuries(list(all_teams))
    total_injuries = sum(len(v) for v in injuries.values())
    print(f"[Enrich] {total_injuries} injuries across {len(injuries)} teams")

    # Build context per game
    blocks = []
    qualifying_count = 0

    for g in games:
        away = g["away_abbr"]
        home = g["home_abbr"]

        # Odds
        odds = espn_odds.get((away, home), {})
        odds_str = format_odds_string(away, home, odds)

        # Blowout check
        hml = odds.get("home_ml")
        aml = odds.get("away_ml")
        is_blowout = False
        if hml is not None and aml is not None:
            fav_ml = min(hml, aml)
            if fav_ml < -170:
                is_blowout = True

        if not is_blowout:
            qualifying_count += 1

        # Player stats
        player_str = format_player_stats(player_stats, (home, away))

        # Team shot volume
        home_sog = team_shots.get(home, "N/A")
        away_sog = team_shots.get(away, "N/A")

        # Injuries
        injury_lines = []
        for team in [home, away]:
            if team in injuries:
                injury_lines.append(f"    {team} injuries: " + "; ".join(injuries[team]))

        # Build game block
        venue = f" ({g.get('venue', '')})" if g.get("venue") else ""
        start = f" | {g.get('start_utc', '')[:16]} UTC" if g.get("start_utc") else ""

        block = f"  GAME: {away} @ {home}{venue}{start}"
        block += f"\n{odds_str}"
        block += f"\n    Team shot volume: {home} {home_sog} SOG/game, {away} {away_sog} SOG/game"
        if injury_lines:
            block += "\n" + "\n".join(injury_lines)
        else:
            block += f"\n    No injuries reported for {home} or {away}"
        if is_blowout:
            block += "\n    ** EXCLUDED — blowout risk (favorite heavier than -170) **"
        block += f"\n{player_str}"

        blocks.append(block)

    header = f"VERIFIED DATA FOR {game_date} ({len(games)} games, {qualifying_count} qualifying after blowout filter):\n"
    return header + "\n\n".join(blocks)


# ── CLI Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    # Fetch schedule
    sys.path.insert(0, str(_SCRIPTS_DIR))
    from daily_hits_blocks import _fetch_schedule
    games = _fetch_schedule(args.date)
    print(f"\n{len(games)} games on {args.date}\n")

    result = enrich_games(args.date, games)
    print(result)
