// ─────────────────────────────────────────────────────────────────────────────
// SportsPredictor / PEGASUS Ecosystem Graph Data
// ─────────────────────────────────────────────────────────────────────────────

export type NodeCategory =
  | 'source'
  | 'core'
  | 'pipeline'
  | 'ml'
  | 'storage'
  | 'pegasus'
  | 'sync'
  | 'output';

/** Whether the node itself IS statistical, ML-based, or infra. */
export type NodeMethod = 'statistical' | 'ml_dormant' | 'ml_active' | 'infra';

export interface EcoNode {
  id: string;
  label: string;
  category: NodeCategory;
  method: NodeMethod;
  desc: string;
  /** Displayed in the info panel — extra bullet points */
  details?: string[];
  /** Relative node size weight (1–10) */
  val: number;
}

export interface EcoLink {
  source: string;
  target: string;
  label?: string;
  /** 'feedback' draws a dimmed dashed style */
  type?: 'data' | 'control' | 'sync' | 'feedback';
}

// ─── COLOURS ────────────────────────────────────────────────────────────────

export const CATEGORY_COLORS: Record<NodeCategory, string> = {
  source:   '#4fc3f7', // sky blue
  core:     '#ffd54f', // amber / gold
  pipeline: '#81c784', // green
  ml:       '#ef5350', // red
  storage:  '#ce93d8', // lavender
  pegasus:  '#ffb74d', // orange
  sync:     '#4dd0e1', // cyan
  output:   '#e0e0e0', // near-white
};

export const CATEGORY_LABELS: Record<NodeCategory, string> = {
  source:   'Data Sources',
  core:     'Orchestration',
  pipeline: 'Prediction Pipelines',
  ml:       'ML Training',
  storage:  'Storage',
  pegasus:  'PEGASUS Layer',
  sync:     'Sync & Integration',
  output:   'Outputs & Consumers',
};

/** Ring colour around the node indicating statistical vs ML method */
export const METHOD_RING: Record<NodeMethod, string> = {
  statistical: '#60a5fa',   // blue ring → pure stats
  ml_dormant:  '#f87171',   // red ring → ML exists but OFF
  ml_active:   '#34d399',   // green ring → ML live (none currently)
  infra:       '#6b7280',   // grey → infrastructure, no method
};

export const METHOD_LABELS: Record<NodeMethod, string> = {
  statistical: 'Statistical model (active)',
  ml_dormant:  'ML model (trained — INACTIVE)',
  ml_active:   'ML model (live)',
  infra:       'Infrastructure',
};

// ─── NODES ──────────────────────────────────────────────────────────────────

export const NODES: EcoNode[] = [

  // ── DATA SOURCES ──────────────────────────────────────────────────────────
  {
    id: 'nhl_api', label: 'NHL Official API', category: 'source', method: 'infra', val: 4,
    desc: 'api-web.nhle.com — authoritative source for game schedules, play-by-play, player stats, goalie data.',
    details: ['Used by both NHL Pipeline (predictions) and NHL Grader (actuals)', 'Provides hits, blockedShots, goals, shots on goal'],
  },
  {
    id: 'espn_api', label: 'ESPN NBA API', category: 'source', method: 'infra', val: 4,
    desc: 'Primary source for NBA box scores and player game-level statistics.',
    details: ['Structure changed Dec 2025 — self-healer patched it automatically', 'players now at data.boxscore.players'],
  },
  {
    id: 'nba_stats_api', label: 'NBA Stats API', category: 'source', method: 'infra', val: 3,
    desc: 'Fallback stats source for NBA grading when ESPN is unavailable.',
    details: ['Six-team abbreviation mismatch vs ESPN (WAS/WSH, NYK/NY, etc.)', 'Handled by TEAM_ALIASES dict in grading script'],
  },
  {
    id: 'prizepicks_api', label: 'PrizePicks API', category: 'source', method: 'infra', val: 5,
    desc: 'Live prop lines: player names, line values, odds_type (standard / goblin / demon).',
    details: [
      'Standard break-even: 52.38%  |  Goblin: 76.19%  |  Demon: 45.45%',
      'Afternoon pp-sync re-fetches lines at 12:30 PM (NBA) / 1 PM (NHL)',
    ],
  },
  {
    id: 'dk_odds', label: 'DraftKings Odds', category: 'source', method: 'infra', val: 4,
    desc: 'Real sportsbook juice fetched by PEGASUS DK client — enables true EV calculation beyond flat -110.',
    details: ['PEGASUS/pipeline/draftkings_odds.py', 'Allows computing actual break-even per line, not assumed 52.4%'],
  },
  {
    id: 'mlb_feeds', label: 'MLB Data Feeds', category: 'source', method: 'infra', val: 3,
    desc: 'Multiple stat sources aggregated into 73k+ historical game logs (latest: Mar 31, 2026).',
    details: ['mlb_feature_store/ + mlb/database/mlb_predictions.db', 'Data collection phase — wiring to PEGASUS in progress'],
  },

  // ── ORCHESTRATOR ──────────────────────────────────────────────────────────
  {
    id: 'orchestrator', label: 'Orchestrator', category: 'core', method: 'infra', val: 10,
    desc: 'Master controller running 24/7 (orchestrator.py). Schedules all pipelines, grading, pp-sync, ML auto-retrain, and Discord alerts.',
    details: [
      'Morning: grade 3/5 AM  →  predict 4/6 AM CST',
      'Afternoon: pp-sync 12:30/1 PM CST (re-fetch lines)',
      'Sunday auto-retrain: NHL 3:30 AM  |  NBA 5:30 AM CST',
      'Skips retrain if < 500 new predictions since last run',
      'Discord: !refresh, !picks, !parlay, !status, !health',
    ],
  },

  // ── PREDICTION PIPELINES ──────────────────────────────────────────────────
  {
    id: 'nhl_pipeline', label: 'NHL Pipeline', category: 'pipeline', method: 'statistical', val: 6,
    desc: 'generate_predictions_daily_V5.py — Poisson distribution model for NHL player props.',
    details: [
      'Props: points (0.5/1.5), shots (1.5/2.5/3.5), hits (0.5–3.5), blocked_shots (0.5/1.5)',
      'Features stored as JSON blob in features_json column',
      'Confidence tiers T1-ELITE → T5-FADE based on edge above break-even',
      'Probability capped 18–77% (statistical model)',
    ],
  },
  {
    id: 'nba_pipeline', label: 'NBA Pipeline', category: 'pipeline', method: 'statistical', val: 6,
    desc: 'generate_predictions_daily_V6.py — Normal distribution model for NBA player props.',
    details: [
      '14 prop types: points, rebounds, assists, threes, steals, blocks, turnovers, PRA, pts+rebs, pts+asts, reb+asts, fantasy, double_double, triple_double',
      'Team assignment CTE fix (Mar 2026): uses most-recent team per player',
      'Threes OVER guard: always skipped (model degenerate, 0% hit rate)',
      'Features as individual f_* columns (50+)',
    ],
  },
  {
    id: 'mlb_pipeline', label: 'MLB Pipeline', category: 'pipeline', method: 'statistical', val: 4,
    desc: 'Statistical model for MLB game lines and player props. LEARNING_MODE=True.',
    details: [
      'mlb/scripts/ — data collection phase',
      'Not yet wired into PEGASUS pick selector',
      'Models will train once sufficient samples collected',
    ],
  },
  {
    id: 'nhl_grader', label: 'NHL Grader', category: 'pipeline', method: 'infra', val: 4,
    desc: 'v2_auto_grade_yesterday_v3_RELIABLE.py — grades yesterday\'s NHL predictions against NHL API actuals.',
    details: [
      'Writes HIT/MISS + actual_value to prediction_outcomes',
      'Fetches hits, blockedShots, goals, shotsOnGoal from NHL API',
      'Creates DB backup before every run',
    ],
  },
  {
    id: 'nba_grader', label: 'NBA Grader', category: 'pipeline', method: 'infra', val: 4,
    desc: 'auto_grade_multi_api_FIXED.py — ESPN primary, NBA Stats API fallback. Integrated with self-healer.',
    details: [
      'Step 0: API health check + self-heal before grading',
      'Writes HIT/MISS + actual_value to prediction_outcomes',
      'Triggers Supabase user-pick grading Edge Function on completion',
    ],
  },

  // ── ML TRAINING ───────────────────────────────────────────────────────────
  {
    id: 'ml_engine', label: 'ML Training Engine', category: 'ml', method: 'infra', val: 7,
    desc: 'ml_training/train_models.py — trains prop-specific models with 4-way temporal split and isotonic calibration.',
    details: [
      'Split: 60% train / 15% val / 10% cal / 15% test (temporal)',
      'Calibration: isotonic regression on held-out cal set only',
      'Auto-retrain: Sundays via orchestrator (skips if < 500 new rows)',
      'Manual: python ml_training/train_models.py --sport nba --all',
    ],
  },
  {
    id: 'nhl_models', label: 'NHL ML Models', category: 'ml', method: 'ml_dormant', val: 5,
    desc: 'v20260325_003 — LR models trained across 13 prop/line combos but NOT active.',
    details: [
      'v2_config.py: MODEL_TYPE = "statistical_only"',
      'Models stored in ml_training/model_registry/nhl/ (gitignored)',
      'Memory note: prior belief "60/40 blend LIVE" was WRONG — verified Apr 2026',
    ],
  },
  {
    id: 'nba_models', label: 'NBA ML Models', category: 'ml', method: 'ml_dormant', val: 5,
    desc: 'REVERTED Apr 2026 — 471 models in registry but LEARNING_MODE=True after Mar 15 retrain catastrophe.',
    details: [
      'Mar 15 retrain: UNDER accuracy 84% → 47% (destroyed)',
      'Root cause: contaminated Jan 18-26 rows + calibration overfit',
      'Next safe retrain: Oct 2026 with clean data',
      'ml_training/model_registry/nba/ (gitignored)',
    ],
  },

  // ── GOLF ──────────────────────────────────────────────────────────────────
  {
    id: 'golf_source', label: 'PGA / ESPN Golf API', category: 'source', method: 'infra', val: 3,
    desc: 'ESPN Golf API + PGA stats scraper — tournament schedules, round scores, strokes-gained, player rankings.',
    details: [
      'golf/scripts/espn_golf_api.py  |  pga_stats_scraper.py',
      'fetch_tournament_schedule.py populates upcoming events',
      'backfill_round_logs.py loaded historical rounds',
    ],
  },
  {
    id: 'golf_pipeline', label: 'Golf Pipeline', category: 'pipeline', method: 'statistical', val: 4,
    desc: 'generate_predictions_daily.py — statistical model for PGA player props (strokes-gained, finish position).',
    details: [
      'LEARNING_MODE = True  |  MODEL_TYPE = "statistical"',
      'golf/scripts/golf_config.py is the config authority',
      'ML scaffold planned post-Masters once samples reach 700+',
      'Props: top-20 finish, top-10 finish, made-cut, round score lines',
    ],
  },
  {
    id: 'golf_grader', label: 'Golf Grader', category: 'pipeline', method: 'infra', val: 3,
    desc: 'auto_grade_daily.py — grades round-by-round outcomes from ESPN Golf API.',
    details: [
      'Grades after each round completes (not end-of-tournament)',
      'Writes HIT/MISS to prediction_outcomes in golf_predictions.db',
    ],
  },
  {
    id: 'golf_models', label: 'Golf ML Models', category: 'ml', method: 'ml_dormant', val: 3,
    desc: 'Not yet built — ML scaffold planned for post-Masters 2026 once 700+ graded samples exist.',
    details: [
      'Target threshold: 700 samples (lower than NHL/NBA due to weekly cadence)',
      'Likely model: XGBoost on strokes-gained features',
      'No model registry entries yet',
    ],
  },
  {
    id: 'golf_db', label: 'Golf SQLite DB', category: 'storage', method: 'infra', val: 3,
    desc: 'golf/database/golf_predictions.db — predictions, outcomes, round logs.',
    details: [
      'Backed up before each grading run',
      'Not yet synced to Turso or Supabase',
    ],
  },

  // ── GAME LINES ────────────────────────────────────────────────────────────
  {
    id: 'game_context_source', label: 'Game Context API', category: 'source', method: 'infra', val: 3,
    desc: 'ESPN + weather APIs for game-level context: park factors, wind, game totals, Vegas lines.',
    details: [
      'shared/fetch_game_odds.py — ESPN moneyline / spread / total',
      'PEGASUS/pipeline/mlb_game_context.py — park factors (32 stadiums), wind advisory',
      'game_context table: 273 rows since Mar 25, 2026',
    ],
  },
  {
    id: 'game_context_engine', label: 'MLB Game Context', category: 'pegasus', method: 'statistical', val: 4,
    desc: 'PEGASUS/pipeline/mlb_game_context.py — park factors, wind advisory, game total advisory injected as flags on MLB picks.',
    details: [
      'Outputs: game_context_flag + game_context_notes on each PEGASUSPick',
      'HR_SUPPRESS, HIGH_TOTAL, WIND_OUT advisory flags',
      'Advisory only — does NOT modify probability or edge values',
      'Step 11a XGBoost planned Jun 2026 (~700 rows)',
    ],
  },
  {
    id: 'game_lines_ml', label: 'Game Lines ML (Step 11)', category: 'ml', method: 'ml_dormant', val: 4,
    desc: 'Full game lines models (moneyline / spread / totals) — gated until Oct 2026 when full-season game_context data is available.',
    details: [
      'NBA + NHL game_context collection started Mar 2026 (need full 2026-27 season)',
      'MLB Step 11a possible Jun 2026 once ~700 rows validated',
      'Will output game_context_score (0.8–1.2×) as continuous modifier',
      'Not a pick generator — adjusts player prop edges based on game environment',
    ],
  },

  // ── STORAGE ───────────────────────────────────────────────────────────────
  {
    id: 'nhl_db', label: 'NHL SQLite DB', category: 'storage', method: 'infra', val: 6,
    desc: 'nhl/database/nhl_predictions_v2.db — predictions, prediction_outcomes, player_game_logs.',
    details: [
      'features_json: TEXT (JSON blob of all model features)',
      'confidence_tier, expected_value, reasoning columns',
      'prediction_outcomes: actual_value, prediction (HIT/MISS)',
    ],
  },
  {
    id: 'nba_db', label: 'NBA SQLite DB', category: 'storage', method: 'infra', val: 6,
    desc: 'nba/database/nba_predictions.db — predictions, prediction_outcomes, player_game_logs.',
    details: [
      '50+ individual f_* feature columns per row',
      'prediction_outcomes: actual_value, prediction (HIT/MISS)',
      'No confidence_tier or reasoning columns (simpler schema)',
    ],
  },
  {
    id: 'mlb_db', label: 'MLB SQLite DB', category: 'storage', method: 'infra', val: 4,
    desc: 'mlb/database/mlb_predictions.db — 73k+ game logs in data collection phase.',
    details: ['mlb_feature_store/ contains enriched features', 'Wiring to PEGASUS pick selector in progress'],
  },
  {
    id: 'turso', label: 'Turso (Cloud SQLite)', category: 'storage', method: 'infra', val: 7,
    desc: 'Cloud SQLite — 772k rows across all sports. PEGASUS primary read/write store.',
    details: [
      'Migrated from Supabase Apr 6, 2026 (turso_migrate.py)',
      'PEGASUS writes enriched picks here after pick_selector runs',
      'PEGASUS FastAPI reads exclusively from Turso',
    ],
  },
  {
    id: 'supabase', label: 'Supabase', category: 'storage', method: 'infra', val: 8,
    desc: 'PostgreSQL + Auth + Realtime. User-facing tables: daily_props, user_picks, profiles, watchlist, daily_games.',
    details: [
      'Ref: txleohtoesmanorqcurt  |  Region: us-east-1',
      'Edge Functions deployed: grade-user-picks v1, award-points v1',
      'daily_props.sport stores "NBA" / "NHL" (UPPERCASE)',
      'Pagination cap: 1000 rows — all batch queries must use .range() loop',
    ],
  },

  // ── PEGASUS ───────────────────────────────────────────────────────────────
  {
    id: 'pegasus_runner', label: 'PEGASUS Daily Runner', category: 'pegasus', method: 'infra', val: 6,
    desc: 'PEGASUS/run_daily.py — orchestrates the full PEGASUS pipeline: fetch odds + lines → select picks → write Turso.',
    details: [
      'Runs after prediction pipelines complete',
      'Reads statistical model outputs from SQLite DBs',
      'Combines with DK real odds for true EV scoring',
    ],
  },
  {
    id: 'pegasus_selector', label: 'PEGASUS Pick Selector', category: 'pegasus', method: 'statistical', val: 7,
    desc: 'PEGASUS/pipeline/pick_selector.py — combines model probability + DraftKings real odds for true EV picks.',
    details: [
      'Edge = (model_prob − real_break_even) × 100',
      'Tiers: T1≥+19%  T2≥+14%  T3≥+9%  T4≥0%  T5<0%',
      'Goblin/demon break-evens use actual sportsbook juice, not flat 52.4%',
      'Threes OVER guard active (degenerate model protection)',
    ],
  },
  {
    id: 'pegasus_api', label: 'PEGASUS FastAPI', category: 'pegasus', method: 'infra', val: 7,
    desc: 'PEGASUS/api/main.py — REST API on port 8600 serving enriched picks to mobile.',
    details: [
      'GET /picks/{date}?sport=nba&min_tier=T2-STRONG',
      'GET /picks/{date}/{player_name}',
      'GET /health',
      'Reads Turso exclusively. JSON snapshot fallback.',
      'All CORS origins open for mobile dev',
    ],
  },
  {
    id: 'calibration', label: 'Calibration Engine', category: 'pegasus', method: 'statistical', val: 5,
    desc: 'PEGASUS/calibration/ — reliability diagrams, Brier scores, always-UNDER baseline to detect bias.',
    details: [
      'Bins predictions into 10% probability buckets → checks actual hit rate',
      'Always-UNDER baseline: real_edge = our_accuracy − always_under_accuracy',
      'If real_edge < 3%, model has no true edge (pure UNDER bias)',
      'Must pass before any user-facing launch',
    ],
  },

  // ── SYNC & INTEGRATION ────────────────────────────────────────────────────
  {
    id: 'smart_pick', label: 'Smart Pick Selector', category: 'sync', method: 'statistical', val: 6,
    desc: 'shared/smart_pick_selector.py — selects top picks from SQLite for the Supabase (legacy) flow.',
    details: [
      'Edge-based tiers (goblin/demon break-evens correct since Mar 8 fix)',
      'Threes OVER guard (Mar 15 fix)',
      'Trade correction: PP team is ALWAYS authoritative',
      '_is_initial_match() handles "A. Fox" vs "Adam Fox" name style',
    ],
  },
  {
    id: 'supabase_sync', label: 'Supabase Sync', category: 'sync', method: 'infra', val: 5,
    desc: 'sync/supabase_sync.py — four-stage sync: predictions → smart_picks → odds_types → game_times.',
    details: [
      'sync_odds_types() recomputes ai_edge for any row where stored edge is stale (> 0.05 tolerance)',
      'Backfill applied Mar 6: 312 NHL + 1,179 NBA rows corrected',
      'pp-sync = pure Supabase upserts, NO new SQLite rows. Safe to repeat.',
      'DO NOT manually run — wired into orchestrator',
    ],
  },
  {
    id: 'api_healer', label: 'API Self-Healer', category: 'sync', method: 'infra', val: 4,
    desc: 'api_health_monitor.py — detects API schema changes, calls Claude API, generates + applies fixes automatically.',
    details: [
      'Validates API responses against known schemas',
      'On structural change: backup → Claude analysis → patch → validate',
      'Integrated as Step 0 in NBA grading pipeline',
      'Validation history: data/api_schemas/validation_history.jsonl',
    ],
  },

  // ── OUTPUTS ───────────────────────────────────────────────────────────────
  {
    id: 'mobile', label: 'FreePicks Mobile', category: 'output', method: 'infra', val: 8,
    desc: 'Expo React Native app — 4-tab navigator: Play | Scores | Track | Profile.',
    details: [
      'Reads PEGASUS FastAPI (port 8600) for enriched picks',
      'Reads Supabase for user data (auth, user_picks, profiles, watchlist)',
      'Auth: Social-only (Google, Apple, Discord) via Supabase Auth',
      'Points system: correct pick = 10 pts, streak bonuses up to +50',
      'URL scheme: freepicks://',
    ],
  },
  {
    id: 'discord', label: 'Discord Bot', category: 'output', method: 'infra', val: 5,
    desc: 'FreePicks Bot — posts picks, handles commands, alerts on pipeline events.',
    details: [
      '!parlay [nba|nhl] [2-6]  |  !picks [nba|nhl]  |  !refresh  |  !status  |  !health',
      'Top-20 picks posted 2:00 PM CST daily (after afternoon pp-sync)',
      'Auto-restart with 15s cooldown (start_bot.bat)',
      'NHL name fix: "A. Fox" vs "Adam Fox" handled by _is_initial_match()',
    ],
  },
  {
    id: 'dashboard', label: 'Streamlit Dashboard', category: 'output', method: 'infra', val: 5,
    desc: 'dashboards/cloud_dashboard.py — port 8502 via Cloudflare tunnel. Internal monitoring.',
    details: [
      'Tabs: Today\'s Picks (All | By Prop | Parlay Builder | Line Compare) | Performance | System',
      'Performance tab: calibration buckets, OVER/UNDER breakdown, odds_type breakdown',
      'System tab: ML model count, last retrained date, avg accuracy per sport',
      'Supabase queries use .range() pagination (1000-row cap)',
    ],
  },
  {
    id: 'tui', label: 'TUI Terminal', category: 'output', method: 'infra', val: 4,
    desc: 'tui-terminal/ — Rust-powered interactive terminal dashboard.',
    details: [
      'Pick views, heatmaps, live orchestrator status',
      'Phase 4 (Heatmap view) not yet started',
      'DO NOT touch parlay_lottery/ — separate scope',
    ],
  },
];

// ─── LINKS ──────────────────────────────────────────────────────────────────

export const LINKS: EcoLink[] = [

  // External APIs → Pipelines / Graders
  { source: 'nhl_api',       target: 'nhl_pipeline', label: 'schedule + stats' },
  { source: 'nhl_api',       target: 'nhl_grader',   label: 'game actuals' },
  { source: 'espn_api',      target: 'nba_grader',   label: 'box scores' },
  { source: 'nba_stats_api', target: 'nba_grader',   label: 'fallback stats' },
  { source: 'mlb_feeds',     target: 'mlb_pipeline', label: 'game logs' },

  // PrizePicks → two paths
  { source: 'prizepicks_api', target: 'smart_pick',        label: 'live lines' },
  { source: 'prizepicks_api', target: 'pegasus_selector',  label: 'live lines' },

  // DraftKings → PEGASUS
  { source: 'dk_odds', target: 'pegasus_selector', label: 'real odds / juice' },

  // Orchestrator → everything it controls
  { source: 'orchestrator', target: 'nhl_pipeline',  type: 'control', label: '4 AM CST' },
  { source: 'orchestrator', target: 'nba_pipeline',  type: 'control', label: '6 AM CST' },
  { source: 'orchestrator', target: 'mlb_pipeline',  type: 'control' },
  { source: 'orchestrator', target: 'nhl_grader',    type: 'control', label: '3 AM CST' },
  { source: 'orchestrator', target: 'nba_grader',    type: 'control', label: '5 AM CST' },
  { source: 'orchestrator', target: 'ml_engine',     type: 'control', label: 'Sundays' },
  { source: 'orchestrator', target: 'supabase_sync', type: 'control', label: 'pp-sync' },
  { source: 'orchestrator', target: 'pegasus_runner',type: 'control', label: 'daily' },
  { source: 'orchestrator', target: 'discord',       type: 'control', label: '2 PM alerts' },

  // Pipelines → DBs
  { source: 'nhl_pipeline', target: 'nhl_db', label: 'write predictions' },
  { source: 'nba_pipeline', target: 'nba_db', label: 'write predictions' },
  { source: 'mlb_pipeline', target: 'mlb_db', label: 'write predictions' },

  // Graders → DBs
  { source: 'nhl_grader', target: 'nhl_db', label: 'HIT / MISS' },
  { source: 'nba_grader', target: 'nba_db', label: 'HIT / MISS' },

  // DBs → ML Engine
  { source: 'nhl_db', target: 'ml_engine', label: 'training data' },
  { source: 'nba_db', target: 'ml_engine', label: 'training data' },

  // ML Engine → Models
  { source: 'ml_engine', target: 'nhl_models', label: 'trains' },
  { source: 'ml_engine', target: 'nba_models', label: 'trains' },

  // Models → Pipelines (feedback loop — dormant)
  { source: 'nhl_models', target: 'nhl_pipeline', type: 'feedback', label: 'inactive' },
  { source: 'nba_models', target: 'nba_pipeline', type: 'feedback', label: 'inactive' },

  // DBs → Smart Pick (legacy Supabase path)
  { source: 'nhl_db', target: 'smart_pick', label: 'predictions' },
  { source: 'nba_db', target: 'smart_pick', label: 'predictions' },

  // DBs → PEGASUS (new path)
  { source: 'nhl_db', target: 'pegasus_runner', label: 'model probs' },
  { source: 'nba_db', target: 'pegasus_runner', label: 'model probs' },
  { source: 'mlb_db', target: 'pegasus_runner', label: 'model probs' },

  // PEGASUS chain
  { source: 'pegasus_runner',   target: 'pegasus_selector', label: 'enriches' },
  { source: 'pegasus_selector', target: 'turso',            label: 'write enriched picks' },
  { source: 'pegasus_selector', target: 'calibration',      label: 'validates' },
  { source: 'turso',            target: 'pegasus_api',      label: 'read' },

  // Smart Pick → Supabase Sync
  { source: 'smart_pick',    target: 'supabase_sync', label: 'picks' },
  { source: 'supabase_sync', target: 'supabase',      label: 'upserts' },

  // API Healer
  { source: 'api_healer', target: 'nba_grader', type: 'sync', label: 'heals' },
  { source: 'api_healer', target: 'espn_api',   type: 'sync', label: 'monitors' },

  // Outputs
  { source: 'pegasus_api', target: 'mobile',    label: 'enriched picks feed' },
  { source: 'supabase',    target: 'mobile',    label: 'user data / auth' },
  { source: 'supabase',    target: 'dashboard', label: 'results + picks' },
  { source: 'orchestrator', target: 'tui',      label: 'live status' },

  // Golf
  { source: 'golf_source',   target: 'golf_pipeline', label: 'scores + stats' },
  { source: 'golf_source',   target: 'golf_grader',   label: 'round actuals' },
  { source: 'orchestrator',  target: 'golf_pipeline', type: 'control', label: 'daily' },
  { source: 'orchestrator',  target: 'golf_grader',   type: 'control' },
  { source: 'golf_pipeline', target: 'golf_db',       label: 'predictions' },
  { source: 'golf_grader',   target: 'golf_db',       label: 'HIT / MISS' },
  { source: 'golf_db',       target: 'ml_engine',     label: 'training data (future)' },
  { source: 'ml_engine',     target: 'golf_models',   label: 'trains (future)', type: 'feedback' },
  { source: 'golf_models',   target: 'golf_pipeline', label: 'inactive', type: 'feedback' },

  // Game Context / Game Lines
  { source: 'game_context_source',  target: 'game_context_engine', label: 'park + weather + totals' },
  { source: 'game_context_engine',  target: 'pegasus_selector',    label: 'advisory flags' },
  { source: 'game_context_source',  target: 'game_lines_ml',       label: 'raw data', type: 'feedback' },
  { source: 'game_lines_ml',        target: 'pegasus_selector',    label: 'score modifier (Oct 2026)', type: 'feedback' },
  { source: 'mlb_db',               target: 'game_context_engine', label: 'game_context table' },
];
