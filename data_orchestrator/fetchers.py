"""
data_orchestrator/fetchers.py

Box score fetchers for NBA (nba_api), NHL (public API), and MLB (pybaseball).

Each function returns a normalized pandas DataFrame with consistent column names
so the storage layer needs zero sport-specific logic.

Error handling philosophy:
  - Network timeouts → log warning, return empty DataFrame
  - Partial failures (one game fails) → log and continue with remaining games
  - Schema changes → KeyError caught, logged with enough context to debug
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import requests

from .config import NHL_API_BASE, NHL_SEASON, NHL_TEAMS, NBA_API_DELAY, NBA_API_TIMEOUT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def _to_nba_date(iso_date: str) -> str:
    """'2026-04-21' → '04/21/2026' (format nba_api expects)"""
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    return dt.strftime("%m/%d/%Y")


def _american_to_implied(odds: int) -> float:
    """Convert American odds to raw (pre-vig) implied probability."""
    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 100.0 / (odds + 100.0)


# ---------------------------------------------------------------------------
# NBA — nba_api
# ---------------------------------------------------------------------------

def fetch_nba_boxscores(game_date: str = None) -> pd.DataFrame:
    """
    Fetch all NBA player box scores for a given date.

    Args:
        game_date: 'YYYY-MM-DD'. Defaults to yesterday.

    Returns:
        DataFrame with columns: game_date, sport, player_name, player_id,
        team, opponent, home_away, points, assists, rebounds, minutes
    """
    from nba_api.stats.endpoints import scoreboardv2, boxscoretraditionalv2

    game_date = game_date or _yesterday()
    nba_fmt   = _to_nba_date(game_date)

    logger.info(f"[NBA] Fetching box scores for {game_date}")

    try:
        scoreboard = scoreboardv2.ScoreboardV2(
            game_date=nba_fmt, timeout=NBA_API_TIMEOUT
        )
        game_header = scoreboard.game_header.get_data_frame()
    except Exception as exc:
        logger.warning(f"[NBA] Scoreboard fetch failed: {exc}")
        return pd.DataFrame()

    if game_header.empty:
        logger.info(f"[NBA] No games on {game_date}")
        return pd.DataFrame()

    rows: list[dict] = []

    for _, game in game_header.iterrows():
        game_id   = game["GAME_ID"]
        home_team = game.get("HOME_TEAM_ABBREVIATION", "")
        away_team = game.get("VISITOR_TEAM_ABBREVIATION", "")

        time.sleep(NBA_API_DELAY)

        try:
            box = boxscoretraditionalv2.BoxScoreTraditionalV2(
                game_id=game_id, timeout=NBA_API_TIMEOUT
            )
            player_stats = box.player_stats.get_data_frame()
        except Exception as exc:
            logger.warning(f"[NBA] Box score failed for game {game_id}: {exc}")
            continue

        for _, p in player_stats.iterrows():
            team      = p.get("TEAM_ABBREVIATION", "")
            home_away = "HOME" if team == home_team else "AWAY"
            opponent  = away_team if home_away == "HOME" else home_team
            minutes   = str(p.get("MIN") or "0:00")

            # Skip DNPs (null minutes or 0:00)
            if not minutes or minutes in ("0:00", "None"):
                continue

            rows.append({
                "game_date":  game_date,
                "sport":      "NBA",
                "player_name": p.get("PLAYER_NAME", ""),
                "player_id":  str(p.get("PLAYER_ID", "")),
                "team":       team,
                "opponent":   opponent,
                "home_away":  home_away,
                "points":     float(p.get("PTS") or 0),
                "assists":    float(p.get("AST") or 0),
                "rebounds":   float(p.get("REB") or 0),
                "minutes":    minutes,
            })

    df = pd.DataFrame(rows)
    logger.info(f"[NBA] {len(df)} player lines fetched for {game_date}")
    return df


# ---------------------------------------------------------------------------
# NHL — public NHL API
# ---------------------------------------------------------------------------

def _fetch_nhl_schedule(game_date: str) -> list[dict]:
    """Return list of game dicts for a given date from the NHL schedule API."""
    url = f"{NHL_API_BASE}/schedule/{game_date}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        week = body.get("gameWeek", [])
        if not week:
            return []
        return week[0].get("games", [])
    except Exception as exc:
        logger.warning(f"[NHL] Schedule fetch failed for {game_date}: {exc}")
        return []


def _fetch_nhl_roster_all(store) -> dict[str, str]:
    """
    Populate nhl_roster table with full player names for all teams.
    Returns {player_id: full_name}. Runs once per session.
    """
    logger.info("[NHL] Fetching full roster for all teams (name expansion)")
    all_players: dict[str, str] = {}

    for team in NHL_TEAMS:
        url = f"{NHL_API_BASE}/roster/{team}/{NHL_SEASON}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.warning(f"[NHL] Roster fetch failed for {team}: {exc}")
            continue

        records: list[dict] = []
        for group in ("forwards", "defense", "goalies"):
            for p in body.get(group, []):
                pid      = str(p.get("id", ""))
                first    = p.get("firstName", {}).get("default", "")
                last     = p.get("lastName", {}).get("default", "")
                full     = f"{first} {last}".strip()
                pos      = p.get("positionCode", "")
                all_players[pid] = full
                records.append({"id": pid, "full_name": full, "position": pos})

        if store is not None:
            store.upsert_nhl_roster(records, team, NHL_SEASON)

        time.sleep(0.3)

    logger.info(f"[NHL] Cached {len(all_players)} player names")
    return all_players


def fetch_nhl_boxscores(
    game_date: str = None,
    store=None,
    _id_to_name: dict[str, str] = None,
) -> pd.DataFrame:
    """
    Fetch all NHL player box scores for a given date.

    The public NHL API returns abbreviated names (e.g. 'C. Caufield').
    If `store` is provided and `_id_to_name` is None, the roster is fetched
    from the store's nhl_roster table to expand to full names.

    Args:
        game_date:   'YYYY-MM-DD'. Defaults to yesterday.
        store:       DataStore instance (used for name lookup).
        _id_to_name: Pre-loaded {player_id: full_name} map (skips store lookup).

    Returns:
        DataFrame with: game_date, sport, player_name, player_id,
        team, opponent, home_away, shots_on_goal, goals, nhl_assists, time_on_ice
    """
    game_date = game_date or _yesterday()
    logger.info(f"[NHL] Fetching box scores for {game_date}")

    # Resolve full name map
    if _id_to_name is None:
        if store is not None:
            _id_to_name = store.get_nhl_roster()
        else:
            _id_to_name = {}

    games = _fetch_nhl_schedule(game_date)
    if not games:
        logger.info(f"[NHL] No games found for {game_date}")
        return pd.DataFrame()

    # Filter to Final games only (skip future/postponed)
    finished = [g for g in games if g.get("gameState") in ("FINAL", "OFF")]
    if not finished:
        logger.info(f"[NHL] No finished games for {game_date}")
        return pd.DataFrame()

    rows: list[dict] = []

    for game in finished:
        game_id   = game.get("id")
        home_abbr = game.get("homeTeam", {}).get("abbrev", "")
        away_abbr = game.get("awayTeam", {}).get("abbrev", "")

        url = f"{NHL_API_BASE}/gamecenter/{game_id}/boxscore"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.warning(f"[NHL] Boxscore failed for game {game_id}: {exc}")
            continue

        by_team = body.get("playerByGameStats", {})

        for side, team_abbr, opp_abbr in [
            ("homeTeam", home_abbr, away_abbr),
            ("awayTeam", away_abbr, home_abbr),
        ]:
            team_stats = by_team.get(side, {})
            home_away  = "HOME" if side == "homeTeam" else "AWAY"

            for group in ("forwards", "defense"):
                for p in team_stats.get(group, []):
                    pid      = str(p.get("playerId", ""))
                    toi      = str(p.get("toi", "0:00"))
                    # Skip players who didn't take ice time
                    if not toi or toi == "0:00":
                        continue

                    # Full name from roster; fall back to abbreviated API name
                    full_name = _id_to_name.get(
                        pid,
                        p.get("name", {}).get("default", "")
                    )

                    rows.append({
                        "game_date":    game_date,
                        "sport":        "NHL",
                        "player_name":  full_name,
                        "player_id":    pid,
                        "team":         team_abbr,
                        "opponent":     opp_abbr,
                        "home_away":    home_away,
                        "shots_on_goal": int(p.get("sog", 0)),
                        "goals":         int(p.get("goals", 0)),
                        "nhl_assists":   int(p.get("assists", 0)),
                        "time_on_ice":   toi,
                    })

        time.sleep(0.2)

    df = pd.DataFrame(rows)
    logger.info(f"[NHL] {len(df)} player lines fetched for {game_date}")
    return df


# ---------------------------------------------------------------------------
# MLB — pybaseball (Statcast)
# ---------------------------------------------------------------------------

_STATCAST_EVENTS_TO_BASES: dict[str, int] = {
    "single":   1,
    "double":   2,
    "triple":   3,
    "home_run": 4,
}

def _normalize_mlb_name(name: str) -> str:
    """Convert pybaseball 'Last, First' to 'First Last' (sportsbook format)."""
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2:
            return f"{parts[1]} {parts[0]}"
    return name


_AT_BAT_EVENTS = {
    "single", "double", "triple", "home_run",
    "strikeout", "strikeout_double_play",
    "field_out", "force_out", "double_play",
    "grounded_into_double_play", "fielders_choice",
    "fielders_choice_out", "field_error",
    "sac_fly", "sac_fly_double_play",
    # walks, HBP, etc. are NOT official at-bats
}


def fetch_mlb_boxscores(game_date: str = None) -> pd.DataFrame:
    """
    Fetch MLB player stats for a given date using pybaseball's Statcast feed.

    Computes per-batter:
      - total_bases  (1B=1, 2B=2, 3B=3, HR=4)
      - at_bats      (plate appearances excluding walks/HBP/sac)
      - hits          (single+double+triple+HR)

    Args:
        game_date: 'YYYY-MM-DD'. Defaults to yesterday.

    Returns:
        DataFrame with: game_date, sport, player_name, player_id,
        team, opponent, home_away, total_bases, at_bats, hits
    """
    import warnings
    from pybaseball import statcast

    game_date = game_date or _yesterday()
    logger.info(f"[MLB] Fetching Statcast data for {game_date}")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df_raw = statcast(start_dt=game_date, end_dt=game_date, verbose=False)
    except Exception as exc:
        logger.warning(f"[MLB] Statcast fetch failed for {game_date}: {exc}")
        return pd.DataFrame()

    if df_raw is None or df_raw.empty:
        logger.info(f"[MLB] No Statcast data for {game_date}")
        return pd.DataFrame()

    # Focus on batting plate appearances
    batter_pa = df_raw[df_raw["events"].notna()].copy()

    # Compute per-event stats
    batter_pa["_bases"]  = batter_pa["events"].map(_STATCAST_EVENTS_TO_BASES).fillna(0)
    batter_pa["_hit"]    = batter_pa["events"].isin({"single", "double", "triple", "home_run"}).astype(int)
    batter_pa["_at_bat"] = batter_pa["events"].isin(_AT_BAT_EVENTS).astype(int)

    # Resolve home/away: inning_topbot T=away batting, B=home batting
    batter_pa["_home_away"] = batter_pa["inning_topbot"].map({"Top": "AWAY", "Bot": "HOME"}).fillna("UNK")

    # Aggregate per batter per game
    agg = (
        batter_pa
        .groupby(["game_pk", "batter", "player_name", "home_team", "away_team", "_home_away"])
        .agg(
            total_bases=("_bases", "sum"),
            at_bats=("_at_bat", "sum"),
            hits=("_hit", "sum"),
        )
        .reset_index()
    )

    rows: list[dict] = []
    for _, r in agg.iterrows():
        home_away = str(r["_home_away"])
        team     = r["home_team"] if home_away == "HOME" else r["away_team"]
        opponent = r["away_team"] if home_away == "HOME" else r["home_team"]

        # pybaseball returns "Last, First" — convert to "First Last" to match sportsbooks
        raw_name  = str(r["player_name"])
        full_name = _normalize_mlb_name(raw_name)

        rows.append({
            "game_date":   game_date,
            "sport":       "MLB",
            "player_name": full_name,
            "player_id":   str(r["batter"]),
            "team":        str(team),
            "opponent":    str(opponent),
            "home_away":   home_away,
            "total_bases": float(r["total_bases"]),
            "at_bats":     int(r["at_bats"]),
            "hits":        int(r["hits"]),
        })

    result = pd.DataFrame(rows)
    logger.info(f"[MLB] {len(result)} batter lines for {game_date}")
    return result


# ---------------------------------------------------------------------------
# Player registry seeding
# ---------------------------------------------------------------------------

def seed_player_registry(store) -> dict[str, int]:
    """
    Populate the player_registry table with all active players from each sport.

    Sources:
      NBA: nba_api static player list (~500 active players)
      NHL: NHL API roster for all 32 teams (~700 players)
      MLB: pybaseball playerid_lookup — seeded from Statcast data instead
           (full MLB active roster isn't cleanly available; we use a lookup
            approach: query all unique player names from pybaseball's chadwick
            register and store them)

    Returns: {sport: player_count}
    """
    counts: dict[str, int] = {}

    # --- NBA ---
    try:
        from nba_api.stats.static import players as _nba_players
        active = _nba_players.get_active_players()
        records = [
            {"player_id": str(p["id"]), "full_name": p["full_name"]}
            for p in active
        ]
        store.upsert_registry(records, "NBA")
        counts["NBA"] = len(records)
        logger.info(f"[Registry] NBA: {len(records)} active players seeded")
    except Exception as exc:
        logger.warning(f"[Registry] NBA seed failed: {exc}")
        counts["NBA"] = 0

    # --- NHL ---
    try:
        id_map = _fetch_nhl_roster_all(store)   # also writes to nhl_roster table
        records = [
            {"player_id": pid, "full_name": name}
            for pid, name in id_map.items()
        ]
        store.upsert_registry(records, "NHL")
        counts["NHL"] = len(records)
        logger.info(f"[Registry] NHL: {len(records)} players seeded")
    except Exception as exc:
        logger.warning(f"[Registry] NHL seed failed: {exc}")
        counts["NHL"] = 0

    # --- MLB ---
    # pybaseball's chadwick register has all historical + current players.
    # Filter to recent seasons to get active-only names.
    try:
        from pybaseball import chadwick_register
        import warnings, datetime as _dt

        current_year = _dt.date.today().year
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            register = chadwick_register()

        # Filter: played in last 3 seasons (mlb_played_last >= current_year - 2)
        if "mlb_played_last" in register.columns:
            active_mlb = register[
                register["mlb_played_last"] >= current_year - 2
            ].copy()
        else:
            active_mlb = register.copy()

        # Build full name: name_first + name_last
        active_mlb = active_mlb.dropna(subset=["name_first", "name_last"])
        active_mlb["full_name"] = (
            active_mlb["name_first"].str.strip()
            + " "
            + active_mlb["name_last"].str.strip()
        )

        records = []
        for _, row in active_mlb.iterrows():
            pid = str(row.get("key_mlbam", row.get("key_bbref", "")))
            if not pid or pid == "nan":
                continue
            records.append({
                "player_id": pid,
                "full_name":  row["full_name"],
                "position":   row.get("pro_played_first", ""),
            })

        store.upsert_registry(records, "MLB")
        counts["MLB"] = len(records)
        logger.info(f"[Registry] MLB: {len(records)} players seeded")
    except Exception as exc:
        logger.warning(f"[Registry] MLB seed failed: {exc}")
        counts["MLB"] = 0

    return counts
