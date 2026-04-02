# SportsPredictor — Project Status
_Snapshot: 2026-04-01_

---

## System Overview

Multi-sport ML prediction pipeline targeting PrizePicks props and game lines.

| Sport | Status | Predictions | Outcomes | Model |
|-------|--------|-------------|---------|-------|
| NBA | ✅ Live | 181,664 SQLite / 202,789 Supabase | 129,882 graded | ML active (19 models) |
| NHL | ✅ Live | 62,309 SQLite / 63,885 Supabase | 56,059 graded | ML active (5 models) |
| MLB | ✅ Live (new) | 13,194 SQLite / 7,327 Supabase | 4,510 graded | Statistical only |
| Golf | 🔄 Data collection | In DB | Being graded | Backtest only |

---

## Supabase (Cloud) State

| Table | Rows | Notes |
|-------|------|-------|
| `daily_props` | 274,001 | Primary prediction store — NHL + NBA + MLB, Nov 2024 → today |
| `daily_games` | 33 | Live scores |
| `profiles` | 1 | Single user (you) |
| `user_picks`, `user_bets`, `watchlist` | 0 | App tables — waiting for users |

**New schema tables** (`sports_games`, `player_game_logs`, `predictions` etc.) — **NOT created**. The handoff doc's full migration plan was evaluated and deemed unnecessary — `daily_props` already contains the prediction data in Supabase.

---

## SQLite Databases

| Database | Path | Size | Key Tables |
|----------|------|------|-----------|
| NHL | `nhl/database/nhl_predictions_v2.db` | 77 MB | predictions (62k), outcomes (56k), game_logs (40k) |
| NBA | `nba/database/nba_predictions.db` | 208 MB | predictions (182k), outcomes (130k), game_logs (32k) |
| MLB | `mlb/database/mlb_predictions.db` | 46 MB | predictions (13k), outcomes (4.5k), game_logs (74k) |
| PrizePicks | `shared/prizepicks_lines.db` | 187 MB | 618,819 historical lines |
| Bets | `scoreboard/bets.db` | <1 MB | game_bets (29), prop_bets (1) ⚠️ |
| Golf | `golf/database/golf_predictions.db` | 24 MB | active |

---

## Known Gaps (Confirmed by Audit)

| Gap | Impact | Priority |
|-----|--------|----------|
| `goalie_stats` always empty (NHL) | Missing matchup signal for NHL predictions | HIGH |
| `game_prediction_outcomes` empty (MLB) | Can't measure MLB game bet P&L | HIGH |
| `prop_bets` has 1 row | True ROI unknown | HIGH |
| `model_versions` always empty | No model performance history | MEDIUM |
| Dead line predictions | Noise in picks, wasted capacity | MEDIUM |
| Occasional DNP players | Rare but happens | LOW |

---

## Architecture

```
PrizePicks API → shared/prizepicks_lines.db
                         ↓
Schedule APIs  →  generate_predictions_daily.py (NHL/NBA/MLB/Golf)
                         ↓
              nhl/nba/mlb/golf databases (SQLite)
                         ↓
              sync/supabase_sync.py (daily)
                         ↓
              Supabase → daily_props (274k rows)
                         ↓
              FreePicks mobile app (React Native, Expo)
```

**Orchestrator** (`orchestrator.py`) schedules all of the above 24/7.
**Discord bot** (`discord_bot.py`) provides `!picks`, `!parlay`, `!refresh`, `!status` commands.
**Dashboard** (`dashboards/cloud_dashboard.py`) on port 8502 via Cloudflare tunnel.

---

## ML Models

- **Status**: LIVE — `LEARNING_MODE = False` for NHL and NBA
- **Latest**: v20260315_001 (trained Mar 15, 2026)
- **NBA**: 14 models (Brier improved +0.07–0.12 vs prior)
- **NHL**: 5 models (points, shots — hits/blocked_shots still collecting data)
- **MLB**: Statistical only (not yet trained — season just started)
- **Auto-retrain**: Every Sunday, NHL 3:30 AM / NBA 5:30 AM CST
- **Registry**: `ml_training/model_registry/` (gitignored — large binaries)

---

## Git / GitHub

- **Repo**: `thomascp2/SportsPredictor`
- **Branch**: `master` only (all feature branches deleted 2026-04-01)
- **Latest commit**: `e45d662` — Merge golf module + system upgrades
- **Remote**: Clean — only `origin/master`

---

## Performance Targets vs Actuals

| Sport | Direction | Target | Current |
|-------|-----------|--------|---------|
| NHL | UNDER | 70%+ | 74.4% ✅ |
| NHL | OVER | 55%+ | 54.6% ⚠️ |
| NHL | Overall | — | 67.9% |
| NBA | UNDER | 65%+ | 84.2% ✅ |
| NBA | OVER | 55%+ | 61.2% ✅ |
| NBA | Overall | — | 80.0% |

---

## Environment

- **OS**: Windows 11 Home
- **Python**: 3.13
- **Shell**: Git Bash
- **Key env vars**: `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `DISCORD_WEBHOOK_URL`
- **Startup**: `start_orchestrator.bat`, `start_bot.bat`, `start_dashboard.bat` (gitignored — contain credentials)
- **Windows Defender**: Must exclude Python site-packages to prevent sklearn/scipy import hang
