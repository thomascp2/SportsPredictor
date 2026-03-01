# Option D: Add admin monitoring tab to FreePicks mobile app

**Label:** enhancement, mobile
**Priority:** Medium (best long-term path — one app for everything)
**Blocked by:** OAuth providers not yet configured (Discord/Google/Apple)

---

## Context

From the Feb 28 2026 session — we evaluated 4 options for mobile monitoring of picks,
system health, and model performance. Option D integrates monitoring directly into the
FreePicks React Native app as an admin-only tab, using the Supabase backend already in place.

This is the best long-term solution but requires OAuth to be working first so the admin
user can be authenticated.

---

## What this needs

### 1. Admin guard
- Check `profiles.role` in Supabase (or a hardcoded admin UID list) on app load
- Only show the Monitor tab if the signed-in user is an admin
- Non-admin users see nothing different

### 2. New tab: Monitor (5th tab, admin-only)
Add to the existing 4-tab navigator (`mobile/App.tsx`):

```
Play | Scores | Track | Profile | Monitor (admin only)
```

### 3. Monitor tab screens

**System Health screen**
- Last prediction date + count per sport (query `daily_props`)
- Pipeline status: Today ✅ / Yesterday 🟡 / Stale 🔴
- API health indicators (cached, refreshes every 5 min)

**Picks screen** (mirrors `cloud_dashboard.py` Today's Picks tab)
- Sport selector (NBA / NHL)
- Date picker (default today)
- Filterable table: player, prop, line, probability, edge, tier
- Tap a row to see full pick details

**Performance screen**
- Accuracy last 14 days (overall, by tier, by prop)
- Graded counts per sport
- Line chart: model accuracy over time (from `model_performance` table)

**Pipeline Log screen** (nice to have)
- Last 7 days of prediction + grading run history
- Success/failure status, counts, timestamps

### 4. Supabase queries needed
All data is already in Supabase — just needs React Native screens to query it:
- `daily_props` — picks, accuracy
- `model_performance` — trend data
- `daily_games` — game status

### 5. Zustand store
Add `adminStore.ts` (or extend existing stores) to cache monitoring data with a 5-min TTL.

---

## Implementation order

1. Add `role` column to `profiles` table in Supabase (`anon` | `admin`)
2. Set admin role for your user account
3. Add Monitor tab to navigator (hidden for non-admins)
4. Build System Health screen (simplest — just a few metric cards)
5. Build Picks screen (table component, reuse existing UI patterns)
6. Build Performance screen (charts — use `react-native-chart-kit` or Victory Native)

---

## Relevant files

- `mobile/App.tsx` — tab navigator (add 5th tab here)
- `mobile/src/services/supabase.ts` — Supabase client (already configured)
- `mobile/src/types/supabase.ts` — TypeScript types
- `supabase/migrations/001_initial_schema.sql` — table schemas
- `dashboards/cloud_dashboard.py` — Streamlit equivalent (reference for what to show)
- `docs/sessions/2026-02-28.md` — Session notes with full option comparison

---

## Prerequisites

- [ ] OAuth configured (Discord easiest — discord.com/developers, ~5 min)
- [ ] At least one user has signed in (to set admin role)
- [ ] `profiles.role` column added to Supabase
