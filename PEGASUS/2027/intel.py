"""
PEGASUS Situational Intelligence Engine — 2027 Edition

Forked from situational/intel.py (Session 3, 2026-04-15).
Extended for calendar year 2027 use cases:
  - NBA second half of season (Jan–Apr 2027): stretch run + playoffs
  - NHL second half of season (Jan–Apr 2027): stretch run + playoffs
  - MLB full 2027 season (March–October): all 162 games, including stretch run Aug–Oct

KEY ADDITION vs. 2026 version:
  Layer 2 — Minutes Deviation Signal
  ────────────────────────────────────
  The 2026 version used only standings position to score motivation.
  The 2027 version adds a second signal derived from player_game_logs:

      deviation = avg_minutes_last_5 - avg_minutes_season

  This detects coach behavioural change INDEPENDENT of standings:
    deviation >= +4  → coach leaning on this player hard → ELEVATION of stakes
    deviation <= -4  → load management / rest mode → REDUCTION of stakes

  This matters most during the "stretch run" window (last ~15-20 games) where
  teams in contention change their rotation before the standings fully reflect it.
  It is sport-agnostic and works for MLB (position player rest-day patterns) too.

  See: get_minutes_deviation() and the blended motivation in get_situation()

ADVISORY ONLY — this module NEVER modifies probability, ai_edge, or tier
stored anywhere. All output fields (situation_flag, situation_modifier,
situation_notes) are display-only.

Data sources:
  NBA:  ESPN standings API — site.api.espn.com (season param: 2027)
  NHL:  NHL official API — api-web.nhle.com/v1/standings/now
  MLB:  ESPN standings API — site.api.espn.com/apis/v2/sports/baseball/mlb/standings
        (active from late August; NORMAL placeholder before that)
  Minutes deviation: player_game_logs in each sport's SQLite DB (read-only)

Fallback: when API unavailable → situation_flag=NORMAL, modifier=0.0, notes=''

Design decisions carried forward from 2026 (see bookmark-03.md for full list):
  1. No Grok dependency — algorithmic motivation from structured API data only
  2. games_remaining=0 + clinched + rank ≤ 8 → playoffs in progress → HIGH_STAKES
  3. ESPN clincher is numeric — read displayValue, not value
  4. games_remaining = 82 - (wins + losses) for NBA; from gamesPlayed for NHL
  5. None-guard for games_remaining (0 is falsy, `0 or 10` = 10 — fixed)
  6. File cache per (sport, date) + in-process dict cache
"""

import json
import sqlite3
import time
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# ── Path resolution — 2027/ is one level deeper than situational/ ────────────
# PEGASUS root = parent of parent of this file
_HERE = Path(__file__).parent          # PEGASUS/2027/
PEGASUS_ROOT = _HERE.parent            # PEGASUS/
PROJECT_ROOT  = PEGASUS_ROOT.parent    # SportsPredictor/

NHL_DB = PROJECT_ROOT / "nhl" / "database" / "nhl_predictions_v2.db"
NBA_DB = PROJECT_ROOT / "nba" / "database" / "nba_predictions.db"
MLB_DB = PROJECT_ROOT / "mlb" / "database" / "mlb_predictions.db"

# Import flags from the existing situational package
import sys
sys.path.insert(0, str(PROJECT_ROOT))
from PEGASUS.situational.flags import SituationFlag, flag_from_motivation, get_modifier

# ── Cache directory ───────────────────────────────────────────────────────────
CACHE_DIR = PEGASUS_ROOT / "data" / "situational_cache_2027"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── HTTP session ──────────────────────────────────────────────────────────────
_SESSION = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; SportsPredictor/1.0)",
            "Accept": "application/json",
        })
    return _SESSION


def _safe_get(url: str, params: Optional[Dict] = None, timeout: int = 10) -> Optional[Dict]:
    """GET with retry + graceful fallback on any error."""
    for attempt in range(3):
        try:
            resp = _get_session().get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            if attempt == 2:
                print(f"  [INTEL-2027] API error ({url}): {exc}")
                return None
            time.sleep(1.5 ** attempt)
    return None


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _standings_cache_path(sport: str, game_date: str) -> Path:
    return CACHE_DIR / f"{sport}_{game_date}_standings.json"


def _load_cache(path: Path) -> Optional[Dict]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_cache(path: Path, data: Dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"  [INTEL-2027] Cache write failed ({path.name}): {exc}")


# ── Default (safe) output ─────────────────────────────────────────────────────

NORMAL_RESULT: Tuple[SituationFlag, float, str] = (SituationFlag.NORMAL, 0.0, "")


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2 — Minutes Deviation Signal (NEW in 2027 version)
# ═══════════════════════════════════════════════════════════════════════════════

# Thresholds for deviation to trigger motivation adjustment
DEVIATION_ELEVATION_THRESHOLD = +4.0   # min/game above season avg → coach leaning hard
DEVIATION_REDUCTION_THRESHOLD = -4.0   # min/game below season avg → rest/load management

# How many recent games to use for "recent average"
DEVIATION_RECENT_GAMES = 5

# Minimum season games to consider the season average reliable
DEVIATION_MIN_SEASON_GAMES = 15


def get_minutes_deviation(
    player_name: str,
    team: str,
    sport: str,
) -> Optional[float]:
    """
    Compute: avg_minutes_last_5 - avg_minutes_season for a player.

    Positive = coach playing them MORE than usual → high stakes signal
    Negative = coach resting them more than usual → load management signal

    Returns None if insufficient data or DB unavailable.

    Args:
        player_name:  Exact player name as stored in player_game_logs
        team:         Team abbreviation
        sport:        "nba" | "nhl" | "mlb"

    Data source: player_game_logs (read-only SQLite)
    """
    db_path = {"nba": NBA_DB, "nhl": NHL_DB, "mlb": MLB_DB}.get(sport.lower())
    if not db_path or not Path(db_path).exists():
        return None

    minutes_col = {
        "nba": "minutes_played",
        "nhl": "toi",           # time on ice in minutes
        "mlb": "pa",            # plate appearances (proxy for "did they play a full game")
    }.get(sport.lower())

    if not minutes_col:
        return None

    try:
        conn = sqlite3.connect(str(db_path))
        cur  = conn.cursor()

        # Season average (all games this season for this player)
        cur.execute(f"""
            SELECT AVG({minutes_col}), COUNT(*)
            FROM player_game_logs
            WHERE player_name = ? AND team = ?
        """, (player_name, team.upper()))
        row = cur.fetchone()
        if not row or row[1] < DEVIATION_MIN_SEASON_GAMES:
            conn.close()
            return None
        season_avg = row[0]
        if season_avg is None:
            conn.close()
            return None

        # Recent average (last DEVIATION_RECENT_GAMES games)
        cur.execute(f"""
            SELECT AVG({minutes_col})
            FROM (
                SELECT {minutes_col}
                FROM player_game_logs
                WHERE player_name = ? AND team = ?
                ORDER BY game_date DESC
                LIMIT {DEVIATION_RECENT_GAMES}
            )
        """, (player_name, team.upper()))
        row2 = cur.fetchone()
        conn.close()

        if not row2 or row2[0] is None:
            return None

        recent_avg = row2[0]
        deviation  = recent_avg - season_avg
        return round(deviation, 2)

    except Exception as exc:
        print(f"  [INTEL-2027] Minutes deviation query failed ({sport} {player_name}): {exc}")
        return None


def _apply_deviation_to_motivation(base_motivation: float, deviation: Optional[float]) -> float:
    """
    Blend the standing-based motivation score with the minutes deviation signal.

    If deviation is None (not enough data), return base_motivation unchanged.

    Blending logic:
      - Strong elevation (deviation >= +4): nudge motivation toward HIGH_STAKES
      - Strong reduction (deviation <= -4): nudge motivation toward DEAD_RUBBER
      - Magnitude of nudge is capped at ±0.15 so standings remain the primary signal

    This ensures that a bubble team whose stars are suddenly playing 40 min
    gets flagged correctly even if the standings gap hasn't fully closed yet.
    And a clinched team whose stars are being rested (deviation = -6) gets
    properly flagged as DEAD_RUBBER even if standings say "fighting for seeding."
    """
    if deviation is None:
        return base_motivation

    if deviation >= DEVIATION_ELEVATION_THRESHOLD:
        # Positive deviation: coach leaning hard → raise motivation toward urgency
        nudge = min(0.15, (deviation - DEVIATION_ELEVATION_THRESHOLD) * 0.025)
        return min(1.0, base_motivation + nudge)

    elif deviation <= DEVIATION_REDUCTION_THRESHOLD:
        # Negative deviation: rest mode → lower motivation toward dead rubber
        nudge = min(0.15, abs(deviation - DEVIATION_REDUCTION_THRESHOLD) * 0.025)
        return max(0.05, base_motivation - nudge)

    return base_motivation


def get_team_minutes_deviation_summary(
    team: str,
    sport: str,
    top_n: int = 8,
) -> Dict[str, float]:
    """
    Return {player_name: deviation} for the top_n minute leaders on a team.
    Used by pick_selector to check multiple players at once.
    Returns empty dict if DB unavailable.
    """
    db_path = {"nba": NBA_DB, "nhl": NHL_DB, "mlb": MLB_DB}.get(sport.lower())
    if not db_path or not Path(db_path).exists():
        return {}

    minutes_col = {"nba": "minutes_played", "nhl": "toi", "mlb": "pa"}.get(sport.lower())
    if not minutes_col:
        return {}

    try:
        conn = sqlite3.connect(str(db_path))
        cur  = conn.cursor()

        # Get the team's top-N players by season avg minutes
        cur.execute(f"""
            SELECT player_name, AVG({minutes_col}) AS season_avg, COUNT(*) AS games
            FROM player_game_logs
            WHERE team = ?
            GROUP BY player_name
            HAVING games >= {DEVIATION_MIN_SEASON_GAMES}
            ORDER BY season_avg DESC
            LIMIT {top_n}
        """, (team.upper(),))
        season_rows = cur.fetchall()

        result = {}
        for player_name, season_avg, _ in season_rows:
            if season_avg is None:
                continue
            cur.execute(f"""
                SELECT AVG({minutes_col})
                FROM (
                    SELECT {minutes_col}
                    FROM player_game_logs
                    WHERE player_name = ? AND team = ?
                    ORDER BY game_date DESC
                    LIMIT {DEVIATION_RECENT_GAMES}
                )
            """, (player_name, team.upper()))
            row = cur.fetchone()
            if row and row[0] is not None:
                result[player_name] = round(row[0] - season_avg, 2)

        conn.close()
        return result

    except Exception as exc:
        print(f"  [INTEL-2027] Team deviation summary failed ({sport} {team}): {exc}")
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# NBA — ESPN standings
# ═══════════════════════════════════════════════════════════════════════════════

ESPN_NBA_STANDINGS = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"

NBA_ABBREV_MAP = {
    "NY": "NYK", "NYK": "NYK", "NO": "NOP", "NOP": "NOP",
    "GS": "GSW", "GSW": "GSW", "SA": "SAS", "SAS": "SAS",
    "UTAH": "UTA", "UTA": "UTA", "PHO": "PHX", "PHX": "PHX",
    "WSH": "WAS", "WAS": "WAS",
}


def _normalize_nba_abbrev(raw: str) -> str:
    raw = (raw or "").upper().strip()
    return NBA_ABBREV_MAP.get(raw, raw)


def _fetch_nba_standings(game_date: str) -> Dict[str, Dict]:
    """Fetch NBA standings from ESPN (2027 season param)."""
    cache_path = _standings_cache_path("nba", game_date)
    cached = _load_cache(cache_path)
    if cached:
        return cached

    # 2027 season = "2027" (ESPN uses the year the season ends)
    data = _safe_get(ESPN_NBA_STANDINGS, params={"season": "2027", "seasontype": "2"})
    if not data:
        return {}

    result: Dict[str, Dict] = {}
    try:
        groups = data.get("children", []) or data.get("standings", {}).get("groups", [])
        for group in groups:
            for entry in group.get("standings", {}).get("entries", []):
                team_info = entry.get("team", {})
                raw_abbr  = team_info.get("abbreviation", "")
                abbr      = _normalize_nba_abbrev(raw_abbr)

                stats = {s["name"]: s.get("value") for s in entry.get("stats", []) if "name" in s}

                wins       = int(stats.get("wins", 0) or 0)
                losses     = int(stats.get("losses", 0) or 0)
                games_back = float(stats.get("gamesBehind", 0) or 0)
                conf_rank  = int(stats.get("playoffSeed", stats.get("rank", 99)) or 99)

                clinch_display = ""
                elim_display   = ""
                for s in entry.get("stats", []):
                    name = s.get("name", "")
                    if name == "clincher":
                        clinch_display = str(s.get("displayValue", "") or "").lower()
                    elif name == "eliminationNumber":
                        elim_display = str(s.get("displayValue", "") or "").lower()

                games_played    = wins + losses
                games_remaining = max(0, 82 - games_played)

                clinched_playoffs = clinch_display in ("x", "y", "z", "p") or conf_rank <= 6
                eliminated        = elim_display in ("0", "e") or clinch_display == "e"

                result[abbr] = {
                    "wins": wins, "losses": losses, "games_back": games_back,
                    "conference_rank": conf_rank, "games_remaining": games_remaining,
                    "clinched_playoffs": clinched_playoffs, "eliminated": eliminated,
                    "espn_team": raw_abbr,
                }
    except Exception as exc:
        print(f"  [INTEL-2027] NBA standings parse error: {exc}")
        return {}

    _save_cache(cache_path, result)
    print(f"  [INTEL-2027] NBA standings loaded: {len(result)} teams")
    return result


def _nba_motivation_score(team_info: Dict) -> float:
    """
    Standings-only motivation score. Combined with minutes deviation in get_situation().

    Stretch-run window (last ~15 games) is where this matters most:
      - Bubble teams not yet mathematically clinched but close → 0.85
      - Clinched but seed moveable → 0.50
      - games_remaining=0 + clinched = playoffs in progress → 1.00
    """
    if not team_info:
        return 0.60

    rank     = team_info.get("conference_rank", 99)
    gb_raw   = team_info.get("games_back")
    gb       = float(gb_raw if gb_raw is not None else 0)
    left_raw = team_info.get("games_remaining")
    left     = int(left_raw if left_raw is not None else 10)
    clinched = bool(team_info.get("clinched_playoffs", False))
    elim     = bool(team_info.get("eliminated", False))

    if elim:
        return 0.10

    # Playoffs active (regular season over)
    if left == 0:
        if rank <= 8 and clinched:
            return 1.00
        if rank in (9, 10):
            return 1.00   # play-in game
        if rank > 10 and not clinched:
            return 0.10

    # Deep out of play-in contention
    if rank > 10 and gb >= 3 and left <= 5:
        return 0.10

    # Seed locked (can't move)
    if clinched and gb == 0 and left <= 4:
        return 0.20

    # Clinched but seed moveable
    if clinched and rank <= 6:
        return 0.50

    # Play-in zone — stretch run urgency
    if rank in (9, 10) and left <= 8:
        return 0.90

    # Seeding battle
    if clinched and rank <= 8 and gb <= 2 and left <= 6:
        return 0.75

    # Stretch run: bubble team still fighting
    if not clinched and rank <= 12 and left <= 15:
        return 0.85

    # Mid-season contender (L2 signal will refine)
    return 0.70


def _nba_stakes_notes(abbr: str, team_info: Dict, deviation: Optional[float] = None) -> str:
    rank = team_info.get("conference_rank", "?")
    left = team_info.get("games_remaining", "?")
    elim = team_info.get("eliminated", False)
    clin = team_info.get("clinched_playoffs", False)
    gb   = team_info.get("games_back", 0)

    parts = [abbr.upper()]
    if elim:
        parts.append("eliminated")
    elif clin and isinstance(rank, int) and rank <= 8:
        parts.append(f"{rank}-seed clinched")
    elif rank in (9, 10):
        parts.append(f"{rank}-seed play-in")
    else:
        parts.append(f"{rank}-seed")

    if left and not elim:
        parts.append(f"{left} games left")
    if gb and not elim and not clin:
        parts.append(f"{gb:.1f} GB")

    if deviation is not None:
        if deviation >= DEVIATION_ELEVATION_THRESHOLD:
            parts.append(f"mins +{deviation:.1f} vs avg (coach leaning hard)")
        elif deviation <= DEVIATION_REDUCTION_THRESHOLD:
            parts.append(f"mins {deviation:.1f} vs avg (load management)")

    return " | ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# NHL — NHL official API standings
# ═══════════════════════════════════════════════════════════════════════════════

NHL_STANDINGS_URL = "https://api-web.nhle.com/v1/standings/now"

NHL_ABBREV_MAP = {
    "TB": "TBL", "NJ": "NJD", "SJ": "SJS", "LA": "LAK",
    "VGK": "VGK", "LV": "VGK",
}


def _normalize_nhl_abbrev(raw: str) -> str:
    raw = (raw or "").upper().strip()
    return NHL_ABBREV_MAP.get(raw, raw)


def _fetch_nhl_standings(game_date: str) -> Dict[str, Dict]:
    """Fetch NHL standings from api-web.nhle.com/v1/standings/now."""
    cache_path = _standings_cache_path("nhl", game_date)
    cached = _load_cache(cache_path)
    if cached:
        return cached

    data = _safe_get(NHL_STANDINGS_URL)
    if not data:
        return {}

    result: Dict[str, Dict] = {}
    try:
        for entry in data.get("standings", []):
            raw_abbr = entry.get("teamAbbrev", {})
            if isinstance(raw_abbr, dict):
                raw_abbr = raw_abbr.get("default", "")
            abbr = _normalize_nhl_abbrev(str(raw_abbr))

            wins            = int(entry.get("wins", 0) or 0)
            losses          = int(entry.get("losses", 0) or 0)
            ot_losses       = int(entry.get("otLosses", 0) or 0)
            points          = int(entry.get("points", 0) or 0)
            games_played    = int(entry.get("gamesPlayed", 0) or 0)
            games_remaining = max(0, 82 - games_played)

            clinch_indicator  = str(entry.get("clinchIndicator", "") or "")
            div_seq           = int(entry.get("divisionSequence", 99) or 99)
            wc_seq            = int(entry.get("wildcardSequence", 99) or 99)
            clinched_playoffs = clinch_indicator.lower() in ("x", "y", "z", "p")
            eliminated        = clinch_indicator.lower() == "e"

            result[abbr] = {
                "wins": wins, "losses": losses, "ot_losses": ot_losses,
                "points": points, "games_remaining": games_remaining,
                "division_sequence": div_seq, "wildcard_sequence": wc_seq,
                "clinch_indicator": clinch_indicator,
                "clinched_playoffs": clinched_playoffs, "eliminated": eliminated,
            }
    except Exception as exc:
        print(f"  [INTEL-2027] NHL standings parse error: {exc}")
        return {}

    _save_cache(cache_path, result)
    print(f"  [INTEL-2027] NHL standings loaded: {len(result)} teams")
    return result


def _nhl_motivation_score(team_info: Dict) -> float:
    """
    Standings-only motivation. Layer 2 deviation applied in get_situation().

    Stretch run for NHL is ~last 10 games (82-game season).
    Wild card races are tightest here — a team 2 points back with 5 games left
    is at maximum urgency regardless of their division rank.
    """
    if not team_info:
        return 0.60

    clinched = bool(team_info.get("clinched_playoffs", False))
    elim     = bool(team_info.get("eliminated", False))
    div_seq  = int(team_info.get("division_sequence", 99) or 99)
    wc_seq   = int(team_info.get("wildcard_sequence", 99) or 99)
    left_raw = team_info.get("games_remaining")
    left     = int(left_raw if left_raw is not None else 8)

    if elim:
        return 0.10

    # Playoffs in progress (regular season over, team clinched)
    if left == 0 and clinched:
        return 1.00
    if left == 0 and not clinched and not elim:
        return 0.10   # Season ended, missed playoffs

    # Division leader / Presidents' Trophy — likely coasting
    if clinched and div_seq == 1 and left <= 5:
        return 0.20

    # Clinched but seed still moveable
    if clinched:
        return 0.45

    # Tight wild card race (stretch run)
    if not clinched and wc_seq <= 2 and left <= 10:
        return 0.90

    # On the bubble
    if not clinched and wc_seq <= 4 and left <= 12:
        return 0.85

    # General contender (L2 signal will refine)
    return 0.65


def _nhl_stakes_notes(abbr: str, team_info: Dict, deviation: Optional[float] = None) -> str:
    elim = team_info.get("eliminated", False)
    clin = team_info.get("clinched_playoffs", False)
    left = team_info.get("games_remaining", "?")
    pts  = team_info.get("points", "?")
    div  = team_info.get("division_sequence", "?")
    wc   = team_info.get("wildcard_sequence", "?")
    ci   = team_info.get("clinch_indicator", "")

    parts = [abbr.upper()]
    if elim:
        parts.append("eliminated")
    elif clin:
        parts.append(f"clinched ({ci.upper()})")
        if div != "?":
            parts.append(f"div-{div}")
    else:
        if isinstance(wc, int) and wc <= 4:
            parts.append(f"WC{wc}")
        parts.append(f"{pts} pts")

    if left:
        parts.append(f"{left} games left")

    if deviation is not None:
        if deviation >= DEVIATION_ELEVATION_THRESHOLD:
            parts.append(f"TOI +{deviation:.1f} vs avg")
        elif deviation <= DEVIATION_REDUCTION_THRESHOLD:
            parts.append(f"TOI {deviation:.1f} vs avg (resting)")

    return " | ".join(str(p) for p in parts)


# ═══════════════════════════════════════════════════════════════════════════════
# MLB — active from late August; NORMAL placeholder before that
# ═══════════════════════════════════════════════════════════════════════════════

ESPN_MLB_STANDINGS = "https://site.api.espn.com/apis/v2/sports/baseball/mlb/standings"

MLB_ABBREV_MAP = {
    "WSH": "WSN", "WSN": "WSN", "SF": "SFG", "SFG": "SFG",
    "SD": "SDP", "SDP": "SDP", "TB": "TBR", "TBR": "TBR",
    "KC": "KCR", "KCR": "KCR", "CWS": "CWS", "CHW": "CWS",
    "ARI": "ARI", "AZ": "ARI",
}

# MLB has 162 regular season games
MLB_SEASON_GAMES = 162

# Only activate standings-based flags after this many games remain
# Before this threshold → NORMAL for everyone (early/mid season)
MLB_STAKES_WINDOW_GAMES = 35


def _normalize_mlb_abbrev(raw: str) -> str:
    raw = (raw or "").upper().strip()
    return MLB_ABBREV_MAP.get(raw, raw)


def _fetch_mlb_standings(game_date: str) -> Dict[str, Dict]:
    """
    Fetch MLB standings from ESPN.

    Returns NORMAL (empty dict) before the last MLB_STAKES_WINDOW_GAMES games.
    Active from late August onward.

    Note: pitcher rotation is FIXED (every 5 days) regardless of standings.
    The situational signal for MLB is primarily:
      1. Position player rest-day patterns (detected via PA deviation in Layer 2)
      2. Team stakes score (standings-based, active only in stretch run)
    """
    cache_path = _standings_cache_path("mlb", game_date)
    cached = _load_cache(cache_path)
    if cached:
        return cached

    # Determine rough games remaining from date — MLB season ends ~Sep 28
    try:
        d = datetime.strptime(game_date, "%Y-%m-%d").date()
        # Rough season end for 2027
        season_end = date(2027, 9, 28)
        days_left  = max(0, (season_end - d).days)
        # ~0.875 games/day (162 games / 185 day season)
        approx_games_left = int(days_left * 0.875)
        if approx_games_left > MLB_STAKES_WINDOW_GAMES:
            # Too early — no meaningful standings signal yet
            return {}
    except ValueError:
        return {}

    data = _safe_get(ESPN_MLB_STANDINGS, params={"season": "2027", "seasontype": "2"})
    if not data:
        return {}

    result: Dict[str, Dict] = {}
    try:
        groups = data.get("children", []) or data.get("standings", {}).get("groups", [])
        for group in groups:
            for entry in group.get("standings", {}).get("entries", []):
                team_info = entry.get("team", {})
                raw_abbr  = team_info.get("abbreviation", "")
                abbr      = _normalize_mlb_abbrev(raw_abbr)

                stats = {s["name"]: s.get("value") for s in entry.get("stats", []) if "name" in s}

                wins         = int(stats.get("wins", 0) or 0)
                losses       = int(stats.get("losses", 0) or 0)
                games_back   = float(stats.get("gamesBehind", 0) or 0)
                div_rank     = int(stats.get("divisionRank", stats.get("rank", 99)) or 99)

                games_played    = wins + losses
                games_remaining = max(0, MLB_SEASON_GAMES - games_played)

                clinch_display = ""
                elim_display   = ""
                for s in entry.get("stats", []):
                    name = s.get("name", "")
                    if name == "clincher":
                        clinch_display = str(s.get("displayValue", "") or "").lower()
                    elif name == "eliminationNumber":
                        elim_display = str(s.get("displayValue", "") or "").lower()

                clinched_playoffs = clinch_display in ("x", "y", "z", "e", "w") or div_rank == 1
                eliminated        = elim_display in ("0", "e") or clinch_display == "e"

                result[abbr] = {
                    "wins": wins, "losses": losses, "games_back": games_back,
                    "division_rank": div_rank, "games_remaining": games_remaining,
                    "clinched_playoffs": clinched_playoffs, "eliminated": eliminated,
                    "espn_team": raw_abbr,
                }
    except Exception as exc:
        print(f"  [INTEL-2027] MLB standings parse error: {exc}")
        return {}

    _save_cache(cache_path, result)
    print(f"  [INTEL-2027] MLB standings loaded: {len(result)} teams")
    return result


def _mlb_motivation_score(team_info: Dict) -> float:
    """
    MLB motivation score.

    Key MLB nuances (different from NBA/NHL):
      - Pitchers play on fixed rotation — motivation score has NO EFFECT on
        starting pitcher props. Only affects position player usage patterns.
      - Stars often take scheduled rest days mid-season. During playoff hunt,
        these rest days are eliminated — the Layer 2 PA deviation detects this.
      - Wild card races are highly competitive in MLB (3 wild cards per league).
      - Teams clinch divisions but may still chase playoff positioning.

    Empty dict (early season) → always returns 0.60 (NORMAL).
    """
    if not team_info:
        return 0.60   # No standings data = early season = NORMAL

    div_rank = team_info.get("division_rank", 99)
    gb       = float(team_info.get("games_back", 0) or 0)
    left_raw = team_info.get("games_remaining")
    left     = int(left_raw if left_raw is not None else 50)
    clinched = bool(team_info.get("clinched_playoffs", False))
    elim     = bool(team_info.get("eliminated", False))

    if elim:
        return 0.10

    # Playoffs in progress
    if left == 0 and clinched:
        return 1.00

    # Division clinched + seed locked
    if clinched and gb == 0 and left <= 10:
        return 0.25   # Clinched division, coasting into playoffs

    # Clinched but games matter (wild card seeding, home field)
    if clinched:
        return 0.55

    # Wild card stretch run — within 3 GB with < 20 games left
    if not clinched and gb <= 3 and left <= 20:
        return 0.88

    # Bubble — still in contention, mid-stretch
    if not clinched and gb <= 5 and left <= 35:
        return 0.80

    # Mathematically out but early (rare — see stakes window gate above)
    if gb > 15 and left <= 20:
        return 0.15

    return 0.65  # Regular mid-season competition


def _mlb_stakes_notes(abbr: str, team_info: Dict, deviation: Optional[float] = None) -> str:
    if not team_info:
        return ""
    div  = team_info.get("division_rank", "?")
    left = team_info.get("games_remaining", "?")
    gb   = team_info.get("games_back", 0)
    elim = team_info.get("eliminated", False)
    clin = team_info.get("clinched_playoffs", False)

    parts = [abbr.upper()]
    if elim:
        parts.append("eliminated")
    elif clin:
        parts.append(f"div-{div} clinched")
    else:
        parts.append(f"div-{div}")
        if gb:
            parts.append(f"{gb:.1f} GB")

    if left:
        parts.append(f"{left} games left")

    if deviation is not None:
        if deviation >= DEVIATION_ELEVATION_THRESHOLD:
            parts.append(f"PA +{deviation:.1f} vs avg (no rest days)")
        elif deviation <= DEVIATION_REDUCTION_THRESHOLD:
            parts.append(f"PA {deviation:.1f} vs avg (scheduled rest)")

    return " | ".join(str(p) for p in parts)


# ═══════════════════════════════════════════════════════════════════════════════
# Star player USAGE_BOOST detection (carried from 2026)
# ═══════════════════════════════════════════════════════════════════════════════

USAGE_BOOST_THRESHOLD  = 0.75
TOP_N_MINUTE_LEADERS   = 2
USAGE_LOOKBACK_GAMES   = 10


def get_usage_boost_players(
    team: str,
    sport: str,
    game_stakes_score: float,
) -> List[str]:
    """
    Top-N minute leaders on the team when stakes are high enough.
    Unchanged from 2026 version.
    """
    if game_stakes_score < USAGE_BOOST_THRESHOLD:
        return []

    db_path    = {"nba": NBA_DB, "nhl": NHL_DB}.get(sport.lower())
    if not db_path or not Path(db_path).exists():
        return []

    minutes_col = {"nba": "minutes_played", "nhl": "toi"}.get(sport.lower())
    if not minutes_col:
        return []

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(f"""
            SELECT player_name, AVG({minutes_col}) AS avg_min, COUNT(*) AS games
            FROM player_game_logs
            WHERE team = ?
            GROUP BY player_name
            HAVING games >= 3
            ORDER BY avg_min DESC
            LIMIT {TOP_N_MINUTE_LEADERS}
        """, (team.upper(),))
        rows = cur.fetchall()
        conn.close()
        leaders = [row["player_name"] for row in rows if row["avg_min"] is not None]
        if leaders:
            print(f"  [INTEL-2027] USAGE_BOOST leaders for {team}: {', '.join(leaders)}")
        return leaders
    except Exception as exc:
        print(f"  [INTEL-2027] Usage boost query failed ({sport} {team}): {exc}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# Standings registry
# ═══════════════════════════════════════════════════════════════════════════════

_STANDINGS_FETCHERS = {
    "nba": _fetch_nba_standings,
    "nhl": _fetch_nhl_standings,
    "mlb": _fetch_mlb_standings,
}

_MOTIVATION_SCORERS = {
    "nba": _nba_motivation_score,
    "nhl": _nhl_motivation_score,
    "mlb": _mlb_motivation_score,
}

_NOTES_BUILDERS = {
    "nba": _nba_stakes_notes,
    "nhl": _nhl_stakes_notes,
    "mlb": _mlb_stakes_notes,
}

_standings_cache: Dict[Tuple[str, str], Dict[str, Dict]] = {}


def _get_standings(sport: str, game_date: str) -> Dict[str, Dict]:
    key = (sport.lower(), game_date)
    if key not in _standings_cache:
        fetcher = _STANDINGS_FETCHERS.get(sport.lower(), lambda _: {})
        _standings_cache[key] = fetcher(game_date)
    return _standings_cache[key]


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def get_team_stakes(
    team: str,
    sport: str,
    game_date: Optional[str] = None,
) -> Tuple[float, Dict]:
    """Return (motivation_score_standings_only, team_info_dict)."""
    if game_date is None:
        game_date = date.today().isoformat()
    standings = _get_standings(sport, game_date)
    team_info = standings.get(team.upper(), {})
    scorer    = _MOTIVATION_SCORERS.get(sport.lower(), lambda _: 0.60)
    return scorer(team_info), team_info


def get_situation(
    team: str,
    sport: str,
    game_date: Optional[str] = None,
    injury_status: str = "ACTIVE",
    player_name: Optional[str] = None,
    usage_boost_override: bool = False,
) -> Tuple[SituationFlag, float, str]:
    """
    Primary entry point for PEGASUS pick_selector.py (2027).

    Two-layer motivation:
      Layer 1: standings position → base motivation_score
      Layer 2: minutes deviation (L5 vs season avg) → adjust motivation_score

    Args:
        team:                Team abbreviation
        sport:               "nba" | "nhl" | "mlb"
        game_date:           YYYY-MM-DD
        injury_status:       Player status from injury report
        player_name:         Used for L2 deviation + usage boost check
        usage_boost_override: Force USAGE_BOOST (star absence detected upstream)

    Returns:
        (SituationFlag, modifier, notes_str) — advisory only, never written to DB
    """
    if game_date is None:
        game_date = date.today().isoformat()
    sport = sport.lower()

    try:
        base_motivation, team_info = get_team_stakes(team, sport, game_date)
    except Exception as exc:
        print(f"  [INTEL-2027] get_team_stakes failed ({sport} {team}): {exc}")
        return NORMAL_RESULT

    # Layer 2: minutes deviation adjustment
    deviation = None
    if player_name:
        try:
            deviation = get_minutes_deviation(player_name, team, sport)
        except Exception:
            pass

    blended_motivation = _apply_deviation_to_motivation(base_motivation, deviation)

    # Determine flag
    if usage_boost_override:
        flag     = SituationFlag.USAGE_BOOST
        modifier = get_modifier(SituationFlag.USAGE_BOOST, injury_status)
    else:
        flag, modifier = flag_from_motivation(blended_motivation, injury_status)

        # High stakes + minute leader → USAGE_BOOST
        if flag == SituationFlag.HIGH_STAKES and player_name:
            boost_players = get_usage_boost_players(team, sport, blended_motivation)
            if player_name in boost_players:
                flag     = SituationFlag.USAGE_BOOST
                modifier = get_modifier(SituationFlag.USAGE_BOOST, injury_status)

    # Build notes (include deviation if meaningful)
    notes_builder = _NOTES_BUILDERS.get(sport, lambda a, i, **kw: "")
    try:
        base_notes = notes_builder(team, team_info, deviation)
    except TypeError:
        base_notes = notes_builder(team, team_info)

    prefix_map = {
        SituationFlag.USAGE_BOOST:    f"USAGE BOOST: {player_name} | " if player_name else "USAGE BOOST | ",
        SituationFlag.DEAD_RUBBER:    "DEAD RUBBER risk | ",
        SituationFlag.ELIMINATED:     "ELIMINATED — full rest mode | ",
        SituationFlag.HIGH_STAKES:    "HIGH STAKES | ",
        SituationFlag.REDUCED_STAKES: "Reduced stakes | ",
        SituationFlag.NORMAL:         "",
    }
    notes = prefix_map.get(flag, "") + base_notes

    return flag, modifier, notes


def get_team_situation_summary(
    teams: List[str],
    sport: str,
    game_date: Optional[str] = None,
) -> Dict[str, Dict]:
    """Summary dict for a list of teams — used by Situational Analyst agent."""
    if game_date is None:
        game_date = date.today().isoformat()
    sport = sport.lower()
    result: Dict[str, Dict] = {}

    for team in teams:
        try:
            motivation, team_info = get_team_stakes(team, sport, game_date)
            flag, modifier        = flag_from_motivation(motivation)
            notes_builder         = _NOTES_BUILDERS.get(sport, lambda a, i, **kw: "")
            try:
                notes = notes_builder(team.upper(), team_info)
            except TypeError:
                notes = ""
            result[team.upper()] = {
                "motivation_score":  round(motivation, 3),
                "flag":              flag.value,
                "modifier":          modifier,
                "notes":             notes,
                "games_remaining":   team_info.get("games_remaining"),
                "clinched_playoffs": team_info.get("clinched_playoffs", False),
                "eliminated":        team_info.get("eliminated", False),
            }
        except Exception as exc:
            print(f"  [INTEL-2027] Summary failed for {team}: {exc}")
            result[team.upper()] = {
                "motivation_score": 0.60, "flag": SituationFlag.NORMAL.value,
                "modifier": 0.0, "notes": "",
                "games_remaining": None, "clinched_playoffs": False, "eliminated": False,
            }

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# CLI smoke-test
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    sport_arg = sys.argv[1] if len(sys.argv) > 1 else "nba"
    date_arg  = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()

    print(f"\n[INTEL-2027] Smoke test — {sport_arg.upper()} for {date_arg}")
    print("=" * 60)
    standings = _get_standings(sport_arg, date_arg)
    if not standings:
        print("  No data (API down or early-season MLB placeholder).")
        sys.exit(0)

    sample = list(standings.keys())[:6]
    summary = get_team_situation_summary(sample, sport_arg, date_arg)
    print(f"{'Team':<6} {'Motiv':>6} {'Flag':<18} Notes")
    print("-" * 75)
    for t, info in summary.items():
        print(f"{t:<6} {info['motivation_score']:>6.3f} {info['flag']:<18} {info['notes']}")
