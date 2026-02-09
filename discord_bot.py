#!/usr/bin/env python3
"""
Discord Bot Controller for Sports Predictor
============================================

Control your prediction system from Discord on any device (iPad, phone, etc.)

Commands:
  !status          - Show system status
  !picks nba       - Get today's NBA smart picks
  !picks nba 2026-02-10  - Get picks for specific date
  !predict nba     - Run NBA prediction pipeline
  !grade nba       - Run NBA grading pipeline
  !health          - Check API health
  !help            - Show commands

Setup:
1. Create a Discord bot at https://discord.com/developers/applications
2. Get your bot token
3. Set environment variable: DISCORD_BOT_TOKEN=your_token
4. Invite bot to your server with appropriate permissions
5. Run: python discord_bot.py

Requirements:
  pip install discord.py
"""

import os
import sys
import asyncio
import sqlite3
from datetime import datetime, date
from pathlib import Path

# Add shared folder to path
sys.path.insert(0, str(Path(__file__).parent / "shared"))

try:
    import discord
    from discord.ext import commands
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    print("ERROR: discord.py not installed. Run: pip install discord.py")
    sys.exit(1)

# Bot token from environment
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')

# Initialize bot with command prefix
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Project paths
PROJECT_ROOT = Path(__file__).parent
NBA_DB = PROJECT_ROOT / "nba" / "database" / "nba_predictions.db"
NHL_DB = PROJECT_ROOT / "nhl" / "database" / "nhl_predictions_v2.db"


@bot.event
async def on_ready():
    print(f'[BOT] Logged in as {bot.user.name}')
    print(f'[BOT] Ready to receive commands!')


@bot.command(name='status')
async def status(ctx):
    """Show system status"""
    try:
        # Check databases
        nba_status = "OK" if NBA_DB.exists() else "MISSING"
        nhl_status = "OK" if NHL_DB.exists() else "MISSING"

        # Get prediction counts
        nba_count = 0
        nhl_count = 0

        if NBA_DB.exists():
            conn = sqlite3.connect(NBA_DB)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM predictions")
            nba_count = cursor.fetchone()[0]
            cursor.execute("SELECT MAX(game_date) FROM predictions")
            nba_last = cursor.fetchone()[0]
            conn.close()

        if NHL_DB.exists():
            conn = sqlite3.connect(NHL_DB)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM predictions")
            nhl_count = cursor.fetchone()[0]
            cursor.execute("SELECT MAX(game_date) FROM predictions")
            nhl_last = cursor.fetchone()[0]
            conn.close()

        msg = f"""```
SPORTS PREDICTOR STATUS
{'='*40}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}

NBA Database: {nba_status}
  Predictions: {nba_count:,}
  Last Date: {nba_last}

NHL Database: {nhl_status}
  Predictions: {nhl_count:,}
  Last Date: {nhl_last}
```"""
        await ctx.send(msg)

    except Exception as e:
        await ctx.send(f"```Error: {str(e)}```")


@bot.command(name='picks')
async def picks(ctx, sport: str = 'nba', game_date: str = None):
    """Get smart picks for a sport and date"""
    try:
        if game_date is None:
            game_date = date.today().isoformat()

        sport = sport.upper()

        await ctx.send(f"```Fetching {sport} picks for {game_date}...```")

        # Import smart pick selector
        from smart_pick_selector import SmartPickSelector

        selector = SmartPickSelector(sport.lower())
        picks_list = selector.get_smart_picks(
            game_date=game_date,
            min_edge=5.0,
            min_prob=0.55,
            odds_types=['standard', 'goblin'],
            refresh_lines=False
        )

        if not picks_list:
            await ctx.send(f"```No high-edge picks found for {sport} on {game_date}```")
            return

        # Generate and send Discord message
        message = selector.generate_discord_message(picks_list, game_date)
        await ctx.send(message)

    except Exception as e:
        await ctx.send(f"```Error: {str(e)}```")


@bot.command(name='predict')
async def predict(ctx, sport: str = 'nba'):
    """Run prediction pipeline for a sport"""
    try:
        sport = sport.lower()
        await ctx.send(f"```Running {sport.upper()} prediction pipeline...```")

        # Run orchestrator
        import subprocess
        result = subprocess.run(
            [sys.executable, 'orchestrator.py', '--sport', sport, '--mode', 'once', '--operation', 'prediction'],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT)
        )

        # Get last few lines of output
        output = result.stdout[-1500:] if result.stdout else "No output"

        if result.returncode == 0:
            await ctx.send(f"```[OK] {sport.upper()} predictions complete!\n\n{output}```")
        else:
            error = result.stderr[-500:] if result.stderr else "Unknown error"
            await ctx.send(f"```[ERROR] Pipeline failed:\n{error}```")

    except subprocess.TimeoutExpired:
        await ctx.send("```[ERROR] Pipeline timed out after 5 minutes```")
    except Exception as e:
        await ctx.send(f"```Error: {str(e)}```")


@bot.command(name='grade')
async def grade(ctx, sport: str = 'nba', game_date: str = None):
    """Run grading pipeline for a sport"""
    try:
        sport = sport.lower()
        if game_date is None:
            # Grade yesterday by default
            from datetime import timedelta
            game_date = (date.today() - timedelta(days=1)).isoformat()

        await ctx.send(f"```Grading {sport.upper()} for {game_date}...```")

        # Run orchestrator
        import subprocess
        result = subprocess.run(
            [sys.executable, 'orchestrator.py', '--sport', sport, '--mode', 'once', '--operation', 'grading'],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT)
        )

        output = result.stdout[-1500:] if result.stdout else "No output"

        if result.returncode == 0:
            await ctx.send(f"```[OK] {sport.upper()} grading complete!\n\n{output}```")
        else:
            error = result.stderr[-500:] if result.stderr else "Unknown error"
            await ctx.send(f"```[ERROR] Grading failed:\n{error}```")

    except subprocess.TimeoutExpired:
        await ctx.send("```[ERROR] Grading timed out after 5 minutes```")
    except Exception as e:
        await ctx.send(f"```Error: {str(e)}```")


@bot.command(name='health')
async def health(ctx):
    """Check API health"""
    try:
        import requests

        apis = {
            'ESPN NBA': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard',
            'NHL Official': 'https://api-web.nhle.com/v1/schedule/now',
            'PrizePicks': 'https://api.prizepicks.com/projections?per_page=1'
        }

        results = []
        for name, url in apis.items():
            try:
                resp = requests.get(url, timeout=10)
                status = "OK" if resp.status_code == 200 else f"ERR:{resp.status_code}"
            except Exception as e:
                status = f"DOWN"
            results.append(f"{name}: {status}")

        msg = f"""```
API HEALTH CHECK
{'='*30}
{chr(10).join(results)}
```"""
        await ctx.send(msg)

    except Exception as e:
        await ctx.send(f"```Error: {str(e)}```")


@bot.command(name='refresh')
async def refresh(ctx, sport: str = 'nba'):
    """Refresh PrizePicks lines"""
    try:
        await ctx.send(f"```Refreshing PrizePicks {sport.upper()} lines...```")

        from prizepicks_client import PrizePicksIngestion
        ingestion = PrizePicksIngestion()
        result = ingestion.run_ingestion([sport.upper()])

        total = result.get('total_lines', 0)
        await ctx.send(f"```[OK] Fetched {total} {sport.upper()} lines from PrizePicks```")

    except Exception as e:
        await ctx.send(f"```Error: {str(e)}```")


def main():
    if not BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set!")
        print("1. Create a bot at https://discord.com/developers/applications")
        print("2. Get your bot token")
        print("3. Set: export DISCORD_BOT_TOKEN=your_token_here")
        sys.exit(1)

    print("[BOT] Starting Discord bot...")
    bot.run(BOT_TOKEN)


if __name__ == '__main__':
    main()
