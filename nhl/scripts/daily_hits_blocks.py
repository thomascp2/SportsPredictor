"""
NHL Daily Hits & Blocked Shots Picks — Grok Edition
=====================================================
Calls the xAI Grok API (which has live web search) with tonight's NHL
schedule and real Vegas odds injected as context, then generates 8
floor-based hits/blocks plays for PrizePicks Flex.

Completely standalone — no dependency on the main NHL prediction pipeline.
Storage: nhl/database/hits_blocks.db

Setup:
    pip install requests          # only dependency (usually already installed)

    # Required:
    export XAI_API_KEY="xai-..."

    # Optional but strongly recommended (500 free req/month):
    export ODDS_API_KEY="..."     # from https://the-odds-api.com  (free tier)

    # Optional:
    export NHL_HITS_BLOCKS_WEBHOOK="https://discord.com/api/webhooks/..."
    export GROK_HB_MODEL="grok-2-1212"   # default

Usage:
    cd nhl
    python scripts/daily_hits_blocks.py              # run for today
    python scripts/daily_hits_blocks.py --date 2026-03-26
    python scripts/daily_hits_blocks.py --discord    # run + post to Discord
    python scripts/daily_hits_blocks.py --force      # regenerate even if run today
    python scripts/daily_hits_blocks.py --show       # print latest saved picks
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

# ── xAI / Grok ────────────────────────────────────────────────────────────────
GROK_API_URL  = "https://api.x.ai/v1/chat/completions"
GROK_MODEL    = os.getenv("GROK_HB_MODEL", "grok-3")
MAX_TOKENS    = 2048

# ── The Odds API (optional — real-time Vegas lines) ───────────────────────────
ODDS_API_KEY    = os.getenv("ODDS_API_KEY", "")
ODDS_API_URL    = ("https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds/"
                   "?apiKey={key}&regions=us&markets=h2h,spreads,totals"
                   "&oddsFormat=american&dateFormat=iso")

# ── Discord ───────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK = os.getenv(
    "NHL_HITS_BLOCKS_WEBHOOK",
    os.getenv("DISCORD_WEBHOOK_URL", "")
)

# ── NHL schedule API ──────────────────────────────────────────────────────────
NHL_SCHEDULE_API = "https://api-web.nhle.com/v1/schedule/{date}"

# NHL full name → abbreviation (for matching Odds API team names)
_TEAM_NAME_TO_ABBR = {
    "anaheim ducks": "ANA", "boston bruins": "BOS", "buffalo sabres": "BUF",
    "calgary flames": "CGY", "carolina hurricanes": "CAR",
    "chicago blackhawks": "CHI", "colorado avalanche": "COL",
    "columbus blue jackets": "CBJ", "dallas stars": "DAL",
    "detroit red wings": "DET", "edmonton oilers": "EDM",
    "florida panthers": "FLA", "los angeles kings": "LAK",
    "minnesota wild": "MIN", "montreal canadiens": "MTL",
    "montreal canadiens": "MTL", "nashville predators": "NSH",
    "new jersey devils": "NJD", "new york islanders": "NYI",
    "new york rangers": "NYR", "ottawa senators": "OTT",
    "philadelphia flyers": "PHI", "pittsburgh penguins": "PIT",
    "san jose sharks": "SJS", "seattle kraken": "SEA",
    "st. louis blues": "STL", "tampa bay lightning": "TBL",
    "toronto maple leafs": "TOR", "utah hockey club": "UTA",
    "utah hc": "UTA", "vancouver canucks": "VAN",
    "vegas golden knights": "VGK", "washington capitals": "WSH",
    "winnipeg jets": "WPG",
}

def _abbr(full_name: str) -> str:
    return _TEAM_NAME_TO_ABBR.get(full_name.lower().strip(), full_name[:3].upper())


# ============================================================================
# PROMPT TEMPLATE
# ============================================================================

PROMPT = """You are an NHL hits & blocked shots analyst. Today is {date}.

ALL DATA BELOW IS VERIFIED AND CURRENT — do NOT disclaim about future dates or inability to access data. The stats, odds, and injury reports below were fetched moments ago from live APIs (ESPN, NHL.com, and our 38,000+ player game log database). Use ONLY this data for your analysis.

{enriched_data}

YOUR TASK:
Pick exactly 8 highest-probability OVER plays for hits and blocked shots props from the qualifying games above (games NOT marked as EXCLUDED).

RULES:
1. ONLY use players and stats from the verified data above. Do not invent or estimate stats.
2. ONLY pick from games that passed the blowout filter (not marked EXCLUDED).
3. Prioritize players with: highest season averages, trending UP in recent form, high TOI (20+ min), and favorable matchups (opponent has high shot volume for blocks, or physical style for hits).
4. Set the line at a realistic floor: if a player averages 2.4 blocks/game, suggest "Over 1.5 Blocked Shots" (not 2.5). The line should be BELOW their average for high probability.
5. Mix blocks and hits picks. Prioritize defensemen for blocks, physical forwards for hits.
6. All players must NOT appear on the injury list provided above.

FORMAT (follow exactly):

1. **Player Name Over X.5 Category** (Team @ Opponent)
   - Season avg: [use exact number from data above]; recent form: [use L14d data above]
   - Matchup: [reference opponent's shot volume from data above]
   - Game flow: [reference Vegas odds from data above]
   - Vegas: [exact ML, puck line, O/U from data above]

(Repeat for 2-8)

**Flex build tip**: [One sentence on stacking 4-6 in PrizePicks Flex from moderate-ML games.]

End with exactly: "These are the sharpest floor-based hits/blocks legs on the board for PrizePicks Flex."

Do NOT add disclaimers, caveats, or commentary outside this format.
"""

# ============================================================================
# DATABASE
# ============================================================================

def _ensure_db():
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
            odds_source       TEXT DEFAULT 'grok_search',
            UNIQUE(run_date)
        )
    """)
    # Add odds_source column if upgrading from older schema
    try:
        conn.execute("ALTER TABLE daily_picks ADD COLUMN odds_source TEXT DEFAULT 'grok_search'")
        conn.commit()
    except Exception:
        pass   # column already exists
    conn.commit()
    conn.close()


def _save(run_date, output, model, prompt_tok, comp_tok, games_count, odds_source):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO daily_picks
        (run_date, generated_at, raw_output, model,
         prompt_tokens, completion_tokens, games_count, odds_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        run_date, datetime.now().isoformat(), output, model,
        prompt_tok, comp_tok, games_count, odds_source,
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
            "prompt_tokens, completion_tokens, games_count, odds_source "
            "FROM daily_picks WHERE run_date = ?", (run_date,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT run_date, generated_at, raw_output, model, "
            "prompt_tokens, completion_tokens, games_count, odds_source "
            "FROM daily_picks ORDER BY run_date DESC LIMIT 1"
        ).fetchone()
    conn.close()
    if not row:
        return {}
    keys = ["run_date", "generated_at", "raw_output", "model",
            "prompt_tokens", "completion_tokens", "games_count", "odds_source"]
    return dict(zip(keys, row))


def load_recent(n: int = 14) -> list:
    """Return the n most recent dates that have picks saved."""
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT run_date FROM daily_picks ORDER BY run_date DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


# ============================================================================
# NHL SCHEDULE FETCH
# ============================================================================

def _fetch_schedule(target_date: str) -> list:
    """
    Return list of dicts: {away_abbr, home_abbr, away_full, home_full, start_utc, venue}
    """
    try:
        url = NHL_SCHEDULE_API.format(date=target_date)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FreePicks/1.0)"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        games = []
        for day_block in data.get("gameWeek", []):
            if day_block.get("date") == target_date:
                for g in day_block.get("games", []):
                    away_team = g.get("awayTeam", {})
                    home_team = g.get("homeTeam", {})
                    games.append({
                        "away_abbr":  away_team.get("abbrev", "???"),
                        "home_abbr":  home_team.get("abbrev", "???"),
                        "away_full":  away_team.get("name", {}).get("default",
                                      away_team.get("abbrev", "")),
                        "home_full":  home_team.get("name", {}).get("default",
                                      home_team.get("abbrev", "")),
                        "start_utc":  g.get("startTimeUTC", "")[:16],
                        "venue":      g.get("venue", {}).get("default", ""),
                    })
        return games
    except Exception as e:
        print(f"[H+B] Schedule fetch warning: {e}")
        return []


# ============================================================================
# ODDS API FETCH (optional)
# ============================================================================

def _fetch_odds() -> dict:
    """
    Fetch real-time NHL odds from The Odds API.
    Returns dict keyed by (away_abbr, home_abbr) -> formatted odds string.
    Free tier: 500 req/month  |  sign up at https://the-odds-api.com
    """
    if not ODDS_API_KEY:
        return {}
    try:
        url = ODDS_API_URL.format(key=ODDS_API_KEY)
        req = urllib.request.urlopen(url, timeout=15)
        games_raw = json.loads(req.read())

        odds_by_matchup = {}
        for game in games_raw:
            away_full  = game.get("away_team", "")
            home_full  = game.get("home_team", "")
            away_abbr  = _abbr(away_full)
            home_abbr  = _abbr(home_full)

            # Parse bookmaker markets (use first available US book)
            ml_away = ml_home = pl_away = pl_home = ou_total = None
            ou_over_price = ou_under_price = None

            for bm in game.get("bookmakers", []):
                for market in bm.get("markets", []):
                    key = market.get("key")
                    outcomes = {o["name"]: o for o in market.get("outcomes", [])}

                    if key == "h2h" and ml_away is None:
                        ml_away = outcomes.get(away_full, {}).get("price")
                        ml_home = outcomes.get(home_full, {}).get("price")

                    elif key == "spreads" and pl_away is None:
                        for o in market.get("outcomes", []):
                            pt = o.get("point", 0)
                            pr = o.get("price")
                            nm = o.get("name", "")
                            if nm == away_full and pt > 0:
                                pl_away = (pt, pr)   # away gets + spread
                            elif nm == home_full and pt < 0:
                                pl_home = (abs(pt), pr)

                    elif key == "totals" and ou_total is None:
                        for o in market.get("outcomes", []):
                            nm  = o.get("name", "")
                            pt  = o.get("point")
                            pr  = o.get("price")
                            if nm == "Over":
                                ou_total = pt
                                ou_over_price = pr
                            elif nm == "Under":
                                ou_under_price = pr

                # Stop after first bookmaker that gave us data
                if ml_away and pl_away and ou_total:
                    break

            # Format the line string
            parts = []
            if ml_away is not None and ml_home is not None:
                def fmt_ml(p):
                    return f"+{p}" if p > 0 else str(p)
                parts.append(
                    f"ML: {away_abbr} {fmt_ml(ml_away)} / {home_abbr} {fmt_ml(ml_home)}"
                )
            if pl_away is not None and pl_home is not None:
                def fmt_pl(side_abbr, pt, pr):
                    sign = "+" if pr > 0 else ""
                    return f"{side_abbr} +{pt} ({sign}{pr})"
                parts.append(
                    f"PL: {fmt_pl(away_abbr, pl_away[0], pl_away[1])} / "
                    f"{fmt_pl(home_abbr, pl_home[0], pl_home[1])}"
                )
            if ou_total is not None:
                def fmt_price(p):
                    return f"+{p}" if p > 0 else str(p)
                ou_str = f"O/U: {ou_total}"
                if ou_over_price and ou_under_price:
                    ou_str += (f" (Ov {fmt_price(ou_over_price)} / "
                               f"Un {fmt_price(ou_under_price)})")
                parts.append(ou_str)

            if parts:
                odds_by_matchup[(away_abbr, home_abbr)] = " | ".join(parts)

        return odds_by_matchup

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        print(f"[H+B] Odds API HTTP {e.code}: {body}")
        print("[H+B] Continuing without pre-fetched odds — Grok will search for lines")
        return {}
    except Exception as e:
        print(f"[H+B] Odds API warning: {e}")
        return {}


# ============================================================================
# BUILD GAME CONTEXT STRING
# ============================================================================

def _build_game_context(games: list, odds: dict) -> tuple:
    """
    Returns (context_string, games_count, odds_source_label).
    """
    if not games:
        return "  No NHL games found for tonight.", 0, "none"

    lines = []
    for g in games:
        away = g["away_abbr"]
        home = g["home_abbr"]
        start = g["start_utc"]

        line = f"  - {away} @ {home}"
        if g.get("venue"):
            line += f"  ({g['venue']})"
        if start:
            line += f"  |  {start} UTC"

        # Attach real odds if available
        matchup_odds = odds.get((away, home)) or odds.get((home, away))
        if matchup_odds:
            line += f"\n      {matchup_odds}"

        lines.append(line)

    odds_source = "the-odds-api.com (real-time)" if odds else "grok_live_search"
    return "\n".join(lines), len(games), odds_source


# ============================================================================
# GROK API CALL
# ============================================================================

def _call_grok(prompt: str, api_key: str) -> dict:
    """
    POST to xAI Grok API (OpenAI-compatible endpoint).
    Returns {"output": str, "prompt_tokens": int, "completion_tokens": int}
    """
    payload = json.dumps({
        "model": GROK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": MAX_TOKENS,
    }).encode("utf-8")

    req = urllib.request.Request(
        GROK_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "User-Agent":    "FreePicks/1.0",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())

    content = data["choices"][0]["message"]["content"]
    usage   = data.get("usage", {})
    return {
        "output":            content,
        "prompt_tokens":     usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
    }


# ============================================================================
# DISCORD
# ============================================================================

def _post_discord(text: str, run_date: str, webhook: str) -> bool:
    if not webhook:
        print("[Discord] No webhook set (NHL_HITS_BLOCKS_WEBHOOK)")
        return False

    header = f"**NHL Hits & Blocks - {run_date}**\n\n"
    full   = header + text
    chunks = []
    MAX    = 1900

    # Split cleanly on double-newline (keeps each play together)
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
                headers={
                    "Content-Type": "application/json",
                    "User-Agent":   "FreePicks/1.0",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            if i < len(chunks) - 1:
                time.sleep(0.6)
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
    Generate NHL hits/blocks picks for target_date via Grok API.

    Args:
        target_date:  YYYY-MM-DD (defaults to today)
        post_discord: post output to Discord webhook after generating
        force:        overwrite existing picks for this date

    Returns dict with keys: success, run_date, output, [error]
    """
    api_key = os.getenv("XAI_API_KEY", "").strip()
    if not api_key:
        return {
            "success": False,
            "error": (
                "XAI_API_KEY environment variable not set. "
                "Get a key at https://console.x.ai"
            )
        }

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

    # ── Step 1: Fetch NHL schedule ────────────────────────────────────────────
    print(f"[H+B] Fetching NHL schedule for {run_date}...")
    games = _fetch_schedule(run_date)
    print(f"[H+B] {len(games)} game(s) tonight")

    if not games:
        msg = f"No NHL games scheduled for {run_date}."
        print(f"[H+B] {msg}")
        return {"success": True, "run_date": run_date, "output": msg, "no_games": True}

    # ── Step 2: Enrich with real data (ESPN odds, player stats, injuries) ────
    try:
        from hb_data_enrichment import enrich_games
        print("[H+B] Enriching with real data (ESPN odds + player stats + injuries)...")
        enriched_data = enrich_games(run_date, games)
        odds_source = "espn_verified"
    except ImportError:
        print("[H+B] hb_data_enrichment.py not found, falling back to old method")
        enriched_data = None
        odds_source = "grok_live_search"

    # Fallback: old method if enrichment fails
    if enriched_data is None:
        odds = {}
        if ODDS_API_KEY:
            print("[H+B] Fetching real-time odds from The Odds API...")
            odds = _fetch_odds()
            print(f"[H+B] Got odds for {len(odds)} matchup(s)")
        games_context, games_count, odds_source = _build_game_context(games, odds)
        enriched_data = f"Tonight's scheduled games:\n{games_context}"

    games_count = len(games)

    # ── Step 3: Build prompt & call Grok ─────────────────────────────────────
    prompt = PROMPT.format(
        date=run_date,
        enriched_data=enriched_data,
    )

    print(f"[H+B] Calling Grok API ({GROK_MODEL})...")
    try:
        result = _call_grok(prompt, api_key)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"success": False, "run_date": run_date,
                "error": f"Grok API HTTP {e.code}: {body[:300]}"}
    except Exception as e:
        return {"success": False, "run_date": run_date, "error": str(e)}

    output   = result["output"]
    p_tokens = result["prompt_tokens"]
    c_tokens = result["completion_tokens"]
    print(f"[H+B] {len(output)} chars | {p_tokens}p + {c_tokens}c tokens")

    # ── Step 5: Persist ───────────────────────────────────────────────────────
    _save(run_date, output, GROK_MODEL, p_tokens, c_tokens, games_count, odds_source)
    print(f"[H+B] Saved to {DB_PATH}")

    # ── Step 6: Discord ───────────────────────────────────────────────────────
    if post_discord:
        ok = _post_discord(output, run_date, DISCORD_WEBHOOK)
        print(f"[H+B] Discord: {'OK' if ok else 'FAILED'}")

    return {
        "success": True,
        "run_date": run_date,
        "output": output,
        "prompt_tokens": p_tokens,
        "completion_tokens": c_tokens,
        "games_count": games_count,
        "odds_source": odds_source,
    }


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate NHL daily hits & blocked shots picks via Grok API"
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
            odds_src = picks.get("odds_source", "unknown")
            print(f"\n{'='*70}")
            print(f"NHL Hits & Blocks — {picks['run_date']}  "
                  f"(generated {picks['generated_at'][:16]})")
            print(f"Model: {picks['model']}  |  Odds: {odds_src}  |  "
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
            print("No NHL games tonight.")
        else:
            print(f"\n{'='*70}\n")
            print(result.get("output", ""))
    else:
        print(f"ERROR: {result.get('error')}")
        sys.exit(1)
