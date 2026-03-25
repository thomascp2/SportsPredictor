# FreePicks — Project Roadmap

*Last updated: 2026-03-02*

---

## At a Glance

```
                         F R E E P I C K S   R O A D M A P
  ──────────────────────────────────────────────────────────────────────────────

  PHASE 1 ████████████████████████████ COMPLETE (Feb 14, 2026)
  Foundation: Backend + Mobile MVP + Sync Pipeline

  PHASE 2 ████████████████████████████ COMPLETE (Mar 2, 2026)
  Dashboard & Data: Cloud dashboard live, data quality hardened

  PHASE 3 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ~Apr 2026
  Mobile Launch: OAuth, device test, App Store prep

  PHASE 4 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ~May 2026
  Social: Leaderboard + Friends + Push Notifications

  PHASE 5 ████████████████████████████ COMPLETE (Feb 23, 2026)
  ML Upgrade: 19 models trained, learning mode lifted, real probabilities live

  PHASE 6 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ~Jun 2026
  Monetization: FreePicks Plus + Ads + Sportsbook Links

  PHASE 7 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ~Aug 2026
  Correlated Parlay Optimizer: team stacking, zero-sum awareness, cross-sport EV
  ──────────────────────────────────────────────────────────────────────────────
```

---

## Phase 1 — Foundation (Complete ✅ Feb 14, 2026)

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
│       award-points      →  streak logic, tier, point ledger    │
│                                                                 │
│  SYNC PIPELINE (Python)                                         │
│  ✅ supabase_sync.py — predictions + grading + smart-picks     │
│  ✅ game_sync.py — ESPN live scores → daily_games               │
│  ✅ Orchestrator auto-sync after prediction + grading runs     │
│                                                                 │
│  MOBILE APP (Expo React Native)                                 │
│  ✅ Auth gate + 4-tab navigator (Play | Scores | Track | Profile│
│  ✅ Social OAuth (expo-web-browser, freepicks:// scheme)        │
│  ✅ 5 Zustand stores (auth, picks, bets, watchlist, parlay)    │
│  ✅ 12 screens, 9 components, 7 hooks                           │
│  ✅ Points system wired (10pts/hit, streak bonuses)             │
│  ✅ Watchlist (max 10 players)                                  │
│                                                                 │
│  STILL PENDING (Phase 3 blocker):                               │
│  ⬜ OAuth provider credentials (Discord/Google/Apple)           │
│  ⬜ First device test via Expo Go                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 2 — Dashboard & Data Infrastructure (Complete ✅ Mar 2, 2026)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 2 — DASHBOARD & DATA INFRASTRUCTURE         COMPLETE ✅  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  CLOUD DASHBOARD (cloud_dashboard.py)                           │
│  ✅ Streamlit app backed by Supabase (port 8502)               │
│  ✅ Cloudflare quick tunnel — public URL via cloudflared.exe   │
│  ✅ Launched via start_dashboard.bat                           │
│  ✅ Today's Picks: All Picks | By Prop | Parlay Builder tabs   │
│  ✅ Line Compare tab — card+badge layout per player-prop       │
│       Dark green = recommended, dim green = above BE, red = ↓ │
│  ✅ Performance tab — historical accuracy by sport/prop        │
│  ✅ System tab — pipeline health, last sync times              │
│  ✅ Game times displayed ("1:10 PM ET") from Supabase          │
│                                                                 │
│  ORCHESTRATOR SYNC PIPELINE (fully automated)                   │
│  ✅ sync_predictions() — base prediction rows                  │
│  ✅ sync_smart_picks() — AI pick enrichment                    │
│  ✅ sync_odds_types() — goblin/demon/standard labels           │
│  ✅ sync_game_times() — game tip-off times from PP data        │
│       All 4 wired into orchestrator — no manual intervention   │
│                                                                 │
│  DATA QUALITY HARDENING (Mar 1–2, 2026)                        │
│  ✅ Traded players: sync_predictions() loads PP team lookup    │
│       PP team is ALWAYS authoritative over local DB team       │
│  ✅ Multiple STD lines: median line kept, extras dropped       │
│       Platform rule enforced: max 1 STD line per player-prop  │
│  ✅ Probability inversion: pred_lookup sorted by prob desc     │
│  ✅ Goblin/demon UNDERs: client-side post-filter in dashboard  │
│  ✅ Team abbreviation normalization (BKN/BRK, PHO/PHX etc.)   │
│  ✅ Player name ASCII normalization (accents stripped)         │
│  ✅ NHL name abbreviation matching (A. Fox ↔ Adam Fox)         │
│                                                                 │
│  DISCORD BOT & WEBHOOKS                                         │
│  ✅ FreePicks Bot (ID: 1477419889667866727)                    │
│  ✅ !parlay [nba|nhl|both] [2-6] — random top-10 parlay       │
│  ✅ !picks [nba|nhl] — top 20 picks                            │
│  ✅ !status / !health / !predict / !grade                      │
│  ✅ Daily Discord top-20 at 6:15 AM CST (both sports)         │
│       NHL: 2 messages (any direction + OVERs only)             │
│       NBA: 1 message (top picks)                               │
│                                                                 │
│  STILL PENDING:                                                 │
│  ⬜ Permanent URL (Streamlit Community Cloud deployment)        │
│  ⬜ Dashboard URL announcement to users each restart           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 3 — Mobile Launch (~Apr 2026)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3 — MOBILE LAUNCH                           UPCOMING    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  OAUTH CONFIGURATION (BLOCKER)                                  │
│  ⬜ Discord OAuth — discord.com/developers → OAuth2             │
│       Callback: https://***REMOVED***/      │
│                 auth/v1/callback                               │
│  ⬜ Google OAuth — Google Cloud Console                        │
│  ⬜ Apple Sign-In — Apple Developer Portal                      │
│  ⬜ Enable all 3 in Supabase Auth dashboard                     │
│                                                                 │
│  FIRST DEVICE TEST                                              │
│  ⬜ cd mobile && npx expo start                                 │
│  ⬜ Scan QR → Expo Go on iOS/Android                           │
│  ⬜ Verify: sign-in → profile created → picks appear            │
│  ⬜ Make a pick → confirm points awarded → grade fires          │
│  ⬜ Test watchlist (add/remove, max 10)                         │
│  ⬜ Test parlay builder (combine picks)                         │
│                                                                 │
│  UI POLISH                                                      │
│  ⬜ Loading state skeletons                                     │
│  ⬜ Error state empty screens                                   │
│  ⬜ Offline banner                                              │
│  ⬜ Accessibility pass (a11y labels)                            │
│                                                                 │
│  PERMANENT DEPLOYMENT                                           │
│  ⬜ Streamlit Community Cloud — share.streamlit.io              │
│       Stable URL for dashboard (no tunnel restart needed)      │
│  ⬜ Expo EAS Build — generate .ipa and .apk                     │
│  ⬜ TestFlight (iOS internal testing)                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 4 — Social & Discovery (~May 2026)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 4 — SOCIAL & DISCOVERY                      UPCOMING    │
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
│  DATA ENRICHMENT                                                │
│  ⬜ Player news integration (injury / lineup alerts)            │
│  ⬜ Historical pick accuracy by player / prop type for users    │
│  ⬜ "On fire" indicators (player on streak)                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 5 — ML Upgrade (Complete ✅ Feb 23, 2026)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 5 — ML UPGRADE                              COMPLETE ✅  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  TRAINED & LIVE (Feb 23, 2026)                                  │
│                                                                 │
│  NBA  14/14 core combos  ·  4,506–4,815 samples each           │
│        Best Brier delta: threes_2.5 (+0.12), minutes (+0.12)   │
│        Models: LR / RF / GB / XGBoost / LightGBM competed      │
│        Registry: ml_training/model_registry/nba/               │
│                                                                 │
│  NHL  5/5 core combos   ·  all above 6,700 samples             │
│        Best Brier delta: shots_3.5 (+0.39), points_1.5 (+0.34) │
│        Registry: ml_training/model_registry/nhl/               │
│                                                                 │
│  DEPLOYMENT                                                     │
│  ✅ LEARNING_MODE = False in both sport configs                 │
│  ✅ PROBABILITY_CAP removed (0.0–1.0, real spread)             │
│  ✅ NBA V6 wired to ProductionPredictor (ensemble 60/40)        │
│  ✅ NHL V6 was already wired                                    │
│  ✅ Daily Discord top-20 picks at 6:15 AM CST (both sports)    │
│                                                                 │
│  REMAINING / FUTURE MODEL IMPROVEMENTS                          │
│  ⬜ Opponent defensive features for NHL                         │
│  ⬜ Rest/travel fatigue features                                │
│  ⬜ Referee/officiating tendency features (NBA fouls/FTA)       │
│  ⬜ Real-time injury/lineup adjustment                          │
│  ⬜ Retrain periodically as graded data grows                   │
│  ⬜ Fix data timing: combo stat L5 stale after restarts         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 6 — Monetization (~Jun 2026)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 6 — MONETIZATION                            UPCOMING    │
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

## Phase 7 — Correlated Parlay Optimizer (~Aug 2026)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 7 — CORRELATED PARLAY OPTIMIZER             UPCOMING    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  GOAL: Move beyond single-pick confidence to optimal            │
│  COMBINATIONS of picks that maximize EV while managing          │
│  correlation risk. Two modes:                                   │
│    (A) Ceiling parlays — stack correlated OVERs for big payout  │
│    (B) Hedging parlays — mix negative correlations for floor    │
│                                                                 │
│  LAYER 1 — CORRELATION MATRIX                                   │
│  ⬜ Build player-pair correlation dataset from graded outcomes   │
│       For each pair (PlayerA_PropX, PlayerB_PropY):             │
│       Pearson r of actual outcomes on shared game dates         │
│  ⬜ Team-level correlation (teammates vs. opponents)             │
│  ⬜ Cross-sport correlation baseline (NHL+NBA independence)      │
│                                                                 │
│  LAYER 2 — ZERO-SUM / GAME-TOTAL AWARENESS                     │
│  ⬜ Model expected team total (pts, rebounds, assists budget)    │
│       NBA: ~115 pts/game distributed across ~8 players          │
│       If SGA projected 35+ pts, adjust teammates downward       │
│  ⬜ Win/loss influence on stat lines                             │
│  ⬜ Pace/tempo influence (high-pace games inflate counting stats)│
│                                                                 │
│  LAYER 3 — PARLAY CONSTRUCTION ENGINE                           │
│  ⬜ Input: today's ML predictions + correlation matrix           │
│  ⬜ Optimizer: maximize combined EV subject to correlation cap   │
│  ⬜ Output: ranked 2-leg, 3-leg, 4-leg parlay combos            │
│                                                                 │
│  LAYER 4 — CROSS-SPORT PARLAYS                                  │
│  ⬜ NBA + NHL cross-sport parlay analysis                        │
│  ⬜ Future sports: NFL, MLB, NCAAB                               │
│                                                                 │
│  LAYER 5 — INTEGRATION                                          │
│  ⬜ Daily "PARLAY OF THE DAY" Discord post (6:20 AM CST)        │
│  ⬜ "Smart Parlays" tab in FreePicks app                         │
│                                                                 │
│  DATA REQUIREMENTS                                              │
│  · ~1 full season of graded pair outcomes to build reliable    │
│    correlation matrix (~500+ shared game dates)                 │
│  · NBA: approaching this now                                    │
│  · NHL: will have it by end of 2025-26 season                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Parallel Tracks (Ongoing)

```
  PREDICTION ENGINE                  MOBILE APP                    BACKEND / INFRA
  ─────────────────                  ──────────                    ───────────────
  Running 24/7 via orchestrator      Configure OAuth (BLOCKER)     Supabase edge fn monitoring
  Auto-syncs all 4 operations        Device testing (Expo Go)      DB cost monitoring
  Grading after each game            UI polish                     Cloudflare tunnel mgmt
  API health self-healing            App Store prep (Phase 3+)     Streamlit Cloud deploy
  Retrain models as data grows       Android testing               Rate limit review
  Fix combo stat L5 stale bug        Accessibility pass            Index optimization
```

---

## Data Flow Architecture

```
  LOCAL MACHINE                          SUPABASE CLOUD
  ─────────────                          ──────────────

  nhl/database/*.db  ──┐                 ┌─────────────────────────┐
                       │  sync/          │  daily_props            │
  nba/database/*.db  ──┤  supabase_  ──► │  daily_games            │◄── cloud_dashboard.py
                       │  sync.py        │  model_performance      │    (Streamlit, port 8502)
  prizepicks_lines.db──┤                 │                         │    via Cloudflare tunnel
                       │  game_          │  user_picks   ◄─────────┼── Mobile App
  ESPN API           ──┘  sync.py        │  user_bets    ◄─────────┼── (user data)
  (live scores)                          │  profiles     ◄─────────┤
                                         │  watchlist    ◄─────────┤
  orchestrator.py                        │  point_transactions ◄───┘
  (schedules all 24/7)                   │                         │
                                         │  Edge Functions:        │
  Sync order each run:                   │  grade-user-picks  ─────┤
  1. sync_predictions()                  │  award-points      ─────┘
  2. sync_smart_picks()                  └─────────────────────────┘
  3. sync_odds_types()                               │
  4. sync_game_times()                               │ @supabase/supabase-js
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

## Pipeline Schedule (CST, Daily)

```
  TIME      SPORT   OPERATION
  ────────  ──────  ─────────────────────────────────────
  02:00 AM  NHL     Grade yesterday's predictions
  07:30 AM  NHL     Fetch PrizePicks lines
  08:00 AM  NHL     Generate predictions → sync all 4 ops
  09:00 AM  NBA     Grade yesterday's predictions
  09:30 AM  NBA     Fetch PrizePicks lines
  10:00 AM  NBA     Generate predictions → sync all 4 ops
  06:15 AM  BOTH    Discord top-20 picks (NHL: 2 msgs, NBA: 1 msg)
  Every hr  BOTH    Orchestrator health check
```

---

## Immediate Next Steps (Ordered by Priority)

```
  1. ⬜  Configure Discord OAuth (~5 min)                         [BLOCKER for Phase 3]
          → discord.com/developers → New App → OAuth2 → copy ID+Secret
          → Add redirect: https://***REMOVED***/auth/v1/callback
          → Enable in Supabase Auth dashboard

  2. ⬜  Configure Google & Apple OAuth
          → Google: console.cloud.google.com → Credentials → OAuth 2.0 Client
          → Apple: developer.apple.com → Sign In with Apple

  3. ⬜  Test app on device (Expo Go) — after OAuth configured
          → cd mobile && npx expo start
          → Scan QR code on iOS/Android
          → Verify: sign-in → profile created → picks appear → make a pick → grade fires

  4. ⬜  Deploy dashboard to Streamlit Community Cloud (permanent URL)
          → share.streamlit.io → connect GitHub → select cloud_dashboard.py
          → Set SUPABASE_URL + SUPABASE_ANON_KEY as secrets
          → No more Cloudflare restart URL changes

  5. ⬜  Fix data timing: combo stat L5 stale after orchestrator restarts
          → Grading must update player_game_logs before predictions run
          → Investigate whether grading script refreshes logs or only prediction_outcomes
          → Consider: prediction script should refresh recent game logs on startup

  6. ⬜  Retrain ML models on updated dataset (~6 weeks of new data since Feb 23)
          → python orchestrator.py --sport nba --mode once --operation ml-train
          → python orchestrator.py --sport nhl --mode once --operation ml-train
          → Monitor Brier delta improvement

  7. ⬜  Begin Phase 7 groundwork: player correlation matrix
          → Query graded outcome pairs for all players on shared game dates
          → Compute Pearson r for each (playerA_prop, playerB_prop) pair
          → Store in new player_correlations table

  8. ⬜  Begin Phase 4 planning (leaderboard, friends, push notifications)
```

---

## Completed Milestones Log

| Date | Milestone |
|------|-----------|
| Dec 28, 2025 | 30-day launch roadmap created; data collection at 58% |
| Jan 27, 2026 | NBA reached 7,500 predictions per prop |
| Jan 30, 2026 | NHL reached 7,500 predictions per prop |
| Feb 2, 2026 | ML training environment set up |
| Feb 14, 2026 | Phase 1 complete: Supabase backend + mobile MVP + sync pipeline |
| Feb 23, 2026 | Phase 5 complete: 19 ML models trained, learning mode lifted, real probabilities live |
| Feb 25, 2026 | NHL predictions resumed after Olympic break; pipeline reliability hardened |
| Feb 28, 2026 | Discord bot live (!parlay, !picks, !status); NHL name matching fixed (3→39 picks) |
| Mar 1, 2026 | Cloud dashboard launched; De'Aaron Fox trade fix; goblin/demon platform rules |
| Mar 2, 2026 | Phase 2 complete: Line Compare tab, all data quality issues resolved, full sync automation |
