# FreePicks — Project Roadmap

*Last updated: 2026-02-23*

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

  PHASE 4 ████████████████████████████ COMPLETE (Feb 23, 2026)
  ML Upgrade: 19 models trained, learning mode lifted, real probabilities live

  PHASE 5 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ~Jun 2026
  Correlated Parlay Optimizer: team stacking, zero-sum awareness, cross-sport EV
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

## Phase 4 — ML Upgrade (Complete ✅ Feb 23, 2026)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 4 — ML UPGRADE                              COMPLETE ✅  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  TRAINED & LIVE (Feb 23, 2026)                                 │
│                                                                 │
│  NBA  14/14 core combos  ·  4,506–4,815 samples each          │
│        Best Brier delta: threes_2.5 (+0.12), minutes (+0.12)  │
│        Models: LR / RF / GB / XGBoost / LightGBM competed     │
│        Registry: ml_training/model_registry/nba/               │
│                                                                 │
│  NHL  5/5 core combos   ·  all above 6,700 samples            │
│        Best Brier delta: shots_3.5 (+0.39), points_1.5 (+0.34)│
│        Registry: ml_training/model_registry/nhl/               │
│                                                                 │
│  DEPLOYMENT                                                     │
│  ✅ LEARNING_MODE = False in both sport configs                │
│  ✅ PROBABILITY_CAP removed (0.0–1.0, real spread)            │
│  ✅ NBA V6 wired to ProductionPredictor (ensemble 60/40)       │
│  ✅ NHL V6 was already wired                                   │
│  ✅ Daily Discord top-20 picks at 10:15 CST (both sports)     │
│                                                                 │
│  REMAINING / FUTURE MODEL IMPROVEMENTS                          │
│  ⬜ Opponent defensive features for NHL                        │
│  ⬜ Rest/travel fatigue features                               │
│  ⬜ Referee/officiating tendency features (NBA fouls/FTA)      │
│  ⬜ Real-time injury/lineup adjustment                         │
│  ⬜ Retrain periodically as graded data grows                  │
│  ⬜ Fix data timing: combo stat L5 stale after restarts        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 5 — Correlated Parlay Optimizer (~Jun 2026)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 5 — CORRELATED PARLAY OPTIMIZER             UPCOMING    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  GOAL: Move beyond single-pick confidence to optimal            │
│  COMBINATIONS of picks that maximize EV while managing          │
│  correlation risk. Two modes:                                   │
│    (A) Ceiling parlays — stack correlated OVERs for big payout │
│    (B) Hedging parlays — mix negative correlations for floor   │
│                                                                 │
│  LAYER 1 — CORRELATION MATRIX                                   │
│  ⬜ Build player-pair correlation dataset from graded outcomes  │
│       For each pair (PlayerA_PropX, PlayerB_PropY):            │
│       Pearson r of actual outcomes on shared game dates        │
│  ⬜ Team-level correlation (teammates vs. opponents)            │
│  ⬜ Cross-sport correlation baseline (NHL+NBA independence)     │
│                                                                 │
│  LAYER 2 — ZERO-SUM / GAME-TOTAL AWARENESS                     │
│  ⬜ Model expected team total (pts, rebounds, assists budget)   │
│       NBA: ~115 pts/game distributed across ~8 players         │
│       If SGA projected 35+ pts, adjust teammates downward      │
│  ⬜ Win/loss influence on stat lines                            │
│       Star player underperforms → team loses → support players │
│       must carry → their UNDERs become less likely             │
│       e.g. OKC: SGA cold → Lu Dort/Holmgren must do more      │
│  ⬜ Pace/tempo influence (high-pace games inflate counting stats│
│                                                                 │
│  LAYER 3 — PARLAY CONSTRUCTION ENGINE                           │
│  ⬜ Input: today's ML predictions + correlation matrix          │
│  ⬜ Stacking rules (PrizePicks / sportsbook compliance):        │
│       Min 2 different teams in a parlay                        │
│       Handle "power play" vs. "flex play" modes                │
│  ⬜ Optimizer: maximize combined EV subject to correlation cap  │
│       e.g. don't stack 3 players with r > 0.7 (too correlated)│
│  ⬜ Output: ranked list of 2-leg, 3-leg, 4-leg parlay combos   │
│                                                                 │
│  LAYER 4 — CROSS-SPORT PARLAYS                                  │
│  ⬜ Baseline: NBA and NHL are largely uncorrelated              │
│       Combining reduces single-sport variance                  │
│  ⬜ Future sports (NFL, MLB, NCAAB, Soccer) add more legs       │
│  ⬜ Analyze: does cross-sport mixing improve EV or just dilute? │
│       Answer via backtest on graded outcome pairs              │
│                                                                 │
│  LAYER 5 — DISCORD / APP INTEGRATION                            │
│  ⬜ Daily "PARLAY OF THE DAY" Discord post (10:20 CST)         │
│       Best 3-leg combo + best 5-leg combo, with correlation    │
│       scores and EV estimate                                   │
│  ⬜ Expose in FreePicks app as "Smart Parlays" tab             │
│  ⬜ User can tap any parlay leg to see individual pick details  │
│                                                                 │
│  DATA REQUIREMENTS                                              │
│  · Need ~1 full season of graded pair outcomes to build        │
│    reliable correlation matrix (~500+ shared game dates)       │
│  · NBA has this now (124k predictions, 79 game days)           │
│  · NHL will have it by end of 2025-26 season                   │
│  · Cross-sport needs concurrent game dates with both sports    │
│                                                                 │
│  TECH STACK (proposed)                                          │
│  · scipy.stats.pearsonr for pairwise correlations              │
│  · scipy.optimize or PuLP for parlay LP optimization           │
│  · New table: player_correlations (player_a, player_b,         │
│               prop_a, prop_b, r, n_samples, last_updated)      │
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
  1. ⬜  Configure Discord OAuth (~5 min)                         [BLOCKER]
          → discord.com/developers → New App → OAuth2 → copy ID+Secret
          → Add redirect: https://***REMOVED***/auth/v1/callback
          → Enable via Supabase Management API (curl command in FREEPICKS_PLAN.md)

  2. ⬜  Test app on device (Expo Go)
          → cd mobile && npx expo start
          → Scan QR code
          → Verify: sign-in → profile created → picks appear → make a pick

  3. ⬜  Monitor first ML-driven predictions (Feb 24+)
          → Verify real probability spread (not all 80%)
          → Check for data timing issues on combo stat L5 values
          → Watch NHL predictions Feb 25 (first post-Olympic-break run)

  4. ⬜  Fix data timing: combo stat L5 stale after restarts
          → Grading must populate player_game_logs before predictions run
          → Investigate: does grading update player_game_logs or only prediction_outcomes?
          → Consider: prediction script should refresh recent game logs on startup

  5. ⬜  Begin Phase 5 groundwork: player correlation matrix
          → Query graded outcome pairs for all players on shared game dates
          → Compute Pearson r for each (playerA_prop, playerB_prop) pair
          → Store in new player_correlations table

  6. ⬜  Begin Phase 2 planning (leaderboard, friends, push notifications)
```
