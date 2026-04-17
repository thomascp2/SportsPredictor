import os
import sys
import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# Load .env if XAI_API_KEY not already in environment
if not os.environ.get("XAI_API_KEY"):
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

DB_PATHS = {
    "NBA": PROJECT_ROOT / "nba" / "database" / "nba_predictions.db",
    "NHL": PROJECT_ROOT / "nhl" / "database" / "nhl_predictions_v2.db",
    "MLB": PROJECT_ROOT / "mlb" / "database" / "mlb_predictions.db",
}

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

SCHEMA_CONTEXT = """You are StatBot — a SQL assistant for the SportsPredictor database system.
Translate natural language questions into SQLite queries.
Return ONLY valid JSON: {"db": "NBA|NHL|MLB", "sql": "SELECT ...", "note": "one-line plain English explanation"}

SEASON NOTE: "this season" or current season = game_date >= '2025-10-01'. All dates stored as 'YYYY-MM-DD'.
TODAY = date('now') in SQLite.

=== NBA DATABASE ===
player_game_logs:
  game_id TEXT, game_date TEXT, player_name TEXT, team TEXT, opponent TEXT, home_away TEXT,
  minutes REAL, points INT, rebounds INT, assists INT, steals INT, blocks INT,
  turnovers INT, threes_made INT, fga INT, fgm INT, fta INT, ftm INT,
  plus_minus INT, pra INT (points+rebounds+assists), stocks INT (steals+blocks)

predictions:
  game_date TEXT, player_name TEXT, team TEXT, opponent TEXT, home_away TEXT,
  prop_type TEXT, line REAL, prediction TEXT (OVER/UNDER), probability REAL, model_version TEXT

prediction_outcomes:
  game_date TEXT, player_name TEXT, prop_type TEXT, line REAL,
  prediction TEXT (OVER/UNDER), actual_value REAL, outcome TEXT (HIT/MISS), profit REAL

=== NHL DATABASE ===
player_game_logs:
  game_id TEXT, game_date TEXT, player_name TEXT, team TEXT, opponent TEXT,
  is_home INT (1=home 0=away), goals INT, assists INT, points INT,
  shots_on_goal INT, hits INT, blocked_shots INT, toi_seconds INT,
  plus_minus INT, pim INT (penalty minutes)

predictions:
  game_date TEXT, player_name TEXT, team TEXT, opponent TEXT, prop_type TEXT,
  line REAL, prediction TEXT (OVER/UNDER), probability REAL,
  confidence_tier TEXT (T1-ELITE/T2-STRONG/T3-GOOD/T4-LEAN/T5-FADE),
  expected_value REAL

prediction_outcomes:
  game_date TEXT, player_name TEXT, prop_type TEXT, line REAL,
  prediction TEXT (OVER/UNDER), actual_value REAL, outcome TEXT (HIT/MISS),
  confidence_tier TEXT, profit REAL

=== MLB DATABASE ===
player_game_logs:
  game_id TEXT, game_date TEXT, player_name TEXT, team TEXT, opponent TEXT,
  home_away TEXT, player_type TEXT (batter/pitcher),
  -- Pitcher stats: innings_pitched REAL, outs_recorded INT, strikeouts_pitched INT,
  --   walks_allowed INT, hits_allowed INT, earned_runs INT, pitches INT
  -- Batter stats: at_bats INT, hits INT, home_runs INT, rbis INT, runs INT,
  --   stolen_bases INT, walks_drawn INT, strikeouts_batter INT, doubles INT,
  --   triples INT, total_bases INT, hrr INT, batting_order INT

predictions:
  game_date TEXT, player_name TEXT, team TEXT, prop_type TEXT, line REAL,
  prediction TEXT (OVER/UNDER), probability REAL

prediction_outcomes:
  game_date TEXT, player_name TEXT, prop_type TEXT, line REAL,
  prediction TEXT (OVER/UNDER), actual_value REAL, outcome TEXT (HIT/MISS), profit REAL

QUERY PATTERNS:
- "How many times has [player] gone over [X] [stat]" -> COUNT(*) from player_game_logs WHERE [stat_col] > X
- "Hit rate for [prop]" -> prediction_outcomes GROUP BY prop_type with hit%
- "Best picks today" -> predictions WHERE game_date = date('now') ORDER BY probability DESC LIMIT 10
- "[Player]'s last N games" -> player_game_logs WHERE player_name LIKE '%name%' ORDER BY game_date DESC LIMIT N
- Player name matching: use LIKE '%lastname%' for partial matches
- For "this season" always add: AND game_date >= '2025-10-01'
- pra column exists directly in NBA player_game_logs — do not compute it
"""


def _get_client():
    """Returns (client, provider, model) using XAI_API_KEY (Grok)."""
    xai_key = os.environ.get("XAI_API_KEY")
    if not xai_key:
        return None, None, None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=xai_key, base_url="https://api.x.ai/v1")
        return client, "xai", "grok-3-mini"
    except ImportError:
        return None, None, None


def _call_ai(question, client, provider, model):
    """Send question to AI, return parsed JSON dict."""
    if provider == "xai":
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SCHEMA_CONTEXT},
                {"role": "user", "content": question},
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
    elif provider == "anthropic":
        response = client.messages.create(
            model=model,
            max_tokens=600,
            system=SCHEMA_CONTEXT,
            messages=[{"role": "user", "content": question}],
        )
        raw = response.content[0].text.strip()
    else:
        raise RuntimeError("No AI provider available.")

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def _execute_query(db_key, sql):
    """Returns (rows, error_string). rows is None on error."""
    path = DB_PATHS.get(db_key.upper())
    if not path or not path.exists():
        return None, f"Database '{db_key}' not found at {path}"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql).fetchall()
        conn.close()
        return rows, None
    except Exception as e:
        conn.close()
        return None, str(e)


def _format_table(rows):
    """Pretty-print sqlite3.Row results as a table."""
    if not rows:
        return f"  {YELLOW}(no rows returned){RESET}"
    cols = list(rows[0].keys())
    data = [[str(r[c]) if r[c] is not None else "NULL" for c in cols] for r in rows[:50]]
    widths = [max(len(c), max(len(d[i]) for d in data)) for i, c in enumerate(cols)]
    sep   = "  " + "  ".join("-" * w for w in widths)
    header = "  " + "  ".join(c.ljust(w) for c, w in zip(cols, widths))
    lines = [f"{BOLD}{header}{RESET}", sep]
    for row_data in data:
        lines.append("  " + "  ".join(v.ljust(w) for v, w in zip(row_data, widths)))
    if len(rows) > 50:
        lines.append(f"  {DIM}... and {len(rows) - 50} more rows (showing first 50){RESET}")
    return "\n".join(lines)


def run_statbot():
    print(f"\n{BOLD}{CYAN}============================================================{RESET}")
    print(f"{BOLD}   STATBOT -- Natural Language Sports Database Query{RESET}")
    print(f"{BOLD}{CYAN}============================================================{RESET}")
    print(f"  Ask anything about NBA, NHL, or MLB player/prediction data.")
    print(f"  {DIM}Examples:{RESET}")
    print(f"  {DIM}  > How many times has Tyrese Maxey gone over 34.5 pra this season?{RESET}")
    print(f"  {DIM}  > Show me Nikita Kucherov's last 5 games{RESET}")
    print(f"  {DIM}  > What is our NBA points prop hit rate this season?{RESET}")
    print(f"  {DIM}  > Who are today's top NHL picks by probability?{RESET}")
    print(f"  Type {BOLD}exit{RESET} or {BOLD}q{RESET} to return to Mission Control.\n")

    client, provider, model = _get_client()
    if not client:
        print(f"  {RED}XAI_API_KEY not found in environment.{RESET}")
        print(f"  Make sure start_orchestrator.bat has been run in this session.\n")
        input(f"{CYAN}  Press Enter to return to menu...{RESET}")
        return

    print(f"  {GREEN}AI: xAI Grok ({model}){RESET}\n")

    while True:
        try:
            query = input(f"{BOLD}{CYAN}StatBot >{RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not query:
            continue
        if query.lower() in ("exit", "quit", "q"):
            break

        print(f"  {DIM}Thinking...{RESET}", end="\r", flush=True)

        try:
            result = _call_ai(query, client, provider, model)
            db  = result.get("db", "NBA").upper()
            sql = result.get("sql", "")
            note = result.get("note", "")

            print(f"  {DIM}              {RESET}", end="\r")  # clear "Thinking..."
            if note:
                print(f"  {CYAN}> {note}{RESET}")
            print(f"  {DIM}[{db}] {sql}{RESET}\n")

            rows, err = _execute_query(db, sql)

            if err:
                print(f"  {RED}SQL Error: {err}{RESET}")
                print(f"  {YELLOW}Try rephrasing your question.{RESET}")
            elif rows is not None:
                if rows:
                    print(_format_table(rows))
                    print(f"\n  {GREEN}{len(rows)} row(s) returned.{RESET}")
                else:
                    print(f"  {YELLOW}No results found in {db} database for that query.{RESET}")

        except json.JSONDecodeError:
            print(f"  {DIM}              {RESET}", end="\r")
            print(f"  {RED}Could not parse AI response. Try rephrasing.{RESET}")
        except Exception as e:
            print(f"  {DIM}              {RESET}", end="\r")
            print(f"  {RED}Error: {e}{RESET}")

        print()

    print(f"\n  {CYAN}StatBot session ended.{RESET}\n")


if __name__ == "__main__":
    run_statbot()
