# FreePicks — Project Roadmap

*Last updated: 2026-02-14*

---

## At a Glance

```
                         F R E E P I C K S   R O A D M A P
  ──────────────────────────────────────────────────────────────────────────────

  PHASE 1 ████████████████████████████ COMPLETE (Feb 14, 2026)
  Foundation: Backend + Mobile MVP + Sync Pipeline

  PHASE 2 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ~Mar 2026
  Social: Leaderboard + Friends + Push Notifications

  PHASE 3 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ~Apr 2026
  Monetization: FreePicks Plus + Ads + Sportsbook Links

  PHASE 4 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ~May 2026
  ML Upgrade: Retrained models → higher accuracy → bigger edge
  ──────────────────────────────────────────────────────────────────────────────
```

---

## Phase 1 — Foundation (Complete ✅)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1 — FOUNDATION                              COMPLETE ✅  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  BACKEND (Supabase)                                             │
│  ✅ 8 tables: profiles, daily_props, user_picks, user_bets,    │
│              point_transactions, daily_games,                   │
│              model_performance, watchlist                       │
│  ✅ Row Level Security on all tables                            │
│  ✅ handle_new_user() trigger (auto-creates profile)            │
│  ✅ increment_vote() for community picks                        │
│  ✅ Edge Functions deployed (ACTIVE v1):                        │
│       grade-user-picks  →  determines HIT / MISS               │
│       award-points      →  streak logic, tier, point ledger     │
│                                                                 │
│  SYNC PIPELINE (Python)                                         │
│  ✅ supabase_sync.py — predictions + grading + smart-picks     │
│  ✅ game_sync.py — ESPN live scores → daily_games               │
│  ✅ Orchestrator auto-sync after prediction + grading runs      │
│  ✅ ~8k props, 33 games, 5 model_performance entries live       │
│                                                                 │
│  MOBILE APP (Expo React Native)                                 │
│  ✅ Auth gate + 4-tab navigator (Play | Scores | Track | Profile│
│  ✅ Social OAuth (expo-web-browser, freepicks:// scheme)        │
│  ✅ 5 Zustand stores (auth, picks, bets, watchlist, parlay)    │
│  ✅ 12 screens, 9 components, 7 hooks                           │
│  ✅ Points system wired (10pts/hit, streak bonuses)             │
│  ✅ Watchlist (max 10 players)                                  │
│                                                                 │
│  BLOCKER REMAINING:                                             │
│  ⬜ OAuth provider credentials (Discord/Google/Apple)           │
│  ⬜ First device test via Expo Go                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 2 — Social & Discovery (~Mar 2026)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 2 — SOCIAL & DISCOVERY                      UPCOMING    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  LEADERBOARD                                                    │
│  ⬜ Global leaderboard (daily / weekly / all-time)              │
│  ⬜ Sport-specific leaderboards                                  │
│  ⬜ Personal rank + percentile display                          │
│                                                                 │
│  SOCIAL                                                         │
│  ⬜ Follow / friend system                                      │
│  ⬜ Friend feed ("@user hit Trae Young OVER assists")           │
│  ⬜ Shareable pick card (image export for social media)         │
│  ⬜ Public profile page                                         │
│                                                                 │
│  NOTIFICATIONS                                                  │
│  ⬜ Push: daily props reminder ("Your picks are ready")         │
│  ⬜ Push: pick graded ("You hit Nikola Jokic OVER 25pts")       │
│  ⬜ Push: game started (prop locked notification)               │
│  ⬜ In-app notification center                                  │
│                                                                 │
│  CHALLENGES                                                     │
│  ⬜ Weekly challenge system ("Hit 5 T1-ELITE picks this week") │
│  ⬜ Challenge badges on profile                                 │
│  ⬜ Seasonal achievements                                       │
│                                                                 │
│  DATA                                                           │
│  ⬜ Player news integration (injury / lineup alerts)            │
│  ⬜ Historical pick accuracy by player / prop type for users    │
│  ⬜ "On fire" indicators (player on streak)                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 3 — Monetization (~Apr 2026)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3 — MONETIZATION                            UPCOMING    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  FREEPICKS PLUS (~$4.99/mo)                                     │
│  ⬜ Unlimited AI pick unlocks (vs. 25pts cost in free tier)    │
│  ⬜ Advanced stats per prop (last 10 games, home/away splits)   │
│  ⬜ Early access to next day's props                            │
│  ⬜ Ad-free experience                                          │
│  ⬜ Exclusive Plus-only leaderboard                             │
│                                                                 │
│  ADS (free tier)                                                │
│  ⬜ Banner ads on scoreboard / track screens                    │
│  ⬜ Interstitial after each pick session                        │
│  ⬜ Rewarded video for bonus points                             │
│                                                                 │
│  AFFILIATE / SPORTSBOOK LINKS                                   │
│  ⬜ "Bet this pick" deep-link to partner sportsbooks            │
│  ⬜ Affiliate revenue share (DraftKings / FanDuel / etc.)       │
│  ⬜ Legal compliance review by state                            │
│                                                                 │
│  ENTERPRISE / WHITE-LABEL                                       │
│  ⬜ License prediction API to other apps                        │
│  ⬜ White-label mobile app for other prediction systems         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 4 — ML Upgrade (~May 2026)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 4 — ML UPGRADE                              UPCOMING    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ML TRAINING READINESS (as of Feb 14, 2026)                    │
│                                                                 │
│  NBA  ████████████████████████████░  97.8%  (~117k predictions)│
│        → All 14 prop/line combos above 7,500 target            │
│        → Can trigger training NOW                              │
│                                                                 │
│  NHL  ████████████████████████████   94.9%  (~45k predictions) │
│        → Bottleneck: points_1.5 (7,114 / 7,500 — 386 needed)  │
│        → ~2-3 weeks of games after break to clear bottleneck   │
│                                                                 │
│  TRAINING PIPELINE                                              │
│  ⬜ Trigger NBA training (may be ready now)                    │
│       python orchestrator.py --sport nba --operation ml-train  │
│  ⬜ NHL training after points_1.5 threshold cleared            │
│  ⬜ A/B test new models vs. current rule-based system          │
│  ⬜ Deploy winning model, monitor accuracy delta               │
│                                                                 │
│  ACCURACY TARGETS (current → goal)                             │
│  NBA UNDER:  84.2% → 88%+                                      │
│  NBA OVER:   61.2% → 68%+                                      │
│  NHL UNDER:  74.4% → 78%+                                      │
│  NHL OVER:   54.6% → 60%+                                      │
│                                                                 │
│  FEATURE IMPROVEMENTS                                           │
│  ⬜ Opponent defensive features (currently 0% in last 14d NHL) │
│  ⬜ Rest/travel fatigue features                               │
│  ⬜ Referee/officiating tendency features (NBA fouls/FTA)      │
│  ⬜ Real-time injury/lineup adjustment                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Parallel Tracks (Ongoing)

```
  PREDICTION ENGINE                  MOBILE APP                    BACKEND
  ─────────────────                  ──────────                    ───────
  Running 24/7 via orchestrator      OAuth configure (blocker)     Edge Fn monitoring
  Auto-syncs to Supabase             Device testing                DB backups
  Grading after each game            UI polish                     Cost monitoring
  API health self-healing            App Store prep (Phase 2+)     Realtime sub tuning
  NHL opponent features (bug)        Android testing               Rate limit review
  NBA ML training (ready now?)       Accessibility pass            Index optimization
```

---

## Data Flow Architecture

```
  LOCAL MACHINE                          SUPABASE CLOUD
  ─────────────                          ──────────────

  nhl/database/*.db  ──┐                 ┌─────────────────────────┐
                       │  sync/          │  daily_props            │
  nba/database/*.db  ──┤  supabase_  ──► │  daily_games            │
                       │  sync.py        │  model_performance      │
  ESPN API           ──┤  game_          │                         │
  (live scores)        │  sync.py        │  user_picks   ◄─────────┼── Mobile App
                       └─────────────    │  user_bets    ◄─────────┼── (user data)
                                         │  profiles     ◄─────────┤
  orchestrator.py                        │  watchlist    ◄─────────┤
  (schedules all)                        │  point_transactions ◄───┘
                                         │                         │
                                         │  Edge Functions:        │
                                         │  grade-user-picks  ─────┤
                                         │  award-points      ─────┘
                                         └─────────────────────────┘
                                                    │
                                                    │ @supabase/supabase-js
                                                    │ + Realtime subscriptions
                                                    ▼
                                         ┌─────────────────────────┐
                                         │  EXPO REACT NATIVE      │
                                         │  Play | Scores | Track  │
                                         │  Profile                │
                                         │                         │
                                         │  Auth: Google/Discord/  │
                                         │        Apple (OAuth)    │
                                         └─────────────────────────┘
```

---

## Immediate Next Steps (Ordered)

```
  1. ⬜  Configure Discord OAuth (~5 min)
          → discord.com/developers → New App → OAuth2 → copy ID+Secret
          → Add redirect: https://***REMOVED***/auth/v1/callback
          → Enable via Supabase Management API (curl command in FREEPICKS_PLAN.md)

  2. ⬜  Test app on device (Expo Go)
          → cd mobile && npx expo start
          → Scan QR code
          → Verify: sign-in → profile created → picks appear → make a pick

  3. ⬜  Wait for All-Star break to end (~Feb 20)
          → Orchestrator resumes auto-generating predictions
          → First full live pipeline run

  4. ⬜  Check NBA ML training readiness
          → python orchestrator.py --sport nba --mode once --operation ml-check
          → May be ready to trigger training now

  5. ⬜  Begin Phase 2 planning (leaderboard, friends, push notifications)
```
