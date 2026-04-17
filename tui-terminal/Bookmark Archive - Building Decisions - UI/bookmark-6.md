# TUI Bookmark 6 — Apr 11 2026

## Status: ml_bridge rewrite done, smart_picks table missing, need fresh session

## What works
- Rust ingester: PP (NHL/NBA/MLB), odds_type now written correctly
- Kalshi: auth works (elections domain), ticker cache wired (600s backoff on 429)
- Grok intel: raw requests, confirmed 200 from API — needs TUI restart to pick up
- Grid filter: reads from smart_picks table (exact same picks as streamlit)

## Immediate next step (do this first in new session)

### 1. Create smart_picks table (one-time, until ingester runs)
```bash
cd ~/SportsPredictor/tui-terminal
python -c "
import sqlite3; conn=sqlite3.connect('props.db')
conn.execute('''CREATE TABLE IF NOT EXISTS smart_picks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, sport TEXT NOT NULL,
  player_name TEXT NOT NULL, team TEXT, opponent TEXT,
  stat_type TEXT NOT NULL, prediction TEXT NOT NULL,
  pp_line REAL NOT NULL, odds_type TEXT NOT NULL,
  probability REAL NOT NULL, edge REAL NOT NULL, tier TEXT NOT NULL,
  game_date TEXT NOT NULL, ev_4leg REAL, refreshed_at TEXT NOT NULL,
  UNIQUE(sport,player_name,stat_type,pp_line,odds_type,game_date))''')
conn.commit(); print('done')
"
```

### 2. Test bridge (run from SportsPredictor root)
```bash
cd ~/SportsPredictor && python tui-terminal/tui/ml_bridge.py 2>&1 | tail -10
```
Expected: NHL ~28 picks, NBA 0 (no games), MLB varies

### 3. Full relaunch
```bash
cd ~/SportsPredictor/tui-terminal && ./kill.sh
python -c "import sqlite3; c=sqlite3.connect('props.db'); c.execute('DELETE FROM current_lines'); c.execute('DELETE FROM line_history'); c.commit()"
./launch.sh
```

## Underdog
- Token not set. Get from browser devtools → underdog.com → any API request → Authorization header
- Add to tui-terminal/.env: UNDERDOG_AUTH_TOKEN=Bearer xxxxx
- Rust ingester already polls UD — just needs the token

## Key files changed this session
- src/kalshi.rs — elections domain, ticker cache (load/save_kalshi_tickers)
- src/db.rs — smart_picks + kalshi_tickers tables in schema
- src/prizepicks.rs — odds_type now passed through to UnifiedProp
- src/types.rs — odds_type field added to UnifiedProp
- tui/ml_bridge.py — FULL REWRITE: calls SmartPickSelector, writes to smart_picks
- tui/widgets/main_grid.py — query reads from smart_picks not current_lines
- tui/app.py — Grok raw requests, loads SportsPredictor/.env for XAI_API_KEY

## Known remaining issues
- MLB PP returning 429 intermittently (rate limited — poll interval may need increase)
- Kalshi still hitting 429 on first discovery attempt — needs 10min cooldown after restart
- UD shows no data until token added
