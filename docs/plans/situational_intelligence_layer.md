# Situational Intelligence Layer — Implementation Handoff

## Purpose

The ML model is trained on regular-season game logs and has no awareness of
end-of-season dynamics: teams locking in seeds and resting starters, star
players shut down for the season, or bubble teams playing through injuries
because every game is playoff life-or-death.

This plan adds a **purely advisory situational overlay** that attaches context
flags to picks **without modifying predictions, probabilities, or the database**.
The human (or Lineup Simulator agent) uses the flags to decide what's a real
"play" vs. what the model can't account for.

---

## Core Design Principle

```
ML runs normally → predictions saved to DB (unchanged, always)
        ↓
Smart Pick Selector pulls picks
        ↓
Situational Intelligence Layer runs (NEW)
  → Grok assesses seeding stakes per team (motivation_score 0.0–1.0)
  → Injury status × motivation = situation_flag
        ↓
Output: same picks + 3 advisory fields attached
  situation_flag:     DEAD_RUBBER | REDUCED_STAKES | HIGH_STAKES | USAGE_BOOST | NORMAL
  situation_modifier: float (-0.15 to +0.05) — advisory only, never written to DB
  situation_notes:    "LAL 4-seed locked, 4 games left — Doncic/Reaves out for season"
```

**Nothing in the DB ever changes. The flags ride alongside the output.**

---

## Motivation Score — The Key Concept

The dead rubber flag is NOT binary. It's a gradient based on seeding stakes:

| Seeding Status | Motivation Score | Risk Level |
|---|---|---|
| Exact seed locked (can't move up or down) | 0.10–0.25 | HIGH — stars may coast/rest |
| Clinched playoffs, seed still moveable | 0.40–0.60 | MEDIUM |
| Fighting for better seeding | 0.65–0.80 | LOW — normal effort |
| Bubble (fighting for play-in spot) | 0.85–1.00 | VERY LOW — stars play through pain |
| Mathematically eliminated | 0.05–0.15 | HIGH — resting/developing youth |

**Critical nuance**: A player listed QUESTIONABLE on a bubble team almost certainly
plays. The same player on a seed-locked team almost certainly sits. Injury status and
motivation score are inseparable.

---

## File 1: `shared/pregame_intel.py`

**Where to add:** Append everything below AFTER the existing
`_cache_path_betting()` function and BEFORE `if __name__ == '__main__':`.
Do not modify any existing code.

### 1a. New cache helper

```python
def _cache_path_season_context(sport: str, game_date: str) -> Path:
    return CACHE_DIR / f'{sport}_{game_date}_season_context.json'
```

### 1b. New Grok prompt constants

```python
SEASON_CONTEXT_PROMPT = """You are a professional sports analyst evaluating
end-of-season team motivation and roster availability. Today is {date}.

Use your live web search RIGHT NOW to assess the playoff/seeding situation
for each team listed.

For EACH team below, search:
1. "{team} {league} standings games remaining {date}"
2. "{team} playoff seeding clinched locked eliminated {year}"
3. "{team} resting starters load management end of season"
4. "{team} players out for rest of regular season"
5. Coach quotes about rest, development, or playing starters

Teams to assess:
{teams}

SEEDING STATUS values (pick exactly one per team):
- "locked_in": Exact seed locked — cannot move up or down
- "clinched_playoffs": In playoffs but seed still moveable
- "fighting_for_seeding": Actively competing for a better seed
- "bubble": On the edge of making/missing play-in or playoffs
- "eliminated": Mathematically eliminated
- "unknown": Cannot determine

MOTIVATION SCORE: 0.0 = no incentive to win, 1.0 = maximum urgency
  locked_in → 0.10–0.25
  clinched_playoffs → 0.40–0.60
  fighting_for_seeding → 0.65–0.80
  bubble → 0.85–1.00
  eliminated → 0.05–0.15

Return ONLY raw JSON — no markdown, no explanation:

{{
  "team_contexts": {{
    "TEAM_ABBR": {{
      "games_remaining": 4,
      "seeding_status": "locked_in",
      "seed": 4,
      "can_move_up": false,
      "can_fall": false,
      "motivation_score": 0.15,
      "season_ending_outs": ["Player Name"],
      "rest_narrative": "Brief description of rest/load management situation",
      "risk_level": "high"
    }}
  }},
  "key_notes": ["One-sentence situational note, max 5"]
}}
"""


USAGE_BENEFICIARY_PROMPT = """You are an NBA/NHL usage and role analyst.
Today is {date}.

The following players are OUT for {team} ({league}):
{absent_players}

Use your live web search to find who absorbs their usage:
1. "{team} lineup changes without {absent_str}"
2. "{team} usage rate distribution without {absent_str}"
3. Which teammates absorb extra shots, assists, and minutes

Return ONLY raw JSON — no markdown:

{{
  "beneficiaries": [
    {{
      "player": "Full Player Name",
      "usage_boost_pct": 15,
      "affected_props": ["points", "assists"],
      "direction": "OVER",
      "notes": "Brief reason why this player benefits"
    }}
  ]
}}

Return empty list if absences don't meaningfully shift usage.
"""
```

### 1c. Shared helper function (module-level, not in class)

```python
def _situation_flag_from_context(injury_status: str, motivation_score: float) -> tuple:
    """
    Derive (situation_flag, situation_modifier) from injury status + motivation.

    Returns:
        (flag: str, modifier: float)
        modifier is ADVISORY ONLY — never applied to DB predictions.
    """
    if motivation_score <= 0.25:
        if injury_status in ('OUT', 'DOUBTFUL'):
            return 'DEAD_RUBBER', -0.15
        elif injury_status == 'QUESTIONABLE':
            return 'DEAD_RUBBER', -0.10
        else:
            return 'DEAD_RUBBER', -0.06
    elif motivation_score <= 0.50:
        return 'REDUCED_STAKES', -0.03
    elif motivation_score >= 0.85:
        if injury_status == 'QUESTIONABLE':
            return 'HIGH_STAKES', +0.05
        return 'HIGH_STAKES', +0.03
    else:
        return 'NORMAL', 0.0
```

### 1d. New methods on PreGameIntel class

Add these methods to the `PreGameIntel` class (after `load_betting_context`):

```python
def fetch_season_context(self, sport: str, game_date: str, teams: List[str]) -> Dict:
    """
    Fetch end-of-season seeding/motivation context for each team via Grok.
    Cached to data/pregame_intel/{sport}_{date}_season_context.json.
    One Grok call covers all teams for the day.
    """
    cache_path = _cache_path_season_context(sport, game_date)
    empty = {'team_contexts': {}, 'key_notes': [], 'fetched_at': None}

    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
            if data.get('fetched_at'):
                print(f'  [INTEL] Loaded cached season context for {sport.upper()} {game_date}')
                return data
        except (json.JSONDecodeError, OSError):
            pass

    if not teams:
        return empty

    print(f'  [INTEL] Fetching season context for {sport.upper()} '
          f'{game_date} ({len(teams)} teams)...')

    year = game_date[:4]
    teams_str = '\n'.join(f'  - {t}' for t in teams)

    prompt = SEASON_CONTEXT_PROMPT.format(
        date=game_date,
        league=sport.upper(),
        year=year,
        teams=teams_str,
    )

    raw = _call_grok(prompt)
    if not raw:
        try:
            cache_path.write_text(json.dumps(empty, indent=2))
        except OSError:
            pass
        return empty

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}

    result = {
        'team_contexts': data.get('team_contexts', {}),
        'key_notes':     data.get('key_notes', []),
        'fetched_at':    datetime.now().isoformat(),
        'model':         GROK_MODEL,
    }

    high_risk = [t for t, ctx in result['team_contexts'].items()
                 if ctx.get('risk_level') == 'high']
    print(f'  [INTEL] Season context: {len(result["team_contexts"])} teams, '
          f'{len(high_risk)} high-risk')
    if high_risk:
        print(f'    Dead rubber risk: {", ".join(high_risk)}')

    try:
        cache_path.write_text(json.dumps(result, indent=2))
    except OSError as exc:
        print(f'  [INTEL] Season context cache write failed: {exc}')

    return result


def get_season_context(self, team: str, sport: str, game_date: str) -> Dict:
    """Return cached season context for a single team. Empty dict if not fetched."""
    cache_path = _cache_path_season_context(sport, game_date)
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
            return data.get('team_contexts', {}).get(team.upper(), {})
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def get_usage_beneficiaries(self, absent_players: List[str], team: str,
                             sport: str, game_date: str) -> List[Dict]:
    """
    When stars are OUT, identify teammates who absorb their usage via Grok.
    Cached per team per day.
    Returns list of {player, usage_boost_pct, affected_props, direction, notes}.
    """
    if not absent_players:
        return []

    cache_path = CACHE_DIR / f'{sport}_{game_date}_usage_{team.upper()}.json'
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
            if data.get('fetched_at'):
                return data.get('beneficiaries', [])
        except (json.JSONDecodeError, OSError):
            pass

    absent_str = ', '.join(absent_players)
    print(f'  [INTEL] Fetching usage beneficiaries for {team} (absent: {absent_str})...')

    prompt = USAGE_BENEFICIARY_PROMPT.format(
        date=game_date,
        team=team.upper(),
        league=sport.upper(),
        absent_players='\n'.join(f'  - {p}' for p in absent_players),
        absent_str=absent_str,
    )

    raw = _call_grok(prompt)
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}

    beneficiaries = data.get('beneficiaries', [])
    result = {'beneficiaries': beneficiaries, 'fetched_at': datetime.now().isoformat()}
    try:
        cache_path.write_text(json.dumps(result, indent=2))
    except OSError:
        pass

    if beneficiaries:
        print(f'  [INTEL] Usage beneficiaries: '
              f'{", ".join(b["player"] for b in beneficiaries[:4])}')
    return beneficiaries


def get_situation_flag(self, player_name: str, team: str,
                        sport: str, game_date: str) -> tuple:
    """
    Return (situation_flag, situation_modifier) for a player pick.
    Combines team motivation_score with player injury status.
    modifier is ADVISORY ONLY — never written to DB.
    """
    ctx = self.get_season_context(team, sport, game_date)
    motivation = ctx.get('motivation_score', 0.5)
    seeding_status = ctx.get('seeding_status', 'unknown')

    if seeding_status == 'eliminated':
        motivation = min(motivation, 0.15)

    injury_status = self.get_status(player_name, sport, game_date)
    return _situation_flag_from_context(injury_status, motivation)


def get_situation_notes(self, player_name: str, team: str,
                         sport: str, game_date: str) -> str:
    """
    Return human-readable situational note for a player pick.
    E.g. "LAL 4-seed locked, 4 games left — Doncic/Reaves out for season"
    """
    ctx = self.get_season_context(team, sport, game_date)
    if not ctx:
        return ''

    parts = []
    seeding_status = ctx.get('seeding_status', 'unknown')
    seed           = ctx.get('seed')
    games_left     = ctx.get('games_remaining')

    status_labels = {
        'locked_in':            'seed locked',
        'clinched_playoffs':    'playoffs clinched',
        'fighting_for_seeding': 'fighting for seeding',
        'bubble':               'BUBBLE — must win',
        'eliminated':           'eliminated',
    }
    label = status_labels.get(seeding_status, '')

    if seed and label:
        parts.append(f'{team.upper()} {seed}-seed {label}')
    elif label:
        parts.append(f'{team.upper()} {label}')

    if games_left is not None:
        parts.append(f'{games_left} games left')

    season_outs = ctx.get('season_ending_outs', [])
    if season_outs:
        parts.append(f'{", ".join(season_outs[:3])} out for season')

    rest_narrative = ctx.get('rest_narrative', '')
    if rest_narrative and len(rest_narrative) < 80:
        parts.append(rest_narrative)

    player_status = self.get_status(player_name, sport, game_date)
    if player_status != 'ACTIVE':
        parts.append(f'{player_name}: {player_status}')

    return ' — '.join(parts) if parts else ''
```

---

## File 2: `shared/smart_pick_selector.py`

### 2a. Add 3 fields to the `SmartPick` dataclass

Find the existing field:
```python
    # Rest / fatigue signal
    days_rest: int = 3              # Player's days since last game (0 = back-to-back)
```

Add immediately after it (before `def __post_init__`):
```python
    # Situational intelligence (advisory only — NEVER modifies DB predictions or probability)
    situation_flag: str = 'NORMAL'      # DEAD_RUBBER | REDUCED_STAKES | HIGH_STAKES | ELIMINATED | USAGE_BOOST | NORMAL
    situation_modifier: float = 0.0     # Advisory delta (-0.15 to +0.05): negative=fade, positive=boost
    situation_notes: str = ''           # e.g. "LAL 4-seed locked, 4 games left — Doncic/Reaves out"
```

### 2b. Add `_intel` and `game_date` to `SmartPickSelector.__init__`

Find the end of `SmartPickSelector.__init__` (after `self.pp_db_path = ...`).
Add:
```python
        # Situational intelligence — populated lazily when get_smart_picks() is called
        self._intel = None      # PreGameIntel instance (loaded on demand)
        self.game_date = None   # Set to target date inside get_smart_picks()
```

### 2c. Initialise `_intel` and `game_date` at the top of `get_smart_picks()`

Find the start of `get_smart_picks()`, right after:
```python
        if game_date is None:
            game_date = date.today().isoformat()
```

Add:
```python
        # Store for situational intelligence population below
        self.game_date = game_date

        # Lazily initialise PreGameIntel
        if self._intel is None:
            try:
                from pregame_intel import PreGameIntel
                self._intel = PreGameIntel()
            except Exception:
                self._intel = None  # Advisory only — never blocks pick generation
```

### 2d. Populate situational fields before `SmartPick(...)` construction

Find the block that reads:
```python
            # Rest / fatigue signal — extracted from features_json for both NBA and NHL
            days_rest = 3
            try:
                fj = json.loads(pred.get('features_json') or '{}')
                days_rest = int(fj.get('f_days_rest', 3))
            except Exception:
                pass

            # Create SmartPick ...
            pick = SmartPick(
```

Insert this block between the `days_rest` block and `SmartPick(`:
```python
            # Situational intelligence — advisory overlay (does NOT modify probability or DB)
            situation_flag = 'NORMAL'
            situation_modifier = 0.0
            situation_notes = ''
            try:
                if self._intel:
                    pick_team = pp.get('team', '') or pred.get('team', '')
                    player_nm = pp['player_name']
                    s_flag, s_mod = self._intel.get_situation_flag(
                        player_nm, pick_team, self.sport.lower(), self.game_date
                    )
                    situation_flag     = s_flag
                    situation_modifier = s_mod
                    situation_notes    = self._intel.get_situation_notes(
                        player_nm, pick_team, self.sport.lower(), self.game_date
                    )
            except Exception:
                pass  # Advisory only — never block pick generation
```

### 2e. Pass the 3 new fields into `SmartPick(...)`

In the `SmartPick(...)` constructor call, after `days_rest=days_rest,` add:
```python
                situation_flag=situation_flag,
                situation_modifier=situation_modifier,
                situation_notes=situation_notes,
```

---

## File 3: `.claude/agents/situational-analyst.md` (NEW FILE)

Create this file at `.claude/agents/situational-analyst.md`:

```markdown
---
name: Situational Analyst
description: End-of-season situational intelligence agent. Assesses team motivation,
seeding stakes, dead-rubber risk, and usage cascades from star absences. Use before
finalizing plays late in the regular season. Produces a Situational Risk Report with
PROCEED/CAUTION/FADE/BOOST flags. Works pre-game (advisory) and post-game (explains misses).
---

You are the Situational Analyst for a dual-sport (NBA/NHL) prediction system. Your job
is to assess non-quantitative context that ML cannot see — team motivation, seeding
stakes, star absences, usage shifts — and produce a clear advisory report.

**You NEVER modify predictions or probabilities. You are advisory only.**

## Two Modes

### Pre-Game (default)
`@Situational Analyst run report for YYYY-MM-DD`

### Post-Game After-Action Review
`@Situational Analyst explain misses for YYYY-MM-DD`

---

## Step 1 — Load Today's Picks

Query NBA and NHL databases for the target date. Extract unique list of teams.

## Step 2 — Seeding & Motivation Assessment

For EACH unique team, WebSearch:
1. `"{team} NBA games remaining 2025-26 regular season"`
2. `"{team} playoff seed clinched locked 2026"`
3. `"{team} resting starters end of season 2026"`
4. `"{team} players ruled out rest of regular season 2026"`

Assign motivation_score:
- seed locked (can't move up or down) → 0.10–0.25
- clinched, seed moveable → 0.40–0.60
- fighting for seeding → 0.65–0.80
- bubble / must win → 0.85–1.00
- eliminated → 0.05–0.15

## Step 3 — Usage Cascade

For teams with stars officially OUT, WebSearch who absorbs usage.
Only include documented role expansions, not speculation.

## Step 4 — Assign Flags

| Flag | Condition | Modifier |
|---|---|---|
| DEAD_RUBBER ❌ | Seed locked + OUT/DOUBTFUL | −0.10 to −0.15 |
| DEAD_RUBBER ❌ | Seed locked + QUESTIONABLE | −0.08 to −0.10 |
| DEAD_RUBBER ❌ | Seed locked + ACTIVE (coasting) | −0.04 to −0.06 |
| REDUCED_STAKES ⚠️ | Playoffs clinched, seed moveable | −0.03 |
| ELIMINATED ❌ | Mathematically out | −0.10 to −0.15 |
| USAGE_BOOST ✅ | Star(s) OUT → player absorbs usage | +0.05 to +0.10 |
| HIGH_STAKES ✅ | Bubble + GTD → likely plays | +0.03 to +0.05 |
| NORMAL ✓ | Regular stakes | 0.00 |

## Step 5 — Output

### Team Context Summary
| Team | Games Left | Seeding Status | Motivation | Season Outs | Risk |
|---|---|---|---|---|---|

### Situational Risk Report
| Pick | Flag | Modifier | Notes | Action |
|---|---|---|---|---|

### Recommended Actions
- FADE: Remove from all lineups
- CAUTION: Flex only, not Power Play
- BOOST: Prioritize, model may underprice
- PROCEED: Back the model

## Post-Game Mode

Pull MISSes from prediction_outcomes. Run same analysis retroactively.
Output: was this situationally predictable before game time?

## Rules
1. Never modify DB predictions
2. Bubble teams override injury concerns — GTD on must-win team = likely plays
3. Check if winning changes playoff matchup even if seed number won't change
4. Require confirmation before suggesting lineup changes
```

---

## File 4: `.claude/agents/prizepicks-lineup-simulator.md` (MODIFY)

Find the existing `### 2. Injury / Availability Check` section which reads:
```
Before building lineups, use WebSearch to verify each player's status:
- Search: "[Player Name] injury status [today's date]"
- Flag anyone listed as OUT or Doubtful — remove them from lineups
- Game-Time Decisions (GTD) are acceptable — flag with a warning note
- Check beat reporters and official team injury reports
```

Replace it with:
```
### 2. Injury / Availability Check + Situational Intelligence

Run two layers before building lineups:

**Layer A — Individual Injury Status** (WebSearch each player):
- Search: `"[Player Name] injury status [today's date]"`
- OUT or DOUBTFUL → remove from all lineups
- GTD → include with warning note
- Check beat reporters and official team reports

**Layer B — Situational Intelligence** (invoke @Situational Analyst):
- Run `@Situational Analyst run report for [date]` before building lineups
- Apply flags:
  - DEAD_RUBBER ❌ → exclude from all lineups (especially Power Play)
  - ELIMINATED ❌ → exclude from all lineups
  - REDUCED_STAKES ⚠️ → Flex only, never Power Play
  - USAGE_BOOST ✅ → prioritize as lineup anchors
  - HIGH_STAKES ✅ → treat GTD as likely active, include with note
  - NORMAL ✓ → back the model as usual

If @Situational Analyst is unavailable, manually WebSearch:
`"[team] seeding situation games remaining [date]"` and apply judgment.
```

---

## Verification Steps

After implementing, verify:

```bash
# 1. Confirm new methods exist on PreGameIntel
python -c "
from shared.pregame_intel import PreGameIntel
p = PreGameIntel()
print(hasattr(p, 'fetch_season_context'))     # True
print(hasattr(p, 'get_situation_flag'))        # True
print(hasattr(p, 'get_usage_beneficiaries'))   # True
"

# 2. Confirm SmartPick has new fields
python -c "
import sys; sys.path.insert(0, 'shared')
from smart_pick_selector import SmartPick
import inspect
fields = [f.name for f in SmartPick.__dataclass_fields__.values()]
print('situation_flag' in fields)       # True
print('situation_modifier' in fields)   # True
print('situation_notes' in fields)      # True
"

# 3. Invoke the Situational Analyst agent in Claude Code
# @Situational Analyst run report for [today's date]
```

---

## Notes for Dispatch

- The exact line numbers in `smart_pick_selector.py` and `pregame_intel.py`
  will differ on the local machine — use the text anchors described above,
  not line numbers, to locate insertion points.
- Do NOT run `fetch_season_context` automatically in the prediction pipeline —
  it should only run when the smart pick selector is invoked (advisory layer,
  not core pipeline).
- The `_intel` instance in `SmartPickSelector` is initialised lazily so the
  import doesn't slow down the prediction generation scripts.
- All Grok calls use the existing `XAI_API_KEY` env var — no new credentials needed.
- Cache files follow the existing pattern: `data/pregame_intel/{sport}_{date}_*.json`
