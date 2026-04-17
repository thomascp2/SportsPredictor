"""
PEGASUS/pipeline/mlb_game_context.py

MLB game-level context advisory layer.

Produces an advisory flag for MLB picks based on:
  1. Park factors — static lookup by venue (affects HR, hits, Ks)
  2. Wind — live from game_context table (mainly HR prop)
  3. Vegas game total (O/U) — proxy for pace/scoring environment

This is advisory only — never modifies probability, edge, or tier.
Attaches to PEGASUSPick as game_context_flag + game_context_notes.

Data sources (read-only):
  mlb/database/mlb_predictions.db  →  game_context, player_game_logs
  (opposing_pitcher_hand column exists but is empty — not used)

Flags returned:
  HR_BOOST         — favorable park + outbound wind for home_runs prop
  HR_SUPPRESS      — pitcher's park or dome suppresses HR
  HITTER_PARK      – generally favorable for hits/TB props
  PITCHER_PARK     — generally unfavorable for hits/TB props
  HIGH_TOTAL       — game O/U ≥ 9.5 (high-scoring environment expected)
  LOW_TOTAL        — game O/U ≤ 7.0 (pitching-heavy game expected)
  NEUTRAL          — no strong signal
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PEGASUS_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT    = _PEGASUS_ROOT.parent
_MLB_DB       = _REPO_ROOT / "mlb" / "database" / "mlb_predictions.db"

# ---------------------------------------------------------------------------
# Park factor table
# Static factors based on multi-year park-adjusted run environment data.
# Sources: Baseball Reference park factors (3-year avg through 2025).
#
# hr_factor:   >1.0 = HR-friendly, <1.0 = HR-suppressing
# hit_factor:  >1.0 = hit-friendly (helps hits/TB props)
# k_factor:    >1.0 = more strikeouts expected (helps K props for pitchers)
# is_dome:     True = weather irrelevant, wind never applies
# ---------------------------------------------------------------------------

PARK_FACTORS: dict[str, dict] = {
    # HR-friendly / hitter parks
    "Coors Field":                          {"hr": 1.35, "hit": 1.14, "k": 0.92, "dome": False},
    "Great American Ball Park":             {"hr": 1.22, "hit": 1.06, "k": 1.00, "dome": False},
    "Citizens Bank Park":                   {"hr": 1.18, "hit": 1.05, "k": 1.01, "dome": False},
    "Fenway Park":                          {"hr": 1.08, "hit": 1.10, "k": 0.97, "dome": False},
    "Yankee Stadium":                       {"hr": 1.17, "hit": 1.02, "k": 1.00, "dome": False},
    "Globe Life Field":                     {"hr": 1.10, "hit": 1.03, "k": 1.00, "dome": True},  # retractable
    "Truist Park":                          {"hr": 1.10, "hit": 1.02, "k": 1.01, "dome": False},
    "Chase Field":                          {"hr": 1.07, "hit": 1.04, "k": 0.99, "dome": True},  # retractable
    "Wrigley Field":                        {"hr": 1.08, "hit": 1.05, "k": 0.97, "dome": False},
    "Kauffman Stadium":                     {"hr": 1.04, "hit": 1.02, "k": 0.98, "dome": False},
    "Target Field":                         {"hr": 1.03, "hit": 1.01, "k": 1.00, "dome": False},
    "Camden Yards":                         {"hr": 1.05, "hit": 1.03, "k": 0.99, "dome": False},
    "Oriole Park at Camden Yards":          {"hr": 1.05, "hit": 1.03, "k": 0.99, "dome": False},
    "Angel Stadium":                        {"hr": 1.04, "hit": 1.01, "k": 1.00, "dome": False},
    "Busch Stadium":                        {"hr": 0.99, "hit": 1.00, "k": 1.02, "dome": False},

    # Neutral
    "Guaranteed Rate Field":                {"hr": 1.02, "hit": 1.01, "k": 1.00, "dome": False},
    "American Family Field":                {"hr": 1.01, "hit": 1.00, "k": 1.00, "dome": True},  # retractable
    "Minute Maid Park":                     {"hr": 1.00, "hit": 1.00, "k": 1.01, "dome": True},  # retractable
    "Daikin Park":                          {"hr": 1.00, "hit": 1.00, "k": 1.01, "dome": True},  # was Minute Maid
    "PNC Park":                             {"hr": 0.98, "hit": 1.00, "k": 1.01, "dome": False},
    "T-Mobile Park":                        {"hr": 0.97, "hit": 0.99, "k": 1.02, "dome": True},  # retractable
    "Nationals Park":                       {"hr": 0.99, "hit": 1.00, "k": 1.00, "dome": False},
    "Citi Field":                           {"hr": 0.97, "hit": 0.99, "k": 1.02, "dome": False},
    "Progressive Field":                    {"hr": 0.98, "hit": 0.99, "k": 1.01, "dome": False},

    # Pitcher-friendly / HR-suppressing
    "Oracle Park":                          {"hr": 0.76, "hit": 0.94, "k": 1.04, "dome": False},
    "Petco Park":                           {"hr": 0.83, "hit": 0.95, "k": 1.04, "dome": False},
    "Dodger Stadium":                       {"hr": 0.88, "hit": 0.97, "k": 1.03, "dome": False},
    "UNIQLO Field at Dodger Stadium":       {"hr": 0.88, "hit": 0.97, "k": 1.03, "dome": False},
    "loanDepot park":                       {"hr": 0.85, "hit": 0.95, "k": 1.05, "dome": True},
    "Comerica Park":                        {"hr": 0.87, "hit": 0.97, "k": 1.03, "dome": False},
    "Rogers Centre":                        {"hr": 0.96, "hit": 1.00, "k": 1.01, "dome": True},
    "Sutter Health Park":                   {"hr": 0.95, "hit": 0.98, "k": 1.01, "dome": False},  # Athletics temp
}

# Wind directions that blow toward outfield (favor HR)
_WIND_OUT_TOKENS = {"out", "out to cf", "out to lf", "out to rf", "out to center",
                    "out to left", "out to right", "l-r", "r-l"}

# Wind directions that blow in from outfield (suppress HR)
_WIND_IN_TOKENS  = {"in", "in from cf", "in from lf", "in from rf", "in from center",
                    "in from left", "in from right"}


# ---------------------------------------------------------------------------
# Game context DB cache — one query per (game_date, opponent) pair per run
# ---------------------------------------------------------------------------

_game_ctx_cache: dict[tuple, Optional[dict]] = {}


def _fetch_game_context(game_date: str, opponent: str) -> Optional[dict]:
    """
    Look up game_context row for a given date and either team.

    Returns dict with keys: venue, game_total, wind_speed, wind_direction, conditions
    or None if not found.
    """
    key = (game_date, opponent)
    if key in _game_ctx_cache:
        return _game_ctx_cache[key]

    result = None
    try:
        conn = sqlite3.connect(f"file:{_MLB_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT venue, game_total, wind_speed, wind_direction, conditions
                FROM game_context
                WHERE game_date = ?
                  AND (home_team = ? OR away_team = ?)
                LIMIT 1
                """,
                [game_date, opponent, opponent],
            ).fetchone()
            if row:
                result = dict(row)
        finally:
            conn.close()
    except Exception as e:
        print(f"[mlb_game_context] Error fetching game_context ({game_date}, {opponent}): {e}")

    _game_ctx_cache[key] = result
    return result


# ---------------------------------------------------------------------------
# Park factor lookup
# ---------------------------------------------------------------------------

def _park_factors(venue: Optional[str]) -> dict:
    """Return park factor dict for a venue name. Falls back to neutral if unknown."""
    if not venue:
        return {"hr": 1.0, "hit": 1.0, "k": 1.0, "dome": False}
    # Try exact match first, then case-insensitive
    if venue in PARK_FACTORS:
        return PARK_FACTORS[venue]
    venue_lower = venue.lower()
    for k, v in PARK_FACTORS.items():
        if k.lower() == venue_lower:
            return v
    # Partial match (handles name changes like "Daikin Park" / "Minute Maid Park")
    for k, v in PARK_FACTORS.items():
        if any(token in venue_lower for token in k.lower().split() if len(token) > 4):
            return v
    return {"hr": 1.0, "hit": 1.0, "k": 1.0, "dome": False}


# ---------------------------------------------------------------------------
# Wind assessment
# ---------------------------------------------------------------------------

def _wind_hr_boost(wind_speed: Optional[int], wind_direction: Optional[str]) -> Optional[bool]:
    """
    Returns True if wind is blowing out (HR boost), False if blowing in (HR suppress),
    None if neutral/calm/dome.
    """
    if not wind_direction or wind_speed is None:
        return None
    if wind_speed < 8:
        return None  # too light to matter

    wd = wind_direction.lower().strip()
    if any(t in wd for t in _WIND_OUT_TOKENS):
        return True
    if any(t in wd for t in _WIND_IN_TOKENS):
        return False
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_game_context(
    player_name: str,
    prop: str,
    game_date: str,
    opponent: str,
) -> tuple[str, str]:
    """
    Return (flag, notes) for a single MLB pick.

    Args:
        player_name: player name (unused currently — reserved for future handedness lookup)
        prop:        prop type string (e.g. "home_runs", "hits", "total_bases", "strikeouts")
        game_date:   YYYY-MM-DD
        opponent:    opponent team abbreviation (used to find the game in game_context)

    Returns:
        (flag: str, notes: str)

    Flags (in priority order, highest wins):
        HR_BOOST      — HR prop + hitter park + outbound wind
        HR_SUPPRESS   — HR prop + pitcher park or inbound wind
        HITTER_PARK   — hits/TB prop + favorable park (hit_factor > 1.08)
        PITCHER_PARK  — hits/TB/K prop + pitcher park (hit_factor < 0.93)
        HIGH_TOTAL    — game O/U >= 9.5 (any prop)
        LOW_TOTAL     — game O/U <= 7.0 (any prop)
        NEUTRAL       — no strong signal
    """
    try:
        ctx = _fetch_game_context(game_date, opponent)
        venue         = ctx.get("venue") if ctx else None
        game_total    = ctx.get("game_total") if ctx else None
        wind_speed    = ctx.get("wind_speed") if ctx else None
        wind_dir      = ctx.get("wind_direction") if ctx else None

        pf = _park_factors(venue)
        is_dome = pf["dome"]

        notes_parts: list[str] = []
        if venue:
            notes_parts.append(venue)

        # ── HR prop logic ───────────────────────────────────────────────────
        if prop == "home_runs":
            wind_boost = None if is_dome else _wind_hr_boost(wind_speed, wind_dir)

            if wind_boost is True and pf["hr"] >= 1.05:
                notes = f"{venue or 'unknown'} (HR factor {pf['hr']:.2f}) + {wind_speed}mph out"
                return ("HR_BOOST", notes)

            if wind_boost is True and pf["hr"] >= 0.95:
                notes = f"{venue or 'unknown'} + {wind_speed}mph out"
                return ("HR_BOOST", notes)

            if pf["hr"] >= 1.15:
                notes = f"{venue or 'unknown'} (HR factor {pf['hr']:.2f})"
                return ("HR_BOOST", notes)

            if wind_boost is False and pf["hr"] <= 1.05:
                notes = f"{venue or 'unknown'} + {wind_speed}mph in"
                return ("HR_SUPPRESS", notes)

            if pf["hr"] <= 0.85:
                notes = f"{venue or 'unknown'} (HR factor {pf['hr']:.2f})"
                return ("HR_SUPPRESS", notes)

        # ── Hits / total_bases prop logic ───────────────────────────────────
        if prop in ("hits", "total_bases"):
            if pf["hit"] >= 1.08:
                notes = f"{venue or 'unknown'} (hit factor {pf['hit']:.2f})"
                return ("HITTER_PARK", notes)
            if pf["hit"] <= 0.93:
                notes = f"{venue or 'unknown'} (hit factor {pf['hit']:.2f})"
                return ("PITCHER_PARK", notes)

        # ── Strikeouts prop logic (for pitchers) ────────────────────────────
        if prop in ("strikeouts", "outs_recorded"):
            if pf["k"] >= 1.04:
                notes = f"{venue or 'unknown'} (K factor {pf['k']:.2f})"
                return ("PITCHER_PARK", notes)

        # ── Game total — applies to all props ───────────────────────────────
        if game_total is not None:
            if game_total >= 9.5:
                notes = f"O/U {game_total}"
                return ("HIGH_TOTAL", notes)
            if game_total <= 7.0:
                notes = f"O/U {game_total}"
                return ("LOW_TOTAL", notes)

        return ("NEUTRAL", venue or "")

    except Exception as e:
        print(f"[mlb_game_context] Error for {player_name} {prop} {game_date}: {e}")
        return ("NEUTRAL", "")
