"""
Shared Game Odds Fetcher — Get real sportsbook lines for all sports.

Fetches moneyline, spread, and over/under from ESPN (primary, free, no key needed).
Falls back to The Odds API if ESPN data is incomplete (requires ODDS_API_KEY).

Normalizes team abbreviations to match what's in our databases:
  ESPN 'NY' -> 'NYK', 'NO' -> 'NOP', 'GS' -> 'GSW', etc.

Usage:
    from fetch_game_odds import fetch_odds_for_date, save_odds_to_db

    odds = fetch_odds_for_date("nba", "2026-03-26")
    save_odds_to_db("nba", db_path, odds)
"""

import os
import sys
import json
import time
import sqlite3
import requests
from datetime import datetime
from typing import Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Team abbreviation normalization ──────────────────────────────────────────
# ESPN uses short abbreviations; our databases use standard ones.

NBA_TEAM_MAP = {
    "NY": "NYK", "NYK": "NYK",
    "NO": "NOP", "NOP": "NOP",
    "GS": "GSW", "GSW": "GSW",
    "SA": "SAS", "SAS": "SAS",
    "UTAH": "UTA", "UTA": "UTA",
    "PHO": "PHX", "PHX": "PHX",
    "WSH": "WAS", "WAS": "WAS",
    # Everything else maps to itself
}

NHL_TEAM_MAP = {
    "TB": "TBL", "TBL": "TBL",
    "NJ": "NJD", "NJD": "NJD",
    "SJ": "SJS", "SJS": "SJS",
    "LA": "LAK", "LAK": "LAK",
    "VGK": "VGK", "LV": "VGK",
    "WSH": "WSH",
    # Everything else maps to itself
}

MLB_TEAM_MAP = {
    "WSH": "WSN", "WSN": "WSN",
    "SF": "SFG", "SFG": "SFG",
    "SD": "SDP", "SDP": "SDP",
    "TB": "TBR", "TBR": "TBR",
    "KC": "KCR", "KCR": "KCR",
    "CWS": "CWS", "CHW": "CWS",
    "ARI": "ARI", "AZ": "ARI",
    # Everything else maps to itself
}

TEAM_MAPS = {"nba": NBA_TEAM_MAP, "nhl": NHL_TEAM_MAP, "mlb": MLB_TEAM_MAP}


def normalize_team(sport: str, abbr: str) -> str:
    """Normalize a team abbreviation to match our database conventions."""
    if not abbr:
        return abbr
    abbr = abbr.upper().strip()
    team_map = TEAM_MAPS.get(sport, {})
    return team_map.get(abbr, abbr)


# ── ESPN Odds Fetcher ────────────────────────────────────────────────────────

ESPN_BASES = {
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba",
    "nhl": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl",
    "mlb": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb",
}


def _moneyline_to_prob(ml) -> Optional[float]:
    """Convert American moneyline to implied probability."""
    if ml is None:
        return None
    try:
        ml = float(ml)
        if ml > 0:
            return round(100.0 / (ml + 100.0), 4)
        elif ml < 0:
            return round(abs(ml) / (abs(ml) + 100.0), 4)
        else:
            return 0.5
    except (ValueError, TypeError):
        return None


def _fetch_espn_odds(sport: str, game_date: str) -> List[Dict]:
    """
    Fetch odds from ESPN for all games on a date.

    ESPN NBA: odds are in the scoreboard response (competition.odds[])
    ESPN NHL/MLB: odds require a per-game summary call (pickcenter)

    Returns list of dicts with normalized team abbreviations:
        {home_team, away_team, spread, over_under, home_ml, away_ml,
         home_implied_prob, away_implied_prob, espn_id, odds_provider}
    """
    base = ESPN_BASES.get(sport)
    if not base:
        print(f"[ESPN] Unknown sport: {sport}")
        return []

    date_str = game_date.replace("-", "")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; SportsPredictor/1.0)",
        "Accept": "application/json",
    })

    # Step 1: Get scoreboard
    try:
        resp = session.get(f"{base}/scoreboard", params={"dates": date_str, "limit": 50}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[ESPN-{sport.upper()}] Scoreboard error: {e}")
        return []

    results = []
    events = data.get("events", [])

    for event in events:
        if not isinstance(event, dict):
            continue

        competitions = event.get("competitions", [])
        if not competitions:
            continue
        comp = competitions[0]

        # Extract teams
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        home_comp = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away_comp = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home_comp or not away_comp:
            continue

        raw_home = (home_comp.get("team", {}).get("abbreviation") or "").upper()
        raw_away = (away_comp.get("team", {}).get("abbreviation") or "").upper()
        home_team = normalize_team(sport, raw_home)
        away_team = normalize_team(sport, raw_away)

        espn_id = str(event.get("id") or comp.get("id") or "")

        # Lock odds once a game is live or final — pre-game lines are the ones we bet on
        status_state = event.get("status", {}).get("type", {}).get("state", "pre")
        game_started = status_state in ("in", "post")

        # Try getting odds from scoreboard first (NBA has them inline)
        odds_data = _extract_scoreboard_odds(comp)

        # Always fetch summary when moneylines are missing — the scoreboard
        # gives over/under but rarely provides moneylines for any sport.
        needs_summary = odds_data.get("home_ml") is None and espn_id

        if needs_summary and espn_id:
            summary_odds = _fetch_summary_odds(session, base, espn_id)
            # Merge: prefer summary data for anything missing
            for k, v in summary_odds.items():
                if v is not None and odds_data.get(k) is None:
                    odds_data[k] = v
            time.sleep(0.15)  # Rate limit

        # Calculate implied probabilities from moneylines
        home_prob = _moneyline_to_prob(odds_data.get("home_ml"))
        away_prob = _moneyline_to_prob(odds_data.get("away_ml"))

        # If we have spread but no moneylines, estimate from spread.
        # Convention: spread is from the home team's perspective.
        #   negative spread = home team is favored (e.g. -9.5 means home -9.5)
        #   positive spread = away team is favored (e.g. +9.5 means home +9.5)
        # So home_prob increases as spread decreases (more negative = bigger home favorite).
        if home_prob is None and odds_data.get("spread") is not None:
            spread = odds_data["spread"]
            # Quick approximation: each point of spread ~ 3% probability
            if sport == "nba":
                home_prob = round(max(0.15, min(0.85, 0.50 - spread * 0.03)), 4)
            elif sport == "nhl":
                home_prob = round(max(0.20, min(0.80, 0.50 - spread * 0.10)), 4)
            elif sport == "mlb":
                # MLB spread is typically run line (1.5), use ML for prob
                home_prob = 0.50
            away_prob = round(1.0 - home_prob, 4) if home_prob else None

        results.append({
            "game_date": game_date,
            "home_team": home_team,
            "away_team": away_team,
            "espn_id": espn_id,
            "spread": odds_data.get("spread"),
            "over_under": odds_data.get("over_under"),
            "home_ml": odds_data.get("home_ml"),
            "away_ml": odds_data.get("away_ml"),
            "home_implied_prob": home_prob,
            "away_implied_prob": away_prob,
            "odds_provider": odds_data.get("odds_provider", "ESPN"),
            "game_started": game_started,
        })

    return results


def _extract_scoreboard_odds(comp: dict) -> dict:
    """Extract odds from ESPN scoreboard competition object."""
    result = {
        "spread": None, "over_under": None,
        "home_ml": None, "away_ml": None,
        "odds_provider": "ESPN",
    }

    try:
        odds_list = comp.get("odds", [])
        if not isinstance(odds_list, list) or not odds_list:
            return result

        odds_obj = odds_list[0]
        if not isinstance(odds_obj, dict):
            return result

        # Over/under
        ou = odds_obj.get("overUnder")
        if ou is not None:
            try:
                result["over_under"] = float(ou)
            except (ValueError, TypeError):
                pass

        # Spread
        spread = odds_obj.get("spread")
        if spread is not None:
            try:
                result["spread"] = float(spread)
            except (ValueError, TypeError):
                pass

        # Fall back to details string for spread: "CHA -1.5"
        if result["spread"] is None:
            details = odds_obj.get("details", "")
            if details:
                try:
                    parts = str(details).strip().split()
                    result["spread"] = float(parts[-1])
                except (ValueError, IndexError):
                    pass

        # Moneylines
        home_odds = odds_obj.get("homeTeamOdds", {})
        away_odds = odds_obj.get("awayTeamOdds", {})
        if isinstance(home_odds, dict):
            ml = home_odds.get("moneyLine") or (home_odds.get("current", {}) or {}).get("moneyLine")
            if ml is not None:
                try:
                    result["home_ml"] = int(ml)
                except (ValueError, TypeError):
                    pass
        if isinstance(away_odds, dict):
            ml = away_odds.get("moneyLine") or (away_odds.get("current", {}) or {}).get("moneyLine")
            if ml is not None:
                try:
                    result["away_ml"] = int(ml)
                except (ValueError, TypeError):
                    pass

        # Provider
        provider = odds_obj.get("provider", {})
        if isinstance(provider, dict):
            result["odds_provider"] = provider.get("name", "ESPN")

    except Exception:
        pass

    return result


def _fetch_summary_odds(session, base_url: str, event_id: str) -> dict:
    """Fetch odds from ESPN summary/pickcenter endpoint for a single game."""
    result = {
        "spread": None, "over_under": None,
        "home_ml": None, "away_ml": None,
        "over_odds": None, "under_odds": None,
        "home_spread_odds": None, "away_spread_odds": None,
        "odds_provider": None,
    }

    try:
        resp = session.get(f"{base_url}/summary", params={"event": event_id}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return result

    # Try pickcenter first
    pickcenter = data.get("pickcenter", [])
    if isinstance(pickcenter, list) and pickcenter:
        # Use first entry (usually highest priority provider)
        pc = pickcenter[0]
        if isinstance(pc, dict):
            result["spread"] = _safe_float(pc.get("spread"))
            result["over_under"] = _safe_float(pc.get("overUnder"))
            result["odds_provider"] = (pc.get("provider", {}) or {}).get("name", "ESPN")

            home_odds = pc.get("homeTeamOdds", {})
            away_odds = pc.get("awayTeamOdds", {})
            if isinstance(home_odds, dict):
                result["home_ml"] = _safe_int(home_odds.get("moneyLine"))
                result["home_spread_odds"] = _safe_int(home_odds.get("spreadOdds"))
            if isinstance(away_odds, dict):
                result["away_ml"] = _safe_int(away_odds.get("moneyLine"))
                result["away_spread_odds"] = _safe_int(away_odds.get("spreadOdds"))
            result["over_odds"]  = _safe_int(pc.get("overOdds"))
            result["under_odds"] = _safe_int(pc.get("underOdds"))

    # Fallback: header.competitions[0].odds
    if result["over_under"] is None:
        try:
            comps = data.get("header", {}).get("competitions", [])
            if comps:
                comp_odds = comps[0].get("odds", [{}])
                if comp_odds:
                    o = comp_odds[0]
                    result["over_under"] = _safe_float(o.get("overUnder"))
                    result["spread"] = result["spread"] or _safe_float(o.get("spread"))
                    hto = o.get("homeTeamOdds", {})
                    ato = o.get("awayTeamOdds", {})
                    if isinstance(hto, dict) and result["home_ml"] is None:
                        result["home_ml"] = _safe_int(hto.get("moneyLine"))
                    if isinstance(ato, dict) and result["away_ml"] is None:
                        result["away_ml"] = _safe_int(ato.get("moneyLine"))
        except (KeyError, IndexError, TypeError):
            pass

    return result


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


# ── Save to Database ─────────────────────────────────────────────────────────

def save_odds_to_db(sport: str, db_path: str, odds_list: List[Dict]) -> int:
    """
    Save fetched odds to the game_lines table.

    Creates the table if it doesn't exist. Updates existing rows.
    Returns count of rows saved.
    """
    conn = sqlite3.connect(db_path)

    # Ensure game_lines table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS game_lines (
            game_id          TEXT NOT NULL,
            game_date        TEXT NOT NULL,
            home_team        TEXT,
            away_team        TEXT,
            spread           REAL,
            abs_spread       REAL,
            over_under       REAL,
            home_moneyline   INTEGER,
            away_moneyline   INTEGER,
            home_implied_prob REAL,
            away_implied_prob REAL,
            over_odds        INTEGER,
            under_odds       INTEGER,
            home_spread_odds INTEGER,
            away_spread_odds INTEGER,
            odds_details     TEXT,
            odds_provider    TEXT,
            fetched_at       TEXT,
            PRIMARY KEY (game_date, home_team, away_team)
        )
    """)
    # Add new columns to existing tables that were created before this schema update
    for col, typ in [("over_odds", "INTEGER"), ("under_odds", "INTEGER"),
                     ("home_spread_odds", "INTEGER"), ("away_spread_odds", "INTEGER")]:
        try:
            conn.execute(f"ALTER TABLE game_lines ADD COLUMN {col} {typ}")
        except Exception:
            pass  # column already exists

    saved = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for odds in odds_list:
        game_id = odds.get("espn_id", f"{odds['game_date']}_{odds['away_team']}_{odds['home_team']}")
        spread = odds.get("spread")
        abs_spread = abs(spread) if spread is not None else None

        try:
            # Once a game is live or final, lock the pre-game odds in place.
            # Live odds are volatile and meaningless for pre-game predictions.
            if odds.get("game_started"):
                insert_mode = "INSERT OR IGNORE"
                print(f"  [ODDS] {odds['away_team']}@{odds['home_team']} already started — locking pre-game odds")
            else:
                insert_mode = "INSERT OR REPLACE"

            conn.execute(f"""
                {insert_mode} INTO game_lines
                (game_id, game_date, home_team, away_team, spread, abs_spread,
                 over_under, home_moneyline, away_moneyline,
                 home_implied_prob, away_implied_prob,
                 over_odds, under_odds, home_spread_odds, away_spread_odds,
                 odds_details, odds_provider, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                game_id, odds["game_date"], odds["home_team"], odds["away_team"],
                spread, abs_spread,
                odds.get("over_under"),
                odds.get("home_ml"), odds.get("away_ml"),
                odds.get("home_implied_prob"), odds.get("away_implied_prob"),
                odds.get("over_odds"), odds.get("under_odds"),
                odds.get("home_spread_odds"), odds.get("away_spread_odds"),
                "", odds.get("odds_provider", "ESPN"), now,
            ))
            saved += 1
        except Exception as e:
            print(f"  [WARN] Could not save odds for {odds['away_team']}@{odds['home_team']}: {e}")

    conn.commit()
    conn.close()
    return saved


# ── High-level API ───────────────────────────────────────────────────────────

def fetch_odds_for_date(sport: str, game_date: str) -> List[Dict]:
    """
    Fetch odds for all games on a date. ESPN primary, no key needed.

    Args:
        sport: 'nba', 'nhl', or 'mlb'
        game_date: 'YYYY-MM-DD'

    Returns:
        List of odds dicts with normalized team abbreviations
    """
    print(f"  [ODDS] Fetching {sport.upper()} lines for {game_date} from ESPN...")
    odds = _fetch_espn_odds(sport, game_date)

    if odds:
        print(f"  [ODDS] Got lines for {len(odds)} games:")
        for o in odds:
            spread_str = f"spread={o['spread']}" if o['spread'] is not None else "spread=N/A"
            ou_str = f"o/u={o['over_under']}" if o['over_under'] is not None else "o/u=N/A"
            ml_str = f"ML={o.get('home_ml', 'N/A')}/{o.get('away_ml', 'N/A')}"
            print(f"    {o['away_team']} @ {o['home_team']}: {spread_str} {ou_str} {ml_str}")
    else:
        print(f"  [ODDS] No games found on ESPN for {game_date}")

    return odds


def fetch_and_save_odds(sport: str, db_path: str, game_date: str) -> List[Dict]:
    """
    Fetch odds and save to database in one call.

    Returns the odds list for immediate use by prediction scripts.
    """
    odds = fetch_odds_for_date(sport, game_date)
    if odds:
        saved = save_odds_to_db(sport, db_path, odds)
        print(f"  [ODDS] Saved {saved} game lines to database")
    return odds


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fetch game odds from ESPN")
    parser.add_argument("sport", choices=["nba", "nhl", "mlb"])
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--save", help="Database path to save results")
    args = parser.parse_args()

    odds = fetch_odds_for_date(args.sport, args.date)

    if args.save and odds:
        saved = save_odds_to_db(args.sport, args.save, odds)
        print(f"\nSaved {saved} rows to {args.save}")
