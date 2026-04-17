"""
InjuryView -- center column injury report panel.
Toggled by pressing 'n'. Shows all injuries grouped by sport.
Auto-refreshes every 60s.
"""

import sqlite3
from pathlib import Path

from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Label, Static


_SPORT_COLORS = {
    "NHL": "#5588ff",
    "NBA": "#ff8c00",
    "MLB": "#00c853",
}

def _truncate(text: str, max_chars: int) -> str:
    """Truncate at word boundary to avoid mid-word cuts."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(" ", 1)[0]
    return truncated.rstrip(",.;:") + "..."


_STATUS_COLORS = {
    "out":         "#ff4444",
    "injured reserve": "#ff4444",
    "ir":          "#ff4444",
    "questionable": "#ffd600",
    "doubtful":    "#ffa500",
    "day-to-day":  "#ffa500",
    "probable":    "#88cc88",
    "active":      "#00c853",
}


def _status_color(status: str) -> str:
    sl = status.lower()
    for key, color in _STATUS_COLORS.items():
        if key in sl:
            return color
    return "#c8d8e8"


def _fetch_injuries(db_path: Path) -> dict:
    """
    Returns {sport: [{name, status, comment, ts}]}
    Dedupes by player_id (keeps most recent), groups by sport.
    """
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT player_id, summary, created_at
               FROM   news_context
               WHERE  trigger = 'injury_feed'
               ORDER  BY player_id, created_at DESC"""
        ).fetchall()
        conn.close()
    except Exception:
        return {}

    seen: set = set()
    by_sport: dict = {}
    for row in rows:
        pid = row["player_id"]
        if pid in seen:
            continue
        seen.add(pid)
        parts = pid.split("_")
        sport = parts[0].upper() if parts else "?"
        name  = " ".join(p.capitalize() for p in parts[1:]) if len(parts) > 1 else pid
        summary = row["summary"] or ""
        if " -- " in summary:
            status, comment = summary.split(" -- ", 1)
        else:
            status, comment = summary, ""
        by_sport.setdefault(sport, []).append({
            "name":    name,
            "status":  status.strip(),
            "comment": comment.strip(),
        })
    return by_sport


class InjuryView(Widget):
    """Full injury report — replaces center column when 'n' is pressed."""

    DEFAULT_CSS = """
    InjuryView {
        width: 60%;
        border: solid #1e3a5f;
    }
    #injury-title {
        background: #0d1b2a;
        color: #ff1744;
        text-style: bold;
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    #injury-body {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
        color: #c8d8e8;
    }
    """

    def __init__(self, db_path: Path, **kwargs):
        super().__init__(**kwargs)
        self._db_path = db_path

    def compose(self) -> ComposeResult:
        yield Label(
            " INJURY REPORT  [dim]press [n] to return to props[/dim]",
            id="injury-title",
        )
        yield Static("Loading...", id="injury-body", markup=True)

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(60.0, self._refresh)

    def _refresh(self) -> None:
        by_sport = _fetch_injuries(self._db_path)
        body = self.query_one("#injury-body", Static)

        if not by_sport:
            body.update(
                "\n [#3a5570]No injury data yet.\n"
                " Wait ~60s for the ESPN feed to load, or restart the TUI.[/#3a5570]"
            )
            return

        lines: list = []
        total = sum(len(v) for v in by_sport.values())
        lines.append(f"\n [dim]{total} players reported injured across all sports[/dim]\n")

        for sport in ("NHL", "NBA", "MLB"):
            players = by_sport.get(sport, [])
            if not players:
                continue
            sc = _SPORT_COLORS.get(sport, "#c8d8e8")
            lines.append(f" [bold {sc}]{sport}[/bold {sc}]  [dim]({len(players)} players)[/dim]")
            lines.append(f" [#1e3a5f]{'─' * 68}[/#1e3a5f]")
            for p in players:
                name    = p["name"][:24]
                status  = p["status"][:22]
                comment = _truncate(p["comment"], 110)
                stc     = _status_color(status)
                # Line 1: name + status badge
                lines.append(
                    f"  [#c8d8e8]{name:<24}[/#c8d8e8]"
                    f"  [{stc}]{status}[/{stc}]"
                )
                # Line 2: comment clipped at word boundary (only if non-empty)
                if comment:
                    lines.append(f"    [dim]{comment}[/dim]")
            lines.append("")

        body.update("\n".join(lines))
