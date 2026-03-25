"""
NHL Daily Hits & Blocked Shots Picks
=====================================
Calls the Claude API with tonight's game slate and generates 8 high-probability
hits/blocks plays for PrizePicks Flex. Completely standalone — no dependency on
the main NHL prediction pipeline.

Storage: nhl/database/hits_blocks.db  (separate from nhl_predictions_v2.db)

Usage:
    cd nhl
    python scripts/daily_hits_blocks.py              # run for today
    python scripts/daily_hits_blocks.py --date 2026-03-26
    python scripts/daily_hits_blocks.py --discord    # also post to Discord
    python scripts/daily_hits_blocks.py --force      # regenerate even if already run
    python scripts/daily_hits_blocks.py --show       # print latest saved picks

Environment variables:
    ANTHROPIC_API_KEY          (required)
    NHL_HITS_BLOCKS_WEBHOOK    Discord webhook URL for this channel
    CLAUDE_HB_MODEL            Override Claude model (default: claude-3-5-sonnet-20241022)
"""

import sys
import os
import sqlite3
import json
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime, date
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).parent
_NHL_ROOT    = _SCRIPTS_DIR.parent
DB_PATH      = str(_NHL_ROOT / "database" / "hits_blocks.db")

# ── Claude ────────────────────────────────────────────────────────────────────
try:
    from anthropic import Anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False

CLAUDE_MODEL   = os.getenv("CLAUDE_HB_MODEL", "claude-3-5-sonnet-20241022")
MAX_TOKENS     = 2048

# ── Discord ───────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK = os.getenv(
    "NHL_HITS_BLOCKS_WEBHOOK",
    os.getenv("DISCORD_WEBHOOK_URL", "")
)

# ── NHL schedule API ──────────────────────────────────────────────────────────
NHL_SCHEDULE_API = "https://api-web.nhle.com/v1/schedule/{date}"


# ============================================================================
# PROMPT
# ============================================================================

PROMPT = """Today is {date}. Run the NHL daily hits & blocked shots task for tonight's NHL slates.

Tonight's scheduled games:
{games_context}

Requirements (follow exactly every time):
- Focus ONLY on hits and blocked shots props (lowest-variance NHL categories).
- Give me exactly 8 highest-probability plays (players + exact line, e.g. "Over 2.5 Blocked Shots" or "Over 3.5 Hits").
- Only players with locked-in 20-23+ min TOI roles (top-pair D, heavy-minute shutdown forwards, etc.).
- Justify each with: season avg + recent form (last 5-10 games), opposing team's style (high-shot-volume for blocks or physical/forecheck-heavy for hits), and expected game flow.
- CRITICAL: Only include games with zero blowout risk - favorites no heavier than -170 ML (ideally lighter), moderate puck lines, totals in the 5.5-6.5 range. No early-hook scripts or lopsided games. Exclude any game that fails this filter.
- Cover tonight's games only. If fewer than 8 qualifying legs, repeat strong ones or note it - but aim for 8 distinct.
- All players must be confirmed good-to-go (no rest, injury, or scratch flags - use your best knowledge of current roster status).
- Format exactly like this:

  1. **Player Name Over X.5 Category** (Team @ Opponent)
     - Season avg: ... ; recent form: ...
     - Matchup: ...
     - Game flow: ...
     - Vegas: ML, puck line, O/U.

  (Repeat for 2-8)

**Flex build tip**: [One sentence on how to stack 4-6 of these in PrizePicks Flex, prioritizing moderate-ML games.]

End with exactly: "These are the sharpest floor-based hits/blocks legs on the board for PrizePicks Flex."

Additional rules:
- Never add extra commentary outside the format.
- Use your knowledge of this NHL season's stats, player roles, and team playing styles.
- Note: Vegas lines are estimates based on your training data - always verify current lines before placing bets.
- Prioritize defensemen for blocks and physical/energy forwards for hits.
- Keep justifications concise but data-driven.
- If no games qualify under the zero-blowout rule, state that clearly and suggest alternatives only if needed.
"""


# ============================================================================
# DATABASE
# ============================================================================

def _ensure_db():
    """Create the hits_blocks.db and table if they don't exist."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_picks (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date          TEXT NOT NULL,
            generated_at      TEXT NOT NULL,
            raw_output        TEXT NOT NULL,
            model             TEXT DEFAULT '',
            prompt_tokens     INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            games_count       INTEGER DEFAULT 0,
            UNIQUE(run_date)
        )
    """)
    conn.commit()
    conn.close()


def _save(run_date, output, model, prompt_tok, comp_tok, games_count):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO daily_picks
        (run_date, generated_at, raw_output, model,
         prompt_tokens, completion_tokens, games_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        run_date, datetime.now().isoformat(), output, model,
        prompt_tok, comp_tok, games_count,
    ))
    conn.commit()
    conn.close()


def load_picks(run_date: str = None) -> dict:
    """Load picks for a date (or latest if None)."""
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
    if run_date:
        row = conn.execute(
            "SELECT run_date, generated_at, raw_output, model, "
            "prompt_tokens, completion_tokens, games_count "
            "FROM daily_picks WHERE run_date = ?",
            (run_date,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT run_date, generated_at, raw_output, model, "
            "prompt_tokens, completion_tokens, games_count "
            "FROM daily_picks ORDER BY run_date DESC LIMIT 1"
        ).fetchone()
    conn.close()
    if not row:
        return {}
    keys = ["run_date", "generated_at", "raw_output", "model",
            "prompt_tokens", "completion_tokens", "games_count"]
    return dict(zip(keys, row))


def load_recent(n: int = 7) -> list:
    """Return the n most recent pick records (metadata only, no raw_output)."""
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT run_date, generated_at, model, games_count "
        "FROM daily_picks ORDER BY run_date DESC LIMIT ?",
        (n,)
    ).fetchall()
    conn.close()
    return [dict(zip(["run_date", "generated_at", "model", "games_count"], r))
            for r in rows]


# ============================================================================
# SCHEDULE FETCH
# ============================================================================

def _fetch_games(target_date: str) -> tuple:
    """
    Fetch tonight's NHL games.
    Returns (context_string, games_count).
    """
    try:
        url = NHL_SCHEDULE_API.format(date=target_date)
        req = urllib.request.urlopen(url, timeout=10)
        data = json.loads(req.read())

        lines = []
        for day_block in data.get("gameWeek", []):
            if day_block.get("date") == target_date:
                for g in day_block.get("games", []):
                    away  = g.get("awayTeam", {}).get("abbrev", "???")
                    home  = g.get("homeTeam", {}).get("abbrev", "???")
                    start = g.get("startTimeUTC", "")[:16]   # "2026-03-25T23:00"
                    venue = g.get("venue", {}).get("default", "")
                    lines.append(f"  - {away} @ {home}  |  {start} UTC  |  {venue}")

        if not lines:
            return "  No games found in NHL schedule API for this date.", 0
        return "\n".join(lines), len(lines)

    except Exception as e:
        return f"  [Schedule fetch failed: {e}]", 0


# ============================================================================
# DISCORD
# ============================================================================

def _post_discord(text: str, run_date: str, webhook: str) -> bool:
    """Post picks to Discord, splitting at 1900 chars to respect 2000-char limit."""
    if not webhook:
        print("[Discord] No webhook URL set (NHL_HITS_BLOCKS_WEBHOOK)")
        return False

    header = f"**NHL Hits & Blocks - {run_date}**\n\n"
    full   = header + text
    chunks = []
    MAX    = 1900

    # Try to split on double newline so plays stay intact
    parts   = full.split("\n\n")
    current = ""
    for part in parts:
        if len(current) + len(part) + 2 > MAX:
            if current:
                chunks.append(current.strip())
            current = part
        else:
            current += ("\n\n" if current else "") + part
    if current:
        chunks.append(current.strip())

    success = True
    for i, chunk in enumerate(chunks):
        try:
            payload = json.dumps({"content": chunk}).encode("utf-8")
            req = urllib.request.Request(
                webhook,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            if i < len(chunks) - 1:
                time.sleep(0.6)     # avoid Discord rate limit
        except Exception as e:
            print(f"[Discord] Error on chunk {i+1}: {e}")
            success = False

    return success


# ============================================================================
# MAIN RUNNER
# ============================================================================

def run(target_date: str = None,
        post_discord: bool = False,
        force: bool = False) -> dict:
    """
    Generate NHL hits/blocks picks for target_date via Claude API.

    Args:
        target_date:  YYYY-MM-DD (defaults to today)
        post_discord: post output to Discord webhook
        force:        overwrite existing picks for this date

    Returns dict with keys: success, run_date, output, [error]
    """
    if not CLAUDE_AVAILABLE:
        return {"success": False,
                "error": "anthropic package not installed. Run: pip install anthropic"}

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return {"success": False, "error": "ANTHROPIC_API_KEY environment variable not set"}

    run_date = target_date or date.today().isoformat()
    _ensure_db()

    # Skip if already done today
    if not force:
        existing = load_picks(run_date)
        if existing:
            print(f"[H+B] Picks already exist for {run_date}. Use --force to regenerate.")
            return {
                "success": True, "run_date": run_date,
                "output": existing["raw_output"], "skipped": True,
            }

    # Fetch schedule context
    print(f"[H+B] Fetching NHL schedule for {run_date}...")
    games_context, games_count = _fetch_games(run_date)
    print(f"[H+B] {games_count} game(s) found")

    if games_count == 0:
        msg = f"No NHL games scheduled for {run_date}."
        print(f"[H+B] {msg}")
        return {"success": True, "run_date": run_date, "output": msg, "no_games": True}

    # Build prompt
    prompt = PROMPT.format(date=run_date, games_context=games_context)

    # Call Claude
    print(f"[H+B] Calling Claude API ({CLAUDE_MODEL})...")
    client = Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        output        = resp.content[0].text
        prompt_tok    = resp.usage.input_tokens
        comp_tok      = resp.usage.output_tokens
        print(f"[H+B] {len(output)} chars | {prompt_tok} prompt + {comp_tok} completion tokens")
    except Exception as e:
        return {"success": False, "run_date": run_date, "error": str(e)}

    # Persist
    _save(run_date, output, CLAUDE_MODEL, prompt_tok, comp_tok, games_count)
    print(f"[H+B] Saved to DB ({DB_PATH})")

    # Discord
    if post_discord:
        ok = _post_discord(output, run_date, DISCORD_WEBHOOK)
        print(f"[H+B] Discord post: {'OK' if ok else 'FAILED'}")

    return {
        "success": True,
        "run_date": run_date,
        "output": output,
        "prompt_tokens": prompt_tok,
        "completion_tokens": comp_tok,
        "games_count": games_count,
    }


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate NHL daily hits & blocked shots picks via Claude API"
    )
    parser.add_argument("--date",    default=None,
                        help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--discord", action="store_true",
                        help="Post output to Discord after generating")
    parser.add_argument("--force",   action="store_true",
                        help="Regenerate even if picks already exist for this date")
    parser.add_argument("--show",    action="store_true",
                        help="Print latest saved picks and exit (no API call)")
    args = parser.parse_args()

    if args.show:
        picks = load_picks()
        if picks:
            print(f"\n{'='*70}")
            print(f"NHL Hits & Blocks — {picks['run_date']}  "
                  f"(generated {picks['generated_at'][:16]})")
            print(f"Model: {picks['model']}  |  "
                  f"Tokens: {picks['prompt_tokens']}p + {picks['completion_tokens']}c")
            print(f"{'='*70}\n")
            print(picks["raw_output"])
        else:
            print("No picks found. Run without --show to generate.")
        sys.exit(0)

    result = run(
        target_date=args.date,
        post_discord=args.discord,
        force=args.force,
    )

    if result.get("success"):
        if result.get("skipped"):
            print("(Cached — pass --force to regenerate)")
        elif result.get("no_games"):
            print("No games tonight.")
        else:
            print(f"\n{'='*70}\n")
            print(result.get("output", ""))
    else:
        print(f"ERROR: {result.get('error')}")
        sys.exit(1)
