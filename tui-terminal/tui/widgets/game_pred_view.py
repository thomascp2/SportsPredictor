"""
GamePredView -- game line predictions across NHL / NBA / MLB.
Toggled by pressing 'g'. Shows today's model predictions for totals,
spreads, and moneylines grouped by matchup.

Data: reads directly from sport DBs (read-only, no write).
Scroll: manual line-offset pagination (j/k = 3 lines, PgDn/PgUp = 20).
"""

import sqlite3
from datetime import date
from pathlib import Path

from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Label, Static

_SPORTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_DB_PATHS = {
    "NHL": _SPORTS_ROOT / "nhl" / "database" / "nhl_predictions_v2.db",
    "NBA": _SPORTS_ROOT / "nba" / "database" / "nba_predictions.db",
    "MLB": _SPORTS_ROOT / "mlb" / "database" / "mlb_predictions.db",
}

_SPORT_COLORS = {"NHL": "#5588ff", "NBA": "#ff8c00", "MLB": "#00c853"}

_TIER_COLORS = {
    "ELITE":  "#00ff41",
    "STRONG": "#00c853",
    "LEAN":   "#ffd600",
    "PASS":   "#3a5570",
}

_TIER_RANK = {"ELITE": 1, "STRONG": 2, "LEAN": 3, "PASS": 4}

_TIER_ABBREV = {"ELITE": "E", "STRONG": "S", "LEAN": "L", "PASS": "-"}


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_preds(sport: str, db_path: Path) -> list:
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT home_team, away_team, bet_type, line,
                      prediction, probability, edge, confidence_tier,
                      elo_win_prob, elo_diff
               FROM   game_predictions
               WHERE  game_date = date('now', 'localtime')
               ORDER  BY
                   CASE confidence_tier
                       WHEN 'ELITE'  THEN 1 WHEN 'STRONG' THEN 2
                       WHEN 'LEAN'   THEN 3 ELSE 4 END,
                   ABS(COALESCE(edge, 0)) DESC"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ── Rendering ─────────────────────────────────────────────────────────────────

def _fmt_edge(edge) -> str:
    if edge is None:
        return "  --  "
    sign = "+" if edge >= 0 else ""
    return f"{sign}{edge * 100:.1f}%"


def _fmt_prob(prob) -> str:
    if prob is None:
        return " -- "
    return f"{prob * 100:.0f}%"


def _render_all(sport_filter: str = "") -> list:
    """Return a list of Rich markup strings (one per display line)."""
    today    = date.today().isoformat()
    sports   = [sport_filter] if sport_filter else ["NHL", "NBA", "MLB"]
    lines    = []
    n_games  = 0
    n_strong = 0

    for sport in sports:
        rows = _load_preds(sport, _DB_PATHS.get(sport, Path("nonexistent")))
        if not rows:
            continue

        # Group by (away, home) preserving insertion order
        by_game: dict = {}
        for r in rows:
            key = (r["away_team"], r["home_team"])
            by_game.setdefault(key, []).append(r)

        sc = _SPORT_COLORS.get(sport, "#c8d8e8")
        lines.append(f" [bold {sc}]{sport}[/bold {sc}]  [dim]({len(by_game)} games)[/dim]")
        lines.append(f" [#1e3a5f]{'─' * 72}[/#1e3a5f]")
        lines.append(f"   [#3a5570]{'Type':<11}{'Line':<7}{'Pick':<7}{'Prob':<6}{'Edge':<8}{'Tier':<5}{'ELO%':<6}[/#3a5570]")

        for (away, home), preds in by_game.items():
            n_games += 1
            # Best tier for this game (drives the game header color)
            best_tier = min(
                ((p.get("confidence_tier") or "PASS").upper() for p in preds),
                key=lambda t: _TIER_RANK.get(t, 9),
            )
            hc = _TIER_COLORS.get(best_tier, "#c8d8e8") if best_tier != "PASS" else "#c8d8e8"

            # ELO annotation: elo_win_prob is home team's probability
            elo_prob = next((p.get("elo_win_prob") for p in preds if p.get("elo_win_prob") is not None), None)
            if elo_prob is not None:
                h_pct = int(round(elo_prob * 100))
                a_pct = 100 - h_pct
                # Highlight the ELO favorite in yellow
                if h_pct >= 50:
                    elo_ann = (
                        f"  [dim]{away} {a_pct}%[/dim]"
                        f"  [bold #ffd600]{home} {h_pct}%*[/bold #ffd600]"
                    )
                else:
                    elo_ann = (
                        f"  [bold #ffd600]{away} {a_pct}%*[/bold #ffd600]"
                        f"  [dim]{home} {h_pct}%[/dim]"
                    )
            else:
                elo_ann = ""
            lines.append(f"  [{hc}]{away} @ {home}[/{hc}]{elo_ann}")

            for p in preds:
                bet_type = (p.get("bet_type") or "total").upper()
                pred     = (p.get("prediction") or "").upper()
                prob     = p.get("probability")
                edge     = p.get("edge")
                tier     = (p.get("confidence_tier") or "PASS").upper()
                line_val = p.get("line")
                row_elo  = p.get("elo_win_prob")

                tc      = _TIER_COLORS.get(tier, "#c8d8e8")
                tier_ch = _TIER_ABBREV.get(tier, "?")
                line_str = f"{line_val:.1f}" if line_val is not None else " -- "
                elo_str  = f"{row_elo * 100:.0f}%" if row_elo else "  -- "

                # Resolve which team is being picked
                # MONEYLINE: WIN = home wins, LOSE = away wins
                # SPREAD: positive line = away team's spread, negative = home team's spread
                if bet_type == "MONEYLINE":
                    if pred in ("WIN", "HOME"):
                        pick_label = home[:4].upper()
                        arrow = "^"
                    elif pred in ("LOSE", "AWAY"):
                        pick_label = away[:4].upper()
                        arrow = "v"
                    else:
                        pick_label = pred
                        arrow = " "
                elif bet_type == "SPREAD":
                    if line_val is not None and line_val > 0:
                        team = away  # away team gets the + points (underdog)
                    else:
                        team = home  # home team lays the - points (favorite)
                    pick_label = team[:4].upper()
                    arrow = "^" if pred == "WIN" else "v" if pred == "LOSE" else " "
                else:
                    # TOTAL: keep OVER/UNDER
                    pick_label = pred
                    arrow = "^" if pred == "OVER" else "v" if pred == "UNDER" else " "

                if tier == "PASS":
                    lines.append(
                        f"   [dim]  {bet_type:<11}{line_str:<7}{arrow} {pick_label:<6}"
                        f"{_fmt_prob(prob):<6}{_fmt_edge(edge):<8}{tier_ch:<5}{elo_str}[/dim]"
                    )
                else:
                    n_strong += 1
                    lines.append(
                        f"   [{tc}]  {bet_type:<11}{line_str:<7}{arrow} {pick_label:<6}"
                        f"{_fmt_prob(prob):<6}{_fmt_edge(edge):<8}{tier_ch:<5}{elo_str}[/{tc}]"
                    )
            lines.append("")
        lines.append("")

    if not lines:
        return [" [#3a5570]No game predictions for today.[/#3a5570]",
                " [dim]Predictions generate overnight before games.[/dim]"]

    header = [
        f"\n [dim]{today}  |  {n_games} games  |  {n_strong} actionable picks[/dim]",
        f" [bold #ffa500]GAME LINE PREDICTIONS[/bold #ffa500]"
        + (f"  [dim][{sport_filter}][/dim]" if sport_filter else ""),
        "",
    ]
    return header + lines


# ── Widget ────────────────────────────────────────────────────────────────────

class GamePredView(Widget):
    """Game-line predictions panel — center column, toggled with 'g'."""

    can_focus = True

    DEFAULT_CSS = """
    GamePredView {
        width: 60%;
        border: solid #1e3a5f;
    }
    #game-pred-title {
        background: #0d1b2a;
        color: #00c853;
        text-style: bold;
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    #game-pred-body {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
        color: #c8d8e8;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._all_lines:     list = []
        self._scroll_offset: int  = 0
        self._sport_filter:  str  = ""

    def compose(self) -> ComposeResult:
        yield Label(
            " GAME PREDS  [dim][g] back  [j/k] scroll  [PgDn/PgUp] page  [1-3] sport[/dim]",
            id="game-pred-title",
        )
        yield Static("Loading...", id="game-pred-body", markup=True)

    def on_mount(self) -> None:
        self._reload()
        self.set_interval(300.0, self._reload)  # re-read DBs every 5 min

    def on_show(self) -> None:
        self._scroll_offset = 0
        self._reload()
        self.focus()

    def on_key(self, event) -> None:
        key     = event.key
        max_off = max(0, len(self._all_lines) - 5)
        if key == "j":
            self._scroll_offset = min(self._scroll_offset + 3, max_off)
            self._redraw(); event.stop()
        elif key == "k":
            self._scroll_offset = max(0, self._scroll_offset - 3)
            self._redraw(); event.stop()
        elif key == "page_down":
            self._scroll_offset = min(self._scroll_offset + 20, max_off)
            self._redraw(); event.stop()
        elif key == "page_up":
            self._scroll_offset = max(0, self._scroll_offset - 20)
            self._redraw(); event.stop()

    def set_sport_filter(self, sport: str) -> None:
        self._sport_filter  = sport.upper()
        self._scroll_offset = 0
        self._reload()

    def _reload(self) -> None:
        self._all_lines     = _render_all(self._sport_filter)
        self._scroll_offset = 0
        self._redraw()

    def _redraw(self) -> None:
        shown = self._all_lines[self._scroll_offset:]
        try:
            self.query_one("#game-pred-body", Static).update("\n".join(shown))
        except Exception:
            pass
