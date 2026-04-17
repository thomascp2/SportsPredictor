# TUI Terminal — "Bloomberg for Props" — Master Blueprint

*Consolidated from: 1_Initial Research Planning, 2_Continuation of Research Planning, 3_Design-Stack-Research-Planning, 4_Prompt Engineering Preliminary*  
*Cross-referenced against: SportsPredictor orchestrator, smart_pick_selector, pregame_intel, turso_sync*

---

## 1. What This Is

A **local-first, man-cave command center** that surfaces your existing ML model outputs alongside real-time market data (PrizePicks, Underdog, Kalshi) in a high-density terminal UI. The goal is to shift from a passive tracking system to an active **Arbitrage and Analysis Terminal** — the Bloomberg Terminal for prop betting.

### The Core Insight

Your existing SportsPredictor engine already produces:
- ML confidence scores + tiers (T1-ELITE through T5-FADE)
- Edge calculations vs. break-even by odds_type (standard/goblin/demon)
- Pregame intel via Grok (injuries, lineup changes, goalie confirmations)
- Smart picks already synced to Turso cloud

The TUI's job is to **display** this output + **overlay** real-time market signals (Kalshi prices, Underdog lines) so you can spot discrepancies the model can't see alone.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    EXISTING (SportsPredictor/)               │
│  orchestrator.py → smart_pick_selector.py → turso_sync.py   │
│  pregame_intel.py (Grok) → data/pregame_intel/{sport}.json  │
│  Local SQLite DBs → Turso Cloud (already synced)            │
└──────────────────────┬──────────────────────────────────────┘
                       │ reads ML data + smart picks
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  tui-terminal/props.db  (new local SQLite)   │
│  ┌──────────────────┐   writes   ┌──────────────────────┐   │
│  │  Rust Ingester   │ ─────────► │ current_lines table  │   │
│  │  (Kalshi WS +    │            │ line_history table   │   │
│  │   UD + PP REST)  │            │ volatility_events    │   │
│  └──────────────────┘            └──────────────────────┘   │
│                                          │                   │
│  ┌──────────────────┐   reads    ┌──────────────────────┐   │
│  │  Intel Layer     │ ◄───────── │ Python TUI           │   │
│  │  (Gemini/Grok)   │ ─writes──► │ (Textual, main)      │   │
│  │  volatility-     │ news_ctx   │ (Heatmap, secondary) │   │
│  │  triggered       │            └──────────────────────┘   │
│  └──────────────────┘                                        │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow in Plain Terms

1. **Rust sidecar** runs headless — WebSocket to Kalshi, REST polling to Underdog + PrizePicks, writes normalized rows to `tui-terminal/props.db`
2. **Python ML bridge** (at startup + 5-min refresh) reads from your local SQLite DBs (or Turso) and merges ML confidence + tier + edge into `props.db`
3. **Python Intel service** monitors `props.db` for volatility triggers → fires Gemini/Grok → writes summaries to `news_context` table
4. **Textual TUI** reads `props.db` every 1 second — pure local disk I/O, near-zero latency — renders the command center
5. **Heatmap app** reads the same `props.db` for the secondary monitor — no text, just colored tiles

---

## 3. What Already Exists (Do Not Rebuild)

| Component | File | What It Gives You |
|---|---|---|
| ML predictions + tiers | `nhl/database/nhl_predictions_v2.db`, `nba/database/nba_predictions.db` | Confidence, tier, edge, OVER/UNDER |
| Smart picks | `shared/smart_pick_selector.py` + Turso | Filtered, ML-validated plays for today |
| PP lines | `shared/prizepicks_client.py` | Already fetched by orchestrator at 3:30 AM + pp-sync |
| Pregame intel (Grok) | `shared/pregame_intel.py` | Injuries, OUT/DOUBTFUL, goalie starts, cached daily |
| Turso cloud | `sync/turso_sync.py` | Already mirrored — TUI can read from local SQLite instead |
| Discord alerts | `orchestrator.py` | Line move alerts can mirror here |

**Critical reuse rule:** The TUI reads ML data; it does NOT run predictions. `smart_pick_selector.py` already ran this morning. The TUI displays its output + overlays market signals.

---

## 4. New Components to Build (tui-terminal/)

```
tui-terminal/
├── BLUEPRINT.md              ← this file
├── props.db                  ← TUI-specific SQLite (auto-created)
├── Cargo.toml                ← Rust workspace root
├── src/
│   └── ingester/             ← Rust sidecar binary
│       ├── main.rs
│       ├── kalshi.rs         ← WebSocket client
│       ├── underdog.rs       ← REST poller
│       ├── prizepicks.rs     ← REST poller (mirrors PP lines already in main DBs)
│       └── schema.rs         ← UnifiedProp struct + DB writer
├── tui/
│   ├── app.py                ← Main Textual app (ultra-wide layout)
│   ├── widgets/
│   │   ├── ticker.py         ← Scrolling bottom marquee
│   │   ├── main_grid.py      ← Center DataTable (PP vs UD vs Kalshi + ML)
│   │   ├── context_wing.py   ← Left panel — Gemini/Grok intel feed
│   │   └── watchlist.py      ← Right panel — queued plays
│   ├── ml_bridge.py          ← Reads local SQLite DBs → merges into props.db
│   └── styles.tcss           ← Bloomberg dark theme CSS
├── intel/
│   └── context_engine.py     ← Volatility watcher → Gemini search → news_context table
└── heatmap/
    └── app.py                ← Secondary monitor — tile-based color display
```

---

## 5. Database Schema (props.db)

```sql
-- Core unified lines table
CREATE TABLE current_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id       TEXT NOT NULL,          -- normalized key: "jokic_nikola_nba"
    name            TEXT NOT NULL,
    team            TEXT,
    opponent        TEXT,
    sport           TEXT NOT NULL,          -- 'NBA', 'NHL', 'MLB'
    stat_type       TEXT NOT NULL,          -- 'NBA_POINTS', 'NHL_SHOTS', etc.

    -- Market lines
    prizepicks_line REAL,
    underdog_line   REAL,
    kalshi_price    REAL,                   -- cents (0.62 = 62% implied probability)
    kalshi_market_id TEXT,

    -- ML model output (written by ml_bridge.py)
    ml_confidence   REAL,                   -- 0.0-1.0
    ml_prediction   TEXT,                   -- 'OVER' or 'UNDER'
    ml_tier         TEXT,                   -- 'T1-ELITE' .. 'T5-FADE'
    ml_edge         REAL,                   -- edge above break-even (%)
    odds_type       TEXT,                   -- 'standard', 'goblin', 'demon'

    -- Discrepancy flag
    line_discrepancy REAL,                  -- abs(pp_line - ud_line), NULL if one missing
    is_volatile     INTEGER DEFAULT 0,      -- 1 if recent big move

    last_updated    TEXT NOT NULL           -- ISO timestamp
);

-- Line movement history (for ticker + volatility detection)
CREATE TABLE line_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   TEXT NOT NULL,
    source      TEXT NOT NULL,              -- 'prizepicks', 'underdog', 'kalshi'
    old_value   REAL,
    new_value   REAL,
    delta       REAL,
    recorded_at TEXT NOT NULL
);

-- Gemini/Grok context output
CREATE TABLE news_context (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   TEXT NOT NULL,
    summary     TEXT NOT NULL,              -- <=20 words
    source_api  TEXT NOT NULL,              -- 'gemini' or 'grok'
    trigger     TEXT,                       -- what triggered it: "kalshi_move:+0.12"
    created_at  TEXT NOT NULL
);

-- Your watchlist / queued plays
CREATE TABLE watchlist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   TEXT NOT NULL,
    stat_type   TEXT NOT NULL,
    note        TEXT,
    added_at    TEXT NOT NULL
);
```

---

## 6. Display Layout (Ultra-Wide + Secondary)

### Primary Monitor (Curved Ultra-Wide)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  [FreePicks Terminal]  Bankroll: $500  Active: 3  Date: 2026-04-10 14:32 CST│
├───────────────┬──────────────────────────────────────────┬───────────────────┤
│  CONTEXT WING │              THE GRID (CENTER)            │    WATCHLIST      │
│   20% width   │             60% width                     │    20% width      │
│               │                                           │                   │
│ [INTEL FEED]  │ Player       Prop  PP    UD   Kalshi  ML  │ [Queued Plays]    │
│               │ ─────────────────────────────────────────│                   │
│ Tatum OUT —   │ Jokic N.     PTS  25.5  26.0  0.62  T1  ││ Jokic O25.5 T1   │
│ ankle, per    │ Curry S.     PTS  22.5  22.5  0.55  T2  ││ Fox D.  U18.5 T2 │
│ Wojnarowski   │ Fox D.       PTS  18.5  17.5  0.43  T2  ││                   │
│               │ Murray J.    PTS  19.5   —     —    T3  ││ [Press ENTER to   │
│ Goalie:       │ Tkachuk M.   SHT   4.5  4.5  0.58  T1  ││  clear watchlist] │
│ Shesterkin    │ ...          ...  ...   ...   ...   ...  ││                   │
│ confirmed     │                                           │                   │
│               │                                           │                   │
│ [↑↓ to select │                                           │                   │
│  ENTER = add  │                                           │                   │
│  to watchlist]│                                           │                   │
├───────────────┴──────────────────────────────────────────┴───────────────────┤
│ TICKER ► Jokic line +0.5 on UD (25.5→26.0) ▪ Fox line DISCREPANCY PP18.5/UD17.5 ▪ ... │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Secondary Monitor (Above, large)

```
┌──────────────────────────────────────────────────────┐
│         HEATMAP — VALUE SCANNER                       │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │
│  │              │ │              │ │              │ │
│  │     NBA      │ │     NHL      │ │     MLB      │ │
│  │   ████████   │ │   ▓▓▓▓▓▓     │ │    ░░░░░░    │ │
│  │  3 T1-ELITE  │ │  1 T1-ELITE  │ │  No Value    │ │
│  │   GREEN      │ │   AMBER      │ │    GRAY      │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ │
│                                                      │
│   VOLATILE: Fox D. — PP/UD discrepancy +1.0pt       │
└──────────────────────────────────────────────────────┘
```

**Color logic:**
- GREEN — T1-ELITE picks available, no negative intel  
- AMBER — T2/T3 picks or Grok flags a caution  
- RED — Active negative intel (injury, rest) overriding model  
- GRAY — No plays of value  
- FLASHING — Kalshi move >10% or PP/UD discrepancy >1.0pt in last 15 min

---

## 7. The Four Build Phases (from Prompt Engineering Doc)

### Phase 1 — Foundation: Rust Ingester + DB Schema

**Goal:** Headless sidecar that keeps `props.db` current.

**What the prompt builds:**
- Rust binary: `tokio` + `reqwest` + `sqlx` (libSQL/SQLite target)
- Kalshi V2 WebSocket: `/trade-api/v2/markets/orderbooks`, persistent connection, exponential backoff on reconnect
- Underdog REST: `reqwest` with ETag/If-Modified-Since to avoid redundant parses, 30s jittered interval
- PrizePicks REST: same pattern (mirrors the Python `prizepicks_client.py` already in main codebase — Rust version here is solely for the TUI props.db, does not replace the main fetcher)
- `UnifiedProp` struct normalized across all three sources
- UPSERT into `current_lines` on every line change; INSERT into `line_history` for every delta

**Key integration note:** The PP REST call here is a lightweight duplicate for real-time line monitoring. The authoritative PP fetch for predictions still runs in `orchestrator.py`.

**Stick to Prompt 1 verbatim** (4_Prompt Engineering Preliminary.md) when building.

---

### Phase 2 — The UI: Python Textual (Ultra-Wide)

**Goal:** The main terminal interface.

**What the prompt builds:**
- Three-column Textual layout (20/60/20)
- `DataTable` in center: columns = Player | Prop | PP Line | UD Line | Kalshi | ML Tier | Edge | Discrepancy
- Color coding: GREEN value (positive edge, no alert), RED drop (T5 or negative intel), AMBER volatile
- Custom `Ticker` widget bottom: scrolls at 60 FPS, text sourced from `line_history WHERE recorded_at > now-15min ORDER BY abs(delta) DESC`
- `DataTable` refreshes via `set_interval(1.0, self._reload_table)` — reads local SQLite only, no network calls on refresh
- Keyboard shortcuts: `↑↓` navigate rows, `ENTER` = add to watchlist, `i` = force intel fetch for selected player, `q` = quit

**ml_bridge.py** (not in original prompts but needed): Runs at startup and every 5 minutes. Reads `nhl/database/nhl_predictions_v2.db` and `nba/database/nba_predictions.db` (or Turso if preferred), pulls today's smart picks, merges `ml_confidence`, `ml_prediction`, `ml_tier`, `ml_edge`, `odds_type` into `props.db.current_lines` by player name matching.

**Also reuses `pregame_intel.py`** at app startup: reads the cached JSON at `data/pregame_intel/{sport}_{date}.json` and pre-populates `news_context` with any OUT/DOUBTFUL/QUESTIONABLE flags. No new Grok call — just surfaces the cache that orchestrator already built.

**Stick to Prompt 2 verbatim** when building, then add `ml_bridge.py` as a thin addition.

---

### Phase 3 — Intelligence: Gemini Context Engine

**Goal:** Real-time context for line moves, volatility-triggered only.

**What the prompt builds:**
- Python watcher: polls `line_history` every 60 seconds
- Volatility trigger: Kalshi price move >10% OR PP/UD line move >1.0pt within 15 minutes
- On trigger: fires Gemini API (`google-generativeai` SDK) with Google Search retrieval tool
- Prompt template: `"Search for the latest news on [Player Name]. Why is their betting line moving? Check for injuries, resting, or coach comments. Summarize in 15 words or less."`
- Writes result to `news_context` table; TUI Context Wing auto-refreshes from this table

**Key decision — Gemini vs. Grok:**  
Your `pregame_intel.py` already uses **Grok** (xAI) for daily sweeps. Use **Gemini** here for live volatility triggers (free tier, separate quota). The two complement each other: Grok fires once at prediction time for a full sweep; Gemini fires on-demand for specific line moves during the day.

**Free tier management:** Set a daily budget cap (e.g., 10 Gemini calls/day). Log call count to `props.db`. Skip if budget exceeded.

**Stick to Prompt 3 verbatim** when building, but add the budget cap.

---

### Phase 4 — Heatmap: Secondary Monitor App

**Goal:** Heads-up macro view for the second screen.

**What the prompt builds:**
- Separate lightweight Textual app: `heatmap/app.py`
- Three league tiles: NBA / NHL / MLB
- Tile color = best tier available in `current_lines` for that sport, weighted by Gemini intel flags
- Large text only — player names in 24pt equiv, tier count — readable from 5 feet
- Flash behavior: pulsing tile border if `is_volatile = 1` row exists for that sport
- Refresh every 2 seconds from `props.db`

**Stick to Prompt 4 verbatim** when building.

---

## 8. Integration Points Back to SportsPredictor Root

These are the ONLY times `tui-terminal/` reaches into the parent SportsPredictor project:

| Need | How | Direction |
|---|---|---|
| Today's ML smart picks | `ml_bridge.py` reads `../nba/database/nba_predictions.db` and `../nhl/database/nhl_predictions_v2.db` | Read-only |
| Pregame intel cache | Reads `../data/pregame_intel/{sport}_{date}.json` | Read-only |
| Turso cloud (optional) | Can use same Turso env vars (`TURSO_NBA_URL` etc.) to read cloud replica instead of local SQLite | Read-only |

**Nothing in tui-terminal writes to the main SportsPredictor databases.** The main pipeline runs independently; the TUI is a consumer only.

---

## 9. Environment Variables Needed

```bash
# Already in your .env / bat files
TURSO_NBA_URL, TURSO_NBA_TOKEN        # If reading from Turso instead of local SQLite
TURSO_NHL_URL, TURSO_NHL_TOKEN

# New for TUI
KALSHI_API_KEY                        # Kalshi V2 credentials
UNDERDOG_AUTH_TOKEN                   # UD mobile header / token
GEMINI_API_KEY                        # Google AI Studio free tier
XAI_API_KEY                           # Already exists — pregame_intel uses it
```

---

## 10. Build Order & Self-Containment Rule

**Rule:** Every file lives in `tui-terminal/` except reads of existing SQLite/Turso data. Do not add new files to root `SportsPredictor/` as part of this build.

**Build order:**
1. `Phase 1` — Rust ingester (get data landing in props.db before touching UI)
2. `Phase 2` — Textual app skeleton with static mock data, then wire to live props.db
3. Add `ml_bridge.py` — merge ML data into props.db
4. Add pregame intel reader — surface Grok cache in Context Wing on startup
5. `Phase 3` — Intel service (wire Gemini to volatility events)
6. `Phase 4` — Heatmap secondary app

**Testing at each step:** Run `python tui/app.py` with only props.db populated from mock data before wiring to live APIs. Validate layout on ultra-wide resolution first.

---

## 11. The Man Cave Setup Checklist

| Component | Tech | Built From | Status |
|---|---|---|---|
| Rust Ingester | Rust (tokio + sqlx) | Prompt 1 | Not started |
| TUI Main App | Python Textual | Prompt 2 | Not started |
| ML Bridge | Python (sqlite3) | Custom addition | Not started |
| Pregame Cache Reader | Python | Reuses pregame_intel.py pattern | Not started |
| Intel Engine | Python + Gemini API | Prompt 3 | Not started |
| Heatmap App | Python Textual | Prompt 4 | Not started |
| props.db schema | SQLite | Section 5 above | Not started |

---

## 12. Pro Tips for the Curved Setup

- Keep the **active betting grid in the center 50%** of the ultra-wide. On a large curve, looking at extreme corners causes fatigue — put "slow" data (24h news feed) on the outer wings.
- Use **Textual CSS `padding`** on the far edges: `padding: 0 8;` on the outer column containers.
- The **secondary monitor above** should have nothing below 24pt text — it's meant to be read at a glance without moving your head. The heatmap tiles should have names at `text-style: bold; font-size: 2em`.
- On Windows: set `PYTHONIOENCODING=utf-8` before launching the TUI (same as orchestrator does). Textual handles most unicode fine but player names with diacritics can trip up the `DataTable` — use `_strip_diacritics()` from `smart_pick_selector.py` when writing to `current_lines.name`.
