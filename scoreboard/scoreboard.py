"""
Sports Betting Scoreboard
=========================
All-in-one terminal scoreboard for tracking live scores and player props
across NBA, NHL, and MLB.

Usage:
  python scoreboard/scoreboard.py              # Live auto-refreshing scoreboard
  python scoreboard/scoreboard.py add          # Add a new bet interactively
  python scoreboard/scoreboard.py bets         # List all recent bets
  python scoreboard/scoreboard.py delete       # Remove a bet by ID
  python scoreboard/scoreboard.py --date 2026-03-27   # Scoreboard for past date
  python scoreboard/scoreboard.py --refresh 30        # Refresh every 30 seconds
"""

import sys
import time
import argparse
from pathlib import Path
from datetime import date, datetime
from difflib import get_close_matches

try:
    from rich.console import Console, Group
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.live import Live
    from rich.prompt import Prompt, IntPrompt
    from rich import box
except ImportError:
    print("ERROR: 'rich' library required. Run: pip install rich")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from bets_db import init_db, get_bets, add_game_bet, add_prop_bet, delete_bet, all_bets
from live_data import (all_games, player_stats as fetch_player_stats,
                       nba_games, nhl_games, mlb_games, cbb_tournament_games)

console = Console()


# ─── Constants ────────────────────────────────────────────────────────────────

SPORT_PROPS = {
    'NBA': ['points', 'rebounds', 'assists', 'steals', 'blocks', 'threes_made', 'pra', 'turnovers'],
    'CBB': ['points', 'rebounds', 'assists', 'steals', 'blocks', 'threes_made', 'pra', 'turnovers'],
    'NHL': ['points', 'goals', 'assists', 'shots', 'hits', 'blocked_shots'],
    'MLB': ['strikeouts', 'innings_pitched', 'hits', 'home_runs', 'rbi',
            'total_bases', 'earned_runs', 'walks_allowed'],
}

PROP_LABEL = {
    'points': 'Points',   'rebounds': 'Reb',     'assists': 'Ast',
    'steals': 'Stl',      'blocks': 'Blk',       'threes_made': '3PM',
    'pra': 'PRA',         'turnovers': 'TO',
    'goals': 'Goals',     'shots': 'SOG',        'hits': 'Hits',
    'blocked_shots': 'BLK',
    'strikeouts': 'K',    'innings_pitched': 'IP', 'home_runs': 'HR',
    'rbi': 'RBI',         'total_bases': 'TB',   'earned_runs': 'ER',
    'walks_allowed': 'BB',
}

PROP_UNIT = {
    'points': 'pts', 'rebounds': 'reb', 'assists': 'ast',
    'steals': 'stl', 'blocks': 'blk',  'threes_made': '3s',
    'pra': 'PRA',    'turnovers': 'to',
    'goals': 'G',    'assists': 'A',   'shots': 'SOG',
    'hits': 'H',     'blocked_shots': 'BLK',
    'strikeouts': 'K', 'innings_pitched': 'IP', 'home_runs': 'HR',
    'rbi': 'RBI',    'total_bases': 'TB', 'earned_runs': 'ER',
    'walks_allowed': 'BB',
}

SPORT_COLOR = {'NBA': 'orange1', 'CBB': 'bright_yellow', 'NHL': 'cyan', 'MLB': 'green'}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def calc_payout(odds, stake):
    """Calculate profit for a winning bet."""
    if odds >= 0:
        return round(stake * odds / 100, 2)
    return round(stake * 100 / abs(odds), 2)


def fuzzy_lookup(name, stats_dict):
    """Find player stats with fuzzy name matching."""
    if not stats_dict or not name:
        return None
    if name in stats_dict:
        return stats_dict[name]
    matches = get_close_matches(name.strip(), stats_dict.keys(), n=1, cutoff=0.55)
    return stats_dict[matches[0]] if matches else None


def game_bet_status(bet, game):
    """Returns (label, color) reflecting current bet outcome."""
    if game['status'] == 'scheduled':
        return 'pending', 'dim'
    away = game.get('away_score')
    home = game.get('home_score')
    if away is None or home is None:
        return 'pending', 'dim'

    btype = bet['bet_type'].upper()
    side  = bet['side'].lower()
    line  = float(bet.get('line') or 0)
    final = (game['status'] == 'final')

    if btype == 'ML':
        if home == away:
            return 'push', 'yellow'
        winning = (home > away) if side == 'home' else (away > home)
    elif btype == 'SPREAD':
        margin = ((home - away) if side == 'home' else (away - home)) + line
        if margin == 0:
            return 'push', 'yellow'
        winning = margin > 0
    elif btype == 'TOTAL':
        total = away + home
        if total == line:
            return 'push', 'yellow'
        winning = (total > line) if side == 'over' else (total < line)
    else:
        return 'pending', 'dim'

    label = ('WON' if final else 'WINNING') if winning else ('LOST' if final else 'LOSING')
    color = 'green' if winning else 'red'
    return label, color


def prop_status(bet, live_val):
    """Returns (label, color, extra_str) for a prop bet."""
    if live_val is None:
        return 'pending', 'dim', ''
    line = float(bet['line'])
    val  = float(live_val)
    side = bet['side'].upper()
    diff = val - line

    if diff == 0:
        return 'push', 'yellow', ''

    if side == 'OVER':
        winning = diff > 0
        extra = f'+{diff:.1f}' if winning else f'need {-diff:.1f}'
    else:
        winning = diff < 0
        extra = f'+{-diff:.1f}' if winning else f'need {diff:.1f} fewer'

    return ('WINNING', 'green', extra) if winning else ('LOSING', 'red', extra)


def fmt_score(v):
    return str(v) if v is not None else '--'


def fmt_status(game):
    """Rich markup string for game status column."""
    s = game['status']
    if s == 'live':
        parts = [x for x in (game.get('period', ''), game.get('clock', '')) if x]
        return f"[bold green]LIVE {' '.join(parts)}[/bold green]"
    if s == 'final':
        return '[dim]FINAL[/dim]'
    t = game.get('start_time_local', '')
    return f"[dim]{t or 'SCHED'}[/dim]"


def fmt_odds(odds):
    return f"{odds:+d}"


def fmt_bet_desc(bet, game):
    """One-line description of a game bet."""
    btype = bet['bet_type'].upper()
    side  = bet['side'].lower()
    line  = bet.get('line')
    if btype == 'ML':
        team = game['home_team'] if side == 'home' else game['away_team']
        return f"{team} ML"
    if btype == 'SPREAD':
        team = game['home_team'] if side == 'home' else game['away_team']
        return f"{team} {line:+.1f}"
    return f"{side.upper()} {line}"


# ─── Display Builder ──────────────────────────────────────────────────────────

def build_display(games, game_bets, prop_bets, p_stats_cache, game_date):
    parts = []

    # Header
    now_str  = datetime.now().strftime('%I:%M %p').lstrip('0')
    date_str = datetime.strptime(game_date, '%Y-%m-%d').strftime('%A, %B %d %Y')
    live_ct  = sum(1 for g in games if g['status'] == 'live')
    live_tag  = f"  [bold green]{live_ct} LIVE[/bold green]" if live_ct else ''
    parts.append(Panel(
        f"[bold cyan]SPORTS BETTING SCOREBOARD[/bold cyan]{live_tag}  "
        f"[dim]·  {date_str}  ·  updated {now_str}  ·  "
        f"Ctrl+C to exit  ·  'python scoreboard/scoreboard.py add' to add bets[/dim]",
        border_style='cyan', expand=True
    ))

    # ── Games by sport ─────────────────────────────────────────────────────
    for sport in ('CBB', 'NBA', 'NHL', 'MLB'):
        sport_games = [g for g in games if g['sport'] == sport]
        if not sport_games:
            continue

        # Index game bets by matchup
        bet_by_matchup = {}
        for b in game_bets:
            if b['sport'] == sport:
                key = (b['away_team'].upper(), b['home_team'].upper())
                bet_by_matchup[key] = b

        color = SPORT_COLOR[sport]
        t = Table(show_header=False, box=None, padding=(0, 1), expand=True, show_edge=False)
        t.add_column('status',  width=20, no_wrap=True)
        t.add_column('matchup', min_width=14, no_wrap=True)
        t.add_column('score',   width=11, no_wrap=True)
        t.add_column('wager',   min_width=34)

        for g in sorted(sport_games, key=lambda x: (
                0 if x['status'] == 'live' else 1 if x['status'] == 'scheduled' else 2)):
            status_txt = fmt_status(g)
            if sport == 'CBB':
                a_seed = f"({g['away_seed']})" if g.get('away_seed') else ''
                h_seed = f"({g['home_seed']})" if g.get('home_seed') else ''
                matchup = f"{a_seed}{g['away_team']} @ {h_seed}{g['home_team']}"
            else:
                matchup = f"{g['away_team']} @ {g['home_team']}"
            if g['status'] == 'scheduled':
                score = "--  -  --"
            else:
                score = f"{fmt_score(g['away_score'])}  -  {fmt_score(g['home_score'])}"

            key = (g['away_team'].upper(), g['home_team'].upper())
            b   = bet_by_matchup.get(key)

            if not b:
                wager_txt = '[dim]—[/dim]'
            else:
                desc   = fmt_bet_desc(b, g)
                odds   = b['odds']
                stake  = b['stake']
                profit = calc_payout(odds, stake)
                label, bc = game_bet_status(b, g)

                if label in ('WON', 'WINNING'):
                    wager_txt = (f"[{bc}]{desc} {fmt_odds(odds)} ${stake:.0f}  "
                                 f"[{label} +${profit:.2f}][/{bc}]")
                elif label in ('LOST', 'LOSING'):
                    wager_txt = (f"[{bc}]{desc} {fmt_odds(odds)} ${stake:.0f}  "
                                 f"[{label} -${stake:.2f}][/{bc}]")
                elif label == 'push':
                    wager_txt = f"[yellow]{desc} {fmt_odds(odds)} ${stake:.0f}  [PUSH][/yellow]"
                else:
                    wager_txt = f"[dim]{desc} {fmt_odds(odds)} ${stake:.0f}[/dim]"

            t.add_row(status_txt, matchup, score, wager_txt)

        sport_bets = sum(1 for b in game_bets if b['sport'] == sport)
        if sport == 'CBB':
            rounds = list(dict.fromkeys(
                g['round_label'] for g in sport_games if g.get('round_label')
            ))
            round_str = f"  ·  {rounds[0]}" if len(rounds) == 1 else ("  ·  NCAA Tournament" if rounds else "  ·  NCAA Tournament")
            title = f"[bold {color}]CBB[/bold {color}]  [dim]{len(sport_games)} game"
            if len(sport_games) != 1:
                title += 's'
            title += round_str
        else:
            title = f"[bold {color}]{sport}[/bold {color}]  [dim]{len(sport_games)} game"
            if len(sport_games) != 1:
                title += 's'
        if sport_bets:
            title += f"  ·  {sport_bets} bet" + ('s' if sport_bets > 1 else '')
        title += '[/dim]'

        parts.append(Panel(t, title=title, title_align='left',
                           border_style=color, expand=True))

    # ── Player Props ────────────────────────────────────────────────────────
    if prop_bets:
        pt = Table(show_header=True, box=box.SIMPLE_HEAD, padding=(0, 1),
                   expand=True, show_edge=False)
        pt.add_column('Player',  min_width=22, no_wrap=True)
        pt.add_column('Sport',   width=5,  no_wrap=True)
        pt.add_column('Game',    width=12, no_wrap=True)
        pt.add_column('Prop',    width=7,  no_wrap=True)
        pt.add_column('Line',    width=6,  no_wrap=True)
        pt.add_column('O/U',     width=5,  no_wrap=True)
        pt.add_column('Odds',    width=6,  no_wrap=True)
        pt.add_column('Stake',   width=7,  no_wrap=True)
        pt.add_column('Live',    width=12, no_wrap=True)
        pt.add_column('Status',  min_width=20)

        for b in prop_bets:
            gid   = b.get('game_id', '')
            sport = b['sport']
            color = SPORT_COLOR[sport]

            # Match the game
            game = None
            for g in games:
                if gid and g['game_id'] == gid:
                    game = g
                    break
                if (g['sport'] == sport and
                        g['away_team'].upper() == (b.get('away_team') or '').upper() and
                        g['home_team'].upper() == (b.get('home_team') or '').upper()):
                    game = g
                    if not gid:
                        gid = g['game_id']
                    break

            game_label = ''
            if game:
                game_label = f"{game['away_team']}@{game['home_team']}"
            elif b.get('away_team') and b.get('home_team'):
                game_label = f"{b['away_team']}@{b['home_team']}"

            prop_key  = b['prop_type'].lower()
            prop_disp = PROP_LABEL.get(prop_key, prop_key.upper())

            # Live stat value
            live_txt = '--'
            live_val = None
            if game and game['status'] in ('live', 'final') and gid in p_stats_cache:
                pstats = fuzzy_lookup(b['player_name'], p_stats_cache[gid])
                if pstats and prop_key in pstats:
                    live_val = pstats[prop_key]
                    unit = PROP_UNIT.get(prop_key, '')
                    live_txt = (f"{live_val:.1f}{unit}" if prop_key == 'innings_pitched'
                                else f"{int(live_val)}{unit}")
                    if game['status'] == 'live' and game.get('period'):
                        live_txt += f" {game['period']}"

            label, bc, extra = prop_status(b, live_val)
            # Finalise label if game ended
            if game and game['status'] == 'final':
                if label == 'WINNING':
                    label = 'WON'
                elif label == 'LOSING':
                    label = 'LOST'

            status_txt = f"[{bc}]{label}"
            if extra:
                status_txt += f" ({extra})"
            status_txt += f"[/{bc}]"

            pt.add_row(
                b['player_name'][:22],
                f"[{color}]{sport}[/{color}]",
                game_label,
                prop_disp,
                str(b['line']),
                b['side'].upper(),
                fmt_odds(b['odds']),
                f"${b['stake']:.0f}",
                live_txt,
                status_txt,
            )

        parts.append(Panel(pt, title='[bold magenta]PLAYER PROPS[/bold magenta]',
                           title_align='left', border_style='magenta', expand=True))

    if not games:
        parts.append(Panel(
            '[dim]No games found for today. APIs may be unavailable or it may be off-season.[/dim]',
            border_style='dim'
        ))

    return Group(*parts)


# ─── Main Scoreboard Loop ─────────────────────────────────────────────────────

def run_scoreboard(game_date, refresh_interval=60):
    games         = []
    game_bets     = []
    prop_bets     = []
    p_stats_cache = {}
    last_fetch    = [0.0]

    def fetch_all():
        nonlocal games, game_bets, prop_bets
        game_bets, prop_bets = get_bets(game_date)
        games = all_games(game_date)

        # Fetch player stats for live/final games that have prop bets
        needed = set()
        for b in prop_bets:
            gid = b.get('game_id') or ''
            if not gid:
                for g in games:
                    if (g['sport'] == b['sport'] and
                            g['away_team'].upper() == (b.get('away_team') or '').upper() and
                            g['home_team'].upper() == (b.get('home_team') or '').upper()):
                        gid = g['game_id']
                        break
            if gid:
                for g in games:
                    if g['game_id'] == gid and g['status'] in ('live', 'final'):
                        needed.add((b['sport'], gid))
                        break

        for sport, gid in needed:
            stats = fetch_player_stats(sport, gid)
            if stats:
                p_stats_cache[gid] = stats

        last_fetch[0] = time.time()

    def get_display():
        return build_display(games, game_bets, prop_bets, p_stats_cache, game_date)

    with Live(get_display(), refresh_per_second=0, auto_refresh=False, console=console,
              screen=False, vertical_overflow='visible') as live:
        try:
            while True:
                fetch_all()
                live.update(get_display(), refresh=True)
                time.sleep(refresh_interval)
        except KeyboardInterrupt:
            pass

    console.print('[dim]Scoreboard stopped.[/dim]')


# ─── Add Bet ──────────────────────────────────────────────────────────────────

def cmd_add(game_date):
    console.print(Panel('[bold cyan]Add a Bet[/bold cyan]  '
                        '[dim]— Ctrl+C to cancel[/dim]', border_style='cyan'))

    bet_kind = Prompt.ask('Bet type', choices=['game', 'prop'], default='game')
    sport    = Prompt.ask('Sport', choices=['NBA', 'CBB', 'NHL', 'MLB']).upper()

    # Fetch games
    console.print(f'[dim]Fetching {sport} games for {game_date}...[/dim]')
    fetchers = {'NBA': nba_games, 'CBB': cbb_tournament_games, 'NHL': nhl_games, 'MLB': mlb_games}
    g_list = fetchers[sport](game_date)

    if not g_list:
        console.print(f'[yellow]No {sport} games found for {game_date}. Enter teams manually.[/yellow]')
        away    = Prompt.ask('Away team abbreviation').upper()
        home    = Prompt.ask('Home team abbreviation').upper()
        game_id = None
    else:
        console.print()
        for i, g in enumerate(g_list, 1):
            status_tag = g.get('start_time_local') or g['status'].upper()
            live_tag   = ' [bold green][LIVE][/bold green]' if g['status'] == 'live' else ''
            console.print(f"  [cyan]{i}[/cyan].  {g['away_team']} @ {g['home_team']}  "
                          f"[dim]{status_tag}[/dim]{live_tag}")
        console.print()
        idx    = max(0, min(IntPrompt.ask('Game #') - 1, len(g_list) - 1))
        chosen = g_list[idx]
        away, home, game_id = chosen['away_team'], chosen['home_team'], chosen['game_id']
        console.print(f"  [bold]{away} @ {home}[/bold]\n")

    # Odds + stake
    while True:
        raw = Prompt.ask('Odds (e.g. -110 or +130)')
        try:
            odds = int(raw.replace('+', '').strip())
            break
        except ValueError:
            console.print('[red]Enter a valid American odds number.[/red]')

    while True:
        raw = Prompt.ask('Stake ($)')
        try:
            stake = float(raw.replace('$', '').strip())
            break
        except ValueError:
            console.print('[red]Enter a valid dollar amount.[/red]')

    # ── Game bet ──
    if bet_kind == 'game':
        btype = Prompt.ask('Bet type', choices=['ML', 'SPREAD', 'TOTAL']).upper()
        line  = None
        if btype == 'ML':
            side = Prompt.ask('Side', choices=['home', 'away'])
        elif btype == 'SPREAD':
            side = Prompt.ask('Side', choices=['home', 'away'])
            while True:
                try:
                    line = float(Prompt.ask('Spread line (positive = underdog, e.g. +4.5 / -4.5)'))
                    break
                except ValueError:
                    console.print('[red]Enter a number.[/red]')
        else:
            side = Prompt.ask('Over or under', choices=['over', 'under'])
            while True:
                try:
                    line = float(Prompt.ask('Total line (e.g. 220.5)'))
                    break
                except ValueError:
                    console.print('[red]Enter a number.[/red]')

        bet_id = add_game_bet(sport, game_date, away, home, btype, side,
                              odds, stake, line=line, game_id=game_id)
        profit = calc_payout(odds, stake)
        team_tag = (home if side == 'home' else away) if btype != 'TOTAL' else side.upper()
        console.print(f'\n[green]Saved game bet #{bet_id}[/green]  '
                      f'{away} @ {home}  |  {btype} {team_tag}'
                      + (f' {line:+.1f}' if line is not None else '')
                      + f'  |  {fmt_odds(odds)}  |  ${stake:.2f} to win ${profit:.2f}')

    # ── Prop bet ──
    else:
        player = Prompt.ask('Player name')
        props  = SPORT_PROPS[sport]
        console.print('\nProp types:')
        for i, p in enumerate(props, 1):
            console.print(f"  [cyan]{i}[/cyan]. {PROP_LABEL.get(p, p)}")
        pidx      = max(0, min(IntPrompt.ask('Prop #') - 1, len(props) - 1))
        prop_type = props[pidx]

        while True:
            try:
                line = float(Prompt.ask('Line (e.g. 25.5)'))
                break
            except ValueError:
                console.print('[red]Enter a number.[/red]')

        side = Prompt.ask('Over or under', choices=['OVER', 'UNDER']).upper()

        bet_id = add_prop_bet(sport, game_date, player, prop_type, line, side,
                              odds, stake, game_id=game_id, away_team=away, home_team=home)
        profit = calc_payout(odds, stake)
        console.print(f'\n[green]Saved prop bet #{bet_id}[/green]  '
                      f'{player}  |  {PROP_LABEL.get(prop_type, prop_type)} {side} {line}  '
                      f'({away} @ {home})  |  {fmt_odds(odds)}  |  ${stake:.2f} to win ${profit:.2f}')


# ─── Batch Import ────────────────────────────────────────────────────────────

def cmd_import(csv_path, game_date):
    """Import bets from a CSV file. See scoreboard/bets_import.csv for the template."""
    import csv as csv_module
    path = Path(csv_path)
    if not path.exists():
        console.print(f'[red]File not found: {csv_path}[/red]')
        console.print(f'[dim]Template: scoreboard/bets_import.csv[/dim]')
        return

    imported, errors = 0, []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv_module.DictReader(f)
        for i, row in enumerate(reader, 1):
            # Skip comment/blank rows
            if not row or row.get('type', '').startswith('#'):
                continue
            try:
                btype  = row.get('type', '').strip().lower()
                sport  = row.get('sport', '').strip().upper()
                gdate  = row.get('game_date', '').strip() or game_date
                away   = row.get('away_team', '').strip().upper()
                home   = row.get('home_team', '').strip().upper()
                odds   = int(str(row.get('odds', '0')).strip().replace('+', ''))
                stake  = float(str(row.get('stake', '0')).strip().replace('$', ''))

                if not sport or not away or not home:
                    errors.append(f'Row {i}: missing sport/away_team/home_team')
                    continue

                if btype == 'game':
                    bet_type = row.get('bet_type', '').strip().upper()
                    side     = row.get('side', '').strip().lower()
                    line_s   = str(row.get('line', '')).strip()
                    line     = float(line_s) if line_s else None
                    if not bet_type or not side:
                        errors.append(f'Row {i}: missing bet_type or side')
                        continue
                    add_game_bet(sport, gdate, away, home, bet_type, side,
                                 odds, stake, line=line)
                    imported += 1

                elif btype == 'prop':
                    player    = row.get('player_name', '').strip()
                    prop_type = row.get('prop_type', '').strip().lower()
                    side      = row.get('side', '').strip().upper()
                    line_s    = str(row.get('line', '')).strip()
                    line      = float(line_s) if line_s else 0.0
                    if not player or not prop_type or not side:
                        errors.append(f'Row {i}: missing player_name/prop_type/side')
                        continue
                    add_prop_bet(sport, gdate, player, prop_type, line, side,
                                 odds, stake, away_team=away, home_team=home)
                    imported += 1

                else:
                    errors.append(f'Row {i}: type must be "game" or "prop", got "{btype}"')

            except Exception as e:
                errors.append(f'Row {i}: {e}')

    console.print(f'\n[green]Imported {imported} bet{"s" if imported != 1 else ""}[/green]'
                  + (f'  [yellow]{len(errors)} error{"s" if len(errors)!=1 else ""}[/yellow]' if errors else ''))
    for err in errors:
        console.print(f'  [red]{err}[/red]')
    if imported:
        console.print(f'[dim]Run `python scoreboard/scoreboard.py watch` to see them live.[/dim]')


# ─── List Bets ────────────────────────────────────────────────────────────────

def cmd_list():
    gb, pb = all_bets(days_back=14)
    if not gb and not pb:
        console.print('[dim]No bets in the last 14 days.[/dim]')
        return

    if gb:
        t = Table(title='Game Bets (last 14 days)', box=box.SIMPLE_HEAVY, expand=True)
        for col in ('ID', 'Date', 'Sport', 'Matchup', 'Bet', 'Line', 'Odds', 'Stake', 'Result'):
            t.add_column(col, no_wrap=True)
        for b in gb:
            btype = b['bet_type'].upper()
            side  = b['side'].lower()
            line  = b.get('line')
            if btype == 'ML':
                desc = f"{b['home_team'] if side == 'home' else b['away_team']} ML"
            elif btype == 'SPREAD':
                desc = f"{b['home_team'] if side == 'home' else b['away_team']} {side.title()}"
            else:
                desc = f"TOTAL {side.upper()}"
            t.add_row(
                str(b['id']), b['game_date'], b['sport'],
                f"{b['away_team']} @ {b['home_team']}",
                desc,
                f"{line:+.1f}" if line is not None else '—',
                fmt_odds(b['odds']),
                f"${b['stake']:.2f}",
                b.get('result', 'PENDING'),
            )
        console.print(t)

    if pb:
        t = Table(title='Prop Bets (last 14 days)', box=box.SIMPLE_HEAVY, expand=True)
        for col in ('ID', 'Date', 'Sport', 'Player', 'Game', 'Prop', 'Line', 'O/U', 'Odds', 'Stake', 'Result'):
            t.add_column(col, no_wrap=True)
        for b in pb:
            prop_disp = PROP_LABEL.get(b['prop_type'].lower(), b['prop_type'].upper())
            game_tag  = f"{b.get('away_team','?')}@{b.get('home_team','?')}"
            t.add_row(
                str(b['id']), b['game_date'], b['sport'],
                b['player_name'], game_tag, prop_disp,
                str(b['line']), b['side'].upper(),
                fmt_odds(b['odds']),
                f"${b['stake']:.2f}",
                b.get('result', 'PENDING'),
            )
        console.print(t)


# ─── Delete Bet ───────────────────────────────────────────────────────────────

def cmd_delete():
    cmd_list()
    kind   = Prompt.ask('\nDelete from', choices=['game', 'prop'])
    bet_id = IntPrompt.ask('Bet ID')
    delete_bet(kind, bet_id)
    console.print(f'[green]Deleted {kind} bet #{bet_id}[/green]')


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Sports Betting Scoreboard',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('command', nargs='?', default='watch',
                        choices=['watch', 'add', 'bets', 'delete', 'import'],
                        help='watch (default), add, bets, delete, import <file>')
    parser.add_argument('--date',    default=None,
                        help='Date YYYY-MM-DD (default: today)')
    parser.add_argument('--refresh', type=int, default=60,
                        help='Refresh interval seconds (default: 60)')
    parser.add_argument('file', nargs='?', default='scoreboard/bets_import.csv',
                        help='CSV file for import command (default: scoreboard/bets_import.csv)')
    args = parser.parse_args()

    init_db()
    game_date = args.date or date.today().isoformat()

    if args.command == 'watch':
        run_scoreboard(game_date, args.refresh)
    elif args.command == 'add':
        cmd_add(game_date)
    elif args.command == 'bets':
        cmd_list()
    elif args.command == 'delete':
        cmd_delete()
    elif args.command == 'import':
        cmd_import(args.file, game_date)


if __name__ == '__main__':
    main()
