# MASTER TODO — FreePicks / SportsPredictor / Apex Arb
**Last compiled: 2026-04-23**
**Sources:** Session logs Apr 23 (morning/evening/night/DNP-fix), V2_MIGRATION_STRATEGY.md, hlss/MASTER_PLAN.md, docs/ROADMAP.md, docs/TODO.md

---

## STATUS LEGEND
- ✅ Done
- 🔄 In Progress / Partially Done
- ⬜ Pending
- ⏸ Gated (blocked by something else)
- 📅 Scheduled (has a target date)

---

## TRACK 1 — DATA QUALITY (SportsPredictor Production)
*All three major issues resolved Apr 23. A few loose ends remain.*

### ✅ DONE — Completed Apr 23 2026
- ✅ `pp_rules_validator.py` — single source of truth for PrizePicks business rules
- ✅ DNP_INFLATION fix — zero-stat games (actual=0) grade as HIT/MISS not VOID
- ✅ IMPOSSIBLE_COMBO fix — demon+UNDER and goblin+UNDER voided retroactively
- ✅ odds_type mislabeling fix — generator now stores correct goblin/demon/standard from day 1
- ✅ DUPLICATE_LINE tagging — multi-line prediction rows deduped, one canonical row kept
- ✅ Dashboard win rate queries — `data_quality_flag IS NULL` filter added to all 7 locations
- ✅ MLB generator odds_type fix — same fix as NBA applied to `mlb/scripts/generate_predictions_daily.py`
- ✅ db_cleanup.py performance rewrite — Python dict lookups replace hanging cross-DB SQL join
- ✅ Turso sync — `data_quality_flag` column added + 87,280 flagged rows pushed to cloud
- ✅ `tools/sync_data_quality_flags.py` — one-shot tool for future flag syncs

### ⬜ PENDING — Data Quality Loose Ends

| Priority | Task | Detail |
|----------|------|--------|
| **HIGH** | **Confirmed-losing prop guards** | Requires user confirmation per CLAUDE.md before adding to `smart_pick_selector.py`. Guards ready to add: |
| | NHL shots UNDER | 44.3% hit rate vs 52.38% BE → -8.1% edge |
| | NHL points UNDER | 20.2% hit rate → -32.2% edge |
| | NHL hits UNDER | 40.0% hit rate → -12.4% edge (40 samples) |
| | NBA turnovers UNDER | 46.8% hit rate → -5.6% edge |
| | NBA blocked_shots UNDER | 18.9% hit rate → -33.5% edge |
| | NBA steals UNDER | 11.7% hit rate → -40.7% edge |
| | MLB hrr UNDER | 48.3% hit rate → -4.1% edge |
| | MLB outs_recorded UNDER | 38.3% hit rate → -14.1% edge |
| | MLB pitcher_walks UNDER | 43.3% hit rate → -9.1% edge |
| | MLB earned_runs UNDER | 30.4% hit rate → -22.0% edge |
| **MED** | **Investigate trivial-line 99-100% hit props** | NHL points OVER 99% (0.5 lines?), NBA steals goblin OVER 99.5%, NBA blocked_shots 94-96%, MLB batter_strikeouts goblin 100%. Likely needs minimum-line filter or "trivial line" flag. |
| **MED** | **Mirror all guard changes to SportsPredictor_linux** | Every `smart_pick_selector.py` change must be applied to both `SportsPredictor\` and `SportsPredictor_linux\` then pushed to GitHub. |
| **LOW** | **Pre-Dec 2025 dedup tie-break** | ~17K rows not in prizepicks_lines DB; median tie-break doesn't handle ties. Low priority. |
| **LOW** | **MLB hrr demon OVER monitoring** | 68.8% on 32 samples — watch as sample grows, re-evaluate at 100+ samples. |

### True Baselines (post all fixes, is_smart_pick=1, data_quality_flag IS NULL)
| Sport | Win Rate | Clean Rows |
|-------|----------|------------|
| NHL | **57.4%** | 10,722 |
| NBA | **67.2%** | 54,287 |
| MLB | **60.1%** | 1,656 |

---

## TRACK 2 — V2 MIGRATION (5-Phase Plan)
*Source: `SportsPredictor_linux/V2_MIGRATION_STRATEGY.md`*
*Repo: https://github.com/thomascp2/Agentic-Agency-SP-V1-V2*

### Phase 1 — V1 Linux Migration ✅ COMPLETE (Apr 23 2026)
- ✅ Strip Windows paths, hardcoded paths, secrets
- ✅ Create `.env.example` (30+ vars), `.gitattributes`, `start_orchestrator.sh`, `start_dashboard.sh`, `start_bot.sh`
- ✅ Fix `mlb_feature_store/ml/predict_to_db.py` — date lock and SQL injection
- ✅ Push clean repo to GitHub

### Phase 2 — VPS Deployment & V1 Stabilization ⬜ NEXT
**⚠️ SERVER CHANGE: Switched from DigitalOcean → Oracle Cloud Free Tier (Ampere ARM)**
Oracle Cloud Always Free: 4x Ampere A1 cores (ARM64/aarch64) + 24GB RAM — significantly more powerful than DO's $24/mo x86 droplet at no cost.

#### ARM Compatibility Check (Oracle Ampere A1 = aarch64)
All key dependencies ship ARM64 wheels — no source compilation needed:

| Package | ARM64 Wheel? | Notes |
|---------|-------------|-------|
| `numpy>=1.24` | ✅ | Official ARM64 wheels on PyPI |
| `scikit-learn>=1.3` | ✅ | Official ARM64 wheels |
| `xgboost>=2.0` | ✅ | ARM64 wheels since v1.6 |
| `scipy` | ✅ | ARM64 wheels |
| `duckdb>=1.1.3` | ✅ | ARM64 wheels |
| `libsql-client>=0.3` | ✅ | Pure Python (no native ext) |
| `streamlit` | ✅ | Pure Python |
| `crewai` (Phase 4) | ✅ | Pure Python |
| `lightgbm` | ✅ | ARM64 wheels |
| `pandas` | ✅ | ARM64 wheels |

**One potential issue:** `tui-terminal/src/kalshi.rs` (Rust binary) must be compiled on ARM — it won't run a Windows or x86 Linux binary. When Phase 5 wires the Kalshi Rust CLI, `cargo build --release` must run on the Oracle VPS itself.

#### Oracle Cloud Setup Steps
- ⬜ Create Oracle Cloud account → Always Free tier (no credit card charge)
- ⬜ Provision VM: **VM.Standard.A1.Flex** — 4 OCPUs, 24GB RAM, Ubuntu 22.04 ARM64
- ⬜ Open ingress rules: port 22 (SSH), 8502 (dashboard), 8600 (PEGASUS API)
- ⬜ `ssh ubuntu@<OCI_IP>` — confirm ARM: `uname -m` should return `aarch64`
- ⬜ `sudo apt update && sudo apt install -y python3-pip python3-venv git screen`
- ⬜ `git clone https://github.com/thomascp2/Agentic-Agency-SP-V1-V2.git /hlss`
- ⬜ `python3 -m venv /hlss/.venv && source /hlss/.venv/bin/activate`
- ⬜ `pip install -r requirements.txt && pip install -r mlb_feature_store/requirements.txt`
- ⬜ **ARM smoke test:** `python -c "import xgboost, duckdb, sklearn; print('ARM OK')"` — must pass before proceeding
- ⬜ `cp .env.example .env` — fill in all secrets from `start_orchestrator.bat` on Windows
- ⬜ `mkdir -p nhl/database nba/database mlb/database golf/database mlb_feature_store/data`
- ⬜ Transfer SQLite DBs from Windows (use WinSCP, scp via WSL, or rsync):
  ```
  scp nhl/database/nhl_predictions_v2.db ubuntu@<OCI_IP>:/hlss/nhl/database/
  scp nba/database/nba_predictions.db ubuntu@<OCI_IP>:/hlss/nba/database/
  scp mlb/database/mlb_predictions.db ubuntu@<OCI_IP>:/hlss/mlb/database/
  scp golf/database/golf_predictions.db ubuntu@<OCI_IP>:/hlss/golf/database/
  scp mlb_feature_store/data/mlb.duckdb ubuntu@<OCI_IP>:/hlss/mlb_feature_store/data/
  ```
- ⬜ Smoke test: `python orchestrator.py --sport nba --mode once --operation prediction`
- ⬜ Smoke test: `python orchestrator.py --sport nba --mode once --operation grading`
- ⬜ Set up systemd service (preferred over screen — survives reboots):
  ```ini
  # /etc/systemd/system/freepicks.service
  [Service]
  User=ubuntu
  WorkingDirectory=/hlss
  EnvironmentFile=/hlss/.env
  ExecStart=/hlss/.venv/bin/python orchestrator.py --sport all --mode continuous
  Restart=on-failure
  RestartSec=30
  ```
- ⬜ `sudo systemctl enable freepicks && sudo systemctl start freepicks`
- ⬜ Test dashboard: `streamlit run dashboards/cloud_dashboard.py --server.port 8502`
- ⬜ Optional: GitHub Actions CI/CD — add `VPS_HOST` + `VPS_SSH_KEY` as repo secrets

### Phase 3 — The Founder Agent ⏸ (after Phase 2)
- ⬜ Send Founder prompt to `claude-sonnet-4-6` on fresh VPS
- ⬜ Review and execute `setup_v2.sh` (installs CrewAI, DuckDB, heartbeat schema)
- ⬜ Verify heartbeat table at `/hlss/data/heartbeat.db`
- ⬜ Verify `v2/tools/predict_tool.py` (subprocess wrapper for mlb_feature_store)
- ⬜ Verify `v2/main.py` starts without error (Managing Director heartbeat loop)

### Phase 4 — The Agent Firm (CrewAI) ⏸ (after Phase 3)
- ⬜ Wire all 11 agent tool wrappers (predict, grade, fetch, intel, etc.)
- ⬜ Test hierarchical CrewAI process with Managing Director
- ⬜ Verify daily schedule triggers (05:00, 08:00, 12:00 CST phases)
- ⬜ Verify Discord alerts fire on heartbeat miss (>30 min gap)
- ⬜ Test: SRE → Plumber → Insider → Quant → Validator chain
- ⬜ Test: Market Monitor line delta → CRO Kelly size → Executioner alert

**Agent roster (11 agents):**
| Agent | Model | Role |
|-------|-------|------|
| Managing Director | sonnet-4-6 | Orchestration, heartbeat, task delegation |
| Architect | sonnet-4-6 | Code generation, API research |
| SRE | haiku-4-5 | API health pings at 5 AM |
| Data Plumber | haiku-4-5 | Box score ingestion → SQLite |
| The Insider | haiku-4-5 | Rotowire/Grok injury sweep |
| The Quant | haiku-4-5 | BMA probability distributions |
| The Validator | haiku-4-5 | Grading + drift detection |
| Market Monitor | haiku-4-5 | PP + DK line scanning every 5 min |
| CRO | haiku-4-5 | Fractional Kelly sizing |
| Executioner | haiku-4-5 | Kalshi API hedge execution |
| Data Broker | haiku-4-5 | B2B syndication research (weekly) |

### Phase 5 — V2 Full Build / hlss Integration ⏸ (after Phase 4)
- ⬜ Write Python wrapper for Kalshi API (from `tui-terminal/src/kalshi.rs` logic)
- ⬜ Wire BMA engine (`hlss/bma_engine.py`) into Quant agent
- ⬜ Build V1↔V2 DB bridge (shared read from SQLite + orchestrator.db)
- ⬜ Build prop line diff tracker for DraftKings (delta between model prob and DK line)
- ⬜ Test end-to-end arb detection → Kelly size → Executioner alert
- ⬜ Wire Snowball recursive compounding logic (`arb_calculator.py`)
- ⬜ DraftKings prop-level line movement tracker (The Odds API has DK lines but no delta yet)

---

## TRACK 3 — APEX ARB ENGINE (hlss MASTER_PLAN.md)
*Source: `/c/Users/thoma/hlss/MASTER_PLAN.md`*
*The 4-phase plan to build a capital-efficient recursive arbitrage engine.*

### Phase 1 — Intelligence Core (ML & Signal Layer) 🔄 PARTIALLY DONE

| Status | Item |
|--------|------|
| ✅ | BMA engine (`bma_engine.py`) — weighted model averaging + confidence score |
| ✅ | Thompson Sampling MAB weights (`weight_manager.py`) — 7-day rolling window |
| ✅ | KS drift detector (`ml_training/drift_detector.py`) — detects scoring environment changes |
| ✅ | BMA inference layer (`ml_training/production_predictor.py`) |
| ⬜ | **Every signal produces True Probability (P) + 95% Confidence Interval (CI)** — CI output not yet wired into pick output schema |
| ⬜ | **Validate BMA output calibration** — does the BMA's P align with real outcomes within 5% over 500 trials? (Key success metric from MASTER_PLAN) |

### Phase 2 — Linking & Execution Layer ⬜ PARTIALLY DONE

| Status | Item |
|--------|------|
| ✅ | Universal Linker (`linker.py`) — fuzzy name matching across PP/Kalshi/DK |
| ✅ | `arb_calculator.py` — PP→Kalshi hedge math (the CSA math is written) |
| ✅ | `data_orchestrator/odds_client.py` — The Odds API wrapper |
| ⬜ | **Kalshi Python API client** — `arb_calculator.py` has the math but no live API calls. `tui-terminal/src/kalshi.rs` is Rust — need Python wrapper or rewrite. Secrets: `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH` |
| ⬜ | **CSA State Machine** — Step A: place PP promo entry (Taco). Step B: monitor live result. Step C: only if Leg 1 wins, execute Kalshi hedge on Leg 2. "Let it Die" logic if Leg 1 fails |
| ⬜ | **DraftKings line scanner** — detect when DK moves a prop (22.5→25.5) while PP is stale |

### Phase 3 — Snowball & Market-Maker Engine ⏸ (after Phase 2)
- ⬜ Move from Market Orders to **Limit Orders** on Kalshi (act as liquidity provider)
- ⬜ Set "No" prices based on BMA's True Probability to capture bid-ask spread
- ⬜ Snowball Level 1: protect principal ($1,000)
- ⬜ Snowball Level 2+: isolate "Arb Credit" (profits), use to fund exponentially larger positions
- ⬜ "The Apex Trade" — pivot to "Middle" strategy (bet OVER 23.5 on PP + No on 21.5 on Kalshi)

### Phase 4 — Institutional Scaling & Risk Control ⏸ (after Phase 3)
- ⬜ VaR monitoring across entire sequential chain
- ⬜ Cross-venue routing: if Kalshi liquidity low → route partial hedges to Polymarket or sportsbooks
- ⬜ Fractional Kelly Criterion weighted by BMA Confidence Score → determines "Slam" size
- ⬜ WebSocket-based data feeds (minimize latency, avoid being picked off by bots)

**Key Success Metrics (from MASTER_PLAN.md):**
- Net-of-fee yield > 3% (arb spread must exceed Kalshi taker/maker fees)
- BMA True Probability within 5% of real outcomes over 500 trials
- Snowball returns initial principal by Level 3 of any recursive chain

---

## TRACK 4 — FREEPICKS APP (7-Phase Roadmap)
*Source: `SportsPredictor_linux/docs/ROADMAP.md`*

### Phase 1 — Foundation ✅ COMPLETE (Feb 14 2026)
### Phase 2 — Dashboard & Data Infrastructure ✅ COMPLETE (Mar 2 2026)
### Phase 5 — ML Upgrade ✅ COMPLETE (Feb 23 2026)
*(Note: NBA ML reverted Apr 5 after Mar 15 retrain wrecked UNDER accuracy — back to statistical. Retrain Oct 2026.)*

### Phase 3 — Mobile Launch ⬜ ~Apr 2026
- ⬜ Discord OAuth — discord.com/developers → OAuth2 → copy ID+Secret → Supabase Auth
- ⬜ Google OAuth — Google Cloud Console → Credentials → OAuth 2.0 Client
- ⬜ Apple Sign-In — Apple Developer Portal
- ⬜ First device test via Expo Go: sign-in → picks appear → make pick → grade fires
- ⬜ Test watchlist (add/remove, max 10)
- ⬜ Test parlay builder
- ⬜ UI polish: loading skeletons, error states, offline banner, a11y pass
- ⬜ Expo EAS Build — `.ipa` and `.apk`
- ⬜ TestFlight (iOS internal testing)
- ⬜ Deploy dashboard to Streamlit Community Cloud (permanent URL — no more tunnel restarts)

### Phase 4 — Social & Discovery ⬜ ~May 2026
- ⬜ Global leaderboard (daily / weekly / all-time)
- ⬜ Sport-specific leaderboards + personal rank + percentile
- ⬜ Follow / friend system + friend feed
- ⬜ Shareable pick card (image export for social)
- ⬜ Public profile page
- ⬜ Push notifications: daily props reminder, pick graded, game started
- ⬜ Weekly challenge system + badges + seasonal achievements
- ⬜ Player news integration (injury / lineup alerts)

### Phase 6 — Monetization ⬜ ~Jun 2026
- ⬜ FreePicks Plus (~$4.99/mo): unlimited picks, advanced stats, early access, ad-free
- ⬜ Banner ads + interstitial + rewarded video (free tier)
- ⬜ "Bet this pick" deep-link to affiliate sportsbooks (DraftKings / FanDuel)
- ⬜ Legal compliance review by state
- ⬜ Enterprise / white-label API licensing

### Phase 7 — Correlated Parlay Optimizer ⬜ ~Aug 2026
- ⬜ Player-pair correlation matrix (Pearson r on shared game dates)
- ⬜ Team-level correlation (teammates vs opponents)
- ⬜ Zero-sum / game-total awareness (NBA ~115 pts/game distributed across ~8 players)
- ⬜ Parlay construction engine: maximize combined EV subject to correlation cap
- ⬜ Daily "PARLAY OF THE DAY" Discord post (6:20 AM CST)
- ⬜ "Smart Parlays" tab in FreePicks app

---

## TRACK 5 — ML RETRAINING CALENDAR
*Source: project_ml_retrain_plans.md + session logs*

| Date | Action |
|------|--------|
| **May 15, 2026** | MLB game_context ~450 rows — validate HIGH_TOTAL/HR_BOOST flag accuracy |
| **Jun 1, 2026** | MLB game_context ~700 rows — build Step 11a XGBoost if validation passes |
| **Aug 2026** | MLB player props at ~50K graded rows — flip `MODEL_TYPE="ensemble"` |
| **Oct 7, 2026** | NHL/NBA seasons open — trigger Oct retrain (NHL + NBA player props) |
| **Oct 2026** | NHL: audit v20260325_003 LR models → shadow mode → flip if passes |
| **Oct 2026** | NBA: retrain with LR only (delete bad v20260315_001 models first) |
| **Apr 2027** | ~1,200 NBA + 1,000 NHL game_context rows — build Step 11b game lines ML |

---

## TRACK 6 — PRODUCTION PIPELINE GAPS
*From docs/TODO.md (Apr 1) + session logs — items that may still be open*

| Priority | Task | Notes |
|----------|------|-------|
| MED | **Fix goalie_stats population** | Always 0 rows — NHL uses goalie matchup as feature but it's never populated |
| MED | **Wire MLB game_prediction_outcomes grading** | 0 rows today — can't calculate MLB game bet P&L |
| MED | **Fix prop_bets tracking** | Only 1 row in `scoreboard/bets.db` — true ROI unknown, `bets_import.csv` template exists but nothing wired |
| LOW | **Populate model_versions table** | Always empty — no historical model performance tracking; needed for retrain decisions |
| LOW | **Fix combo stat L5 stale bug** | After orchestrator restart, L5 game log features (last 5 games) are stale until new grading runs |
| LOW | **Fix dead pick filtering** | Still predicting on lines gone from PP by game time — waste / noise |
| MED | **Improve DNP filtering** | Scratched/OUT players occasionally sneak through — use pregame_intel more aggressively |

---

## KNOWN CONSTRAINTS (do not override without review)

- **NHL**: `MODEL_TYPE="statistical_only"` — season ended Apr 18. Retrain Oct 2026.
- **NBA**: `LEARNING_MODE=True` — reverted Apr 5. Mar 15 retrain wrecked UNDER (83%→47%). Retrain Oct 2026.
- **MLB**: `MODEL_TYPE="statistical_only"` — flip to ensemble at ~50K graded rows (~Aug 2026).
- **Golf**: No ML scaffolding. Scaffold post-season at 700+ samples/prop.
- **demon OVER guard**: permanent in `smart_pick_selector.py` — 29.41% hit vs 45.45% BE.
- **threes OVER guard**: permanent — 0% hit rate, degenerate model.
- **Do NOT touch** `parlay_lottery/` — out of scope.
- **Do NOT add KNOWN_EXTREME lines** without explicit user confirmation.
- **Do NOT flip any ML flags** without full retrain review.
- **Always mirror** `smart_pick_selector.py` changes to both `SportsPredictor\` and `SportsPredictor_linux\`.
