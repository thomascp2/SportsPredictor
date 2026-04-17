"""
ML Bridge — calls the production SmartPickSelector for each sport and writes
results to the smart_picks table in props.db.  The TUI grid reads from there.

Run at startup and every 5 minutes.

Reads:
  ../nba/database/nba_predictions.db       (via SmartPickSelector)
  ../nhl/database/nhl_predictions_v2.db    (via SmartPickSelector)
  ../mlb/database/mlb_predictions.db       (via SmartPickSelector)
  ../shared/prizepicks_lines.db            (via SmartPickSelector — maintained by orchestrator)
  ../data/pregame_intel/                   (for news_context)

Writes:
  props.db smart_picks   (today's smart picks, exact same set as streamlit dashboard)
  props.db news_context  (pregame intel flags)
"""

import sqlite3
import json
import sys
import os
from datetime import date
from pathlib import Path
from typing import Optional

# ── Path resolution ──────────────────────────────────────────────────────────

_HERE   = Path(__file__).parent          # tui/
_TUI_DIR = _HERE.parent                  # tui-terminal/
_ROOT   = _TUI_DIR.parent               # SportsPredictor/

PROPS_DB  = _TUI_DIR / "props.db"
INTEL_DIR = _ROOT / "data" / "pregame_intel"
SHARED_DIR = _ROOT / "shared"

# Ensure shared/ is on sys.path so we can import SmartPickSelector
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))


# ── Prop-type normalisation (selector prop_type → display stat_type) ─────────

PROP_TO_STAT = {
    # NHL
    "points":         "NHL_POINTS",
    "shots":          "NHL_SHOTS",
    "shots on goal":  "NHL_SHOTS",
    "goals":          "NHL_GOALS",
    "assists":        "NHL_ASSISTS",
    "hits":           "NHL_HITS",
    "blocked shots":  "NHL_BLOCKED_SHOTS",
    "blocked_shots":  "NHL_BLOCKED_SHOTS",
    # NBA
    "rebounds":       "NBA_REBOUNDS",
    "3-pt made":      "NBA_THREES",
    "3 pointers made":"NBA_THREES",
    "threes":         "NBA_THREES",
    "steals":         "NBA_STEALS",
    "blocks":         "NBA_BLOCKS",
    "turnovers":      "NBA_TURNOVERS",
    "fantasy score":  "NBA_FANTASY",
    "fantasy":        "NBA_FANTASY",
    "pts+reb+ast":    "NBA_PRA",
    "pra":            "NBA_PRA",
    # MLB pitchers
    "strikeouts":          "MLB_STRIKEOUTS",
    "pitcher strikeouts":  "MLB_STRIKEOUTS",
    "outs recorded":       "MLB_OUTS_RECORDED",
    "walks allowed":       "MLB_PITCHER_WALKS",
    "hits allowed":        "MLB_HITS_ALLOWED",
    "earned runs":         "MLB_EARNED_RUNS",
    # MLB batters
    "batter hits":         "MLB_HITS",
    "total bases":         "MLB_TOTAL_BASES",
    "home runs":           "MLB_HOME_RUNS",
    "rbis":                "MLB_RBIS",
    "runs scored":         "MLB_RUNS",
    "stolen bases":        "MLB_STOLEN_BASES",
    "hrr":                 "MLB_HRR",
}

# For NHL/NBA 'points' is ambiguous — resolved by sport in run_bridge


def _prop_to_stat(sport: str, prop_type: str) -> str:
    key = prop_type.lower().strip()
    if key == "points":
        return {"NHL": "NHL_POINTS", "NBA": "NBA_POINTS", "MLB": "MLB_RUNS"}.get(sport.upper(), key)
    if key in ("hits", "batter hits"):
        if sport.upper() == "MLB":
            return "MLB_HITS"
        return "NHL_HITS"
    return PROP_TO_STAT.get(key, key.upper().replace(" ", "_"))


# ── Smart pick sync via SmartPickSelector ─────────────────────────────────────

def _sync_sport(sport: str, props_conn: sqlite3.Connection, today: str) -> int:
    """
    Call SmartPickSelector for one sport and upsert results into smart_picks.
    Returns number of picks written.
    """
    try:
        from smart_pick_selector import SmartPickSelector
    except ImportError as e:
        print(f"[ml_bridge] Cannot import SmartPickSelector: {e}")
        return 0

    try:
        selector = SmartPickSelector(sport=sport)
        # refresh_lines=False — the orchestrator's pp-sync keeps prizepicks_lines.db fresh.
        # If that DB is stale or missing, refresh here so TUI works standalone.
        pp_db = _ROOT / "shared" / "prizepicks_lines.db"
        refresh = not pp_db.exists()
        picks = selector.get_smart_picks(game_date=today, refresh_lines=refresh)
    except Exception as e:
        print(f"[ml_bridge] SmartPickSelector({sport}) error: {e}")
        return 0

    if not picks:
        return 0

    now = __import__('datetime').datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    # Delete today's picks for this sport and reinsert
    props_conn.execute(
        "DELETE FROM smart_picks WHERE sport = ? AND game_date = ?",
        (sport.upper(), today)
    )

    written = 0
    for pick in picks:
        stat_type = _prop_to_stat(sport, pick.prop_type)
        try:
            props_conn.execute("""
                INSERT OR REPLACE INTO smart_picks
                    (sport, player_name, team, opponent, stat_type,
                     prediction, pp_line, odds_type, probability,
                     edge, tier, game_date, ev_4leg, refreshed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sport.upper(),
                pick.player_name,
                getattr(pick, 'team', None),
                getattr(pick, 'opponent', None),
                stat_type,
                pick.prediction,
                pick.pp_line,
                pick.pp_odds_type,
                pick.pp_probability,
                pick.edge,           # already in percentage points (e.g. 19.0 = 19%)
                pick.tier,
                today,
                getattr(pick, 'ev_4leg', None),
                now,
            ))
            written += 1
        except Exception as row_err:
            print(f"[ml_bridge] Row insert error ({pick.player_name}): {row_err}")

    props_conn.commit()
    return written


# ── Pregame intel loader (unchanged) ─────────────────────────────────────────

def load_pregame_intel(props_conn: sqlite3.Connection) -> int:
    if not INTEL_DIR.exists():
        return 0

    today = date.today().isoformat()
    inserted = 0

    for sport in ("nba", "nhl", "mlb"):
        intel_file = INTEL_DIR / f"{sport}_{today}.json"
        if not intel_file.exists():
            continue
        try:
            data = json.loads(intel_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        items = data if isinstance(data, list) else list(data.values())
        for item in items:
            if not isinstance(item, dict):
                continue
            player_name = (item.get("player") or item.get("name") or "").strip()
            summary     = (item.get("summary") or item.get("note") or item.get("status") or "").strip()
            if not player_name or not summary:
                continue
            flag_words = {"OUT", "DOUBTFUL", "QUESTIONABLE", "GTD", "INJURED",
                          "SCRATCHED", "CONFIRMED", "STARTING"}
            if not any(w in summary.upper() for w in flag_words):
                continue
            pid = player_name.lower().replace(" ", "_") + f"_{sport}"
            exists = props_conn.execute(
                "SELECT 1 FROM news_context WHERE player_id = ? AND trigger = 'pregame_cache' "
                "AND date(created_at) = ?",
                (pid, today)
            ).fetchone()
            if exists:
                continue
            props_conn.execute(
                "INSERT INTO news_context (player_id, summary, source_api, trigger, created_at) "
                "VALUES (?, ?, 'grok', 'pregame_cache', datetime('now'))",
                (pid, summary[:120])
            )
            inserted += 1

    props_conn.commit()
    return inserted


# ── MLB ML enrichment ────────────────────────────────────────────────────────

# Maps smart_picks stat_type -> ml_predictions prop name (6 supported props only)
_ML_STAT_TO_PROP = {
    "MLB_HITS":          "hits",
    "MLB_TOTAL_BASES":   "total_bases",
    "MLB_HOME_RUNS":     "home_runs",
    "MLB_STRIKEOUTS":    "strikeouts",
    "MLB_PITCHER_WALKS": "walks",
    "MLB_OUTS_RECORDED": "outs_recorded",
}

_DUCK_DB = _ROOT / "mlb_feature_store" / "data" / "mlb.duckdb"


def _enrich_mlb_ml(props_conn: sqlite3.Connection, today: str) -> int:
    """
    Join smart_picks MLB rows against ml_predictions in DuckDB and update
    ml_predicted_value.  Non-fatal — if DuckDB is locked or missing, skips.
    Returns number of rows enriched.
    """
    if not _DUCK_DB.exists():
        return 0
    try:
        import duckdb as _ddb
        dc = _ddb.connect(str(_DUCK_DB), read_only=True)
        ml_df = dc.execute(
            f"SELECT player_name, prop, predicted_value "
            f"FROM ml_predictions WHERE game_date = '{today}'"
        ).fetchdf()
        dc.close()
    except Exception as e:
        print(f"[ml_bridge] DuckDB read failed (non-fatal): {e}")
        return 0

    if ml_df.empty:
        return 0

    # Build lookup: (player_name, prop) -> predicted_value
    lookup: dict = {}
    for _, row in ml_df.iterrows():
        if row["player_name"]:
            lookup[(row["player_name"], row["prop"])] = float(row["predicted_value"])

    cursor = props_conn.execute(
        "SELECT rowid, player_name, stat_type FROM smart_picks "
        "WHERE sport = 'MLB' AND game_date = ?",
        (today,),
    )
    enriched = 0
    for rowid, pname, stat_type in cursor.fetchall():
        prop = _ML_STAT_TO_PROP.get(stat_type)
        if not prop:
            continue
        pred = lookup.get((pname, prop))
        if pred is not None:
            props_conn.execute(
                "UPDATE smart_picks SET ml_predicted_value = ? WHERE rowid = ?",
                (round(pred, 3), rowid),
            )
            enriched += 1

    props_conn.commit()
    return enriched


# ── Public entry point ───────────────────────────────────────────────────────

def run_bridge(props_db_path: Optional[Path] = None, verbose: bool = False) -> dict:
    db_path = props_db_path or PROPS_DB
    if not db_path.exists():
        return {"error": f"props.db not found at {db_path}"}

    props_conn = sqlite3.connect(str(db_path))
    props_conn.row_factory = sqlite3.Row

    today = date.today().isoformat()
    summary = {}

    for sport in ("NHL", "NBA", "MLB"):
        n = _sync_sport(sport, props_conn, today)
        summary[f"{sport.lower()}_updated"] = n
        if verbose:
            print(f"[ml_bridge] {sport}: {n} smart picks written")

    # Enrich MLB rows with ML predicted values from feature store
    ml_enriched = _enrich_mlb_ml(props_conn, today)
    summary["mlb_ml_enriched"] = ml_enriched
    if verbose:
        print(f"[ml_bridge] MLB ML enrichment: {ml_enriched} rows")

    intel_rows = load_pregame_intel(props_conn)
    summary["intel_rows"] = intel_rows
    if verbose:
        print(f"[ml_bridge] Intel: {intel_rows} flags loaded")

    props_conn.close()
    return summary


if __name__ == "__main__":
    result = run_bridge(verbose=True)
    print(f"Bridge complete: {result}")
