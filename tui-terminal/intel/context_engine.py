"""
context_engine.py — Gemini Intelligence Layer

Polls line_history every 60 seconds for volatility triggers:
  - PP/UD line move > 1.0pt within any 15-minute window
  - Kalshi price move > 10% within any 15-minute window

On trigger: calls Gemini API (with Google Search retrieval) to fetch
injury/news context, then writes a summary row to news_context.

Budget cap: 10 Gemini calls/day tracked in gemini_budget table in props.db.

Usage:
    python intel/context_engine.py [--db path/to/props.db] [--dry-run]

Environment:
    GEMINI_API_KEY   — required for live Gemini calls
"""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Load .env from tui-terminal/ automatically so GEMINI_API_KEY is available
# without needing to export it manually in the shell.
try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).parent.parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
except ImportError:
    pass  # python-dotenv not installed; rely on shell env

# ── Constants ────────────────────────────────────────────────────────────────

POLL_INTERVAL_SECS = 60
VOLATILITY_WINDOW_MINS = 15
PP_UD_THRESHOLD = 1.0       # points
KALSHI_THRESHOLD = 0.10     # fractional (10%)
DAILY_GEMINI_BUDGET = 10
SUMMARY_MAX_WORDS = 20      # Gemini prompt asks for <=15 words; cap display at 20

# ── DB helpers ───────────────────────────────────────────────────────────────

def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_budget_table(conn: sqlite3.Connection) -> None:
    """Create gemini_budget table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gemini_budget (
            date        TEXT PRIMARY KEY,
            calls_made  INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()


def _budget_remaining(conn: sqlite3.Connection) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT calls_made FROM gemini_budget WHERE date = ?", (today,)
    ).fetchone()
    used = row["calls_made"] if row else 0
    return max(0, DAILY_GEMINI_BUDGET - used)


def _increment_budget(conn: sqlite3.Connection) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute("""
        INSERT INTO gemini_budget (date, calls_made) VALUES (?, 1)
        ON CONFLICT(date) DO UPDATE SET calls_made = calls_made + 1
    """, (today,))
    conn.commit()


# ── Volatility detection ─────────────────────────────────────────────────────

def _find_volatile_players(conn: sqlite3.Connection) -> list[dict]:
    """
    Scan line_history for moves that exceed thresholds within the last
    VOLATILITY_WINDOW_MINS minutes. Returns a deduplicated list of dicts:
        {player_id, stat_type, source, delta, trigger_label}
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=VOLATILITY_WINDOW_MINS)
    ).strftime("%Y-%m-%dT%H:%M:%S")

    rows = conn.execute("""
        SELECT lh.player_id, lh.stat_type, lh.source,
               MIN(lh.old_value) AS min_val,
               MAX(lh.new_value) AS max_val,
               SUM(ABS(COALESCE(lh.delta, 0))) AS total_move,
               MAX(ABS(COALESCE(lh.delta, 0))) AS max_single_move,
               cl.sport
        FROM   line_history lh
        LEFT JOIN current_lines cl ON cl.player_id = lh.player_id
        WHERE  lh.recorded_at >= ?
        GROUP  BY lh.player_id, lh.stat_type, lh.source
    """, (cutoff,)).fetchall()

    triggered = {}

    for row in rows:
        player_id = row["player_id"]
        stat_type = row["stat_type"]
        source    = row["source"].lower()  # 'prizepicks', 'underdog', 'kalshi'
        move      = row["max_single_move"] or 0.0
        sport     = (row["sport"] or "").upper()

        # Guard: NHL_HITS false positives from UD ingester.
        # UD maps plain "hits" → NHL_HITS for any player, including MLB batters.
        # Real NHL players (from PP league=8) also have NHL_SHOTS/NHL_POINTS under
        # the same player_id. MLB batters mapped as NHL_HITS have ONLY NHL_HITS.
        # Filter: skip NHL_HITS players with no NHL_SHOTS or NHL_POINTS match.
        if stat_type == "NHL_HITS":
            has_nhl_stats = conn.execute(
                """SELECT 1 FROM current_lines
                   WHERE player_id = ? AND stat_type IN ('NHL_SHOTS', 'NHL_POINTS')
                   LIMIT 1""",
                (player_id,)
            ).fetchone()
            if not has_nhl_stats:
                continue

        is_volatile = False
        trigger_label = None

        if source in ("prizepicks", "underdog"):
            if move >= PP_UD_THRESHOLD:
                is_volatile = True
                trigger_label = f"{source}_move_{move:+.1f}"

        elif source == "kalshi":
            # Kalshi prices are stored as decimals (0.0–1.0)
            min_v = row["min_val"] or 0.0
            max_v = row["max_val"] or 0.0
            pct_change = abs(max_v - min_v)
            if pct_change >= KALSHI_THRESHOLD:
                is_volatile = True
                trigger_label = f"kalshi_move_{pct_change:+.1%}"

        if is_volatile:
            key = (player_id, stat_type)
            if key not in triggered:
                # Fetch display name from current_lines
                name_row = conn.execute(
                    "SELECT name FROM current_lines WHERE player_id = ? LIMIT 1",
                    (player_id,)
                ).fetchone()
                display_name = name_row["name"] if name_row else player_id.replace("_", " ").title()

                triggered[key] = {
                    "player_id":     player_id,
                    "stat_type":     stat_type,
                    "display_name":  display_name,
                    "source":        source,
                    "move":          move,
                    "trigger_label": trigger_label,
                }

    return list(triggered.values())


def _already_processed_recently(conn: sqlite3.Connection,
                                player_id: str,
                                stat_type: str,
                                within_mins: int = 30) -> bool:
    """Return True if we already wrote a news_context row for this player/stat recently."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=within_mins)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    row = conn.execute(
        """SELECT 1 FROM news_context
           WHERE player_id = ? AND stat_type = ? AND created_at >= ?
           LIMIT 1""",
        (player_id, stat_type, cutoff)
    ).fetchone()
    return row is not None


# ── Gemini call ───────────────────────────────────────────────────────────────

def _call_gemini(display_name: str, stat_type: str, dry_run: bool) -> Optional[str]:
    """
    Call Gemini with Google Search retrieval.
    Returns the summary string, or None on failure.
    """
    if dry_run:
        return f"[DRY RUN] No real Gemini call — {display_name} {stat_type} flagged."

    try:
        from google import genai
        from google.genai import types

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("[context_engine] GEMINI_API_KEY not set — skipping Gemini call.", flush=True)
            return None

        client = genai.Client(api_key=api_key)

        prompt = (
            f"Search for the latest news on {display_name} ({stat_type.replace('_', ' ').lower()}). "
            f"Why is their betting line moving? Check for injuries, rest, or coach comments. "
            f"Summarize in 15 words or less."
        )

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        summary = response.text.strip()

        # Truncate to SUMMARY_MAX_WORDS words as a safeguard
        words = summary.split()
        if len(words) > SUMMARY_MAX_WORDS:
            summary = " ".join(words[:SUMMARY_MAX_WORDS]) + "..."

        return summary

    except ImportError:
        print("[context_engine] google-genai not installed. Run: pip install google-genai", flush=True)
        return None
    except Exception as exc:
        print(f"[context_engine] Gemini error: {exc}", flush=True)
        return None


# ── Write to news_context ─────────────────────────────────────────────────────

def _write_intel(conn: sqlite3.Connection,
                 player_id: str,
                 stat_type: str,
                 summary: str,
                 trigger: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute("""
        INSERT INTO news_context (player_id, stat_type, summary, source_api, trigger, created_at)
        VALUES (?, ?, ?, 'gemini', ?, ?)
    """, (player_id, stat_type, summary, trigger, now))
    conn.commit()


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(db_path: Path, dry_run: bool) -> None:
    print(f"[context_engine] Starting. DB={db_path}  dry_run={dry_run}  budget={DAILY_GEMINI_BUDGET}/day", flush=True)

    conn = _connect(db_path)
    _ensure_budget_table(conn)

    while True:
        try:
            _tick(conn, db_path, dry_run)
        except sqlite3.OperationalError as exc:
            # DB might be locked briefly by the Rust ingester — retry next cycle
            print(f"[context_engine] DB locked: {exc}", flush=True)
        except Exception as exc:
            print(f"[context_engine] Unexpected error: {exc}", flush=True)

        time.sleep(POLL_INTERVAL_SECS)


def _tick(conn: sqlite3.Connection, db_path: Path, dry_run: bool) -> None:
    remaining = _budget_remaining(conn)
    if remaining <= 0:
        print(f"[context_engine] Daily Gemini budget exhausted ({DAILY_GEMINI_BUDGET} calls). Skipping tick.", flush=True)
        return

    volatile = _find_volatile_players(conn)

    if not volatile:
        return  # Nothing triggered

    print(f"[context_engine] {len(volatile)} volatile player(s) detected. Budget remaining: {remaining}", flush=True)

    for entry in volatile:
        if remaining <= 0:
            print("[context_engine] Budget hit mid-batch — stopping.", flush=True)
            break

        player_id  = entry["player_id"]
        stat_type  = entry["stat_type"]
        name       = entry["display_name"]
        trigger    = entry["trigger_label"]

        # Skip if we already processed this player+stat recently (debounce)
        if _already_processed_recently(conn, player_id, stat_type):
            print(f"[context_engine] Skipping {name} {stat_type} — processed within 30 min.", flush=True)
            continue

        print(f"[context_engine] Calling Gemini for {name} ({stat_type}) — trigger: {trigger}", flush=True)

        summary = _call_gemini(name, stat_type, dry_run)

        if summary:
            _write_intel(conn, player_id, stat_type, summary, trigger)
            if not dry_run:
                _increment_budget(conn)
                remaining -= 1
            print(f"[context_engine] Written: {name} -> '{summary[:60]}'", flush=True)
        else:
            print(f"[context_engine] No summary returned for {name} — skipping write.", flush=True)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemini context engine for TUI intel feed")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).parent.parent / "props.db"),
        help="Path to props.db (default: ../props.db relative to this script)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect volatility and log triggers but do NOT call Gemini or spend budget",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[context_engine] ERROR: props.db not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    run(db_path, args.dry_run)
