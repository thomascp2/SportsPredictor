"""
Watchlist panel — right 20% panel.

Displays plays the user has added (ENTER on a row in MainGrid).
ENTER on a watchlist item removes it.
Shows player name, stat, ML tier, and note.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Label, Static, ListView, ListItem


STAT_ABBREV = {
    "NBA_POINTS":         "PTS",
    "NBA_REBOUNDS":       "REB",
    "NBA_ASSISTS":        "AST",
    "NBA_THREES":         "3PM",
    "NBA_STEALS":         "STL",
    "NBA_BLOCKS":         "BLK",
    "NBA_TURNOVERS":      "TOV",
    "NBA_FANTASY":        "FAN",
    "NBA_PRA":            "PRA",
    "NHL_POINTS":         "PTS",
    "NHL_SHOTS":          "SOG",
    "NHL_GOALS":          "G",
    "NHL_ASSISTS":        "A",
    "NHL_HITS":           "HIT",
    "NHL_BLOCKED_SHOTS":  "BLK",
}

TIER_STYLE = {
    "T1-ELITE":  "bold #00ff41",
    "T2-STRONG": "#00c853",
    "T3-GOOD":   "#76ff03",
    "T4-LEAN":   "#ffd600",
    "T5-FADE":   "#ff1744",
}


def _fetch_watchlist(db_path: Path) -> list:
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, player_id, stat_type, note, added_at FROM watchlist ORDER BY added_at DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _get_ml_tier(db_path: Path, player_id: str, stat_type: str) -> Optional[str]:
    """Quick lookup of ml_tier for a watchlist entry."""
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT ml_tier, ml_prediction FROM current_lines WHERE player_id = ? AND stat_type = ?",
            (player_id, stat_type)
        ).fetchone()
        conn.close()
        return (row[0], row[1]) if row else (None, None)
    except Exception:
        return None, None


def _pretty_pid(player_id: str) -> str:
    tokens = player_id.split("_")
    name_parts = tokens[:-1]
    if len(name_parts) >= 2:
        return f"{name_parts[-1].capitalize()} {name_parts[0][0].upper()}."
    elif name_parts:
        return name_parts[0].capitalize()
    return player_id


class WatchlistPanel(Widget):
    """Right 20% panel — queued plays."""

    def __init__(self, db_path: Path, **kwargs):
        super().__init__(**kwargs)
        self._db_path = db_path
        self._items: list = []

    def compose(self) -> ComposeResult:
        yield Label(" WATCHLIST", id="watchlist-title")
        yield Static("", id="watchlist-items", markup=True)
        yield Label(" [ENTER] add/remove", id="watchlist-hint")

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(5.0, self._refresh)

    def _refresh(self) -> None:
        self._items = _fetch_watchlist(self._db_path)
        content: Static = self.query_one("#watchlist-items", Static)

        if not self._items:
            content.update(
                "[#3a5570]No plays queued.\n\nNavigate the grid\nand press [ENTER]\nto add a play.[/#3a5570]"
            )
            return

        lines = []
        for i, item in enumerate(self._items):
            pid       = item["player_id"]
            stat_type = item["stat_type"]
            note      = item.get("note") or ""
            stat      = STAT_ABBREV.get(stat_type, stat_type.split("_")[-1][:4])
            name      = _pretty_pid(pid)

            ml_tier, ml_pred = _get_ml_tier(self._db_path, pid, stat_type)
            tier_str  = ml_tier or "?"
            tier_style = TIER_STYLE.get(ml_tier, "#3a5570") if ml_tier else "#3a5570"
            pred_arrow = "^ " if ml_pred == "OVER" else "v " if ml_pred == "UNDER" else ""
            sport_suffix = pid.split("_")[-1].upper() if "_" in pid else ""

            lines.append(
                f"[{tier_style}]{pred_arrow}{name}[/{tier_style}] "
                f"[#7a9cb8]{stat}[/#7a9cb8] "
                f"[{tier_style}]{tier_str}[/{tier_style}]"
            )
            if note:
                lines.append(f"   [#3a5570]{note[:30]}[/#3a5570]")
            lines.append("")

        # Summary line
        t1_count = sum(1 for r in self._items
                       if _get_ml_tier(self._db_path, r["player_id"], r["stat_type"])[0] == "T1-ELITE")
        lines.append(f"[#3a5570]─── {len(self._items)} plays")
        if t1_count:
            lines.append(f"[bold #00ff41]{t1_count} T1-ELITE[/bold #00ff41][#3a5570] included[/#3a5570]")

        content.update("\n".join(lines))

    def toggle_play(self, player_id: str, stat_type: str, note: str = "") -> bool:
        """
        Add play if not already in watchlist; remove if it is.
        Returns True if added, False if removed.
        """
        try:
            conn = sqlite3.connect(str(self._db_path))

            existing = conn.execute(
                "SELECT id FROM watchlist WHERE player_id = ? AND stat_type = ?",
                (player_id, stat_type)
            ).fetchone()

            if existing:
                conn.execute("DELETE FROM watchlist WHERE id = ?", (existing[0],))
                conn.commit()
                conn.close()
                self._refresh()
                return False
            else:
                conn.execute(
                    "INSERT INTO watchlist (player_id, stat_type, note, added_at) VALUES (?, ?, ?, datetime('now'))",
                    (player_id, stat_type, note)
                )
                conn.commit()
                conn.close()
                self._refresh()
                return True

        except Exception:
            return False

    def clear_all(self) -> None:
        """Clear the entire watchlist (bound to CTRL+X in app)."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("DELETE FROM watchlist")
            conn.commit()
            conn.close()
        except Exception:
            pass
        self._refresh()
