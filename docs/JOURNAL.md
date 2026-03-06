# FreePicks — Project Journal

A running log of sessions, pivots, and decisions. Add an entry for each
working session. Detailed minutes live in `docs/sessions/YYYY-MM-DD.md`.

---

## 2026-03-06 — Edge Calculation Bug Fix (goblin/demon break-even)

**Sessions:** 1 (short)
**Status going in:** System healthy, orchestrator running
**Status coming out:** Systemic ai_edge bug found and fixed; 312 NHL + 1,179 NBA rows backfilled

### What happened
Noticed two NHL players on identical lines (shots goblin OVER 1.5) showing
similar edges despite very different probabilities: Hertl 76.4%/+20.4%, Hyman
94.9%/+18.9%. Diagnosed: `sync_odds_types()` was correctly relabeling rows from
'standard' to 'goblin' but never recalculating `ai_edge` against the goblin
break-even (76% vs standard's 56%). Players whose names didn't match in
`sync_smart_picks()` (name abbreviation issues — "T. Hertl" vs "Tomas Hertl")
fell through to `sync_odds_types()`, got the right label, but kept the wrong edge.

Fixed `sync_odds_types()` to recompute `ai_edge` for any row where the stored
edge doesn't match `(ai_probability − break_even[odds_type]) × 100`. Backfilled
today immediately. Hertl corrected: +20.4% → +0.4% (genuinely marginal pick).

### Key decision
Fix is fully systemic — runs on every row every day. Not a targeted patch.

**Detailed minutes:** `docs/sessions/2026-03-06.md`

---

## 2026-03-04 — DB Lock Recovery, Dashboard Review, Defender Fix

**Sessions:** 2 (morning + evening)
**Status going in:** NBA predictions 0 for Mar 4; grading 0 for Mar 3; zombie process holding DB lock
**Status coming out:** 1,047 Mar 4 predictions recovered; Defender exclusion applied; NBA tier display issue documented

### What happened
The orchestrator's 6:01 AM prediction run failed with `database is locked`. Root cause:
yesterday's manual `generate_predictions_daily_V6.py 2026-03-03 --force` (started during
the scipy-hang debugging session) was still running as a zombie process after 9+ hours —
it had hung on Windows Defender scanning scipy `.pyd` files and never exited, holding a
write lock on `nba_predictions.db`. Killed the zombie, ran Mar 4 predictions manually
(1,047 predictions, 518 smart picks), synced to Supabase. Mar 3 predictions remain at 0
permanently (games finished, training impact negligible).

Evening review of the dashboard revealed NBA picks showing all T1-ELITE (189 picks at
87.9% avg probability) vs NHL's T1–T3 spread. Investigated: Supabase actually has the
full tier spread (T1=373, T2=101, T3=116), but the dashboard's hard `.limit(200)` ordered
by probability DESC + the NBA ML models' high-confidence output means visible picks cluster
at T1-ELITE. Documented as a low-priority TODO. User applied the permanent fix: Python
site-packages added to Windows Defender exclusions — scipy/sklearn will no longer hang.

### Key decisions / pivots
- **Zombie process = always kill stray Python procs on session start.** Any manually-run
  prediction script that hangs will hold a DB write lock indefinitely. The orchestrator's
  next run will silently fail.
- **NBA T1-only display: accepted for now.** High model confidence is a good problem to
  have. The limit(200) + prob-sort means T2/T3 picks get squeezed out, but the shown
  picks are genuinely high-quality.
- **Windows Defender exclusion is the permanent scipy fix.** The lazy-import mitigation
  in `statistical_predictions.py` stays as belt-and-suspenders, but the root cause is now
  resolved at the OS level.

### What's blocked
- Discord / Google / Apple OAuth still not configured
- Streamlit Community Cloud permanent deployment still pending

**Detailed minutes:** `docs/sessions/2026-03-04.md`

---

## 2026-02-14 — Phase 1 Build Sprint

**Sessions:** 2 (hit context limit between them)
**Status going in:** SportsPredictor prediction engine existed; no mobile product, no cloud backend
**Status coming out:** Full Phase 1 MVP built, tested, deployed

### What happened
The plan to turn SportsPredictor into a consumer mobile app (FreePicks) was
fully scoped in a single document and then implemented in one sprint.

In 2 sessions we went from zero to:
- Supabase project provisioned with 8 tables, RLS, triggers
- Both Edge Functions live (`grade-user-picks`, `award-points`)
- Python sync layer connecting local SQLite → Supabase cloud
- Mobile app restructured: auth gate, 4-tab navigator, 12 screens, 9 components,
  5 Zustand stores
- ~8k rows of prediction data synced across 6 game dates (NBA + NHL)
- 33 live game score records

### Key decisions / pivots
- **Monorepo chosen over separate repo.** Sync layer needs to live next to both
  the prediction engine and mobile app. A separate repo would require publishing
  packages or duplicating code.
- **Working title confirmed: FreePicks**
- **Social-only auth.** Removed email/password option entirely — lower friction,
  no password reset flows to build, and the target audience (sports fans) already
  has Google/Discord/Apple accounts.
- **Removed Supabase TypeScript generic** (`createClient<Database>()`). It caused
  widespread `never` type errors due to interface mismatch. Untyped client with
  application-layer casting is the correct approach for this project.
- **Free tier first.** No monetization in Phase 1. Points have no cash value.
  Keeps launch simple and removes any legal complexity.

### What's blocked
OAuth providers not configured yet. Discord is the recommended first one —
~5 min, no billing, just discord.com/developers. This is the only thing
preventing a first device test.

### Notes
- All-Star break hit both sports simultaneously (NBA Feb 14, NHL Jan 26+).
  Next real data ~Feb 20. Orchestrator handles this correctly (skips gracefully).
- NHL and NBA have meaningfully different database schemas (column names differ
  in `prediction_outcomes`). This is now documented in CLAUDE.md, code comments,
  and this journal. Always check sport before writing sync/grading code.

**Detailed minutes:** `docs/sessions/2026-02-14.md`

---

## 2026-02-18 — Orchestrator Debugging

**Sessions:** 1
**Status going in:** No Discord notifications since Feb 16, orchestrator status unknown
**Status coming out:** Root cause identified and fixed, orchestrator restarted

### What happened
Investigated missing Discord notifications. Orchestrator process had died on Feb 16
(terminal closed / machine restarted) with no auto-restart mechanism. NHL process
had been dead since Jan 18. Both sports were actually healthy — the `consecutive_failures: 1`
was a false positive from the ESPN API health monitor, not a real grading failure.

### Key decisions / pivots
- **Schema validator patched** — empty `events: []` during off-days no longer triggers
  false alarms. `leagues` and `provider` added to expected ESPN scoreboard structure.
- **`start_orchestrator.bat` upgraded** — added auto-restart loop so process recovers
  within 30 seconds if it ever exits. Run with `.\start_orchestrator.bat` (not `python`).

### What's blocked
- OAuth providers still not configured (same as Feb 14)
- NBA games resume ~Feb 20 — first live pipeline run coming up

### Notes
- Orchestrator process is NOT a service — if the terminal closes, it dies. Long-term
  fix would be Windows Task Scheduler or running on a cloud VM.
- The prediction skip logic during All-Star break does NOT send a Discord notification
  (returns early before the notify call) — silence during breaks is expected behavior.
- `start_orchestrator.bat` must be run directly, not with `python`.

**Detailed minutes:** *(short session, no separate file)*

---

## 2026-02-28 — Cloud Dashboard Live, Cloudflare Tunnel, Options C/D Documented

**Sessions:** 1 (second session of the day)
**Status going in:** Streamlit app working locally but no mobile access; Flask dashboard broken stub; user wanted to monitor picks and system health from phone
**Status coming out:** Cloud dashboard built (Supabase-backed, 3 tabs); Cloudflare tunnel live; auto-starts with orchestrator; Options C/D spec'd as GitHub issues

### What happened
Inventoried both existing dashboards — Streamlit (`smart_picks_app.py`) working locally,
Flask (`performance_dashboard.py`) a broken stub (no HTML templates ever created).
Evaluated 4 mobile access options and implemented A + B in one session.

Option A (Cloudflare Tunnel): Downloaded `cloudflared.exe` directly from GitHub releases,
opened a quick tunnel to `localhost:8502`. Created `start_dashboard.bat` to auto-start
Streamlit + tunnel on every orchestrator launch. Mobile URL available immediately but
changes on each restart.

Option B (Supabase-backed Streamlit): Built `dashboards/cloud_dashboard.py` from scratch —
reads from Supabase `daily_props` (22k rows already synced), `model_performance`, and
`daily_games`. Three tabs: Today's Picks (filterable table + parlay builder), Performance
(14-day accuracy by tier and prop), System (pipeline status per sport). Mobile-optimized
layout (sidebar collapsed by default). Verified running at HTTP 200 on port 8502.

Options C (Flask dashboard) and D (FreePicks admin tab) documented as ready-to-paste
GitHub issue specs in `docs/github_issues/`.

### Key decisions / pivots
- **Port 8502 for cloud dashboard** — keeps local SmartPickSelector app on 8501 separately
- **Supabase service role key in `.streamlit/secrets.toml`** — gitignored; Streamlit Cloud
  gets secrets via their UI, local runs via the file
- **Quick tunnel is temporary** — URL changes on restart. Named tunnel (requires Cloudflare
  account) or Streamlit Community Cloud deployment gives a permanent URL
- **All three processes auto-start from one bat** — orchestrator + Discord bot + dashboard + tunnel

### What's blocked
- Streamlit Community Cloud deployment (needs push + 10 min setup at share.streamlit.io)
- Discord OAuth still not configured (FreePicks app device test still blocked)
- Named Cloudflare tunnel (permanent URL) requires a free Cloudflare account

### Notes
- `cloudflared.exe` stored at `C:\Users\thoma\cloudflared.exe` (not in repo, not gitignored)
- Quick tunnel URLs expire — bookmark the new URL each time until Streamlit Cloud is set up
- `gh` CLI not installed — GitHub issues must be created manually from `docs/github_issues/`

**Detailed minutes:** `docs/sessions/2026-02-28b.md`

---

## 2026-02-28 — Discord Bot Live, `!parlay` Command, NHL Name-Match Fix

**Sessions:** 1
**Status going in:** Discord top-20 picks had never fired; Discord bot existed in code but was never running; `!picks nhl` returning only 2-3 picks despite hundreds of predictions
**Status coming out:** Discord fully operational — webhook wired, bot live, top-20 fires daily at 6:15 AM CST; `!parlay` command added; `!picks nhl` fixed (3 → 39 picks)

### What happened
Traced the Discord silence to a missing `DISCORD_WEBHOOK_URL` env var — the orchestrator
reads it from `os.getenv()` but it was never set anywhere (`.env` is never loaded by the
orchestrator; the bat file set no vars). Fixed by adding all three Discord env vars to
`start_orchestrator.bat`. Verified by manually test-firing today's picks — all three
messages (NHL TOP 20, NHL TOP 20 OVERS, NBA TOP 20) delivered successfully.

Set up the Discord bot end-to-end: created application, enabled Message Content Intent,
got bot token, added it to the bat file, created `start_bot.bat` for auto-restart.
Bot verified connecting as **FreePicks Bot**.

Added `!parlay` command to the bot — randomly samples N legs from the top 10 picks per
sport, shows combined probability, re-rolls on each call.

Diagnosed `!picks nhl` returning only 2-3 picks despite 570+ predictions in the DB.
Root cause: our NHL prediction DB stores abbreviated player names (`A. Fox`, `S. Crosby`)
while PrizePicks uses full names (`Adam Fox`, `Sidney Crosby`). The fuzzy matcher's 85%
threshold rejected all abbreviated names (~65% similarity). Fixed with `_is_initial_match()`
— recognizes the `"Initial. Lastname"` convention and matches with 100% confidence.
Result: 3 picks → 39 picks.

### Key decisions / pivots
- **Single Discord channel for now** — all sports post to the same webhook. Separate
  NHL/NBA channels possible later with zero code changes (just swap URLs in bat file).
- **Parlay pool = top 10 per sport** — quality gate ensures every leg is from the model's
  best picks; random sampling provides variety across calls.
- **`_is_initial_match()` preferred over lowering fuzzy threshold** — lowering to 65%
  would cause false matches between similarly-named players. The initial-match check is
  precise and handles the specific NHL abbreviation format.
- **Bat files gitignored** — `start_orchestrator.bat` and `start_bot.bat` contain live
  credentials and are excluded from version control.

### What's blocked
- Discord OAuth providers not yet configured (still blocking first FreePicks device test)
- `!parlay` tested via inline Python — needs live bot test via Discord

### Notes
- The `!picks` path (SmartPickSelector + PrizePicks cross-reference) and the top-20
  webhook path (direct DB query) are completely separate code paths. Top-20 was always
  working correctly once webhook was set; `!picks nhl` needed the name-match fix.
- NHL match rate after fix: 189/285 PrizePicks lines (66%). Unmatched = bench players /
  scratches with no prediction — expected.
- `start_bot.bat` auto-restarts the bot process with 15s cooldown if it ever crashes.
  Both bat files are launched from one double-click on `start_orchestrator.bat`.

**Detailed minutes:** `docs/sessions/2026-02-28.md`

---

## 2026-02-25 — Pipeline Reliability Overhaul & NHL Discord Picks

**Sessions:** 1
**Status going in:** Feb 24 Discord notification showed goblin lines at 100% confidence; Feb 25 NBA predictions never generated (0 in DB despite orchestrator reporting success); NHL had no Discord picks at all
**Status coming out:** 4 bugs fixed; pipeline now fails loudly instead of silently; NHL top-20 picks live (two messages: all picks + OVERs); schedule shifted 4 hrs earlier for pre-work visibility

### What happened
Investigated why Feb 24 Discord report was bad and Feb 25 NBA generated 0 predictions.
Found a chain of silent failures: the prediction loop was swallowing all exceptions with
`except: pass`, the script always exited 0 regardless of outcome, the orchestrator never
verified actual row counts, and the top-picks notification silently skipped instead of
alerting. Fixed the entire chain. Also implemented NHL top-20 Discord picks — NHL's schema
uses `features_json` blob so it needed a separate code path from NBA's `f_*` columns.
Added a second NHL-only message for OVER picks since the model's top picks skew heavily UNDER.

### Key decisions / pivots
- **Probability band 0.56–0.95** — excludes goblin lines (stat model returns 1.0 for trivially easy lines with no ML model) and noise picks near coin-flip. Only genuine-edge picks surface.
- **Exit code 1 on 0 predictions** — scripts now signal real failures to the orchestrator instead of always returning 0.
- **Orchestrator verifies DB count post-run** — exit 0 alone is no longer trusted; actual row count checked after every "successful" prediction script.
- **Pipeline logging always-on** — `logs/pipeline_{sport}_{date}.log` written even on success, providing post-mortem trace for next-day debugging.
- **NHL two-message format** — TOP 20 PICKS (any direction) + TOP 20 OVERS separately, since UNDERs dominate the NHL model's confidence rankings.
- **Schedule: 4 hours earlier** — grading/predictions/picks now complete by 6:15 AM CST, before leaving for work. NHL grading at 3 AM (not 10 PM) to catch west coast games ending ~1 AM CST.

### What's blocked
- OAuth providers still not configured (Discord/Google/Apple)
- Data timing: combo stat L5 can show 0% when grading hasn't populated `player_game_logs` before predictions run

### Notes
- Root cause of 0-prediction failure at 6 AM on Feb 25 was never conclusively confirmed (silent exception swallowing destroyed the trace). The new logging will capture it if it recurs.
- NHL `features_json` keys: `success_rate_l5`, `current_streak`, `is_home`, `games_played` — use these for any future NHL feature queries.
- Feb 25 picks sent manually to Discord for all four messages (NBA top-20, NHL top-20, NHL OVERs, corrected Feb 24).

**Detailed minutes:** `docs/sessions/2026-02-25.md`

---

## 2026-02-23 — Post-Break Bug Hunt, ML Training & Learning Mode Exit

**Sessions:** 2
**Status going in:** NBA prediction pipeline crashing; grading rate ~30%; NHL pipeline falsely reporting FAILED on off days; system was offline Jan 28–Feb 22 (vacation + Olympic/All-Star breaks)
**Status coming out:** 5 bugs fixed; grading restored to 71-73%; Feb 20-22 data recovered; 19 ML models trained across both sports; learning mode lifted; daily Discord top-20 picks running

### Session 1 — Post-Break Bug Hunt & Data Recovery
NBA returned from All-Star break Feb 20 but the prediction pipeline was crashing
with an unhandled urllib3 exception. Grading was only capturing ~30% of predictions —
traced to two compounding bugs: the self-healing system's Dec 2024 auto-fix had
introduced a bad ESPN boxscore filter that excluded all bench players (only 5 starters
per team returned instead of ~20 per team), and 7 V6 prop types were missing from
the grader's stat_map, causing them to grade against 0. Both were fixed. Feb 20-22
data was retroactively recovered. NHL grading was also silently crashing during the
Olympic break.

### Session 2 — ML Training & Learning Mode Exit
Database confirmed all 14 NBA core combos had 4,500–4,815 graded samples with
strong accuracy signal (67–91%). Trained 19 ML models total (14 NBA + 5 NHL),
all beating their statistical baseline. Lifted `LEARNING_MODE = False` in both
sport configs (probability cap removed). Wired `ProductionPredictor` into NBA V6
prediction script (NHL V6 was already wired). Added daily Discord notification
posting top 20 picks per sport at 10:15 CST. Fixed notification display bugs:
L5% is always a multiple of 20% (hits/5 games), shown as directional rate
matching the pick direction.

### Key decisions / pivots
- **ESPN `active` field is NOT a DNP indicator** — only `didNotPlay: True` is correct.
- **V6 generates 13 prop types; grader only knew 6** — 7 missing types added.
- **Off days ≠ errors** — NHL schedule and grading now return 0 (not 1) on off days.
- **ML readiness: 4,500 beats 7,500** — orchestrator target was conservative; training
  script requires 3,000. All 14 NBA combos at 4,500+ was sufficient to train.
- **Data timing known issue** — combo stats (PRA, fantasy) can show L5: 0% in the
  Discord notification if grading hasn't updated player_game_logs before predictions
  run. Rare on steady-state; expect after breaks/restarts.

### What's blocked
- OAuth providers still not configured
- NHL returns Wednesday Feb 25 — orchestrator will auto-resume

### Notes
- Grading rate: 31%/23%/0% → 73%/71%/70% for Feb 20/21/22.
- First real ML-driven predictions run Feb 24 — expect actual probability spread.
- `lightgbm` installed; now all 5 model types compete (LR, RF, GB, XGBoost, LightGBM).
- `train_models.py` fixed: single-class test set crash (threes_2.5 = 91.5% UNDER rate).

**Detailed minutes:** `docs/sessions/2026-02-23.md`

---

## 2026-03-01 — Dashboard Data Quality: Duplicate Rows, odds_type, Team Staleness & Game Times

**Sessions:** 1
**Status going in:** Cloud dashboard live; NHL back from Olympic break; user identified multiple data-quality issues in exported CSV
**Status coming out:** 4 data-quality bugs fixed permanently; game times added to dashboard; 905 odds_type corrections applied; 9 stale NBA teams corrected

### What happened
User exported `daily_props` to CSV and spotted a cluster of problems on the first big NHL
game day: Tkachuk, Marchand, and Bennett all showing `odds_type=standard` for lines that
PrizePicks labels as `goblin`. On top of that, `S. Bennett` and `Sam Bennett` appeared as
separate rows in the same table. Over on the NBA side, De'Aaron Fox was listed on the Kings
(he was traded to San Antonio), and SGA steals OVER 0.5 and Hartenstein POINTS OVER 7.5 were
also showing `standard` instead of `goblin`.

Root-caused all four issues and fixed them permanently. Added `local_player_name` to `SmartPick`
so the sync layer always uses the abbreviated local DB name as the upsert key — no more duplicate
rows. Made PP team authoritative in `SmartPick` so trades are reflected within one sync cycle.
Built `sync_odds_types()` — a direct PrizePicks-to-Supabase label sync with no edge filtering —
which corrected 905 rows. Built `sync_game_times()` to populate the `game_time` TIMESTAMPTZ
column; added an ET-formatted `Time` column to the dashboard. Uncovered and fixed a Supabase
1000-row pagination cap that was silently truncating all batch-update operations.

### Key decisions / pivots
- **`odds_type` is a factual label, not a derived metric.** Never compute it from our edge model.
  Separate `sync_odds_types()` step reads it directly from PrizePicks DB with no filtering.
- **PP team is authoritative over local DB.** Traded players appear in PP immediately; local
  `player_game_logs` catches up slowly. Using `pp.get('team', '') or pred.get('team', '')` fixes
  staleness without any backfill.
- **`local_player_name` separates display name from sync key.** NHL DB uses abbreviated names
  (`S. Bennett`); PP uses full names (`Sam Bennett`). The SmartPick now carries both — full name
  for display, abbreviated name for the upsert conflict key.
- **All Supabase batch queries must paginate.** Default page size is 1000. NBA `daily_props` has
  2,800+ rows. Every future method that fetches all rows for a date must use the `.range()` loop.

### What's blocked
- Discord OAuth providers still not configured (FreePicks app device test still blocked)
- Streamlit Community Cloud deployment (permanent URL) — still pending push + share.streamlit.io

### Notes
- Backfill for Unicode → ASCII player names completed at session start: NBA 87/87, NHL 83/83.
- 37 orphan full-name NHL rows (Sam Bennett, etc.) manually deleted from Supabase; fix is permanent.
- 9 NBA traded players (Fox, Dosunmu, Lopez, Martin, Thomas, Johnson, LeVert, Yabusele, Achiuwa) corrected.
- `sync_game_times()` stores ISO TIMESTAMPTZ (`2026-03-01T13:10:00-05:00`), not a human-readable string.

**Detailed minutes:** `docs/sessions/2026-03-01.md`

---

## 2026-03-03 — Team Assignment Bug Fix, scipy Hang, Auto-Retrain

**Sessions:** 1
**Status going in:** 40+ NBA players predicted for wrong teams all season; prediction script hanging; no automated ML retraining
**Status coming out:** Team assignment fixed at source; scipy lazy-loaded; weekly auto-retrain wired into orchestrator; dashboard shows last retrained date

### What happened
Discovered that `_get_team_players()` had been pulling ALL historical game logs for a team,
not filtering to each player's current team. Kevin Durant and 40+ other traded players had
been generating predictions for their old teams all season. A separate bug caused 6 teams
(WAS, NYK, SAS, NOP, GSW, UTA) to return zero players because ESPN and NBA Stats API use
different abbreviations. Fixed both with a CTE that finds each player's most recent team and
a `TEAM_ALIASES` dict for abbrev normalization. Also removed the `FALLBACK_PROPS` fallback
(no PP line = skip, not predict at fixed lines).

During regeneration, the prediction script hung indefinitely — traced to Windows Defender
scanning scipy/sklearn `.pyd` files after earlier process kills. Mitigated by lazy-loading
scipy in `statistical_predictions.py`. Added weekly Sunday auto-retrain to the orchestrator
(NHL 2 AM / NBA 2:30 AM CST, skips if <500 new predictions) with a snug Discord notification
showing per-model accuracy deltas. Added ML model info (count, last retrained, avg accuracy)
to the System tab of the cloud dashboard.

Mar 3 predictions were not regenerated — games were already in progress by the time the
fixes landed. Negligible training impact.

### Key decisions / pivots
- **CTE over subquery for "current team"** — confirmed fast in raw SQLite (instant vs. hanging
  on the original O(n²) correlated subquery approach attempted earlier in the session).
- **TEAM_ALIASES at prediction time, not stored** — ESPN vs. NBA Stats abbrev normalization
  lives in the predictor class, not in the DB. No backfill needed.
- **Removed FALLBACK_PROPS** — predicting at fixed lines when no PP line exists creates
  phantom training data for lines that were never bettable. Clean skip is better.
- **Lazy scipy import** — the permanent system fix is a Windows Defender exclusion for
  site-packages. The lazy import is the code-level mitigation.
- **Auto-retrain gate: 500 predictions** — conservative enough to skip dead weeks
  (playoffs, injury waves), aggressive enough to retrain every 4–6 weeks during the season.

### What's blocked
- Discord / Google / Apple OAuth still not configured (device test still blocked)
- Streamlit Community Cloud permanent deployment still pending
- Windows Defender exclusion for Python site-packages (prevents future scipy hangs)

### Notes
- ML models (v20260302_001) are NOT affected: NBA models use zero opponent features, so only
  `f_home_away_split` was wrong for ~40 players (~2-4% of training data). Reliable as-is.
- NHL used same CTE fix but no TEAM_ALIASES needed (NHL abbrevs are consistent across APIs).
- The 6-team abbrev mismatch (ESPN vs. NBA Stats) had silently caused zero predictions for
  WAS, NYK, SAS, NOP, GSW, UTA players — unclear for how long before today.

**Detailed minutes:** `docs/sessions/2026-03-03.md`

---

## 2026-03-02 — Data Quality Hardening + Dashboard UI

**Sessions:** 1
**Status going in:** Dashboard live; three data-quality issues observed from first full game day (traded player teams wrong, multiple STD lines, probability inversion); game times blank
**Status coming out:** All three issues fixed permanently via orchestrator pipeline; game times and odds corrections now run automatically every day; Line Compare tab redesigned as card+badge layout

### What happened
User raised GitHub issues #1 and #2 noting that the traded-player team staleness fix from 3/1/26
had already recurred (Quinn Hughes VAN→MIN still showing VAN), and that Jokic had four standard
assists lines in the dashboard (impossible per PP platform rules) with inverted probabilities.
Diagnosed root causes for all three: the 3/1 fix only patched `sync_smart_picks` but
`sync_predictions` ran first and wrote stale teams; `_get_pp_lines` had no deduplication for
multiple STD lines from the PP API; and `sync_odds_types` / `sync_game_times` were never wired
into the orchestrator so they only ran once manually and never again. Also fixed a dashboard
`KeyError: Prop`, a goblin/demon UNDER display bug, and replaced the Line Compare pivot table
with a much more readable card+badge layout.

### Key decisions / pivots
- **Team staleness needs two fixes, not one.** The 3/1 fix only corrected the smart-picks row.
  Added a PP team lookup inside `sync_predictions()` so the base prediction row is also correct
  from the start. Both sync steps now agree on team.
- **Stop skipping traded players.** SmartPickSelector was `continue`-ing on team mismatch, which
  caused traded players to appear with stale team AND get no smart pick. Now logs the trade and
  proceeds — PP team is already authoritative at SmartPick creation.
- **Max 1 standard line per player-prop is a platform rule, not a display preference.** Enforced
  in `_get_pp_lines()` by keeping the median standard line and dropping outliers. Logs any culled
  duplicates for observability.
- **`sync_odds_types` and `sync_game_times` must be in the orchestrator pipeline, not manual.**
  Any step that needs to run daily must be wired into `run_daily_prediction_pipeline()`. Added both.
- **Card+badge layout > pivot table for sparse multi-line data.** When different players have
  different line sets, a pivot table produces mostly empty cells. Cards with inline badges scale
  cleanly to any number of lines per player.

### What's blocked
- Discord OAuth providers still not configured
- Streamlit Community Cloud permanent deployment still pending
- Today's (3/2/26) data already synced before the fixes — needs manual re-run of odds-types and game-times sync

### Notes
- `pred_lookup` now sorts by probability desc so `[0]` is always the highest-confidence prediction.
- Goblin/demon UNDERs now filtered at dashboard query time as a belt-and-suspenders guard.
- All fixes are general (all players, both sports) — not Hughes-specific.

**Detailed minutes:** `docs/sessions/2026-03-02.md`

---

<!-- Template for future entries:

## YYYY-MM-DD — [Session Title]

**Sessions:** N
**Status going in:** ...
**Status coming out:** ...

### What happened
[2-3 sentences summarizing the session]

### Key decisions / pivots
- ...

### What's blocked
- ...

### Notes
- ...

**Detailed minutes:** `docs/sessions/YYYY-MM-DD.md`

-->
