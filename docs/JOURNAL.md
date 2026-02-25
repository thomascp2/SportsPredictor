# FreePicks — Project Journal

A running log of sessions, pivots, and decisions. Add an entry for each
working session. Detailed minutes live in `docs/sessions/YYYY-MM-DD.md`.

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
