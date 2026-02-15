# FreePicks — Full Project Plan & Session Handoff

**Last Updated:** 2026-02-14
**Project Repo:** SportsPredictor (monorepo — everything lives here)
**Working Title:** FreePicks

---

## Context Prompt for Next Claude Session

> Paste this at the start of a new session to restore full project context:

```
We're building FreePicks — a free-to-play PrizePicks alternative mobile app powered
by an existing ML prediction engine (SportsPredictor). The monorepo lives at
C:\Users\thoma\SportsPredictor.

Phase 1 MVP is fully implemented and pushed to GitHub. Here's the current state:

DONE:
- Supabase project (ref: txleohtoesmanorqcurt, us-east-1)
  - 8 tables: profiles, daily_props, user_picks, user_bets,
    point_transactions, daily_games, model_performance, watchlist
  - Both Edge Functions deployed and ACTIVE:
    grade-user-picks (v1), award-points (v1)
  - ~8k daily_props rows synced (6 NBA dates + 2 NHL dates)
  - 33 games in daily_games, 5 model_performance entries
- Expo React Native app (mobile/):
  - 4-tab navigator: Play | Scores | Track | Profile
  - Auth gate (unauthenticated → AuthScreen)
  - 5 Zustand stores: auth, picks, bets, watchlist, parlay
  - 12 screens, many components and hooks
  - Proper OAuth flow using expo-web-browser + expo-auth-session
  - URL scheme: freepicks://
- Python sync layer (sync/):
  - supabase_sync.py: predictions + grading + smart-picks
  - game_sync.py: ESPN live scores → daily_games

NOT YET DONE:
- OAuth providers not configured (need Discord/Google/Apple credentials)
  Supabase callback URL: https://txleohtoesmanorqcurt.supabase.co/auth/v1/callback
  Discord: discord.com/developers — easiest, no billing
  Google: console.cloud.google.com — OAuth 2.0 Web Client
  Apple: developer.apple.com — Sign In with Apple
- App not yet tested on a physical device (Expo Go)
- NBA/NHL All-Star break until ~Feb 20 (no new prediction data until then)

KEY FILES:
- supabase/migrations/001_initial_schema.sql (schema)
- supabase/functions/{grade-user-picks,award-points}/index.ts (edge functions)
- sync/{supabase_sync,game_sync,config}.py (sync pipeline)
- mobile/App.tsx (root navigator + auth gate)
- mobile/src/store/authStore.ts (OAuth flow)
- mobile/src/services/supabase.ts (client)
- mobile/src/utils/constants.ts (Supabase URL/key)
- .env (project root, gitignored — SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)

Supabase Management API access:
  Token: sbp_5695de26814d83ff7b9af9522d031d78f8f40eeb
  (use as: SUPABASE_ACCESS_TOKEN=<token> npx supabase ...)

Next priority: Set up at least one OAuth provider and test the app in Expo Go.
Read docs/FREEPICKS_PLAN.md for the full plan and roadmap.
```

---

## Vision

FreePicks turns the existing SportsPredictor prediction engine into a consumer
product — a free app where users pick OVER/UNDER on today's player props,
earn points for correct picks, track real bets, and get AI-powered pick
recommendations.

Think PrizePicks — but free to play, gamified with a points system, and
backed by a model with 80% NBA accuracy and 68% NHL accuracy.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  PREDICTION ENGINE (existing)                               │
│  nba/ nhl/ — SQLite DBs, Python ML pipeline, orchestrator  │
└───────────────────────┬─────────────────────────────────────┘
                        │ sync/ (one-way)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  SUPABASE CLOUD (txleohtoesmanorqcurt)                      │
│  PostgreSQL + Auth + Realtime + Edge Functions              │
│  daily_props | user_picks | profiles | daily_games | ...   │
└───────────────────────┬─────────────────────────────────────┘
                        │ @supabase/supabase-js
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  MOBILE APP (Expo React Native)                             │
│  Play | Scores | Track | Profile                            │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Decisions
- **Monorepo**: Prediction engine, sync layer, and mobile app live together.
  The sync layer is the glue — keeping them separate repos would break this.
- **One-directional sync**: Prediction data flows local → Supabase only.
  User data (picks, bets, points) lives exclusively in Supabase.
- **Social-only auth**: No email/password. Google, Apple, Discord via OAuth.
  Supabase handles sessions; mobile uses expo-web-browser for the flow.
- **Free tier first**: No paywalls in Phase 1. Points have no cash value.
  Monetization (Phase 3) is via ads or premium tier — never required for core play.

---

## Database Schema (Supabase)

| Table | Purpose | RLS |
|-------|---------|-----|
| `profiles` | User data: points, streak, tier, display_name | Self-read/write, public username read |
| `daily_props` | AI predictions for today's props (synced from SQLite) | Public read |
| `user_picks` | OVER/UNDER picks made by users | Self-only |
| `user_bets` | Real bet tracking (JSONB legs, stake, payout) | Self-only |
| `point_transactions` | Ledger of point awards and deductions | Self-only |
| `daily_games` | Live game scores synced from ESPN | Public read |
| `model_performance` | Daily accuracy stats per sport | Public read |
| `watchlist` | Player watchlist (max 10 per user) | Self-only |

Key functions in schema:
- `handle_new_user()` — auto-creates profile on first sign-in (trigger)
- `increment_vote(prop_id, direction)` — community OVER/UNDER consensus

---

## Sync Pipeline

### `sync/supabase_sync.py`
```
# Sync predictions for a date
python -m sync.supabase_sync --sport nba --operation predictions --date 2026-02-11

# Sync grading results
python -m sync.supabase_sync --sport nba --operation grading --date 2026-02-11

# Sync PrizePicks-matched smart picks
python -m sync.supabase_sync --sport nba --operation smart-picks --date 2026-02-11

# All operations, both sports
python -m sync.supabase_sync --sport all --operation all
```

### `sync/game_sync.py`
```
# Single sync (one date)
python -m sync.game_sync --sport all --once

# Continuous polling (runs during game hours 11am-2am ET)
python -m sync.game_sync --sport all
```

### Orchestrator Integration
The orchestrator (`orchestrator.py`) auto-calls sync after each pipeline:
- After prediction pipeline → `sync_predictions()` + `sync_smart_picks()`
- After grading pipeline → `sync_grading()` + `trigger_user_grading()` (Edge Function)

---

## Edge Functions

Both deployed and ACTIVE at v1:

### `grade-user-picks`
- Triggered after grading sync completes
- Looks up all `user_picks` for a game_date where status = 'pending'
- Matches each pick's ai_prediction to actual result on `daily_props`
- Updates `user_picks.status` → 'hit' or 'miss'
- Calls `award-points` for each user who had picks that day

### `award-points`
- Awards 10pts per correct pick
- Streak bonuses: 3-streak +5pts, 5-streak +15pts, 10-streak +50pts
- Updates `profiles.points`, `profiles.current_streak`, `profiles.tier`
- Writes to `point_transactions` ledger
- Tier thresholds: Rookie(0) → Pro(500) → Elite(2000) → Legend(5000)

---

## Mobile App Structure

```
mobile/
  App.tsx                      — Root: auth gate + navigator
  src/
    screens/
      AuthScreen.tsx           — Social login (Google/Apple/Discord)
      PlayScreen.tsx           — Main FreePicks game (pick OVER/UNDER)
      ScoreboardScreen.tsx     — Live scores (existing, updated)
      TrackScreen.tsx          — Bet tracker
      ProfileScreen.tsx        — Stats, tier, watchlist
      AddBetScreen.tsx         — Add/edit bet (modal)
      WatchlistScreen.tsx      — Manage watchlist (modal)
      SmartPicksScreen.tsx     — Legacy AI picks view
      ParlayBuilderScreen.tsx  — Legacy parlay builder
      PerformanceScreen.tsx    — Legacy model performance
      AdminScreen.tsx          — Dev/debug tools
    store/
      authStore.ts             — Session, profile, OAuth sign-in
      picksStore.ts            — Today's props, user picks, makePick()
      betStore.ts              — Bet CRUD, P/L stats
      watchlistStore.ts        — Max 10 players, add/remove
      parlayStore.ts           — Legacy parlay builder state
    components/
      PickButton.tsx           — Animated OVER/UNDER button (spring + haptics)
      PropCard.tsx             — Player prop card with community bar + AI chip
      PointsBadge.tsx          — Animated points counter
      StreakBadge.tsx          — Color-coded streak display
      AIPredictionChip.tsx     — Locked/unlocked AI pick chip (25pt unlock)
      BetCard.tsx              — Bet with legs, settle buttons
      PLSummary.tsx            — P/L stats header
      PlayerBoxCard.tsx        — Live box score card
      WatchlistStrip.tsx       — Horizontal player chips
      (+ existing components)
    hooks/
      useFreePicks.ts          — Combined picks+auth, Realtime subscriptions
      useSupabaseGames.ts      — Realtime game scores
      usePlayerLiveStats.ts    — Live stats for watchlist players
      useSwipePick.ts          — Swipe gesture handler
      (+ existing hooks)
    services/
      supabase.ts              — createClient, ExpoSecureStoreAdapter
      api.ts                   — Legacy REST API calls
    types/
      supabase.ts              — TypeScript interfaces for all tables
    utils/
      constants.ts             — SUPABASE_URL, SUPABASE_ANON_KEY, POINTS config
      quickActions.ts          — iOS 3D Touch / Android shortcuts
```

### Auth Flow
Uses `expo-web-browser` + `expo-auth-session`:
1. `signInWithOAuth({ provider, options: { redirectTo, skipBrowserRedirect: true } })`
2. `WebBrowser.openAuthSessionAsync(url, redirectTo)`
3. On callback: `QueryParams.getQueryParams(url)` → `supabase.auth.setSession()`

`makeRedirectUri()` generates:
- Expo Go: `exp://192.168.x.x:8081`
- Standalone build: `freepicks://`

---

## Points System

| Action | Points |
|--------|--------|
| Correct pick | +10 |
| 3-pick streak | +5 bonus |
| 5-pick streak | +15 bonus |
| 10-pick streak | +50 bonus |
| Daily login | +5 |
| First pick of day | +5 |
| Unlock AI pick | -25 |
| Top game finish (1st) | +100 |
| Top day finish | +200 |

**Tiers:** Rookie → Pro (500pts) → Elite (2,000pts) → Legend (5,000pts)

---

## Current Data Status (Feb 14, 2026)

| Sport | Dates Synced | Props in Supabase | Graded | Accuracy |
|-------|-------------|------------------|--------|----------|
| NBA | Feb 9, 10, 11, 12 | 7,474 | 3,002 | 81.5% (Feb 9) |
| NHL | Jan 25, 26 | 482 | 328 | 64.7% avg |

- **Games in daily_games:** 33 (NBA + NHL)
- **Model performance entries:** 5
- **Smart picks (PrizePicks-matched):** 881 (Feb 11 NBA)
- **All-Star break:** No new NBA predictions until ~Feb 20

---

## What's Done ✅

### Phase 1 MVP (Session 1 - Feb 14, 2026)
- [x] Supabase project created (txleohtoesmanorqcurt, us-east-1)
- [x] Database migration applied (8 tables + RLS + triggers + functions)
- [x] Edge Functions deployed and tested (grade-user-picks, award-points)
- [x] Python sync layer (`sync/`) — predictions, grading, smart-picks, game scores
- [x] Orchestrator wired to auto-sync after prediction and grading pipelines
- [x] Mobile app restructured — 4-tab navigator, auth gate, 12 screens
- [x] 5 Zustand stores (auth, picks, bets, watchlist, parlay)
- [x] All mobile components (PickButton, PropCard, BetCard, etc.)
- [x] Auth flow fixed for Expo (expo-web-browser + expo-auth-session)
- [x] URL scheme configured (`freepicks://`)
- [x] Supabase redirect URLs configured (freepicks:// + Expo Go URLs)
- [x] Real credentials wired in (.env + constants.ts)
- [x] Full sync dry run — all 3 sports × operations tested successfully
- [x] NHL grading schema bug fixed (actual_stat_value vs actual_value)
- [x] TypeScript clean compile (0 errors)
- [x] All committed and pushed to GitHub (master)

---

## What's Left — Prioritized Roadmap

### 🟥 Blocker: Can't test app without OAuth
**Set up at least one OAuth provider (Discord is fastest — 5 min):**

**Discord:**
1. Go to https://discord.com/developers/applications
2. New Application → "FreePicks"
3. OAuth2 tab → copy Client ID and Client Secret
4. Add redirect: `https://txleohtoesmanorqcurt.supabase.co/auth/v1/callback`
5. Run:
   ```bash
   curl -X PATCH \
     -H "Authorization: Bearer sbp_5695de26814d83ff7b9af9522d031d78f8f40eeb" \
     -H "Content-Type: application/json" \
     -d '{"external_discord_enabled":true,"external_discord_client_id":"YOUR_ID","external_discord_secret":"YOUR_SECRET"}' \
     "https://api.supabase.com/v1/projects/txleohtoesmanorqcurt/config/auth"
   ```

**Google:**
1. https://console.cloud.google.com → New Project "FreePicks"
2. APIs & Services → Credentials → Create OAuth 2.0 Client ID (Web application)
3. Authorized redirect URIs: `https://txleohtoesmanorqcurt.supabase.co/auth/v1/callback`
4. Same curl as above but `external_google_enabled/client_id/secret`

### 🟧 Next: Test on Device
```bash
cd mobile
npx expo start
```
Scan QR code with Expo Go on phone. Test:
1. Auth screen appears for unauthenticated state
2. Sign in with configured OAuth provider
3. Profile created in Supabase profiles table
4. Play tab shows today's props (or Feb 11 data)
5. Make a pick → appears in user_picks

### 🟨 Then: Deploy Edge Function Secrets
If Edge Functions need Supabase service key at runtime, set secrets:
```bash
SUPABASE_ACCESS_TOKEN=sbp_5695de26814d83ff7b9af9522d031d78f8f40eeb \
npx supabase secrets set --project-ref txleohtoesmanorqcurt \
  SUPABASE_URL=https://txleohtoesmanorqcurt.supabase.co \
  SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>
```

### 🟨 Then: NBA Games Resume (~Feb 20)
When All-Star break ends:
1. Orchestrator will auto-generate predictions
2. Auto-sync to Supabase via orchestrator integration
3. Game sync picks up live scores
4. Full pipeline runs end-to-end for first time with real data

### Phase 2 — Social & Discovery (Post-MVP)
- [ ] Community leaderboard (global + friends)
- [ ] Friend system (follow users, see their picks)
- [ ] Shareable pick cards (image export)
- [ ] Push notifications (game start, pick graded, daily reminder)
- [ ] Weekly challenges (hit 5 T1-ELITE picks this week)
- [ ] Player news integration (injury alerts affecting props)

### Phase 3 — Monetization
- [ ] FreePicks Plus tier (~$4.99/mo) — unlimited AI unlocks, advanced stats
- [ ] Sponsored picks / partner sportsbook deep-links
- [ ] White-label license to other prediction systems

### Phase 4 — ML Upgrade
Both sports are near the 10k-per-prop ML training threshold:
- NHL: 94.9% ready (points_1.5 bottleneck — needs 386 more)
- NBA: 97.8% ready (all props above 7,500)

When games resume (~Feb 20), NHL should hit threshold within 2-3 weeks.
NBA may be ready to start ML training now.

```bash
# Check readiness
python orchestrator.py --sport nba --mode once --operation ml-check

# Trigger training when ready
python orchestrator.py --sport nba --mode once --operation ml-train
```

---

## Common Commands Reference

```bash
# Sync predictions for a specific date
python -m sync.supabase_sync --sport nba --operation predictions --date 2026-02-11

# Sync grading results
python -m sync.supabase_sync --sport nba --operation grading --date 2026-02-11

# Sync game scores (one-shot)
python -m sync.game_sync --sport all --once

# Start Expo dev server
cd mobile && npx expo start

# TypeScript check
cd mobile && npx tsc --noEmit

# Deploy/update edge functions
SUPABASE_ACCESS_TOKEN=sbp_5695de26814d83ff7b9af9522d031d78f8f40eeb \
  npx supabase functions deploy grade-user-picks --project-ref txleohtoesmanorqcurt

# Run orchestrator (prediction pipeline)
python orchestrator.py --sport nba --mode once --operation prediction

# Run orchestrator (grading pipeline)
python orchestrator.py --sport nba --mode once --operation grading
```

---

## Critical Gotchas

1. **Dual database schemas** — NHL and NBA have different column names:
   - NHL outcomes: `actual_stat_value`, `predicted_outcome`
   - NBA outcomes: `actual_value`, `prediction`

2. **Supabase CLI auth** — Non-TTY environment means you can't use `supabase login`
   interactively. Always pass the token inline:
   ```bash
   SUPABASE_ACCESS_TOKEN=sbp_... npx supabase <command>
   ```

3. **`signInWithOAuth` alone doesn't work in React Native.** Must use
   `expo-web-browser` + `expo-auth-session` — see `authStore.ts`.

4. **Supabase TypeScript generic** — `createClient<Database>()` caused `never`
   type errors. We use untyped client and cast at the application layer instead.

5. **All-Star break** — The orchestrator correctly skips prediction generation
   when no games are scheduled. NHL hasn't had data since Jan 26 either.

6. **Redirect URLs** — Expo Go generates `exp://192.168.x.x:8081` dynamically.
   We've pre-registered common local IPs in Supabase's allowlist. If your IP
   differs, add it via the Management API or Supabase dashboard.

---

## Environment Variables

**`.env` (project root, gitignored):**
```
SUPABASE_URL=https://txleohtoesmanorqcurt.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
ANTHROPIC_API_KEY=<key>
```

**`mobile/src/utils/constants.ts`:**
```typescript
export const SUPABASE_URL = 'https://txleohtoesmanorqcurt.supabase.co';
export const SUPABASE_ANON_KEY = 'eyJh...';  // public anon key
```

---

*Last session: 2026-02-14 — Phase 1 complete, Edge Functions deployed, sync pipeline tested.*
