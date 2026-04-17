"""
PEGASUS Situational Intelligence Engine

Fetches live standings, computes stakes scores, and flags picks with
situational context.

ADVISORY ONLY — this module NEVER modifies probability, ai_edge, or tier
stored anywhere. All output fields (situation_flag, situation_modifier,
situation_notes) are display-only.

Data sources:
  NBA: ESPN standings API (site.api.espn.com) — already used by fetch_game_odds.py
  NHL: NHL official API (api-web.nhle.com/v1/standings/now) — used in grading scripts
  MLB: No-op placeholder (April = no stakes, all teams have hope)

Fallback: when API unavailable → situation_flag=NORMAL, modifier=0.0, notes=''
"""

import json
import sqlite3
import time
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from PEGASUS.situational.flags import SituationFlag, flag_from_motivation, get_modifier
from PEGASUS.config import PEGASUS_ROOT, NHL_DB, NBA_DB

# ── Cache directory (reuse PEGASUS data layout) ──────────────────────────────
CACHE_DIR = PEGASUS_ROOT / "data" / "situational_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── HTTP session (shared, rate-limited) ──────────────────────────────────────
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
                print(f"  [INTEL] API error ({url}): {exc}")
                return None
            time.sleep(1.5 ** attempt)
    return None


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _standings_cache_path(sport: str, game_date: str) -> Path:
    return CACHE_DIR / f"{sport}_{game_date}_standings.json"


def _usage_cache_path(sport: str, game_date: str, team: str) -> Path:
    return CACHE_DIR / f"{sport}_{game_date}_usage_{team.upper()}.json"


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
        print(f"  [INTEL] Cache write failed ({path.name}): {exc}")


# ── Default (safe) output ─────────────────────────────────────────────────────

NORMAL_RESULT: Tuple[SituationFlag, float, str] = (SituationFlag.NORMAL, 0.0, "")


# ═══════════════════════════════════════════════════════════════════════════════
# NBA — ESPN standings
# ═══════════════════════════════════════════════════════════════════════════════

ESPN_NBA_STANDINGS = (
    "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"
)

# Map ESPN team display abbreviations to our DB abbreviations (from fetch_game_odds.py)
NBA_ABBREV_MAP = {
    "NY": "NYK", "NYK": "NYK",
    "NO": "NOP", "NOP": "NOP",
    "GS": "GSW", "GSW": "GSW",
    "SA": "SAS", "SAS": "SAS",
    "UTAH": "UTA", "UTA": "UTA",
    "PHO": "PHX", "PHX": "PHX",
    "WSH": "WAS", "WAS": "WAS",
}


def _normalize_nba_abbrev(raw: str) -> str:
    raw = (raw or "").upper().strip()
    return NBA_ABBREV_MAP.get(raw, raw)


def _fetch_nba_standings(game_date: str) -> Dict[str, Dict]:
    """
    Fetch NBA conference standings from ESPN.

    Returns:
        dict keyed by team abbreviation:
        {
          "LAL": {
            "wins": 42, "losses": 30, "games_back": 2.5,
            "conference_rank": 5, "games_remaining": 10,
            "clinched_playoffs": True, "eliminated": False,
            "espn_team": "LAL"
          },
          ...
        }
    """
    cache_path = _standings_cache_path("nba", game_date)
    cached = _load_cache(cache_path)
    if cached:
        return cached

    data = _safe_get(ESPN_NBA_STANDINGS, params={"season": "2026", "seasontype": "2"})
    if not data:
        return {}

    result: Dict[str, Dict] = {}
    try:
        groups = data.get("children", []) or data.get("standings", {}).get("groups", [])
        for group in groups:
            for entry in group.get("standings", {}).get("entries", []):
                team_info = entry.get("team", {})
                raw_abbr = team_info.get("abbreviation", "")
                abbr = _normalize_nba_abbrev(raw_abbr)

                # ESPN stats array: each stat has a name and value
                stats = {s["name"]: s.get("value") for s in entry.get("stats", []) if "name" in s}

                wins       = int(stats.get("wins", 0) or 0)
                losses     = int(stats.get("losses", 0) or 0)
                games_back = float(stats.get("gamesBehind", 0) or 0)
                conf_rank  = int(stats.get("playoffSeed", stats.get("rank", 99)) or 99)

                # ESPN returns clincher as a numeric value with displayValue string
                # e.g. value=1.0 displayValue="x", value=3.0 displayValue="z"
                # Find displayValue from the full stats list (not the name→value dict)
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
                    "wins": wins,
                    "losses": losses,
                    "games_back": games_back,
                    "conference_rank": conf_rank,
                    "games_remaining": games_remaining,
                    "clinched_playoffs": clinched_playoffs,
                    "eliminated": eliminated,
                    "espn_team": raw_abbr,
                }
    except Exception as exc:
        print(f"  [INTEL] NBA standings parse error: {exc}")
        return {}

    _save_cache(cache_path, result)
    print(f"  [INTEL] NBA standings loaded: {len(result)} teams")
    return result


def _nba_motivation_score(team_info: Dict) -> float:
    """
    Compute a motivation_score (0.0–1.0) from NBA team standings info.

    Logic per PLAN.md Step 3 spec:
      Eliminated                              → 0.10
      3+ games below play-in, < 5 games left → 0.10
      Playoff seed locked (rank ≤ 8, gb=0)   → 0.20
      Clinched playoffs, rank moveable        → 0.50
      Play-in zone (rank 9-10), < 8 left      → 0.88
      Seeding battle (2v3, 4v5), < 4 gb,
        < 6 left                              → 0.80
      Regular competition                     → 0.70
    """
    if not team_info:
        return 0.60  # Unknown → assume normal

    rank     = team_info.get("conference_rank", 99)
    gb_raw   = team_info.get("games_back")
    gb       = float(gb_raw if gb_raw is not None else 0)
    left_raw = team_info.get("games_remaining")
    left     = int(left_raw if left_raw is not None else 10)
    clinched = bool(team_info.get("clinched_playoffs", False))
    elim     = bool(team_info.get("eliminated", False))

    if elim:
        return 0.10

    # Playoffs active: regular season over + top-8 seed = playoff series in progress
    # Also handles: regular season games_remaining=0 but play-in still possible for 9-10
    if left == 0:
        if rank <= 8 and clinched:
            return 1.00   # In playoff series — maximum urgency
        if rank in (9, 10):
            return 1.00   # Play-in game
        if rank > 10 and not clinched:
            return 0.10   # Season over, missed playoffs

    # Deep out of play-in contention (regular season still live)
    if rank > 10 and gb >= 3 and left <= 5:
        return 0.10

    # Seed fully locked (top seed, no one can catch them)
    if clinched and gb == 0 and left <= 4:
        return 0.20

    # Clinched playoffs but seed still moveable
    if clinched and rank <= 6:
        return 0.50

    # Play-in zone with games left
    if rank in (9, 10) and left <= 8:
        return 0.90

    # Seeding battle — close gap, few games left
    if clinched and rank <= 8 and gb <= 2 and left <= 6:
        return 0.75

    # On the bubble (fighting for play-in or seeding)
    if not clinched and rank <= 12 and left <= 10:
        return 0.85

    # Default — regular competition
    return 0.70


def _nba_stakes_notes(abbr: str, team_info: Dict) -> str:
    if not team_info:
        return ""
    rank  = team_info.get("conference_rank", "?")
    left  = team_info.get("games_remaining", "?")
    elim  = team_info.get("eliminated", False)
    clin  = team_info.get("clinched_playoffs", False)
    gb    = team_info.get("games_back", 0)

    parts = [f"{abbr.upper()}"]
    if elim:
        parts.append("eliminated")
    elif clin and rank <= 8:
        parts.append(f"{rank}-seed clinched")
    elif rank in (9, 10):
        parts.append(f"{rank}-seed play-in")
    else:
        parts.append(f"{rank}-seed")

    if left and not elim:
        parts.append(f"{left} games left")
    if gb and not elim and not clin:
        parts.append(f"{gb:.1f} GB")

    return " | ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# NHL — NHL official API standings
# ═══════════════════════════════════════════════════════════════════════════════

NHL_STANDINGS_URL = "https://api-web.nhle.com/v1/standings/now"

# NHL official abbreviations are already consistent with our DB
# (fetch_game_odds.py normalises TBL, NJD, etc.)
NHL_ABBREV_MAP = {
    "TB": "TBL", "NJ": "NJD", "SJ": "SJS", "LA": "LAK",
    "VGK": "VGK", "LV": "VGK",
}


def _normalize_nhl_abbrev(raw: str) -> str:
    raw = (raw or "").upper().strip()
    return NHL_ABBREV_MAP.get(raw, raw)


def _fetch_nhl_standings(game_date: str) -> Dict[str, Dict]:
    """
    Fetch NHL standings from api-web.nhle.com/v1/standings/now.

    Returns:
        dict keyed by team abbreviation:
        {
          "BOS": {
            "wins": 52, "losses": 18, "ot_losses": 6,
            "points": 110, "games_remaining": 6,
            "wildcard_sequence": 1, "division_sequence": 2,
            "clinched_playoffs": True, "eliminated": False,
          }, ...
        }
    """
    cache_path = _standings_cache_path("nhl", game_date)
    cached = _load_cache(cache_path)
    if cached:
        return cached

    data = _safe_get(NHL_STANDINGS_URL)
    if not data:
        return {}

    result: Dict[str, Dict] = {}
    try:
        standings_list = data.get("standings", [])
        for entry in standings_list:
            raw_abbr = entry.get("teamAbbrev", {})
            if isinstance(raw_abbr, dict):
                raw_abbr = raw_abbr.get("default", "")
            abbr = _normalize_nhl_abbrev(str(raw_abbr))

            wins           = int(entry.get("wins", 0) or 0)
            losses         = int(entry.get("losses", 0) or 0)
            ot_losses      = int(entry.get("otLosses", 0) or 0)
            points         = int(entry.get("points", 0) or 0)
            games_played   = int(entry.get("gamesPlayed", 0) or 0)
            games_remaining = max(0, 82 - games_played)

            # NHL API clinch indicators
            clinch_indicator = str(entry.get("clinchIndicator", "") or "")
            div_seq          = int(entry.get("divisionSequence", 99) or 99)
            wc_seq           = int(entry.get("wildcardSequence", 99) or 99)

            # "x" = clinched playoff berth, "y" = clinched division, "z" = Presidents' Trophy
            clinched_playoffs = clinch_indicator.lower() in ("x", "y", "z", "p")
            # "e" = eliminated (NHL API uses this)
            eliminated        = clinch_indicator.lower() == "e"

            result[abbr] = {
                "wins": wins,
                "losses": losses,
                "ot_losses": ot_losses,
                "points": points,
                "games_remaining": games_remaining,
                "division_sequence": div_seq,
                "wildcard_sequence": wc_seq,
                "clinch_indicator": clinch_indicator,
                "clinched_playoffs": clinched_playoffs,
                "eliminated": eliminated,
            }
    except Exception as exc:
        print(f"  [INTEL] NHL standings parse error: {exc}")
        return {}

    _save_cache(cache_path, result)
    print(f"  [INTEL] NHL standings loaded: {len(result)} teams")
    return result


def _nhl_motivation_score(team_info: Dict) -> float:
    """
    Compute motivation_score for an NHL team.

    NHL regular season ends ~April 18; playoffs start ~April 21.
    Wild card races are the key variable. Division leaders are often coasting
    into playoffs. Bubble teams fight hard.

    Per PLAN.md:
      Eliminated                              → DEAD_RUBBER
      Wild card race, < 3 pts back, < 5 left → HIGH_STAKES (0.90)
      Division leader / clinched             → REDUCED_STAKES (0.25)
      Playoff series in progress             → HIGH_STAKES (1.00)
      Game 7                                 → HIGH_STAKES (1.00)
    """
    if not team_info:
        return 0.60

    clinched = bool(team_info.get("clinched_playoffs", False))
    elim     = bool(team_info.get("eliminated", False))
    div_seq  = int(team_info.get("division_sequence", 99) or 99)
    wc_seq   = int(team_info.get("wildcard_sequence", 99) or 99)
    left_raw = team_info.get("games_remaining")
    left     = int(left_raw if left_raw is not None else 8)
    pts      = int(team_info.get("points", 0) or 0)

    if elim:
        return 0.10

    # Division leader / Presidents' Trophy — seed locked
    if clinched and div_seq == 1 and left <= 5:
        return 0.20

    # Clinched but seed still moveable
    if clinched:
        return 0.45

    # Tight wild card race
    if not clinched and wc_seq <= 2 and left <= 5:
        return 0.90

    # On the bubble — need points
    if not clinched and wc_seq <= 4 and left <= 8:
        return 0.85

    # General playoff contender
    return 0.65


def _nhl_stakes_notes(abbr: str, team_info: Dict) -> str:
    if not team_info:
        return ""
    elim   = team_info.get("eliminated", False)
    clin   = team_info.get("clinched_playoffs", False)
    left   = team_info.get("games_remaining", "?")
    pts    = team_info.get("points", "?")
    div    = team_info.get("division_sequence", "?")
    wc     = team_info.get("wildcard_sequence", "?")
    ci     = team_info.get("clinch_indicator", "")

    parts = [abbr.upper()]
    if elim:
        parts.append("eliminated")
    elif clin:
        parts.append(f"clinched ({ci.upper()})")
        if div != "?":
            parts.append(f"div-{div}")
    else:
        if wc != "?" and wc <= 4:
            parts.append(f"WC{wc}")
        parts.append(f"{pts} pts")

    if left:
        parts.append(f"{left} games left")

    return " | ".join(str(p) for p in parts)


# ═══════════════════════════════════════════════════════════════════════════════
# MLB — no-op placeholder (April = no stakes)
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_mlb_standings(game_date: str) -> Dict[str, Dict]:
    """
    MLB situational intel placeholder.

    April = all 30 teams have full hope, zero are eliminated.
    No motivational flags warranted until ~late August.
    Returns empty dict — all calls fall through to NORMAL.
    """
    return {}


def _mlb_motivation_score(_team_info: Dict) -> float:
    return 0.60  # Normal; mid-season maps to NORMAL flag


# ═══════════════════════════════════════════════════════════════════════════════
# Star player USAGE_BOOST detection
# ═══════════════════════════════════════════════════════════════════════════════

# Minimum game_stakes_score to bother with usage detection
USAGE_BOOST_THRESHOLD = 0.75

# Number of top-minute leaders to flag per team
TOP_N_MINUTE_LEADERS = 2

# How many recent games to average for minutes
USAGE_LOOKBACK_GAMES = 10


def get_usage_boost_players(
    team: str,
    sport: str,
    game_stakes_score: float,
) -> List[str]:
    """
    Return a list of player names (top-N minute leaders on the team) that
    should receive a USAGE_BOOST flag when stakes are high.

    Only fires when game_stakes_score >= USAGE_BOOST_THRESHOLD.

    Data source: player_game_logs in the sport's read-only SQLite DB.

    Args:
        team:              Team abbreviation (e.g. "LAL", "BOS")
        sport:             "nba" | "nhl" | "mlb"
        game_stakes_score: motivation_score computed by this module

    Returns:
        List of player_name strings (may be empty if below threshold or DB unavailable)
    """
    if game_stakes_score < USAGE_BOOST_THRESHOLD:
        return []

    db_path = {"nba": NBA_DB, "nhl": NHL_DB}.get(sport.lower())
    if not db_path or not Path(db_path).exists():
        return []

    # Column that tracks per-game minutes
    minutes_col = {
        "nba": "minutes",      # NBA player_game_logs uses `minutes` (not minutes_played)
        "nhl": "toi",          # time on ice (stored as float minutes in our schema)
    }.get(sport.lower())

    if not minutes_col:
        return []

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Get most recent USAGE_LOOKBACK_GAMES games for this team
        # and average minutes per player. Use team column (exact abbreviation).
        query = f"""
            SELECT player_name, AVG({minutes_col}) AS avg_min, COUNT(*) AS games
            FROM player_game_logs
            WHERE team = ?
            GROUP BY player_name
            HAVING games >= 3
            ORDER BY avg_min DESC
            LIMIT {TOP_N_MINUTE_LEADERS}
        """
        cur.execute(query, (team.upper(),))
        rows = cur.fetchall()
        conn.close()

        leaders = [row["player_name"] for row in rows if row["avg_min"] is not None]
        if leaders:
            print(f"  [INTEL] USAGE_BOOST leaders for {team}: {', '.join(leaders)}")
        return leaders

    except Exception as exc:
        print(f"  [INTEL] Usage boost query failed ({sport} {team}): {exc}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# Standings registry — lazy-loaded per (sport, date)
# ═══════════════════════════════════════════════════════════════════════════════

# Maps sport → fetch function
_STANDINGS_FETCHERS = {
    "nba": _fetch_nba_standings,
    "nhl": _fetch_nhl_standings,
    "mlb": _fetch_mlb_standings,
}

# Maps sport → motivation score function
_MOTIVATION_SCORERS = {
    "nba": _nba_motivation_score,
    "nhl": _nhl_motivation_score,
    "mlb": _mlb_motivation_score,
}

# Maps sport → notes function
_NOTES_BUILDERS = {
    "nba": _nba_stakes_notes,
    "nhl": _nhl_stakes_notes,
    "mlb": lambda abbr, info: "",
}

# In-process standings cache (dict keyed by (sport, date))
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
    """
    Return (motivation_score, team_info_dict) for a team.

    motivation_score: 0.0 (no motivation) → 1.0 (maximum urgency)
    team_info_dict:   raw standings row (may be empty if team not found)

    Args:
        team:       Team abbreviation (e.g. "LAL", "TOR")
        sport:      "nba" | "nhl" | "mlb"
        game_date:  YYYY-MM-DD — defaults to today

    Returns:
        (motivation_score, team_info)
    """
    if game_date is None:
        game_date = date.today().isoformat()

    standings = _get_standings(sport, game_date)
    team_info = standings.get(team.upper(), {})

    scorer = _MOTIVATION_SCORERS.get(sport.lower(), lambda _: 0.60)
    motivation = scorer(team_info)

    return motivation, team_info


def get_situation(
    team: str,
    sport: str,
    game_date: Optional[str] = None,
    injury_status: str = "ACTIVE",
    player_name: Optional[str] = None,
    usage_boost_override: bool = False,
) -> Tuple[SituationFlag, float, str]:
    """
    Core situational assessment for a (team, sport, date, player) combination.

    This is the primary entry point called by PEGASUS pick_selector.py.

    Args:
        team:                Team abbreviation
        sport:               "nba" | "nhl" | "mlb"
        game_date:           YYYY-MM-DD (defaults to today)
        injury_status:       Player injury report status (default "ACTIVE")
        player_name:         Player name — used to check if they are a usage boost leader
        usage_boost_override: If True, force USAGE_BOOST flag (used when you already know a star is out)

    Returns:
        (SituationFlag, modifier, notes_str)
        All three are advisory only — NEVER written to DB or applied to probability.
    """
    if game_date is None:
        game_date = date.today().isoformat()

    sport = sport.lower()

    # ── MLB: always NORMAL in April ───────────────────────────────────────────
    if sport == "mlb":
        return NORMAL_RESULT

    try:
        motivation, team_info = get_team_stakes(team, sport, game_date)
    except Exception as exc:
        print(f"  [INTEL] get_team_stakes failed ({sport} {team}): {exc}")
        return NORMAL_RESULT

    # ── Check if this player is a usage-boost leader ──────────────────────────
    if usage_boost_override:
        flag = SituationFlag.USAGE_BOOST
        modifier = get_modifier(SituationFlag.USAGE_BOOST, injury_status)
    else:
        flag, modifier = flag_from_motivation(motivation, injury_status)

        # If HIGH_STAKES: check if this player is a minute leader → USAGE_BOOST
        if flag == SituationFlag.HIGH_STAKES and player_name:
            boost_players = get_usage_boost_players(team, sport, motivation)
            if player_name in boost_players:
                flag = SituationFlag.USAGE_BOOST
                modifier = get_modifier(SituationFlag.USAGE_BOOST, injury_status)

    # ── Build human-readable notes ────────────────────────────────────────────
    notes_builder = _NOTES_BUILDERS.get(sport, lambda a, i: "")
    base_notes = notes_builder(team, team_info)
    notes = base_notes

    if flag == SituationFlag.USAGE_BOOST and player_name:
        notes = f"USAGE BOOST: {player_name} | {base_notes}"
    elif flag == SituationFlag.DEAD_RUBBER:
        notes = f"DEAD RUBBER risk | {base_notes}"
    elif flag == SituationFlag.ELIMINATED:
        notes = f"ELIMINATED — full rest mode | {base_notes}"
    elif flag == SituationFlag.HIGH_STAKES:
        notes = f"HIGH STAKES | {base_notes}"
    elif flag == SituationFlag.REDUCED_STAKES:
        notes = f"Reduced stakes | {base_notes}"

    return flag, modifier, notes


def get_team_situation_summary(
    teams: List[str],
    sport: str,
    game_date: Optional[str] = None,
) -> Dict[str, Dict]:
    """
    Return a summary dict for a list of teams — used by the Situational Analyst
    agent and dashboard displays.

    Returns:
        {
          "LAL": {
            "motivation_score": 0.25,
            "flag": "DEAD_RUBBER",
            "notes": "LAL | 1-seed clinched | 3 games left",
            "games_remaining": 3,
            "clinched_playoffs": True,
            "eliminated": False,
          },
          ...
        }
    """
    if game_date is None:
        game_date = date.today().isoformat()

    sport = sport.lower()
    result: Dict[str, Dict] = {}

    for team in teams:
        try:
            motivation, team_info = get_team_stakes(team, sport, game_date)
            flag, modifier = flag_from_motivation(motivation)
            notes_builder = _NOTES_BUILDERS.get(sport, lambda a, i: "")
            notes = notes_builder(team.upper(), team_info)

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
            print(f"  [INTEL] Summary failed for {team}: {exc}")
            result[team.upper()] = {
                "motivation_score": 0.60,
                "flag": SituationFlag.NORMAL.value,
                "modifier": 0.0,
                "notes": "",
                "games_remaining": None,
                "clinched_playoffs": False,
                "eliminated": False,
            }

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# CLI smoke-test
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    sport_arg = sys.argv[1] if len(sys.argv) > 1 else "nba"
    date_arg  = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()

    print(f"\n[INTEL] Smoke test — {sport_arg.upper()} standings for {date_arg}")
    print("=" * 60)

    standings = _get_standings(sport_arg, date_arg)
    if not standings:
        print("  No standings data returned (API may be down or cache miss).")
        sys.exit(1)

    print(f"  Loaded {len(standings)} teams\n")

    # Sample 5 teams
    sample_teams = list(standings.keys())[:5]
    summary = get_team_situation_summary(sample_teams, sport_arg, date_arg)

    print(f"{'Team':<6} {'Motivation':>10} {'Flag':<18} Notes")
    print("-" * 75)
    for team, info in summary.items():
        print(f"{team:<6} {info['motivation_score']:>10.3f} {info['flag']:<18} {info['notes']}")
