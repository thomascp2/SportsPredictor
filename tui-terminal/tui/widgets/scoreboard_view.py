"""
ScoreboardView -- center column scoreboard + picks overlay.
Toggled by pressing 's'. Shows live/final/scheduled games grouped by status,
with our active smart picks embedded under each game.

Refresh: every 30s (background thread -- no TUI freeze).
"""

import sys
import sqlite3
import threading
from datetime import date
from pathlib import Path

from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Label, Static

# Allow importing scoreboard.live_data from SportsPredictor root
_SPORTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_SPORTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPORTS_ROOT))

STAT_ABBREV = {
    # NBA
    "NBA_POINTS":              "PTS",
    "NBA_REBOUNDS":            "REB",
    "NBA_ASSISTS":             "AST",
    "NBA_THREES":              "3PM",
    "NBA_STEALS":              "STL",
    "NBA_BLOCKS":              "BLK",
    "NBA_TURNOVERS":           "TOV",
    "NBA_FANTASY":             "FAN",
    "NBA_PRA":                 "PRA",
    # NHL
    "NHL_POINTS":              "PTS",
    "NHL_SHOTS":               "SOG",
    "NHL_GOALS":               "G",
    "NHL_ASSISTS":             "A",
    "NHL_HITS":                "HITS",
    "NHL_BLOCKED_SHOTS":       "BLK",
    # MLB — batters
    "MLB_HITS":                "HITS",
    "MLB_HOME_RUNS":           "HR",
    "MLB_TOTAL_BASES":         "TB",
    "MLB_RBIS":                "RBI",
    "MLB_RUNS":                "RUNS",
    "MLB_STOLEN_BASES":        "SB",
    "MLB_BATTER_WALKS":        "BB",
    "MLB_BATTER_STRIKEOUTS":   "KO",
    "MLB_HRR":                 "HRR",
    # MLB — pitchers
    "MLB_STRIKEOUTS":          "K",
    "MLB_OUTS_RECORDED":       "OUTS",
    "MLB_PITCHER_WALKS":       "BB",
    "MLB_HITS_ALLOWED":        "HA",
    "MLB_EARNED_RUNS":         "ER",
}

TIER_COLORS = {
    "T1-ELITE":  "#00ff41",
    "T2-STRONG": "#00c853",
    "T3-GOOD":   "#76ff03",
    "T4-LEAN":   "#ffd600",
    "T5-FADE":   "#ff1744",
}

SPORT_COLORS = {
    "NHL": "#5588ff",
    "NBA": "#ff8c00",
    "MLB": "#00c853",
    "CBB": "#cc44cc",
}


def _fmt_edge(edge) -> str:
    if edge is None:
        return ""
    sign = "+" if edge >= 0 else ""
    return f"{sign}{edge:.1f}%"


def _load_picks(db_path: Path) -> dict:
    """Returns {team_abbrev: [pick, ...]} for today's smart picks."""
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT player_name, team, sport, stat_type, pp_line,
                      prediction, tier, edge, odds_type
               FROM   smart_picks
               WHERE  game_date = date('now', 'localtime')
               ORDER  BY CASE tier
                   WHEN 'T1-ELITE' THEN 1 WHEN 'T2-STRONG' THEN 2
                   WHEN 'T3-GOOD'  THEN 3 WHEN 'T4-LEAN'   THEN 4
                   ELSE 5 END"""
        ).fetchall()
        conn.close()
    except Exception:
        return {}

    by_team: dict = {}
    for r in rows:
        team = (r["team"] or "").upper()
        if team:
            by_team.setdefault(team, []).append(dict(r))
    return by_team


def _fetch_data(db_path: Path) -> tuple:
    """Returns (games_list, picks_by_team). Runs in background thread."""
    picks_by_team = _load_picks(db_path)
    try:
        from scoreboard.live_data import all_games  # type: ignore
        games = all_games(date.today().isoformat())
    except Exception:
        games = []
    return games, picks_by_team


def _render_content(games: list, picks_by_team: dict, refresh_ts: str,
                    sport_filter: str = "") -> str:
    if sport_filter:
        games = [g for g in games if (g.get("sport") or "").upper() == sport_filter]

    if not games:
        no_msg = f"No {sport_filter} games today." if sport_filter else "No games today or score data unavailable."
        return [f"\n [#3a5570]{no_msg}[/#3a5570]"]

    # Split into sections
    live      = [g for g in games if g.get("status") == "live"]
    final     = [g for g in games if g.get("status") == "final"]
    scheduled = [g for g in games if g.get("status") not in ("live", "final")]

    filter_label = f"  [{sport_filter}]" if sport_filter else ""
    lines = [f"\n [dim]refreshed {refresh_ts}  --  {len(games)} games{filter_label}[/dim]\n"]

    # ── Nested helpers (defined first so TOP PICKS can use them) ─────────────

    def _pick_lines(picks: list) -> list:
        plines = []
        for p in picks:
            name     = (p.get("player_name") or "")[:18]
            stat_raw = p.get("stat_type") or ""
            stat     = STAT_ABBREV.get(stat_raw) or stat_raw.rsplit("_", 1)[-1][:4]
            line  = p.get("pp_line")
            pred  = p.get("prediction") or ""
            tier  = p.get("tier") or ""
            edge  = p.get("edge")
            arrow = "^" if pred == "OVER" else "v" if pred == "UNDER" else " "
            tc    = TIER_COLORS.get(tier, "#c8d8e8")
            ta    = tier[:2] if tier else "?"
            lstr  = f"@{line:.1f}" if line else ""
            plines.append(
                f"    [{tc}]{arrow} {name:<18}  {stat:<5}  {lstr:<6}  {ta}  {_fmt_edge(edge)}[/{tc}]"
            )
        return plines

    def _sport_color(sport: str) -> str:
        return SPORT_COLORS.get(sport.upper(), "#c8d8e8")

    def _game_picks(g: dict) -> list:
        away  = (g.get("away_team") or "").upper()
        home  = (g.get("home_team") or "").upper()
        sport = (g.get("sport") or "").upper()
        picks = picks_by_team.get(away, []) + picks_by_team.get(home, [])
        # Filter by sport to prevent cross-sport abbreviation collisions (PHI Flyers vs PHI Phillies)
        if sport:
            picks = [p for p in picks if (p.get("sport") or "").upper() == sport]
        # Dedupe by player_name + stat_type
        seen: set = set()
        out = []
        for p in picks:
            key = p["player_name"] + p["stat_type"]
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out[:10]  # max 10 picks shown per game

    # ── TODAY'S BEST PICKS (top edge across all games) ────────────────────────
    all_picks: list = []
    seen_all: set = set()
    for picks in picks_by_team.values():
        for p in picks:
            key = p["player_name"] + p["stat_type"]
            if key not in seen_all:
                seen_all.add(key)
                all_picks.append(p)
    if sport_filter:
        all_picks = [p for p in all_picks if (p.get("sport") or "").upper() == sport_filter]
    # Sort: tier rank then edge descending
    _tier_rank = {"T1-ELITE": 1, "T2-STRONG": 2, "T3-GOOD": 3, "T4-LEAN": 4, "T5-FADE": 5}
    all_picks.sort(key=lambda p: (
        _tier_rank.get(p.get("tier") or "", 9),
        -(p.get("edge") or 0)
    ))
    top_picks = all_picks[:5]
    if top_picks:
        lines.append(" [bold #ffa500]TODAY'S BEST PICKS[/bold #ffa500]")
        lines.append(f" [#1e3a5f]{'─' * 68}[/#1e3a5f]")
        lines.extend(_pick_lines(top_picks))
        lines.append("")

    # ── LIVE NOW ──────────────────────────────────────────────────────────────
    if live:
        lines.append(" [bold #ff4444]LIVE NOW[/bold #ff4444]")
        lines.append(f" [#1e3a5f]{'─' * 68}[/#1e3a5f]")
        for g in live:
            sport  = g.get("sport", "")
            away   = g.get("away_team", "?")
            home   = g.get("home_team", "?")
            a_sc   = g.get("away_score", 0) or 0
            h_sc   = g.get("home_score", 0) or 0
            period = g.get("period", "")
            clock  = g.get("clock", "")
            sc     = _sport_color(sport)
            situation = f"{period} {clock}".strip() if clock else period
            lines.append(
                f"  [{sc}]{sport:<4}[/{sc}]"
                f"  [bold]{away} {a_sc}-{h_sc} {home}[/bold]"
                f"  [#ffa500]{situation}[/#ffa500]"
            )
            picks = _game_picks(g)
            if picks:
                lines.extend(_pick_lines(picks))
        lines.append("")

    # ── FINAL ─────────────────────────────────────────────────────────────────
    if final:
        lines.append(" [bold #3a8a3a]FINAL[/bold #3a8a3a]")
        lines.append(f" [#1e3a5f]{'─' * 68}[/#1e3a5f]")
        for g in final:
            sport = g.get("sport", "")
            away  = g.get("away_team", "?")
            home  = g.get("home_team", "?")
            a_sc  = g.get("away_score", 0) or 0
            h_sc  = g.get("home_score", 0) or 0
            sc    = _sport_color(sport)
            winner_away = a_sc > h_sc
            away_bold = "bold" if winner_away else "dim"
            home_bold = "bold" if not winner_away else "dim"
            lines.append(
                f"  [{sc}]{sport:<4}[/{sc}]"
                f"  [{away_bold}]{away} {a_sc}[/{away_bold}]"
                f"  -  "
                f"  [{home_bold}]{h_sc} {home}[/{home_bold}]"
                f"  [dim]FINAL[/dim]"
            )
            picks = _game_picks(g)
            if picks:
                lines.extend(_pick_lines(picks))
        lines.append("")

    # ── TONIGHT ───────────────────────────────────────────────────────────────
    if scheduled:
        lines.append(" [bold #cc7700]TONIGHT[/bold #cc7700]")
        lines.append(f" [#1e3a5f]{'─' * 68}[/#1e3a5f]")
        for g in scheduled:
            sport = g.get("sport", "")
            away  = g.get("away_team", "?")
            home  = g.get("home_team", "?")
            start = g.get("start_time_local", "TBD")
            sc    = _sport_color(sport)
            lines.append(
                f"  [{sc}]{sport:<4}[/{sc}]"
                f"  {away} @ {home}"
                f"  [dim]{start}[/dim]"
            )
            picks = _game_picks(g)
            if picks:
                lines.extend(_pick_lines(picks))

    return lines  # list of strings -- caller joins after slicing for scroll


class ScoreboardView(Widget):
    """Scoreboard + picks overlay -- center column swap on 's' key."""

    can_focus = True  # Allow widget to receive key events for scrolling

    DEFAULT_CSS = """
    ScoreboardView {
        width: 60%;
        border: solid #1e3a5f;
    }
    #scoreboard-title {
        background: #0d1b2a;
        color: #ffa500;
        text-style: bold;
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    #scoreboard-body {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
        color: #c8d8e8;
    }
    """

    def __init__(self, db_path: Path, **kwargs):
        super().__init__(**kwargs)
        self._db_path        = db_path
        self._pending_data   = None   # (games, picks_by_team) written by bg thread
        self._refresh_ts     = "never"
        self._sport_filter   = ""
        self._all_lines:     list = []
        self._scroll_offset: int  = 0

    def compose(self) -> ComposeResult:
        yield Label(
            " SCOREBOARD  [dim][s] back  [j/k] scroll  [1-3] filter sport[/dim]",
            id="scoreboard-title",
        )
        yield Static("Loading scores...", id="scoreboard-body", markup=True)

    def on_mount(self) -> None:
        self._kick_fetch()
        self.set_interval(1.0,  self._drain_pending)
        self.set_interval(30.0, self._kick_fetch)

    def on_show(self) -> None:
        """Grab focus when scoreboard becomes visible so key scroll works."""
        self.focus()

    def on_key(self, event) -> None:
        """j/k/PageDown/PageUp scroll the scoreboard body."""
        key     = event.key
        max_off = max(0, len(self._all_lines) - 5)
        if key == "j":
            self._scroll_offset = min(self._scroll_offset + 3, max_off)
            self._redraw_body(); event.stop()
        elif key == "k":
            self._scroll_offset = max(0, self._scroll_offset - 3)
            self._redraw_body(); event.stop()
        elif key == "page_down":
            self._scroll_offset = min(self._scroll_offset + 20, max_off)
            self._redraw_body(); event.stop()
        elif key == "page_up":
            self._scroll_offset = max(0, self._scroll_offset - 20)
            self._redraw_body(); event.stop()

    def _redraw_body(self) -> None:
        shown = self._all_lines[self._scroll_offset:]
        try:
            self.query_one("#scoreboard-body", Static).update("\n".join(shown))
        except Exception:
            pass

    def set_sport_filter(self, sport: str) -> None:
        """Filter displayed games by sport. Empty string = all sports."""
        self._sport_filter = sport.upper()
        # Immediately re-render with current data and new filter
        self._kick_fetch()

    def _kick_fetch(self) -> None:
        """Launch background fetch thread."""
        t = threading.Thread(target=self._bg_fetch, daemon=True)
        t.start()

    def _bg_fetch(self) -> None:
        """Runs in background thread. Writes result to _pending_data."""
        data = _fetch_data(self._db_path)
        self._pending_data = data  # GIL makes string assignment safe

    def _drain_pending(self) -> None:
        """Called every second on main thread -- drains bg thread result."""
        if self._pending_data is None:
            return
        games, picks_by_team = self._pending_data
        self._pending_data = None
        from datetime import datetime
        self._refresh_ts    = datetime.now().strftime("%H:%M")
        self._all_lines     = _render_content(games, picks_by_team, self._refresh_ts, self._sport_filter)
        self._scroll_offset = 0
        self._redraw_body()


# ── Compact score sidebar (right panel alternative to watchlist) ──────────────

_SPORT_COLORS_SIDEBAR = {
    "NHL": "#5588ff",
    "NBA": "#ff8c00",
    "MLB": "#00c853",
}


def _render_sidebar(games: list, sport_filter: str = "") -> str:
    if sport_filter:
        games = [g for g in games if (g.get("sport") or "").upper() == sport_filter]
    if not games:
        return "\n [#3a5570]No games today.[/#3a5570]"

    live      = [g for g in games if g.get("status") == "live"]
    final     = [g for g in games if g.get("status") == "final"]
    scheduled = [g for g in games if g.get("status") not in ("live", "final")]

    lines = []

    if live:
        lines.append(" [bold #ff4444]LIVE[/bold #ff4444]")
        for g in live:
            sport  = (g.get("sport") or "")[:3].upper()
            away   = (g.get("away_team") or "?")[:4]
            home   = (g.get("home_team") or "?")[:4]
            a_sc   = g.get("away_score") or 0
            h_sc   = g.get("home_score") or 0
            period = g.get("period", "")
            clock  = g.get("clock", "")
            sc     = _SPORT_COLORS_SIDEBAR.get(sport, "#c8d8e8")
            sit    = f"{period} {clock}".strip()[:8] if clock else period
            lines.append(
                f" [{sc}]{sport}[/{sc}]"
                f" [bold]{away} {a_sc}-{h_sc} {home}[/bold]"
                f" [dim]{sit}[/dim]"
            )
        lines.append("")

    if final:
        lines.append(" [bold #3a8a3a]FINAL[/bold #3a8a3a]")
        for g in final:
            sport = (g.get("sport") or "")[:3].upper()
            away  = (g.get("away_team") or "?")[:4]
            home  = (g.get("home_team") or "?")[:4]
            a_sc  = g.get("away_score") or 0
            h_sc  = g.get("home_score") or 0
            sc    = _SPORT_COLORS_SIDEBAR.get(sport, "#c8d8e8")
            aw    = "bold" if a_sc > h_sc else "dim"
            hw    = "bold" if h_sc > a_sc else "dim"
            lines.append(
                f" [{sc}]{sport}[/{sc}]"
                f" [{aw}]{away} {a_sc}[/{aw}]"
                f"-[{hw}]{h_sc} {home}[/{hw}]"
            )
        lines.append("")

    if scheduled:
        lines.append(" [bold #cc7700]TONIGHT[/bold #cc7700]")
        for g in scheduled:
            sport = (g.get("sport") or "")[:3].upper()
            away  = (g.get("away_team") or "?")[:4]
            home  = (g.get("home_team") or "?")[:4]
            start = (g.get("start_time_local") or "TBD")[:5]
            sc    = _SPORT_COLORS_SIDEBAR.get(sport, "#c8d8e8")
            lines.append(f" [{sc}]{sport}[/{sc}] {away}@{home} [dim]{start}[/dim]")

    return "\n".join(lines)


class ScoreSidebar(Widget):
    """Compact live-score panel for the right 20% column.
    Toggle from watchlist with [w].  Refreshes every 30s.
    """

    DEFAULT_CSS = """
    ScoreSidebar {
        width: 20%;
        border: solid #1e3a5f;
        padding: 0 1;
    }
    #score-sidebar-title {
        background: #0d1b2a;
        color: #ffa500;
        text-style: bold;
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    #score-sidebar-body {
        height: 1fr;
        overflow-y: auto;
        color: #c8d8e8;
    }
    """

    def __init__(self, db_path: Path, **kwargs):
        super().__init__(**kwargs)
        self._db_path      = db_path
        self._pending_games: list | None = None
        self._sport_filter = ""

    def compose(self) -> ComposeResult:
        yield Label(" SCORES  [dim][w] watchlist[/dim]", id="score-sidebar-title")
        yield Static("Loading...", id="score-sidebar-body", markup=True)

    def on_mount(self) -> None:
        self._kick_fetch()
        self.set_interval(1.0,  self._drain_pending)
        self.set_interval(30.0, self._kick_fetch)

    def set_sport_filter(self, sport: str) -> None:
        self._sport_filter = sport.upper()
        self._kick_fetch()

    def _kick_fetch(self) -> None:
        t = threading.Thread(target=self._bg_fetch, daemon=True)
        t.start()

    def _bg_fetch(self) -> None:
        try:
            from scoreboard.live_data import all_games  # type: ignore
            games = all_games(date.today().isoformat())
        except Exception:
            games = []
        self._pending_games = games

    def _drain_pending(self) -> None:
        if self._pending_games is None:
            return
        games = self._pending_games
        self._pending_games = None
        content = _render_sidebar(games, self._sport_filter)
        try:
            self.query_one("#score-sidebar-body", Static).update(content)
        except Exception:
            pass
