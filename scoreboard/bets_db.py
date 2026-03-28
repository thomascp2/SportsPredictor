"""
Bet Tracking Database
Stores game bets and player prop bets in a local SQLite database.
"""
import sqlite3
from pathlib import Path
from datetime import date

DB_PATH = Path(__file__).parent / 'bets.db'


def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS game_bets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sport       TEXT    NOT NULL,
                game_id     TEXT,
                game_date   TEXT    NOT NULL,
                away_team   TEXT    NOT NULL,
                home_team   TEXT    NOT NULL,
                bet_type    TEXT    NOT NULL,
                side        TEXT    NOT NULL,
                line        REAL,
                odds        INTEGER NOT NULL,
                stake       REAL    NOT NULL,
                result      TEXT    DEFAULT 'PENDING',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS prop_bets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sport       TEXT    NOT NULL,
                game_id     TEXT,
                game_date   TEXT    NOT NULL,
                away_team   TEXT,
                home_team   TEXT,
                player_name TEXT    NOT NULL,
                team        TEXT,
                prop_type   TEXT    NOT NULL,
                line        REAL    NOT NULL,
                side        TEXT    NOT NULL,
                odds        INTEGER NOT NULL,
                stake       REAL    NOT NULL,
                result      TEXT    DEFAULT 'PENDING',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)


def add_game_bet(sport, game_date, away_team, home_team, bet_type, side,
                 odds, stake, line=None, game_id=None):
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO game_bets "
            "(sport, game_id, game_date, away_team, home_team, bet_type, side, line, odds, stake) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sport, game_id, game_date, away_team.upper(), home_team.upper(),
             bet_type, side, line, odds, stake)
        )
        return cur.lastrowid


def add_prop_bet(sport, game_date, player_name, prop_type, line, side, odds, stake,
                 game_id=None, away_team=None, home_team=None, team=None):
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO prop_bets "
            "(sport, game_id, game_date, away_team, home_team, player_name, team, prop_type, line, side, odds, stake) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sport, game_id, game_date,
             away_team.upper() if away_team else None,
             home_team.upper() if home_team else None,
             player_name, team, prop_type, line, side, odds, stake)
        )
        return cur.lastrowid


def get_bets(game_date=None):
    d = game_date or date.today().isoformat()
    with _conn() as c:
        gb = [dict(r) for r in c.execute(
            "SELECT * FROM game_bets WHERE game_date=? ORDER BY id", (d,)).fetchall()]
        pb = [dict(r) for r in c.execute(
            "SELECT * FROM prop_bets WHERE game_date=? ORDER BY id", (d,)).fetchall()]
    return gb, pb


def delete_bet(kind, bet_id):
    table = 'game_bets' if kind == 'game' else 'prop_bets'
    with _conn() as c:
        c.execute(f"DELETE FROM {table} WHERE id=?", (bet_id,))


def all_bets(days_back=14):
    with _conn() as c:
        gb = [dict(r) for r in c.execute(
            "SELECT * FROM game_bets WHERE date(game_date) >= date('now',?) ORDER BY game_date DESC, id DESC",
            (f'-{days_back} days',)).fetchall()]
        pb = [dict(r) for r in c.execute(
            "SELECT * FROM prop_bets WHERE date(game_date) >= date('now',?) ORDER BY game_date DESC, id DESC",
            (f'-{days_back} days',)).fetchall()]
    return gb, pb
