# PEGASUS Mobile Pick Card — Step 10 Design Spec

**Audience:** Mobile engineer updating `mobile/src/` to display PEGASUS pick data.
**Date:** 2026-04-15
**Backend:** PEGASUS FastAPI (port 8600) → Turso `pegasus_picks` → JSON response
**Legacy backend:** Supabase `daily_props` (PEGASUS does NOT use this — old orchestrator only)

---

## Data Flow

```
PEGASUS/run_daily.py
  → PEGASUS/sync/turso_sync.py (pegasus_picks table)
    → PEGASUS/api/main.py (FastAPI port 8600)
      → mobile picks screen
```

Mobile fetches from:
```
GET http://{server}:8600/picks/{YYYY-MM-DD}?sport=nba&min_tier=T2-STRONG
```

---

## Field Reference (PEGASUSPick JSON)

```ts
interface PEGASUSPick {
  // Identity
  player_name:            string;      // "Kawhi Leonard"
  team:                   string;      // "LAC"
  sport:                  string;      // "nba" | "nhl" | "mlb"
  prop:                   string;      // "pts_asts" | "points" | "hits" | ...
  line:                   number;      // 34.5
  direction:              string;      // "OVER" | "UNDER"
  odds_type:              string;      // "standard" | "goblin" | "demon"
  game_date:              string;      // "2026-04-15"

  // Model outputs
  raw_stat_probability:   number;      // raw stat model output (0.0–1.0)
  ml_probability:         number|null; // ML blend component (null = stat-only)
  blended_probability:    number;      // after ML blend (= raw if no ML)
  calibrated_probability: number;      // DISPLAY THIS — corrected to actual hit rate

  // Edge
  break_even:             number;      // 0.5238 std / 0.7619 goblin / 0.4545 demon
  ai_edge:                number;      // (cal_prob - break_even) × 100 (ppt)
  vs_naive_edge:          number;      // vs always-UNDER baseline

  // Tier
  tier:                   string;      // "T1-ELITE" | "T2-STRONG" | "T3-GOOD" | "T4-LEAN"

  // Situational (advisory — display-only, never affects model output)
  situation_flag:         string;      // "NORMAL" | "HIGH_STAKES" | "DEAD_RUBBER" | "ELIMINATED" | "USAGE_BOOST"
  situation_modifier:     number;      // advisory modifier (display only)
  situation_notes:        string;      // "HIGH STAKES | LAC | 9-seed play-in | 22.0 GB"

  // Sportsbook (nullable — populated only when DK API has the line)
  implied_probability:    number|null; // fair (vig-removed) sportsbook prob for this direction

  // Derived
  true_ev:                number;      // (cal_prob / break_even) - 1  (e.g. 0.62 = +62%)
  usage_boost:            boolean;     // true when situation_flag == "USAGE_BOOST"
  model_version:          string;      // "statistical_v1" | "mlb_xgb_v1" | ...
}
```

---

## Pick Card Layout

```
┌─────────────────────────────────────────────────────────┐
│  [T1-ELITE]  Kawhi Leonard          LAC          NBA    │  ← Header row
│                                                         │
│  pts+asts   UNDER   34.5           [HIGH_STAKES]        │  ← Prop row + situation pill
│                                                         │
│  ────────────────────────────────────────────────       │  ← Edge bar (0→+30%)
│  ██████████████████████░░░░░░░░░░░   +32.8%            │
│                                                         │
│  Model: 85.2%                                           │  ← Probability row
│  Book:  51.4%  |  Edge: +33.8%                         │  ← Only when implied_probability set
│                                                         │
│  True EV: +62.2%                                        │  ← Derived EV
└─────────────────────────────────────────────────────────┘
```

---

## Tier Badge

Color-coded badge in top-left:

| Tier       | Badge Color     | Hex       | Label      |
|------------|-----------------|-----------|------------|
| T1-ELITE   | Gold            | `#F5C518` | T1-ELITE   |
| T2-STRONG  | Silver          | `#A8A9AD` | T2-STRONG  |
| T3-GOOD    | Bronze          | `#CD7F32` | T3-GOOD    |
| T4-LEAN    | Gray            | `#6B7280` | T4-LEAN    |
| T5-FADE    | Red (suppress)  | —         | Hidden     |

**T5-FADE picks are never shown to users.** The API only returns T1–T4 by default.

```tsx
// React Native example
const TIER_COLORS = {
  "T1-ELITE":  "#F5C518",
  "T2-STRONG": "#A8A9AD",
  "T3-GOOD":   "#CD7F32",
  "T4-LEAN":   "#6B7280",
};

<View style={[styles.tierBadge, { backgroundColor: TIER_COLORS[pick.tier] }]}>
  <Text style={styles.tierLabel}>{pick.tier.split("-")[0]}</Text>
</View>
```

---

## Edge Bar

Horizontal progress bar, range 0–30 percentage points:

```tsx
const edgePct = Math.min(Math.max(pick.ai_edge, 0), 30) / 30; // normalize 0–1

<View style={styles.edgeBarContainer}>
  <View style={[styles.edgeBarFill, { width: `${edgePct * 100}%` }]} />
  <Text style={styles.edgeLabel}>{pick.ai_edge > 0 ? "+" : ""}{pick.ai_edge.toFixed(1)}%</Text>
</View>
```

Bar fill color mirrors tier badge. Background is `#E5E7EB` (light gray).

---

## Probability Display

Always show `calibrated_probability` — NOT `raw_stat_probability` or `blended_probability`:

```tsx
// Primary display — always visible
<Text style={styles.modelProb}>
  Model: {(pick.calibrated_probability * 100).toFixed(0)}%
</Text>

// Sportsbook comparison — only when implied_probability is available
{pick.implied_probability != null && (
  <Text style={styles.bookProb}>
    Book: {(pick.implied_probability * 100).toFixed(0)}%
    {" | "}Edge: {pick.ai_edge > 0 ? "+" : ""}{pick.ai_edge.toFixed(1)}%
  </Text>
)}
```

**Display rule:** `"Model: 85%"` (when DK unavailable) or `"Model: 85% | Book: 51% | Edge: +34%"` (when DK available).

---

## Situation Pill

Show as a subtle pill badge on the right side of the prop row.
Hidden when `situation_flag == "NORMAL"`.

| Flag          | Pill Text        | Color     | Meaning                              |
|---------------|------------------|-----------|--------------------------------------|
| HIGH_STAKES   | MUST WIN         | `#EF4444` | Bubble / elimination game — play hard |
| DEAD_RUBBER   | LOW STAKES       | `#9CA3AF` | Seed locked — likely resting stars   |
| ELIMINATED    | ELIMINATED       | `#6B7280` | No playoff shot — full rest mode     |
| USAGE_BOOST   | USAGE UP         | `#F59E0B` | Star out → extra usage expected      |
| REDUCED_STAKES| REDUCED STAKES   | `#D1D5DB` | Clinched but moveable seed           |

```tsx
const SITUATION_CONFIG = {
  HIGH_STAKES:    { label: "MUST WIN",      color: "#EF4444" },
  DEAD_RUBBER:    { label: "LOW STAKES",    color: "#9CA3AF" },
  ELIMINATED:     { label: "ELIMINATED",    color: "#6B7280" },
  USAGE_BOOST:    { label: "USAGE UP",      color: "#F59E0B" },
  REDUCED_STAKES: { label: "REDUCED STAKES",color: "#D1D5DB" },
};

{pick.situation_flag !== "NORMAL" && SITUATION_CONFIG[pick.situation_flag] && (
  <View style={[styles.situationPill, {
    backgroundColor: SITUATION_CONFIG[pick.situation_flag].color
  }]}>
    <Text style={styles.situationText}>
      {SITUATION_CONFIG[pick.situation_flag].label}
    </Text>
  </View>
)}
```

**Tooltip on tap:** Show `pick.situation_notes` (e.g. "HIGH STAKES | LAC | 9-seed play-in | 22.0 GB").

---

## True EV Display

Show below the probability row as a secondary metric:

```tsx
// true_ev = (calibrated_prob / break_even) - 1
// e.g. 0.622 = "+62.2% EV"
const evLabel = pick.true_ev >= 0
  ? `+${(pick.true_ev * 100).toFixed(1)}% EV`
  : `${(pick.true_ev * 100).toFixed(1)}% EV`;

<Text style={[styles.evLabel, { color: pick.true_ev >= 0 ? "#22C55E" : "#EF4444" }]}>
  True EV: {evLabel}
</Text>
```

---

## Odds Type Indicator

Small chip beneath the player name row:

| odds_type | Chip Text | Color     |
|-----------|-----------|-----------|
| standard  | STD       | `#3B82F6` |
| goblin    | GOB       | `#8B5CF6` |
| demon     | DEM       | `#F97316` |

Demon picks have a **lower** break-even (0.4545) — easier to profit from. Show the chip so users understand why a lower model probability can still be a strong pick.

---

## Nullability Contract

All new fields are nullable on the mobile side:

| Field                 | Null when                               | Fallback behavior            |
|-----------------------|-----------------------------------------|------------------------------|
| `implied_probability` | DK API down / no games / market closed  | Hide "Book:" row entirely    |
| `ml_probability`      | NHL/NBA (stat-only sports)              | Omit from tooltip            |
| `situation_flag`      | Never null — defaults to "NORMAL"       | No pill shown                |
| `situation_notes`     | "NORMAL" picks have empty string        | No tooltip                   |
| `true_ev`             | Never null (always computed)            | —                            |

---

## API Integration

### Endpoint
```
GET http://{PEGASUS_HOST}:8600/picks/{date}?sport=nba&min_tier=T2-STRONG
```

### Response format
```json
{
  "game_date": "2026-04-15",
  "sport_filter": "nba",
  "count": 42,
  "picks": [ ... PEGASUSPick objects ... ]
}
```

### Recommended mobile query (daily picks screen)
```ts
const response = await fetch(
  `http://${PEGASUS_HOST}:8600/picks/${today}?min_tier=T2-STRONG&limit=100`
);
const { picks } = await response.json();
```

### Health check
```ts
const { status, last_snapshot, picks_by_sport } = await fetch(
  `http://${PEGASUS_HOST}:8600/health`
).then(r => r.json());
```

---

## Prop Label Display

Map internal prop names to display-friendly labels:

```ts
const PROP_LABELS: Record<string, string> = {
  points:     "PTS",     rebounds:   "REB",
  assists:    "AST",     pts_rebs:   "P+R",
  pts_asts:   "P+A",     rebs_asts:  "R+A",
  pra:        "PRA",     threes:     "3PM",
  steals:     "STL",     blocks:     "BLK",
  stocks:     "S+B",     turnovers:  "TOV",
  fantasy:    "FAN",     shots:      "SOG",
  goals:      "GOL",     hits:       "HIT",
  blocked_shots: "BLS",
  // MLB
  "total_bases": "TB",   home_runs:  "HR",
  strikeouts:  "K",      outs_recorded: "OUT",
  walks:       "BB",
};
```

---

## Summary of Changes Required in mobile/src/

1. **Fetch source:** Point picks screen at `PEGASUS_API_URL` (port 8600) instead of Supabase `daily_props`
2. **Type update:** Add `PEGASUSPick` interface (above) to `mobile/src/types/`
3. **PickCard component:** Add tier badge, edge bar, calibrated prob, situation pill
4. **Config:** Add `PEGASUS_API_URL` env var (e.g., `http://192.168.x.x:8600` for LAN, tunnel URL for external)
5. **Fallback:** Show loading skeleton when API unreachable; do NOT fall back to Supabase automatically

---

*This doc covers Step 10d of the PEGASUS build plan.*
*Next: Step 11 — Game Lines ML (requires full 2026 season data).*
