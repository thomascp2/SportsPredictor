# Mobile App TODO — Eliminate Horizontal Scroll / Layout Issues

_Created: 2026-03-15_

## Context
The current mobile app (Expo React Native) is displaying too many T1 picks (200+) and has layout issues where content extends beyond the screen width on smaller devices. These tasks address both the UX/layout problems and the pick overload problem.

---

## Priority 1 — Critical Layout Fixes

### MOB-001: Fix matchup text overflow in PickCard
**File**: `mobile/src/components/picks/PickCard.tsx`
**Problem**: `matchupRow` uses `flexDirection: 'row'` but `matchup` Text has no `flex:1` or `numberOfLines`. Long team names overflow.
**Fix**:
- Add `flex: 1` to `matchup` Text style
- Add `numberOfLines={1}` and `ellipsizeMode="tail"` to matchup `<Text>`
- Ensure `timeBadge`/`todayBadge` have fixed width so they don't squeeze the matchup

### MOB-002: Fix sort bar overflow in SmartPicksScreen
**File**: `mobile/src/screens/SmartPicksScreen.tsx` (line 219-251)
**Problem**: Sort label + horizontal ScrollView chips + "Filters" button all in one row. On 320px screens (iPhone SE), "Filters" button is clipped or pushed off-screen.
**Fix**:
- Move "Filters" button above the sort row as a standalone full-width row with an icon (`⚙` or filter icon from @expo/vector-icons)
- Or: Make sort row take the full width with Filters as an icon-only button (no text)

### MOB-003: Replace prop type filter scrollview with a bottom sheet picker
**File**: `mobile/src/screens/SmartPicksScreen.tsx` (line 330-353)
**Problem**: Horizontal scroll through 14+ prop type names is awkward. Hard to find specific prop on small screen.
**Fix**:
- Add a "Prop" filter button that opens a `Modal` or bottom sheet
- Inside: 2-column grid of prop type chips (wrapping layout)
- Show count of picks per prop type in each chip: `points (87)`

---

## Priority 2 — Pick Overload Fixes (200 T1 picks problem)

### MOB-004: Add default filter to show Top 30 by edge only
**File**: `mobile/src/screens/SmartPicksScreen.tsx`
**Problem**: 200+ T1 picks shown by default. Users can't action 200 props.
**Fix**:
- Add a `topPicks` toggle (default ON): limits list to top 30 picks sorted by edge
- Show "Showing top 30 | See all" link below the filter bar
- This becomes the default "smart" view

### MOB-005: Add per-player pick deduplication view
**File**: `mobile/src/screens/SmartPicksScreen.tsx`
**Problem**: Same player appears 4-8 times (once per prop type per line).
**Fix**:
- Add "1 per player" toggle: for each unique player, show only their highest-edge prediction
- This reduces 200 picks to ~40-50 unique players
- Keep "Show all" option for power users

### MOB-006: Add "UNDER Focus" quick filter preset
**File**: `mobile/src/screens/SmartPicksScreen.tsx`
**Problem**: UNDER predictions hit at 79-93% vs OVER at 58-72%. Users should be steered to UNDERs.
**Fix**:
- Add a quick filter preset row: `ALL | UNDERS | OVERS | PARLAYS`
- "UNDERS" preset: predictionFilter=UNDER + topPicks=true + tier=T1-T2

### MOB-007: Suppress threes OVER picks from display
**File**: `shared/smart_pick_selector.py` (backend) + `mobile/src/screens/SmartPicksScreen.tsx` (frontend guard)
**Problem**: Threes OVER predictions have 0% hit rate (0/126 in last 30d). They inflate T1 count and are harmful.
**Fix**:
- Backend: In `SmartPickSelector._filter_picks()`, add:
  `if pick['prop_type'] == 'threes' and pick['prediction'] == 'OVER': skip`
- Frontend guard (belt-and-suspenders): filter out `prop_type === 'threes' && prediction === 'OVER'` in `filteredPicks` useMemo

---

## Priority 3 — UX Polish

### MOB-008: Add tier count badges to filter chips
**File**: `mobile/src/screens/SmartPicksScreen.tsx`
**Problem**: Users don't know how many picks are behind each tier filter before tapping it.
**Fix**:
- Compute tier counts from `picks` array: `{T1: 42, T2: 28, ...}`
- Show as small badge on each tier chip: `T1-ELITE (42)`

### MOB-009: Add sport-specific pick count in header
**File**: `mobile/src/screens/SmartPicksScreen.tsx`
**Problem**: Summary row shows total count but not breakdown by tier.
**Fix**:
- Expand summary row to: `42 picks | T1:12 T2:8 T3:10 | 9 games`
- Use smaller font, single line

### MOB-010: Audit PlayerCardModal for wide content
**File**: `mobile/src/components/picks/PlayerCardModal.tsx`
**Problem**: Modal shows player history table — potential for wide content if stat columns overflow.
**Fix**:
- Audit table layout: ensure all columns use `flex` not fixed pixel widths
- Add `numberOfLines={1}` to any stat value cells that might wrap

### MOB-011: Audit ParlaySlip leg value row
**File**: `mobile/src/components/parlay/ParlaySlip.tsx`
**Problem**: Three badges (Goblin=0.5L / Standard=1L / Demon=1.5L) in a row could overflow on 320px phones.
**Fix**:
- Wrap badges with `flexWrap: 'wrap'` so they stack to 2 rows on narrow screens

### MOB-012: Add "Today's Best 5" feature card at top of SmartPicksScreen
**New feature**
**Problem**: With 200 picks, new users don't know where to start.
**Fix**:
- Add a horizontal ScrollView card strip at the top (above filters): "Today's Best 5"
- Shows top 5 picks by edge as compact cards: player + prop + direction + edge%
- These are always T1 standard lines, best edge — one per player

---

## Priority 4 — Performance

### MOB-013: Virtualize filter rows with FlatList instead of ScrollView
**File**: `mobile/src/screens/SmartPicksScreen.tsx`
**Problem**: Prop type filter renders all chips even when collapsed. With 14+ prop types per sport, this causes unnecessary re-renders.
**Fix**:
- Replace `ScrollView horizontal` in prop filter row with `FlatList horizontal`
- Use `getItemLayout` for fixed-width chips to improve performance

### MOB-014: Memoize filteredPicks calculation
**File**: `mobile/src/screens/SmartPicksScreen.tsx`
**Problem**: `filteredPicks` useMemo depends on `picks` (large array), but gameFilter comparison runs on every render even when no game filter is set.
**Fix**:
- Short-circuit `pickMatchesGame` check when `gameFilter === null`
- Already partially done — confirm the early return is in place

---

## Out of Scope (Future)
- Push notifications for T1 picks at game-time
- Apple Watch complication showing today's best pick
- Lock screen widget (requires native module)
- Dark/light theme toggle (currently hardcoded dark)
