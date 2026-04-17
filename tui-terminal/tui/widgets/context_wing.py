"""
Context Wing — left panel.

Shows:
  - Recent news_context entries for the selected player (top section)
  - Global recent intel (last 5 entries from news_context)

Refreshes every 5 seconds from props.db.
"""

import sqlite3
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Label, Static


def _fetch_intel(db_path: Path, player_id: Optional[str]) -> tuple:
    """
    Returns (player_entries, intel_entries, injury_entries) as lists of dicts.
    player_entries: last 5 news_context rows for player_id
    intel_entries:  last 8 non-injury rows (manual/volatility triggers)
    injury_entries: last 6 injury_feed rows
    """
    if not db_path.exists():
        return [], [], []

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        player_rows = []
        if player_id:
            player_rows = conn.execute(
                """SELECT summary, source_api, trigger, created_at
                   FROM   news_context
                   WHERE  player_id = ?
                   ORDER  BY created_at DESC
                   LIMIT  5""",
                (player_id,)
            ).fetchall()

        intel_rows = conn.execute(
            """SELECT player_id, summary, source_api, trigger, created_at
               FROM   news_context
               WHERE  trigger != 'injury_feed'
                 AND  date(created_at) = date('now')
                 AND  summary NOT LIKE 'No real%'
               ORDER  BY created_at DESC
               LIMIT  8"""
        ).fetchall()

        injury_rows = conn.execute(
            """SELECT player_id, summary, created_at
               FROM   news_context
               WHERE  trigger = 'injury_feed'
               ORDER  BY created_at DESC
               LIMIT  25"""
        ).fetchall()

        conn.close()
        return (
            [dict(r) for r in player_rows],
            [dict(r) for r in intel_rows],
            [dict(r) for r in injury_rows],
        )

    except Exception:
        return [], [], []


_KNOWN_SPORTS = {"NHL", "NBA", "MLB", "NFL", "CBB", "PGA"}


def _truncate(text: str, max_chars: int) -> str:
    """Truncate at word boundary to avoid mid-word cuts."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(" ", 1)[0]
    return truncated.rstrip(",.;:") + "..."


def _pretty_pid(player_id: str) -> str:
    """'MLB_bobby_witt_jr' -> 'Bobby Witt Jr [MLB]'
    Sport token is FIRST, name is everything after.
    """
    tokens = player_id.split("_")
    if not tokens:
        return player_id
    first = tokens[0].upper()
    if first in _KNOWN_SPORTS and len(tokens) > 1:
        sport = first
        name = " ".join(p.capitalize() for p in tokens[1:])
        return f"{name} [{sport}]"
    # Fallback: treat all tokens as name
    return " ".join(p.capitalize() for p in tokens)


def _fmt_time(ts: str) -> str:
    """'2026-04-10T14:32:00' -> '14:32'"""
    try:
        return ts[11:16]
    except Exception:
        return ts


class ContextWing(Widget):
    """Left 20% panel — intel feed from news_context table."""

    def __init__(self, db_path: Path, **kwargs):
        super().__init__(**kwargs)
        self._db_path = db_path
        self._selected_player_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield Label(" INTEL FEED", id="context-title")
        yield Static("", id="context-feed", markup=True)
        yield Label(" [↑↓] navigate  [i] force intel", id="context-hint")

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(5.0, self._refresh)

    def set_selected_player(self, player_id: Optional[str]) -> None:
        self._selected_player_id = player_id
        self._refresh()

    def _refresh(self) -> None:
        player_rows, intel_rows, injury_rows = _fetch_intel(
            self._db_path, self._selected_player_id
        )
        feed: Static = self.query_one("#context-feed", Static)

        lines = []

        # Selected player section
        if self._selected_player_id and player_rows:
            display = _pretty_pid(self._selected_player_id)
            lines.append(f"[bold #ffa500]{display}[/bold #ffa500]")
            for row in player_rows:
                ts      = _fmt_time(row.get("created_at", ""))
                src     = row.get("source_api", "?").upper()[:3]
                summary = _truncate(row.get("summary", ""), 65)
                trigger = row.get("trigger") or ""
                if trigger and trigger not in ("pregame_cache", "manual"):
                    lines.append(f"  [#7a9cb8]{ts}[/#7a9cb8] [{src}] {summary}")
                else:
                    lines.append(f"  [#7a9cb8]{ts}[/#7a9cb8] {summary}")
            lines.append("")

        # Intel feed (manual / volatility)
        if intel_rows:
            lines.append("[bold #3a5570]INTEL[/bold #3a5570]")
            shown_pids: set = set()
            for row in intel_rows:
                pid = row.get("player_id", "")
                if pid in shown_pids:
                    continue
                shown_pids.add(pid)
                display = _pretty_pid(pid)
                ts      = _fmt_time(row.get("created_at", ""))
                summary = _truncate(row.get("summary", ""), 55)
                trigger = row.get("trigger") or ""
                if "move" in trigger:
                    lines.append(f"[#ffa500] ! {display}[/#ffa500]")
                    lines.append(f"   [#7a9cb8]{ts}[/#7a9cb8] {summary}")
                else:
                    lines.append(f" [#c8d8e8]{display}[/#c8d8e8]")
                    lines.append(f"   [#3a5570]{summary}[/#3a5570]")
        else:
            lines.append("[#3a5570]No intel yet.\nPress [i] on any player.[/#3a5570]")

        # Injury feed section
        if injury_rows:
            lines.append("")
            lines.append(f"[bold #ff1744]INJURIES ({len(injury_rows)})[/bold #ff1744]")
            for row in injury_rows:
                pid     = row.get("player_id", "")
                # pid format: "sport_player_name" -- first token is sport
                parts   = pid.split("_")
                sport   = parts[0].upper() if parts else ""
                name    = " ".join(p.capitalize() for p in parts[1:]) if len(parts) > 1 else pid
                raw_summary = row.get("summary", "")
                # Extract just the status label (before " -- "), not the full comment
                if " -- " in raw_summary:
                    status = raw_summary.split(" -- ", 1)[0].strip()
                else:
                    status = raw_summary.strip()
                status = status[:20]
                lines.append(
                    f" [#3a5570]{sport[:3]}[/#3a5570]"
                    f" [#ff6b6b]{name[:16]}[/#ff6b6b]"
                    f" [dim]{status}[/dim]"
                )

        feed.update("\n".join(lines))
