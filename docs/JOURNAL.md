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
