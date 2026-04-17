#!/usr/bin/env python3
"""
Discord Bot Controller for Sports Predictor
============================================

Control your prediction system from Discord on any device (iPad, phone, etc.)

Commands:
  !status          - Show system status
  !picks nba       - Get today's NBA smart picks
  !picks nba 2026-02-10  - Get picks for specific date
  !gamelines nba   - Get today's game line predictions (ML, spread, total)
  !gamelines nhl 2026-03-25  - Game lines for specific date
  !parlay          - Random 4-leg parlay from today's top picks (both sports)
  !parlay nba 3    - 3-leg NBA-only parlay
  !parlay nhl 5    - 5-leg NHL-only parlay (2-6 legs supported)
  !predict nba     - Run NBA prediction pipeline
  !grade nba       - Run NBA grading pipeline
  !refresh         - Re-fetch PP lines and refresh smart picks for both sports
  !refresh nhl     - Refresh NHL only
  !health          - Check API health
  !help            - Show commands

HOTKEYS (short aliases):
  !g [nba|nhl|both]          - Grade yesterday (or: !g nba 2026-04-14)
  !p [nba|nhl|both]          - Run predictions for today
  !r [nba|nhl|both]          - PP sync / refresh lines
  !run [nba|nhl|both]        - Grade + Predict + PP-sync in one shot

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
import json
import random
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
async def refresh(ctx, sport: str = 'both'):
    """
    Re-fetch PrizePicks lines and refresh smart picks in Supabase.

    Usage: !refresh [nba|nhl|both]
    Runs the full afternoon PP re-sync: fetch lines -> re-match smart picks -> update app.
    Safe to run anytime — does not re-generate predictions or touch the SQLite DB.
    """
    try:
        sports = ['nba', 'nhl'] if sport.lower() == 'both' else [sport.lower()]
        await ctx.send(f"```Refreshing {sport.upper()} PrizePicks lines and smart picks...```")

        import subprocess
        all_success = True
        summary_lines = []

        for s in sports:
            result = subprocess.run(
                [sys.executable, 'orchestrator.py', '--sport', s, '--mode', 'once', '--operation', 'pp-sync'],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(PROJECT_ROOT)
            )
            if result.returncode == 0:
                # Pull the summary line from output
                for line in result.stdout.splitlines():
                    if '[PP-SYNC] Complete:' in line:
                        summary_lines.append(f"[{s.upper()}] {line.split('[PP-SYNC] Complete: ')[1]}")
                        break
                else:
                    summary_lines.append(f"[{s.upper()}] Done")
            else:
                all_success = False
                summary_lines.append(f"[{s.upper()}] FAILED")

        status = "[OK]" if all_success else "[WARN]"
        await ctx.send(f"```{status} PP sync complete!\n" + "\n".join(summary_lines) + "```")

    except subprocess.TimeoutExpired:
        await ctx.send("```[ERROR] PP sync timed out after 5 minutes```")
    except Exception as e:
        await ctx.send(f"```Error: {str(e)}```")


def _fetch_top_picks_for_parlay(sport: str, game_date: str, pool_size: int = 10) -> list:
    """Fetch top picks from DB for parlay generation. Mirrors orchestrator._fetch_top_picks."""
    db = NBA_DB if sport == 'nba' else NHL_DB
    if not db.exists():
        return []

    conn = sqlite3.connect(str(db))
    cursor = conn.cursor()

    if sport == 'nba':
        cursor.execute("""
            SELECT player_name, team, opponent, prop_type, line, prediction,
                   probability, home_away, f_l5_success_rate, f_current_streak
            FROM predictions
            WHERE game_date = ?
              AND f_insufficient_data = 0
              AND f_games_played >= 5
              AND probability BETWEEN 0.5238 AND 0.95
            GROUP BY player_name
            HAVING probability = MAX(probability)
            ORDER BY probability DESC
            LIMIT ?
        """, (game_date, pool_size))
        rows = cursor.fetchall()
        conn.close()

        picks = []
        for player, team, opp, prop, line, direction, prob, ha, l5_rate, streak in rows:
            picks.append(dict(player=player, team=team, opp=opp, prop=prop,
                              line=line, direction=direction, prob=prob,
                              ha_str="vs" if ha == "H" else "@",
                              l5_rate=l5_rate or 0, streak=streak or 0, sport='NBA'))
        return picks

    else:  # NHL
        cursor.execute("""
            SELECT player_name, team, opponent, prop_type, line, prediction,
                   probability, features_json
            FROM predictions
            WHERE game_date = ?
              AND probability BETWEEN 0.5238 AND 0.95
            ORDER BY probability DESC
        """, (game_date,))
        rows = cursor.fetchall()
        conn.close()

        seen = {}
        for player, team, opp, prop, line, direction, prob, feat_json in rows:
            if player in seen:
                continue
            try:
                features = json.loads(feat_json) if feat_json else {}
            except Exception:
                features = {}
            if features.get('games_played', 0) < 5:
                continue
            l5_rate = features.get('success_rate_l5', 0) or 0
            streak = features.get('current_streak', 0) or 0
            is_home = features.get('is_home', 0)
            seen[player] = dict(player=player, team=team, opp=opp, prop=prop,
                                line=line, direction=direction, prob=prob,
                                ha_str="vs" if is_home else "@",
                                l5_rate=l5_rate, streak=streak, sport='NHL')

        sorted_picks = sorted(seen.values(), key=lambda p: -p['prob'])
        return sorted_picks[:pool_size]


def _format_parlay_leg(i: int, pick: dict) -> str:
    prop_str = pick['prop'].upper().replace('_', ' ')
    conf = int(pick['prob'] * 100)
    sport_tag = f"[{pick['sport']}]"
    return (
        f"`{i}.` **{pick['player']}** ({pick['team']} {pick['ha_str']} {pick['opp']})  "
        f"{pick['direction']} {pick['line']} {prop_str} {sport_tag}  — {conf}%"
    )


@bot.command(name='parlay')
async def parlay_cmd(ctx, sport: str = 'both', size: int = 4):
    """Generate a quick parlay from today's top model picks.

    Usage: !parlay [nba|nhl|both] [2-6]
    Examples:
      !parlay          -> 4-leg parlay from both sports
      !parlay nba 3    -> 3-leg NBA-only parlay
      !parlay nhl 5    -> 5-leg NHL-only parlay
    """
    try:
        sport = sport.lower()
        if sport not in ('nba', 'nhl', 'both'):
            await ctx.send("```Usage: !parlay [nba|nhl|both] [2-6]\nExample: !parlay both 4```")
            return

        size = max(2, min(6, size))
        game_date = date.today().isoformat()

        # Build pool from requested sports (top 10 per sport = quality gate)
        pool = []
        if sport in ('nba', 'both'):
            pool.extend(_fetch_top_picks_for_parlay('nba', game_date, pool_size=10))
        if sport in ('nhl', 'both'):
            pool.extend(_fetch_top_picks_for_parlay('nhl', game_date, pool_size=10))

        if len(pool) < size:
            await ctx.send(
                f"```Not enough qualifying picks today (need {size}, found {len(pool)}).\n"
                f"Try a smaller size or check that predictions ran.```"
            )
            return

        # Random sample from the pool so each call gives a fresh combo
        legs = random.sample(pool, size)
        legs.sort(key=lambda p: -p['prob'])  # highest confidence first

        combined_prob = 1.0
        for leg in legs:
            combined_prob *= leg['prob']

        sport_label = sport.upper() if sport != 'both' else 'NBA + NHL'
        pick_lines = [_format_parlay_leg(i + 1, p) for i, p in enumerate(legs)]

        msg = (
            f"**QUICK PARLAY — {sport_label} — {game_date}**\n"
            f"Sampled from today's top model picks\n"
            f"{'=' * 44}\n"
            + "\n".join(pick_lines)
            + f"\n{'=' * 44}\n"
            f"Combined probability: ~{int(combined_prob * 100)}%\n"
            f"_Run !parlay again for a different combo_"
        )
        await ctx.send(msg)

    except Exception as e:
        await ctx.send(f"```Error generating parlay: {str(e)}```")


@bot.command(name='gamelines')
async def cmd_gamelines(ctx, sport: str = "nba", game_date: str = None):
    """Get today's game line predictions (moneyline, spread, total)."""
    sport = sport.upper()
    if sport not in ["NHL", "NBA", "MLB"]:
        await ctx.send("Usage: `!gamelines nba` or `!gamelines nhl 2026-03-25`")
        return

    if game_date is None:
        game_date = date.today().isoformat()

    db_map = {
        "NHL": PROJECT_ROOT / "nhl" / "database" / "nhl_predictions_v2.db",
        "NBA": PROJECT_ROOT / "nba" / "database" / "nba_predictions.db",
        "MLB": PROJECT_ROOT / "mlb" / "database" / "mlb_predictions.db",
    }
    db_path = db_map.get(sport)
    if not db_path or not db_path.exists():
        await ctx.send(f"Database not found for {sport}")
        return

    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("""
            SELECT home_team, away_team, bet_type, bet_side, line,
                   prediction, probability, edge, confidence_tier
            FROM game_predictions
            WHERE game_date = ?
            ORDER BY
                CASE confidence_tier WHEN 'SHARP' THEN 1 WHEN 'LEAN' THEN 2 ELSE 3 END,
                edge DESC
        """, (game_date,)).fetchall()
        conn.close()
    except Exception as e:
        await ctx.send(f"Error fetching game lines: {e}")
        return

    if not rows:
        await ctx.send(f"No game predictions for {sport} on {game_date}")
        return

    # Build message — show SHARP and LEAN plays only
    sharp_lines = []
    lean_lines = []
    for r in rows:
        home, away, bt, side, line, pred, prob, edge, tier = r
        if tier == "PASS":
            continue
        entry = f"{away} @ {home} | {bt} {side}"
        if line:
            entry += f" ({line:+.1f})" if bt == "spread" else f" ({line:.1f})"
        entry += f" -> {pred} {prob*100:.0f}% edge={edge*100:+.1f}%"

        if tier == "SHARP":
            sharp_lines.append(f"[SHARP] {entry}")
        else:
            lean_lines.append(f"[LEAN]  {entry}")

    msg_parts = [f"```", f"[{sport}] Game Lines - {game_date}", f"{'='*50}"]
    if sharp_lines:
        msg_parts.append("")
        msg_parts.extend(sharp_lines[:10])
    if lean_lines:
        msg_parts.append("")
        msg_parts.extend(lean_lines[:10])
    if not sharp_lines and not lean_lines:
        msg_parts.append("No SHARP or LEAN plays today")
    msg_parts.append(f"\n{len(rows)} total predictions | {len(sharp_lines)} SHARP | {len(lean_lines)} LEAN")
    msg_parts.append("```")

    await ctx.send("\n".join(msg_parts))


async def _run_script(sport: str, operation: str, extra_args: list = None) -> tuple[bool, str]:
    """Run an orchestrator operation and return (success, summary_line)."""
    import subprocess
    cmd = [sys.executable, 'orchestrator.py', '--sport', sport, '--mode', 'once', '--operation', operation]
    if extra_args:
        cmd.extend(extra_args)
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=360, cwd=str(PROJECT_ROOT))
    )
    success = result.returncode == 0
    # Pull a compact summary from the last non-empty output line
    lines = [l for l in (result.stdout or '').splitlines() if l.strip()]
    summary = lines[-1] if lines else (result.stderr[-200:] if result.stderr else 'no output')
    return success, summary


async def _grade_sport(sport: str, game_date: str) -> tuple[bool, str]:
    """Grade a specific date by calling the grading script directly."""
    import subprocess
    script_map = {
        'nhl': ['nhl/scripts/v2_auto_grade_yesterday_v3_RELIABLE.py', game_date],
        'nba': ['nba/scripts/auto_grade_multi_api_FIXED.py', game_date],
        'mlb': ['mlb/scripts/auto_grade_daily.py', game_date],
    }
    if sport not in script_map:
        return False, f'Unknown sport: {sport}'
    cmd = [sys.executable] + script_map[sport]
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=360, cwd=str(PROJECT_ROOT))
    )
    success = result.returncode == 0
    # Find the GRADING COMPLETE / SUCCESS summary line
    for line in reversed((result.stdout or '').splitlines()):
        if any(k in line for k in ('COMPLETE', 'SUCCESS', 'Results:', 'ERROR', 'FAIL')):
            return success, line.strip()
    return success, 'done' if success else (result.stderr[-200:] if result.stderr else 'failed')


@bot.command(name='g')
async def hotkey_grade(ctx, sport: str = 'both', game_date: str = None):
    """Hotkey: grade yesterday (or a specific date). Usage: !g [nba|nhl|both] [YYYY-MM-DD]"""
    from datetime import timedelta
    if game_date is None:
        game_date = (date.today() - timedelta(days=1)).isoformat()

    sports = ['nba', 'nhl'] if sport.lower() == 'both' else [sport.lower()]
    await ctx.send(f"```Grading {sport.upper()} for {game_date}...```")

    lines = []
    all_ok = True
    for s in sports:
        ok, summary = await _grade_sport(s, game_date)
        tag = '[OK]' if ok else '[ERR]'
        lines.append(f'{tag} {s.upper()}: {summary}')
        if not ok:
            all_ok = False

    status = '[OK]' if all_ok else '[WARN]'
    await ctx.send(f"```{status} Grade done — {game_date}\n" + "\n".join(lines) + "```")


@bot.command(name='p')
async def hotkey_predict(ctx, sport: str = 'both'):
    """Hotkey: run predictions for today. Usage: !p [nba|nhl|both]"""
    sports = ['nba', 'nhl'] if sport.lower() == 'both' else [sport.lower()]
    await ctx.send(f"```Running {sport.upper()} predictions...```")

    lines = []
    all_ok = True
    for s in sports:
        ok, summary = await _run_script(s, 'prediction')
        tag = '[OK]' if ok else '[ERR]'
        lines.append(f'{tag} {s.upper()}: {summary}')
        if not ok:
            all_ok = False

    status = '[OK]' if all_ok else '[WARN]'
    await ctx.send(f"```{status} Predictions done\n" + "\n".join(lines) + "```")


@bot.command(name='r')
async def hotkey_refresh(ctx, sport: str = 'both'):
    """Hotkey: PP sync / refresh lines. Usage: !r [nba|nhl|both]"""
    sports = ['nba', 'nhl'] if sport.lower() == 'both' else [sport.lower()]
    await ctx.send(f"```PP-syncing {sport.upper()}...```")

    lines = []
    all_ok = True
    for s in sports:
        ok, summary = await _run_script(s, 'pp-sync')
        tag = '[OK]' if ok else '[ERR]'
        lines.append(f'{tag} {s.upper()}: {summary}')
        if not ok:
            all_ok = False

    status = '[OK]' if all_ok else '[WARN]'
    await ctx.send(f"```{status} PP-sync done\n" + "\n".join(lines) + "```")


@bot.command(name='run')
async def hotkey_run_all(ctx, sport: str = 'both'):
    """Hotkey: grade + predict + pp-sync all in one shot. Usage: !run [nba|nhl|both]"""
    from datetime import timedelta
    sports = ['nba', 'nhl'] if sport.lower() == 'both' else [sport.lower()]
    grade_date = (date.today() - timedelta(days=1)).isoformat()

    await ctx.send(f"```[RUN] Starting full pipeline for {sport.upper()}...\n  1/3 Grading {grade_date}```")

    report = []
    all_ok = True

    # Step 1: Grade
    for s in sports:
        ok, summary = await _grade_sport(s, grade_date)
        tag = '[OK]' if ok else '[ERR]'
        report.append(f'GRADE  {tag} {s.upper()}: {summary}')
        if not ok:
            all_ok = False

    await ctx.send(f"```  2/3 Predicting today...```")

    # Step 2: Predict
    for s in sports:
        ok, summary = await _run_script(s, 'prediction')
        tag = '[OK]' if ok else '[ERR]'
        report.append(f'PRED   {tag} {s.upper()}: {summary}')
        if not ok:
            all_ok = False

    await ctx.send(f"```  3/3 PP-sync...```")

    # Step 3: PP-sync
    for s in sports:
        ok, summary = await _run_script(s, 'pp-sync')
        tag = '[OK]' if ok else '[ERR]'
        report.append(f'SYNC   {tag} {s.upper()}: {summary}')
        if not ok:
            all_ok = False

    status = '[OK] All done!' if all_ok else '[WARN] Done with errors'
    await ctx.send(f"```{status}\n" + "\n".join(report) + "```")


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
