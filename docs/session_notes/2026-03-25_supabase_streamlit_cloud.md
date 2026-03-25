# Session Notes — 2026-03-25
## Supabase Sync + Streamlit Cloud Deployment Prep

### What We Built

#### 1. NHL Hits & Blocks Pipeline (`nhl/scripts/daily_hits_blocks.py`)
- Standalone script that generates 8 daily NHL hits/blocked-shots picks via the **xAI Grok API** (`grok-3` model — has live web search for real Vegas lines)
- Fetches NHL schedule from `api-web.nhle.com/v1/schedule/{date}` (requires `User-Agent` header or gets 403)
- Optionally injects real-time odds from **The Odds API** into the prompt as a guaranteed data source
- Saves output to `nhl/database/hits_blocks.db` (`daily_picks` table)
- Posts to Discord in ≤1900-char chunks (also needs `User-Agent` header)
- CLI flags: `--date`, `--discord`, `--force`, `--show`
- Env vars: `XAI_API_KEY` (required), `ODDS_API_KEY` (optional), `NHL_HITS_BLOCKS_WEBHOOK`

#### 2. Dashboard Additions (`dashboards/cloud_dashboard.py`)
- Added **"NHL Hits & Blocks"** tab (`tab_hb`) — date selector, rendered markdown picks, raw text expander
- Added **"PrizePicks SZLN ML"** inner tab inside MLB Season Props — filters, metrics, picks table, column guide
- Added `fetch_hb_picks()` and `fetch_hb_history()` reading from `hits_blocks.db`
- Added `fetch_szln_picks()` reading from `season_prop_ml_picks` SQLite table

#### 3. Supabase Fallbacks (all 6 data-fetchers)
Every fetch function now tries local SQLite first, then silently falls back to Supabase when the local DB doesn't exist (i.e., on Streamlit Cloud):

| Function | Supabase table |
|---|---|
| `fetch_picks()` | `daily_props` |
| `fetch_season_projections()` | `mlb_season_projections` |
| `fetch_szln_picks()` | `mlb_szln_picks` |
| `_evaluate_line()` | `mlb_season_projections` (ilike player name search) |
| `fetch_hb_picks()` | `nhl_hits_blocks_picks` |
| `fetch_hb_history()` | `nhl_hits_blocks_picks` |

#### 4. Supabase Sync Script (`shared/supabase_local_sync.py`)
- Upserts local SQLite → Supabase for all three new tables
- Functions: `sync_hits_blocks()`, `sync_season_projections()`, `sync_szln_picks()`, `sync_all()`
- CLI: `python shared/supabase_local_sync.py --all`
- Called automatically by orchestrator after every H+B run and SZLN refresh

#### 5. New Supabase Tables (`supabase_tables.sql`)
Three new tables to be created in Supabase SQL Editor:
- `nhl_hits_blocks_picks` — unique key: `run_date`
- `mlb_season_projections` — unique key: `(player_name, stat, season)`
- `mlb_szln_picks` — unique key: `(player_name, stat, line, fetched_at)`

#### 6. Orchestrator Updates (`orchestrator.py`)
- Added `hits_blocks_time = "11:00"` to NHL config (daily at 11am)
- Added `szln_refresh_time = "09:00"` to MLB config (Mondays at 9am)
- `run_nhl_hits_blocks()` auto-calls `sync_hits_blocks()` after a successful run
- `run_szln_ml_refresh()` auto-calls `sync_szln_picks()` + `sync_season_projections()` after a successful run

#### 7. Permanent URL (`start_dashboard.bat`)
- Switched from Cloudflare quick-tunnel (random URL every restart) to **ngrok static domain**
- Permanent URL: `https://benita-wedgelike-healingly.ngrok-free.dev`
- ngrok path: `%LOCALAPPDATA%\Microsoft\WindowsApps\ngrok.exe`

#### 8. Orchestrator .bat Hardening (`start_orchestrator.bat`)
- Added `XAI_API_KEY`, `ODDS_API_KEY`, `NHL_HITS_BLOCKS_WEBHOOK` as SET commands
- Added `tasklist` check before launching dashboard to prevent duplicate windows on orchestrator restart

### Bugs Fixed
- **NHL schedule API 403**: Fixed by adding `User-Agent: Mozilla/5.0 (compatible; FreePicks/1.0)` to urllib requests
- **Grok model name**: `grok-2-1212` doesn't exist — correct name is `grok-3` (confirmed via `GET /v1/models`)
- **The Odds API 401**: Free tier quota was exhausted — script handles gracefully, Grok searches for lines itself
- **Discord webhook 403**: Python's default urllib user-agent blocked — fixed with `User-Agent` header
- **`.bashrc` webhook trailing newline**: Notepad paste included a newline inside the quotes, causing malformed URL — fixed with precise Edit

### Environment Variables (as of this session)
Set in both `~/.bashrc` (Git Bash) and `start_orchestrator.bat` (Windows):
- `XAI_API_KEY` — xAI Grok API key
- `ODDS_API_KEY` — The Odds API key (free tier, 500 req/month)
- `NHL_HITS_BLOCKS_WEBHOOK` — Discord webhook for H+B channel
- `DISCORD_WEBHOOK_URL` — main Discord webhook
- `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` — set in `start_dashboard.bat`
- `ANTHROPIC_API_KEY` — still placeholder in `.bashrc`, not yet needed

### Pending (do tomorrow)
1. **Create Supabase tables** — paste `supabase_tables.sql` into Supabase SQL Editor
2. **Initial sync** — run `python shared/supabase_local_sync.py --all` from project root with Supabase env vars set
3. **Push to GitHub** — `git push origin master`
4. **Deploy to Streamlit Community Cloud** — share.streamlit.io → new app → add secrets → permanent URL, no warning page, free forever

### Key Files Changed This Session
```
dashboards/cloud_dashboard.py   — 6 Supabase fallbacks, H+B tab, SZLN tab
orchestrator.py                 — H+B + SZLN scheduling, auto-sync calls
shared/supabase_local_sync.py   — NEW: SQLite → Supabase sync script
supabase_tables.sql             — NEW: CREATE TABLE statements
start_dashboard.bat             — ngrok static domain
start_orchestrator.bat          — env vars, duplicate-window guard
nhl/scripts/daily_hits_blocks.py — NEW: Grok-powered H+B picks generator
~/.bashrc                       — API keys added
```
