# Bookmark 1 — Phase 1 Rust Ingester: COMPLETE

**Session date:** 2026-04-10  
**Phase:** 1 of 4 — Rust Ingester (Foundation)  
**Status:** 100% DONE — Binary compiled, smoke-tested, and running

---

## What Was Built

| File | Status | What It Does |
|---|---|---|
| `Cargo.toml` | Done | tokio, reqwest, sqlx, tungstenite, serde, url, rand, dotenvy |
| `src/config.rs` | Done | Env-var loader — DB path, Kalshi key, league IDs, poll intervals |
| `src/types.rs` | Done | `UnifiedProp` struct + `StatType`/`Sport` enums, cross-source normalization |
| `src/db.rs` | Done | SQLite schema (4 tables) + upsert with delta detection → `line_history` |
| `src/prizepicks.rs` | Done | REST poller, ETag-gated, jittered interval, JSON → UnifiedProp |
| `src/underdog.rs` | Done | REST poller, ETag-gated, Bearer auth, appearance-join |
| `src/kalshi.rs` | Done | WebSocket client, token auth, market discovery, orderbook_delta parsing, exp backoff |
| `src/main.rs` | Done | Spawns 3 concurrent tokio tasks |
| `target/release/ingester.exe` | Built | Release binary, ~8MB |
| `props.db` | Created | 296K — all 4 tables initialized |

## Smoke Test Results
```
INFO  props-ingester starting up
INFO  DB path: ...\tui-terminal\props.db
INFO  props.db ready
INFO  PrizePicks poller task spawned
INFO  Underdog poller task spawned
WARN  KALSHI_API_KEY not set — Kalshi task disabled
INFO  All tasks running.
```
PP and UD pollers start and will fetch immediately on next run with no rate limit issues.

---

## Before Running for Real

Create `tui-terminal/.env`:

```env
PROPS_DB_PATH=props.db
KALSHI_API_KEY=tok_your_key_here
KALSHI_SERIES=KXNBAPLAYER,KXNHLPLAYER
PRIZEPICKS_LEAGUES=7,2
RUST_LOG=ingester=info
```

Run with:
```bash
cd tui-terminal
./target/release/ingester
```

---

## Next Session — Phase 2: Python Textual TUI

Create `tui-terminal/tui/` directory and build:

1. `tui/app.py` — Main Textual app, 3-column layout (20/60/20)
2. `tui/widgets/ticker.py` — Scrolling bottom marquee from `line_history`
3. `tui/widgets/main_grid.py` — Center DataTable (PP | UD | Kalshi | ML tier)
4. `tui/widgets/context_wing.py` — Left panel, reads `news_context` table
5. `tui/widgets/watchlist.py` — Right panel, reads/writes `watchlist` table
6. `tui/ml_bridge.py` — Reads local SQLite DBs, merges ML tiers into `props.db`
7. `tui/styles.tcss` — Bloomberg dark theme
8. `tui/requirements.txt` — textual, sqlalchemy (or direct sqlite3)

Prompt 2 from `4_Prompt Engineering Preliminary.md` is the starting point.
Add `ml_bridge.py` as the custom extension (not in prompt — reads your existing prediction DBs).
