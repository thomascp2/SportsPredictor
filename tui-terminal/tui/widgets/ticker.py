"""
Ticker widget -- scrolling bottom marquee.
Shows live game scores from NHL, NBA, and MLB.
Refreshes every 60 seconds via background thread (HTTP calls don't block TUI).
"""

import sys
from datetime import date
from pathlib import Path

from rich.text import Text
from textual.widget import Widget
from textual.app import RenderResult

# Allow importing scoreboard.live_data from SportsPredictor root
_SPORTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_SPORTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPORTS_ROOT))


_SEP = "   |   "
_EMPTY = "  No games today  "


def _fmt_game(g: dict) -> str:
    sport  = g.get("sport", "")
    away   = g.get("away_team", "?")
    home   = g.get("home_team", "?")
    a_sc   = g.get("away_score")
    h_sc   = g.get("home_score")
    status = g.get("status", "scheduled")
    period = g.get("period", "")
    clock  = g.get("clock", "")
    start  = g.get("start_time_local", "")

    if status == "final":
        return f"{sport}: {away} {a_sc or 0}-{h_sc or 0} {home} FINAL"
    elif status == "live":
        situation = f"{period} {clock}".strip() if clock else period
        return f"{sport}: {away} {a_sc or 0}-{h_sc or 0} {home} ({situation})"
    else:
        label = f"{away} @ {home}"
        if start:
            label += f" {start}"
        return f"{sport}: {label}"


def _fetch_scores(today: str) -> str:
    try:
        from scoreboard.live_data import all_games  # type: ignore
        games = all_games(today)
        if not games:
            return _EMPTY
        return _SEP.join(_fmt_game(g) for g in games)
    except Exception:
        return _EMPTY


class Ticker(Widget):
    """Scrolling marquee showing live game scores."""

    _SCROLL_RATE = 1
    _TICK_MS = 130  # ~7 chars/sec -- comfortable reading speed

    def __init__(self, db_path: Path, **kwargs):
        super().__init__(**kwargs)
        self._db_path = db_path  # kept for API compat -- not used for scores
        self._content: str         = _EMPTY
        self._padded: str          = _EMPTY + "    "
        self._offset: int          = 0
        self._pending_content: str = ""   # worker writes here; _tick drains it

    def on_mount(self) -> None:
        # Scroll animation tick
        self.set_interval(self._TICK_MS / 1000.0, self._tick)
        # First score fetch 3s after mount (give TUI time to fully render)
        self.set_timer(3.0, lambda: self.run_worker(
            self._thread_fetch_scores, thread=True, name="score_init"
        ))
        # Reload every 60 seconds
        self.set_interval(60.0, lambda: self.run_worker(
            self._thread_fetch_scores, thread=True, name="score_reload"
        ))

    # ── Worker: runs in thread pool, posts result back to main thread ─────────

    def _thread_fetch_scores(self) -> None:
        today = date.today().isoformat()
        new_content = _fetch_scores(today)
        # GIL makes simple string assignment thread-safe; _tick drains this
        self._pending_content = new_content

    # ── Scroll animation ──────────────────────────────────────────────────────

    def _tick(self) -> None:
        # Drain any pending content update from the worker thread
        if self._pending_content:
            self._content         = self._pending_content
            self._padded          = self._pending_content + "      "
            self._pending_content = ""
        if not self._padded:
            return
        self._offset = (self._offset + self._SCROLL_RATE) % max(1, len(self._padded))
        self.refresh()

    def render(self) -> RenderResult:
        width  = self.size.width or 180
        padded = self._padded
        if not padded:
            return Text(_EMPTY, style="#cc7700")

        doubled = padded * 2
        start   = self._offset % len(padded)
        window  = doubled[start : start + width]

        text = Text(overflow="crop", no_wrap=True)
        for part in window.split(_SEP):
            if "FINAL" in part:
                text.append(part, style="#3a8a3a")       # green -- game over
            elif "(" in part:
                text.append(part, style="bold #ffa500")  # amber -- live game
            else:
                text.append(part, style="#cc7700")       # orange -- scheduled
            text.append(_SEP, style="#3a5570")

        return text
