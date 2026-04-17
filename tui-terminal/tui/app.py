"""
FreePicks Terminal -- Bloomberg for Props
Phase 2: Python Textual TUI

Layout (ultra-wide, 3-column 20/60/20):

  +-- HEADER ----------------------------------------------------------+
  |  FreePicks Terminal  |  NHL  T1  |  2026-04-11 14:32 CST          |
  +---------------+-------------------------------+--------------------+
  |  INTEL FEED   |        THE GRID               |   WATCHLIST        |
  |    20%        |         60%                   |     20%            |
  +---------------+-------------------------------+--------------------+
  | TICKER: Jokic PTS +0.5 on UD                                      |
  | q=quit  i=intel  t=tier  p=parlay  1/2/3=sport  0=all  /=search   |
  +-------------------------------------------------------------------+

Hotkeys:
  /         -- open player search filter
  1/2/3     -- filter to NHL/MLB/NBA only
  0         -- show all sports
  t         -- cycle tier filter (ALL -> T1 -> T1+T2 -> T1+T2+T3 -> ALL)
  SPACE     -- mark/unmark current row for parlay (up to 6 legs)
  p         -- open parlay builder modal with EV calculation
  i         -- force Grok intel for selected player
  r         -- refresh ML bridge
  ENTER     -- add/remove selected row from watchlist
  ctrl+x    -- clear entire watchlist
  q         -- quit

Run from tui-terminal/ directory:
    PYTHONIOENCODING=utf-8 python tui/app.py
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# Load .env files -- tui-terminal/.env first, then SportsPredictor/.env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass

_TUI_DIR = Path(__file__).parent
if str(_TUI_DIR) not in sys.path:
    sys.path.insert(0, str(_TUI_DIR))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from widgets.main_grid import MainGrid, STAT_ABBREV, _fmt_edge
from widgets.context_wing import ContextWing
from widgets.watchlist import WatchlistPanel
from widgets.ticker import Ticker
from widgets.injury_view import InjuryView
from widgets.scoreboard_view import ScoreboardView, ScoreSidebar
from widgets.game_pred_view import GamePredView
import ml_bridge

_ROOT_DIR = _TUI_DIR.parent
PROPS_DB  = _ROOT_DIR / "props.db"

# PrizePicks Power Play payout table
_PARLAY_PAYOUTS = {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 25.0}


def _calc_parlay(rows: list) -> dict:
    n = len(rows)
    payout = _PARLAY_PAYOUTS.get(n, 0)
    if not payout:
        return {}
    probs = [r.get("ml_confidence") or 0.55 for r in rows]
    combined = 1.0
    for p in probs:
        combined *= p
    ev = (combined * payout) - 1.0
    return {
        "legs": n,
        "payout": payout,
        "combined_prob": combined,
        "ev": ev,
        "break_even": 1.0 / payout,
        "profitable": ev > 0,
    }


# ── Parlay Modal ──────────────────────────────────────────────────────────────

class ParlayModal(ModalScreen):
    """Overlay: parlay legs + EV calculation."""

    DEFAULT_CSS = """
    ParlayModal {
        align: center middle;
    }
    #parlay-box {
        width: 58;
        height: auto;
        max-height: 32;
        background: #0d1b2a;
        border: double #ffa500;
        padding: 1 2;
    }
    #parlay-title {
        text-align: center;
        color: #ffa500;
        text-style: bold;
        height: 1;
        margin-bottom: 1;
    }
    #parlay-content {
        height: auto;
        color: #c8d8e8;
    }
    #parlay-hint {
        text-align: center;
        color: #3a5570;
        height: 1;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close"),
        Binding("p",      "dismiss_modal", "Close"),
        Binding("q",      "dismiss_modal", "Close"),
    ]

    def __init__(self, rows: list, **kwargs):
        super().__init__(**kwargs)
        self._rows = rows

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical
        with Vertical(id="parlay-box"):
            yield Label("PARLAY BUILDER", id="parlay-title")
            yield Static(self._build_content(), id="parlay-content")
            yield Label("[ESC/P] close  [SPACE on grid] mark picks", id="parlay-hint")

    def _build_content(self) -> str:
        rows = self._rows
        if not rows:
            return (
                "[#3a5570]No picks marked.\n\n"
                "Press [SPACE] on grid rows to mark picks (up to 6).\n"
                "Then press [P] to view this panel.[/#3a5570]"
            )
        if len(rows) < 2:
            return "[#ffd600]Mark at least 2 picks with SPACE to build a parlay.[/#ffd600]"

        tier_colors = {
            "T1-ELITE": "#00ff41", "T2-STRONG": "#00c853",
            "T3-GOOD":  "#76ff03", "T4-LEAN":   "#ffd600", "T5-FADE": "#ff1744",
        }
        tier_abbrev = {
            "T1-ELITE": "T1", "T2-STRONG": "T2", "T3-GOOD": "T3",
            "T4-LEAN":  "T4", "T5-FADE":   "T5",
        }

        lines = []
        for r in rows:
            name     = (r.get("name") or "")[:16]
            stat     = STAT_ABBREV.get(r.get("stat_type", ""), r.get("stat_type", "")[-4:])
            pred     = r.get("ml_prediction") or ""
            arrow    = "^" if pred == "OVER" else "v" if pred == "UNDER" else " "
            tier     = r.get("ml_tier") or "?"
            edge     = r.get("ml_edge")
            pp_line  = r.get("prizepicks_line")
            line_str = f"@{pp_line:.1f}" if pp_line else ""
            tc       = tier_colors.get(tier, "#c8d8e8")
            ta       = tier_abbrev.get(tier, "?")
            lines.append(
                f" [{tc}]{arrow} {name:<16} {stat:<4}  {ta}  {_fmt_edge(edge):<8}[/{tc}] {line_str}"
            )

        calc = _calc_parlay(rows)
        if not calc:
            lines.append("\n[#ff1744]Parlay requires 2-6 legs.[/#ff1744]")
            return "\n".join(lines)

        ev         = calc["ev"]
        combined   = calc["combined_prob"]
        payout     = calc["payout"]
        be         = calc["break_even"]
        profitable = calc["profitable"]
        ev_color   = "#00ff41" if profitable else "#ff1744"
        ev_label   = "PROFITABLE" if profitable else "LOSING MONEY"

        lines += [
            "",
            "[#1e3a5f]" + "-" * 42 + "[/#1e3a5f]",
            f" [bold]Legs:[/bold]           {len(rows)}",
            f" [bold]Payout:[/bold]         {payout:.0f}x",
            f" [bold]Combined prob:[/bold]  {combined * 100:.1f}%",
            f" [bold]Break-even:[/bold]     {be * 100:.1f}%",
            f" [bold]Expected value:[/bold] [{ev_color}]{ev:+.2f}x  [{ev_label}][/{ev_color}]",
        ]
        if not profitable:
            needed = be * 100
            actual = combined * 100
            lines.append(
                f"\n [#ffd600]Need {needed:.1f}% combined, have {actual:.1f}%.[/#ffd600]"
            )

        return "\n".join(lines)

    def action_dismiss_modal(self) -> None:
        self.dismiss()


# ── Main App ──────────────────────────────────────────────────────────────────

class FreePicsTerminal(App):
    """Bloomberg for Props -- FreePicks command center."""

    CSS_PATH = _TUI_DIR / "styles.tcss"

    BINDINGS = [
        Binding("q",      "quit",            "Quit",       show=True),
        Binding("i",      "force_intel",     "Intel",      show=True),
        Binding("t",      "tier_filter",     "Tier",       show=True),
        Binding("p",      "parlay_view",     "Parlay",     show=True),
        Binding("slash",  "open_filter",     "Search",     show=True),
        Binding("0",      "sport_all",       "All",        show=False),
        Binding("1",      "sport_nhl",       "NHL",        show=False),
        Binding("2",      "sport_mlb",       "MLB",        show=False),
        Binding("3",      "sport_nba",       "NBA",        show=False),
        Binding("n",      "injury_view",     "Injuries",   show=False),
        Binding("s",      "scoreboard_view", "Scoreboard", show=False),
        Binding("g",      "game_preds",      "GamePreds",  show=False),
        Binding("w",      "toggle_scores",   "Scores",     show=False),
        Binding("r",      "run_bridge",      "Refresh",    show=False),
        Binding("ctrl+x", "clear_watchlist", "Clear List", show=False),
    ]

    TITLE = "FreePicks Terminal"

    def __init__(self):
        super().__init__()
        self._selected_row: dict = {}
        self._bridge_running: bool = False
        self._status_msg: str = "Initializing..."
        self._active_sport: str = ""
        self._active_tier_label: str = "ALL"
        self._center_view: str = "props"    # "props" | "injuries" | "scoreboard"
        self._right_view:  str = "watchlist"  # "watchlist" | "scores"

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Label(self._header_text(), id="header-bar")
        with Horizontal(id="columns"):
            yield ContextWing(PROPS_DB, id="context-wing")
            yield MainGrid(PROPS_DB, on_row_select=self._on_row_select, id="main-grid")
            yield InjuryView(PROPS_DB, id="injury-view")
            yield ScoreboardView(PROPS_DB, id="scoreboard-view")
            yield GamePredView(id="game-pred-view")
            yield WatchlistPanel(PROPS_DB, id="watchlist-panel")
            yield ScoreSidebar(PROPS_DB, id="score-sidebar")
        yield Ticker(PROPS_DB, id="ticker")
        yield Label(self._hints_text(), id="status-bar")

    # ── Mount ─────────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        # Alternate center views start hidden
        self.query_one("#injury-view",     InjuryView).display      = False
        self.query_one("#scoreboard-view", ScoreboardView).display   = False
        self.query_one("#game-pred-view",  GamePredView).display     = False
        # Score sidebar starts hidden (watchlist is default right panel)
        self.query_one("#score-sidebar",   ScoreSidebar).display    = False
        # Initial ML bridge run
        self.run_worker(self._async_run_bridge, exclusive=True, name="bridge_startup")
        # Refresh header clock every second
        self.set_interval(1.0, self._refresh_header)
        # Re-run ML bridge every 5 minutes
        self.set_interval(300.0, lambda: self.run_worker(
            self._async_run_bridge, exclusive=True, name="bridge_refresh"
        ))
        # Injury feed every 6000 seconds
        self.set_interval(6000.0, lambda: self.run_worker(
            self._injury_feed_tick, exclusive=False, thread=True, name="injury_feed"
        ))
        # First injury fetch 60 seconds after startup (give ingester time to populate)
        self.set_timer(60.0, lambda: self.run_worker(
            self._injury_feed_tick, exclusive=False, thread=True, name="injury_feed_init"
        ))

    # ── Header / status ───────────────────────────────────────────────────────

    def _header_text(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S  CST")
        filters = ""
        if self._center_view != "props":
            filters += f"  [{self._center_view.upper()}]"
        if self._active_sport:
            filters += f"  [{self._active_sport}]"
        if self._active_tier_label != "ALL":
            filters += f"  {self._active_tier_label}"
        sel = ""
        if self._selected_row:
            name = (self._selected_row.get("name") or "")[:18]
            tier = self._selected_row.get("ml_tier") or "-"
            sel  = f"  |  {name}  {tier}"
        return f" FreePicks Terminal{filters}{sel}  |  {now}  |  {self._status_msg}"

    def _hints_text(self) -> str:
        return (
            " q=quit  i=intel  t=tier  p=parlay  n=injuries  s=scoreboard  g=gamepreds  w=scores"
            "  1=NHL  2=MLB  3=NBA  0=all"
            "  /=search  SPACE=mark  ENTER=watchlist  r=refresh"
        )

    def _refresh_header(self) -> None:
        try:
            self.query_one("#header-bar", Label).update(self._header_text())
        except Exception:
            pass

    # ── Row selection callback ────────────────────────────────────────────────

    def _on_row_select(self, row: dict) -> None:
        self._selected_row = row
        pid = row.get("player_id")
        try:
            self.query_one("#context-wing", ContextWing).set_selected_player(pid)
        except Exception:
            pass
        self._refresh_header()

    # ── Key handler (SPACE + ENTER handled here) ──────────────────────────────

    def on_key(self, event) -> None:
        key = event.key

        if key == "space":
            grid = self.query_one("#main-grid", MainGrid)
            row_key = grid.get_selected_row_key()
            row     = grid.get_selected_row()
            if row_key and row:
                marked = grid.toggle_parlay(row_key)
                name   = (row.get("name") or "")[:20]
                count  = grid.parlay_count()
                action = "Marked" if marked else "Removed"
                self._status_msg = f"{action}: {name}  [{count}/6 in parlay]"
                self._refresh_header()
            event.stop()
            return

        if key == "enter":
            grid = self.query_one("#main-grid", MainGrid)
            row  = grid.get_selected_row()
            if row:
                pid       = row.get("player_id", "")
                stat_type = row.get("stat_type", "")
                tier      = row.get("ml_tier") or ""
                pred      = row.get("ml_prediction") or ""
                edge      = row.get("ml_edge")
                note      = f"{pred} {tier}" + (f" +{edge:.1f}%" if edge else "")
                panel     = self.query_one("#watchlist-panel", WatchlistPanel)
                added     = panel.toggle_play(pid, stat_type, note=note)
                name      = row.get("name", pid)[:20]
                self._status_msg = f"{'Added' if added else 'Removed'}: {name}"
                self._refresh_header()

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_quit(self) -> None:
        self.exit()

    def action_open_filter(self) -> None:
        self.query_one("#main-grid", MainGrid).open_filter()

    def _apply_sport_filter(self, sport: str) -> None:
        """Push sport filter to all sport-aware panels."""
        self._active_sport = sport
        self.query_one("#main-grid", MainGrid).set_sport_filter(sport)
        try:
            self.query_one("#scoreboard-view", ScoreboardView).set_sport_filter(sport)
        except Exception:
            pass
        try:
            self.query_one("#score-sidebar", ScoreSidebar).set_sport_filter(sport)
        except Exception:
            pass
        try:
            self.query_one("#game-pred-view", GamePredView).set_sport_filter(sport)
        except Exception:
            pass

    def action_sport_all(self) -> None:
        self._apply_sport_filter("")
        self._status_msg = "Sport: ALL"
        self._refresh_header()

    def action_sport_nhl(self) -> None:
        self._apply_sport_filter("NHL")
        self._status_msg = "Sport: NHL"
        self._refresh_header()

    def action_sport_mlb(self) -> None:
        self._apply_sport_filter("MLB")
        self._status_msg = "Sport: MLB"
        self._refresh_header()

    def action_sport_nba(self) -> None:
        self._apply_sport_filter("NBA")
        self._status_msg = "Sport: NBA"
        self._refresh_header()

    def action_tier_filter(self) -> None:
        grid = self.query_one("#main-grid", MainGrid)
        grid.cycle_tier_filter()
        self._active_tier_label = grid.get_tier_label()
        self._status_msg = f"Tier filter: {self._active_tier_label}"
        self._refresh_header()

    def action_parlay_view(self) -> None:
        grid = self.query_one("#main-grid", MainGrid)
        self.push_screen(ParlayModal(grid.get_parlay_rows()))

    def action_run_bridge(self) -> None:
        self.run_worker(self._async_run_bridge, exclusive=True, name="bridge_manual")
        self._status_msg = "ML bridge syncing..."
        self._refresh_header()

    def action_clear_watchlist(self) -> None:
        try:
            self.query_one("#watchlist-panel", WatchlistPanel).clear_all()
            self._status_msg = "Watchlist cleared"
        except Exception:
            pass
        self._refresh_header()

    def _set_center_view(self, view: str) -> None:
        """Switch center column to 'props', 'injuries', 'scoreboard', or 'gamepreds'."""
        main_grid       = self.query_one("#main-grid",       MainGrid)
        injury_view     = self.query_one("#injury-view",     InjuryView)
        scoreboard_view = self.query_one("#scoreboard-view", ScoreboardView)
        game_pred_view  = self.query_one("#game-pred-view",  GamePredView)
        main_grid.display       = (view == "props")
        injury_view.display     = (view == "injuries")
        scoreboard_view.display = (view == "scoreboard")
        game_pred_view.display  = (view == "gamepreds")
        self._center_view = view

    def action_injury_view(self) -> None:
        """Toggle center column to injury report (or back to props)."""
        if self._center_view == "injuries":
            self._set_center_view("props")
            self._status_msg = "Props view"
        else:
            self._set_center_view("injuries")
            self._status_msg = "Injury report  [n] to return"
        self._refresh_header()

    def action_scoreboard_view(self) -> None:
        """Toggle center column to scoreboard (or back to props)."""
        if self._center_view == "scoreboard":
            self._set_center_view("props")
            self._status_msg = "Props view"
        else:
            self._set_center_view("scoreboard")
            self._status_msg = "Scoreboard  [s] back  [j/k] scroll  [1-3] filter"
        self._refresh_header()

    def action_game_preds(self) -> None:
        """Toggle center column to game-line predictions (or back to props)."""
        if self._center_view == "gamepreds":
            self._set_center_view("props")
            self._status_msg = "Props view"
        else:
            self._set_center_view("gamepreds")
            self._status_msg = "Game Preds  [g] back  [j/k] scroll  [1-3] filter"
        self._refresh_header()

    def action_toggle_scores(self) -> None:
        """Toggle right sidebar between watchlist and compact live scores."""
        watchlist = self.query_one("#watchlist-panel", WatchlistPanel)
        sidebar   = self.query_one("#score-sidebar",   ScoreSidebar)
        if self._right_view == "scores":
            sidebar.display   = False
            watchlist.display = True
            self._right_view  = "watchlist"
            self._status_msg  = "Watchlist  [w] for live scores"
        else:
            watchlist.display = False
            sidebar.display   = True
            self._right_view  = "scores"
            self._status_msg  = "Live Scores  [w] for watchlist  [1-3] filter sport"
        self._refresh_header()

    # ── Intel (Grok) ─────────────────────────────────────────────────────────

    def action_force_intel(self) -> None:
        if not self._selected_row:
            self._status_msg = "Select a player first (arrow keys)"
            self._refresh_header()
            return
        name      = self._selected_row.get("name", "unknown")
        player_id = self._selected_row.get("player_id", "")
        stat_type = self._selected_row.get("stat_type", "")
        self._status_msg = f"Fetching intel for {name}..."
        self._refresh_header()
        self.run_worker(
            lambda: self._run_force_intel(player_id, name, stat_type),
            exclusive=False,
            thread=True,
            name="force_intel",
        )

    def _run_force_intel(self, player_id: str, name: str, stat_type: str) -> None:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent / "intel"))
        from context_engine import _connect, _write_intel

        conn = _connect(PROPS_DB)
        prompt = (
            f"You are a sports betting analyst. In 15 words or less, what should I know about "
            f"{name} ({stat_type.replace('_', ' ').lower()}) today? "
            f"Check injuries, rest, matchup, or recent form."
        )
        summary = self._call_grok(prompt)
        if summary:
            if len(summary.split()) > 20:
                summary = " ".join(summary.split()[:20]) + "..."
            _write_intel(conn, player_id, stat_type, summary, trigger="manual")
            self._status_msg = f"Intel: {summary[:70]}"
        else:
            self._status_msg = "Intel failed -- check XAI_API_KEY in tui-terminal/.env"
        self._refresh_header()

    def _call_grok(self, prompt: str) -> str:
        import requests as _req
        api_key = os.environ.get("XAI_API_KEY", "")
        if not api_key:
            self._status_msg = "XAI_API_KEY not set in tui-terminal/.env"
            self._refresh_header()
            return ""
        try:
            resp = _req.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model":      "grok-3-mini",
                    "messages":   [{"role": "user", "content": prompt}],
                    "max_tokens": 80,
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            self._status_msg = f"Grok error: {str(exc)[:60]}"
            self._refresh_header()
            return ""

    # ── Injury feed ──────────────────────────────────────────────────────────

    def _injury_feed_tick(self) -> None:
        """Fetch ESPN injuries for all sports, write to news_context. Runs every 6000s."""
        import sys as _sys, requests as _req
        _sys.path.insert(0, str(Path(__file__).parent.parent / "intel"))
        from context_engine import _connect, _write_intel

        conn = _connect(PROPS_DB)

        espn_sources = [
            ("NHL", "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"),
            ("NBA", "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"),
            ("MLB", "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries"),
        ]

        total = 0
        sport_counts: dict = {}
        for sport, url in espn_sources:
            try:
                resp = _req.get(url, timeout=10)
                resp.raise_for_status()
                # ESPN structure: injuries[i] = team, injuries[i].injuries[j] = player injury
                team_groups = resp.json().get("injuries", [])
                written = 0
                for team_group in team_groups:
                    for inj in team_group.get("injuries", []):
                        if written >= 10:
                            break
                        athlete     = inj.get("athlete", {})
                        player_name = athlete.get("displayName", "")
                        if not player_name:
                            continue
                        status   = inj.get("status", "")
                        comment  = inj.get("shortComment", "") or inj.get("longComment", "")
                        summary  = status
                        if comment and comment.lower() != status.lower():
                            summary += f" -- {comment}"
                        if not summary.strip():
                            continue
                        pid = f"{sport.lower()}_{player_name.lower().replace(' ', '_')}"
                        _write_intel(conn, pid, f"{sport}_INJURY", summary, trigger="injury_feed")
                        total += 1
                        written += 1
                    if written >= 10:
                        break
                if written:
                    sport_counts[sport] = written
            except Exception:
                pass  # ESPN can be flaky; fail silently

        if total:
            breakdown = "  ".join(f"{s}:{n}" for s, n in sport_counts.items())
            self._status_msg = f"Injuries: {breakdown}  (scroll left panel)"
            self._refresh_header()

    # ── ML Bridge ────────────────────────────────────────────────────────────

    async def _async_run_bridge(self) -> None:
        if self._bridge_running:
            return
        self._bridge_running = True
        self._status_msg = "ML bridge syncing..."
        self._refresh_header()
        try:
            result = await asyncio.to_thread(ml_bridge.run_bridge, PROPS_DB, False)
            nhl   = result.get("nhl_updated", 0)
            mlb   = result.get("mlb_updated", 0)
            intel = result.get("intel_rows", 0)
            now   = datetime.now().strftime("%H:%M")
            self._status_msg = f"ML synced {now} -- NHL:{nhl} MLB:{mlb} Intel:{intel}"
        except Exception as e:
            self._status_msg = f"Bridge error: {str(e)[:60]}"
        finally:
            self._bridge_running = False
        self._refresh_header()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not PROPS_DB.exists():
        print(f"WARNING: props.db not found at {PROPS_DB}")
        print("Run the Rust ingester first: ./target/release/ingester")
        print("Starting TUI anyway (grid will be empty until ingester runs)...")

    FreePicsTerminal().run()
