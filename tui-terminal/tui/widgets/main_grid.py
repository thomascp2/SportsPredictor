"""
Main Grid widget — center DataTable showing all current props.

Columns: Player | Prop | PP | UD | Kalshi% | Tier | Edge | Disc

Color logic:
  GREEN  = T1-ELITE or T2-STRONG, no volatile flag
  AMBER  = volatile (is_volatile=1) or T3-GOOD
  RED    = T5-FADE or negative edge
  DIM    = no ML data yet

Filter state (controlled by app):
  _text_filter   — substring match on player name (case-insensitive)
  _sport_filter  — "NHL" | "MLB" | "NBA" | "" (all)
  _tier_max      — 1=T1 only, 2=T1+T2, 3=T1+T2+T3, 5=all

Parlay:
  _parlay_keys   — set of row_keys marked for parlay (max 6)
"""

import sqlite3
from pathlib import Path
from typing import Optional, Callable

from rich.text import Text
from textual.widgets import DataTable, Input
from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Label
from textual import on


# ── Tier config ──────────────────────────────────────────────────────────────

TIER_RANK = {
    "T1-ELITE":  1,
    "T2-STRONG": 2,
    "T3-GOOD":   3,
    "T4-LEAN":   4,
    "T5-FADE":   5,
}

_TIER_CYCLE = {5: 1, 1: 2, 2: 3, 3: 5}
_TIER_LABEL = {5: "ALL", 1: "T1", 2: "T1+T2", 3: "T1+T2+T3"}


# ── Color helpers ────────────────────────────────────────────────────────────

def _tier_color(tier: Optional[str], is_volatile: int) -> str:
    if is_volatile:
        return "#ffa500"
    if not tier:
        return "#3a5570"
    return {
        "T1-ELITE":  "#00ff41",
        "T2-STRONG": "#00c853",
        "T3-GOOD":   "#76ff03",
        "T4-LEAN":   "#ffd600",
        "T5-FADE":   "#ff1744",
    }.get(tier, "#c8d8e8")


def _edge_color(edge: Optional[float]) -> str:
    if edge is None:
        return "#3a5570"
    if edge >= 14:
        return "#00ff41"
    elif edge >= 9:
        return "#76ff03"
    elif edge >= 0:
        return "#ffd600"
    else:
        return "#ff1744"


def _disc_color(disc: Optional[float]) -> str:
    if disc is None:
        return "#3a5570"
    if disc >= 1.0:
        return "#ffa500"
    if disc >= 0.5:
        return "#ffd600"
    return "#3a5570"


def _fmt_ml_vs_line(diff: Optional[float]) -> tuple[str, str]:
    """
    Format the ML predicted_value - pp_line delta.
    Positive = model predicts player will exceed the line (lean OVER).
    Negative = model predicts player falls short (lean UNDER).
    """
    if diff is None:
        return " -- ", "#3a5570"
    sign = "+" if diff >= 0 else ""
    display = f"{sign}{diff:.2f}"
    if diff >= 0.2:
        return display, "#00c853"   # green — ML leans OVER
    elif diff <= -0.2:
        return display, "#ff6e6e"   # red — ML leans UNDER
    else:
        return display, "#ffd600"   # amber — within 0.2 of line (toss-up)


def _fmt_ml_predicted(val: Optional[float], pp_line: Optional[float]) -> tuple[str, str]:
    """
    Format the ML predicted value column.
    Returns (display_str, color).
    Colors: green if predicted > pp_line (lean OVER), amber if within 0.2, dim if no data.
    """
    if val is None:
        return " -- ", "#3a5570"
    display = f"{val:.2f}"
    if pp_line is None:
        return display, "#c8d8e8"
    diff = val - pp_line
    if diff >= 0.2:
        return display, "#00c853"   # green — ML leans OVER
    elif diff <= -0.2:
        return display, "#ff6e6e"   # red — ML leans UNDER
    else:
        return display, "#ffd600"   # amber — close to the line


def _fmt(val: Optional[float], decimals: int = 1, fallback: str = " -- ") -> str:
    if val is None:
        return fallback
    return f"{val:.{decimals}f}"


def _fmt_kalshi(price: Optional[float]) -> str:
    if price is None:
        return " -- "
    return f"{price * 100:.0f}%"


def _fmt_edge(edge_pct: Optional[float]) -> str:
    if edge_pct is None:
        return " -- "
    sign = "+" if edge_pct >= 0 else ""
    return f"{sign}{edge_pct:.1f}%"


def _fmt_tier(tier: Optional[str]) -> str:
    if not tier:
        return " -- "
    abbrev = {
        "T1-ELITE":  "T1",
        "T2-STRONG": "T2",
        "T3-GOOD":   "T3",
        "T4-LEAN":   "T4",
        "T5-FADE":   "T5",
    }
    return abbrev.get(tier, tier[:2])


STAT_ABBREV = {
    # NBA
    "NBA_POINTS":                  "PTS",
    "NBA_REBOUNDS":                "REB",
    "NBA_ASSISTS":                 "AST",
    "NBA_THREES":                  "3PM",
    "NBA_STEALS":                  "STL",
    "NBA_BLOCKS":                  "BLK",
    "NBA_TURNOVERS":               "TOV",
    "NBA_FANTASY":                 "FAN",
    "NBA_PRA":                     "PRA",
    # NHL
    "NHL_POINTS":                  "PTS",
    "NHL_SHOTS":                   "SOG",
    "NHL_GOALS":                   "G",
    "NHL_ASSISTS":                 "A",
    "NHL_HITS":                    "HITS",   # was "HIT"
    "NHL_BLOCKED_SHOTS":           "BLK",
    # MLB -- batters (prefixed)
    "MLB_HITS":                    "HITS",
    "MLB_HOME_RUNS":               "HR",
    "MLB_TOTAL_BASES":             "TB",
    "MLB_RBIS":                    "RBI",
    "MLB_RUNS":                    "RUNS",
    "MLB_STOLEN_BASES":            "SB",
    "MLB_BATTER_WALKS":            "BB",
    "MLB_BATTER_STRIKEOUTS":       "KO",
    "MLB_HITTER_STRIKEOUTS":       "KO",
    "MLB_HRR":                     "HRR",
    # MLB -- pitchers (prefixed)
    "MLB_STRIKEOUTS":              "K",
    "MLB_PITCHER_STRIKEOUTS":      "K",
    "MLB_OUTS_RECORDED":           "OUTS",
    "MLB_PITCHER_OUTS_RECORDED":   "OUTS",
    "MLB_PITCHER_WALKS":           "BB",
    "MLB_PITCHER_WALKS_ALLOWED":   "BB",
    "MLB_HITS_ALLOWED":            "HA",
    "MLB_PITCHER_HITS_ALLOWED":    "HA",
    "MLB_EARNED_RUNS":             "ER",
    "MLB_PITCHER_EARNED_RUNS":     "ER",
    "MLB_PITCHER_RUNS_ALLOWED":    "ER",
    "MLB_RUNS_ALLOWED":            "ER",
    # Unprefixed variants (some DB rows stored without sport prefix)
    "STRIKEOUTS":                  "K",
    "OUTS_RECORDED":               "OUTS",
    "HITS_ALLOWED":                "HA",
    "EARNED_RUNS":                 "ER",
    "HOME_RUNS":                   "HR",
    "TOTAL_BASES":                 "TB",
    "STOLEN_BASES":                "SB",
    "BATTER_STRIKEOUTS":           "KO",
    "PITCHER_STRIKEOUTS":          "K",
    "PITCHER_WALKS":               "BB",
    "PITCHER_OUTS_RECORDED":       "OUTS",
    "PITCHER_HITS_ALLOWED":        "HA",
    "PITCHER_EARNED_RUNS":         "ER",
}


# ── Query ────────────────────────────────────────────────────────────────────

_QUERY = """
SELECT
    sport || '_' || lower(replace(player_name, ' ', '_')) AS player_id,
    player_name                                           AS name,
    team,
    sport,
    stat_type,
    pp_line              AS prizepicks_line,
    NULL                 AS underdog_line,
    NULL                 AS kalshi_price,
    tier                 AS ml_tier,
    edge                 AS ml_edge,
    prediction           AS ml_prediction,
    probability          AS ml_confidence,
    odds_type,
    NULL                 AS line_discrepancy,
    0                    AS is_volatile,
    ml_predicted_value                      AS ml_predicted_value,
    ml_predicted_value - pp_line            AS ml_vs_line
FROM smart_picks
WHERE game_date = date('now', 'localtime')
ORDER BY
    CASE tier
        WHEN 'T1-ELITE'  THEN 1
        WHEN 'T2-STRONG' THEN 2
        WHEN 'T3-GOOD'   THEN 3
        WHEN 'T4-LEAN'   THEN 4
        WHEN 'T5-FADE'   THEN 5
        ELSE 6
    END,
    sport,
    ABS(COALESCE(edge, 0)) DESC
"""


def _load_rows(db_path: Path) -> list:
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(_QUERY).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ── Widget ───────────────────────────────────────────────────────────────────

class MainGrid(Widget):
    """Center panel: filter bar + props DataTable."""

    DEFAULT_CSS = """
    MainGrid {
        width: 60%;
        border: solid #1e3a5f;
    }
    #filter-input {
        height: 1;
        background: #0d1b2a;
        border: none;
        padding: 0 1;
        color: #ffa500;
        display: none;
    }
    #filter-input:focus {
        border: none;
        background: #0d2a40;
    }
    """

    def __init__(self, db_path: Path, on_row_select: Optional[Callable] = None, **kwargs):
        super().__init__(**kwargs)
        self._db_path = db_path
        self._on_row_select = on_row_select
        self._row_data: dict = {}
        self._last_hash: Optional[int] = None
        # Filter state
        self._text_filter: str = ""
        self._sport_filter: str = ""
        self._tier_max: int = 5
        # Parlay
        self._parlay_keys: set = set()

    def compose(self) -> ComposeResult:
        yield Label(" THE GRID  |  loading...", id="grid-title")
        yield Input(placeholder="search players...", id="filter-input")
        table = DataTable(id="main-table", cursor_type="row", zebra_stripes=True)
        table.add_column("Player", width=22)
        table.add_column("Team",   width=5)
        table.add_column("Prop",   width=6)
        table.add_column("Sport",  width=5)
        table.add_column("PP",     width=6)
        table.add_column("Tier",   width=5)
        table.add_column("Edge",    width=8)
        table.add_column("ML Exp",  width=7)
        table.add_column("ML +/-",  width=7)
        yield table

    def on_mount(self) -> None:
        self.refresh_data()
        # Auto-focus the table so arrow keys work immediately on launch
        self.set_timer(0.3, lambda: self.query_one("#main-table", DataTable).focus())
        self.set_interval(1.0, self.refresh_data)

    # ── Filter input events ───────────────────────────────────────────────────

    @on(Input.Changed, "#filter-input")
    def _filter_changed(self, event: Input.Changed) -> None:
        self._text_filter = event.value.lower()
        self._force_redraw()

    @on(Input.Submitted, "#filter-input")
    def _filter_submitted(self, event: Input.Submitted) -> None:
        self.close_filter()

    def on_key(self, event) -> None:
        """Close filter on ESC when input is visible."""
        if event.key == "escape":
            inp = self.query_one("#filter-input", Input)
            if inp.display:
                inp.value = ""
                self._text_filter = ""
                self._force_redraw()
                self.close_filter()
                event.stop()

    # ── Public API ────────────────────────────────────────────────────────────

    def open_filter(self) -> None:
        inp = self.query_one("#filter-input", Input)
        inp.display = True
        inp.focus()

    def close_filter(self) -> None:
        inp = self.query_one("#filter-input", Input)
        inp.display = False
        self.query_one("#main-table", DataTable).focus()

    def set_text_filter(self, text: str) -> None:
        self._text_filter = text.lower()
        self._force_redraw()

    def set_sport_filter(self, sport: str) -> None:
        self._sport_filter = sport.upper()
        self._force_redraw()

    def cycle_tier_filter(self) -> int:
        """Cycle: all -> T1 -> T1+T2 -> T1+T2+T3 -> all. Returns new tier_max."""
        self._tier_max = _TIER_CYCLE.get(self._tier_max, 5)
        self._force_redraw()
        return self._tier_max

    def get_tier_label(self) -> str:
        return _TIER_LABEL.get(self._tier_max, "ALL")

    def toggle_parlay(self, row_key: str) -> bool:
        """Mark/unmark a row for parlay. Returns True if now marked."""
        if row_key in self._parlay_keys:
            self._parlay_keys.discard(row_key)
            self._force_redraw()
            return False
        if len(self._parlay_keys) >= 6:
            return False  # max 6 legs
        self._parlay_keys.add(row_key)
        self._force_redraw()
        return True

    def get_parlay_rows(self) -> list:
        return [self._row_data[k] for k in self._parlay_keys if k in self._row_data]

    def parlay_count(self) -> int:
        return len(self._parlay_keys)

    def _force_redraw(self) -> None:
        self._last_hash = None
        self.refresh_data()

    # ── Data refresh ─────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        all_rows = _load_rows(self._db_path)

        # Apply filters
        rows = all_rows
        if self._sport_filter:
            rows = [r for r in rows if (r.get("sport") or "").upper() == self._sport_filter]
        if self._text_filter:
            rows = [r for r in rows if self._text_filter in (r.get("name") or "").lower()]
        if self._tier_max < 5:
            rows = [r for r in rows if TIER_RANK.get(r.get("ml_tier"), 99) <= self._tier_max]

        # Deduplicate by the exact row key used in the DataTable
        _seen_keys: set = set()
        _deduped: list = []
        for _r in rows:
            _rk = f"{_r['player_id']}|{_r['stat_type']}|{_r.get('prizepicks_line', '')}"
            if _rk not in _seen_keys:
                _seen_keys.add(_rk)
                _deduped.append(_r)
        rows = _deduped

        # Skip redraw if nothing changed
        new_hash = hash(
            tuple(
                r["player_id"] + r["stat_type"]
                + str(r.get("ml_edge")) + str(r.get("ml_tier"))
                + str(r.get("ml_predicted_value"))
                + str(r.get("ml_vs_line"))
                for r in rows
            )
            + tuple(sorted(self._parlay_keys))
        )
        if new_hash == self._last_hash:
            return
        self._last_hash = new_hash

        # Update title label
        title: Label = self.query_one("#grid-title", Label)
        parts = [" THE GRID"]
        if self._sport_filter:
            parts.append(f"[{self._sport_filter}]")
        if self._tier_max < 5:
            parts.append(self.get_tier_label())
        if self._text_filter:
            parts.append(f'/{self._text_filter}')
        if self._parlay_keys:
            parts.append(f"[{len(self._parlay_keys)}P]")
        parts.append(f"{len(rows)} picks")
        title.update("  ".join(parts))

        table: DataTable = self.query_one("#main-table", DataTable)
        saved_cursor = table.cursor_row
        self._row_data = {r["player_id"] + "|" + r["stat_type"]: r for r in rows}
        table.clear()

        for r in rows:
            pid         = r["player_id"]
            name        = r["name"] or pid
            team        = (r["team"] or "")[:5].upper()
            sport       = (r["sport"] or "").upper()
            stat_raw    = r["stat_type"] or ""
            stat        = STAT_ABBREV.get(stat_raw) or stat_raw.rsplit("_", 1)[-1][:5]
            pp_line     = _fmt(r["prizepicks_line"])
            tier        = r["ml_tier"]
            edge_pct    = r["ml_edge"]
            is_volatile = r["is_volatile"] or 0
            prediction  = r["ml_prediction"] or ""

            color   = _tier_color(tier, is_volatile)
            e_color = _edge_color(edge_pct)

            # ML predicted value + delta vs PP line (MLB props only)
            ml_pred_val = r.get("ml_predicted_value")
            ml_vs_line  = r.get("ml_vs_line")
            pp_line_raw = r.get("prizepicks_line")
            ml_str,  ml_color  = _fmt_ml_predicted(ml_pred_val, pp_line_raw)
            vsl_str, vsl_color = _fmt_ml_vs_line(ml_vs_line)

            # Build name: prediction arrow + parlay marker
            row_key = f"{pid}|{r['stat_type']}|{r.get('prizepicks_line', '')}"
            name_display = name[:18]
            if prediction:
                arrow = "^" if prediction == "OVER" else "v"
                name_display = f"{name_display} {arrow}"
            if row_key in self._parlay_keys:
                name_display = f"*{name_display[:19]}"

            table.add_row(
                Text(name_display, style=color),
                Text(team, style="#3a5570"),
                Text(stat, style=color),
                Text(sport, style="#3a5570"),
                Text(pp_line, style="#c8d8e8"),
                Text(_fmt_tier(tier), style=color),
                Text(_fmt_edge(edge_pct), style=e_color),
                Text(ml_str, style=ml_color),
                Text(vsl_str, style=vsl_color),
                key=row_key,
            )

        row_count = len(rows)
        if row_count > 0:
            restore_to = min(saved_cursor, row_count - 1)
            table.move_cursor(row=restore_to, animate=False)
            # Fire selection callback so header/intel wing always show a player
            keys = list(self._row_data.keys())
            if restore_to < len(keys) and self._on_row_select:
                row = self._row_data.get(keys[restore_to])
                if row:
                    self._on_row_select(row)

    # ── Row access ────────────────────────────────────────────────────────────

    def get_selected_row(self) -> Optional[dict]:
        table: DataTable = self.query_one("#main-table", DataTable)
        keys = list(self._row_data.keys())
        if 0 <= table.cursor_row < len(keys):
            return self._row_data[keys[table.cursor_row]]
        return None

    def get_selected_row_key(self) -> Optional[str]:
        table: DataTable = self.query_one("#main-table", DataTable)
        keys = list(self._row_data.keys())
        if 0 <= table.cursor_row < len(keys):
            return keys[table.cursor_row]
        return None

    @on(DataTable.RowHighlighted)
    def _row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = str(event.row_key.value) if event.row_key else None
        if key and self._on_row_select:
            # DataTable row key = "pid|stat_type|pp_line" (3 parts)
            # _row_data key = "pid|stat_type" (2 parts) -- strip the 3rd part
            two_part = "|".join(key.split("|")[:2])
            row = self._row_data.get(two_part)
            if row:
                self._on_row_select(row)

    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value) if event.row_key else None
        if key and self._on_row_select:
            two_part = "|".join(key.split("|")[:2])
            row = self._row_data.get(two_part)
            if row:
                self._on_row_select(row)
