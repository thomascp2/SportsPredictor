import axios from 'axios';
import { API_BASE_URL } from '../utils/constants';
import { supabase } from './supabase';
import { fetchPlayerHistoryFromTurso } from './turso';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Types
export interface ModelSignals {
  season_success_rate?: number;  // % of all games that went OVER the line this season
  l10_success_rate?: number;     // Hit rate over last 10 games
  l5_success_rate?: number;      // Hit rate over last 5 games
  l3_success_rate?: number;      // Hit rate over last 3 games
  current_streak?: number;       // Positive = consecutive OVERs, negative = consecutive UNDERs
  trend_slope?: number;          // Linear regression slope on last 10 games (positive = improving)
  season_avg?: number;           // Season average stat value
  l10_avg?: number;              // Average stat value over last 10 games
  l5_avg?: number;               // Average stat value over last 5 games
  opp_defensive_rating?: number; // How many of this stat the opponent allows (higher = weaker defense)
  opp_defensive_trend?: number;  // Opponent defense trend (positive = getting worse = easier matchup)
}

export interface SmartPick {
  player_name: string;
  team: string;
  opponent: string;
  prop_type: string;
  pp_line: number;
  pp_probability: number;
  prediction: 'OVER' | 'UNDER';
  edge: number;
  tier: string;
  pp_odds_type: string;
  leg_value: number;
  our_line: number;
  our_probability: number;
  ev_2leg: number;
  ev_3leg: number;
  ev_4leg: number;
  ev_5leg: number;
  ev_6leg: number;
  // Game time fields
  game_time?: string;
  game_time_utc?: string;
  has_started?: boolean;
  game_state?: string;
  matchup?: string;
  venue?: string;
  // ML signal fields
  season_avg?: number;      // Season average stat value
  recent_avg?: number;      // Recent form average (L10 or L5)
  ml_adjustment?: number;   // % difference between ML probability and naive baseline (positive = ML likes it more)
  // Profitability enhancement fields
  sigma_distance?: number;          // (variant_line - standard_line) / σ; 0 for standard lines
  parlay_score?: number;            // Probability adjusted for player consistency (lower CoV = better leg)
  line_movement?: number;           // Standard line change today (+ = moved up, - = moved down)
  movement_agrees?: boolean;        // True if our prediction direction agrees with line movement
  calibration_correction?: number;  // Historical calibration adjustment applied to probability (%)
  days_rest?: number;               // Player's days since last game (0 = back-to-back)
  // League rank field
  percentile_score?: number;        // 0-100: where this player's season_avg ranks among today's tracked players for this prop
  // PEGASUS enrichment fields — optional, only present when data came from PEGASUS API (port 8600)
  calibrated_probability?: number;  // PEGASUS calibration-corrected probability (always show over raw when present)
  implied_probability?: number | null; // DK vig-removed fair probability for this direction
  situation_flag?: string;          // "NORMAL" | "HIGH_STAKES" | "DEAD_RUBBER" | "ELIMINATED" | "USAGE_BOOST"
  situation_notes?: string;         // Tooltip: "HIGH STAKES | LAC | 9-seed play-in | 22.0 GB"
  true_ev?: number;                 // (calibrated_prob / break_even) - 1
  model_version?: string;           // "statistical_v1" | "mlb_xgb_v1" | ...
  pegasus_source?: boolean;         // true when pick originated from PEGASUS API
}

export interface GameGroup {
  matchup: string;
  game_time: string;
  has_started: boolean;
  picks: SmartPick[];
}

export interface SmartPicksResponse {
  success: boolean;
  date: string;
  sport: string;
  total_picks: number;
  total_games?: number;
  picks?: SmartPick[];
  games?: GameGroup[];
  summary: {
    avg_probability: number;
    avg_edge: number;
    by_tier: Record<string, number>;
  };
}

export interface LiveGame {
  game_id: string;
  status: string;
  home_team: string | { abbreviation: string; name: string; score: number };
  away_team: string | { abbreviation: string; name: string; score: number };
  home_score?: number;
  away_score?: number;
  period: string;
  clock: string;
  start_time: string;
  broadcast: string;
}

export interface LiveScoresResponse {
  success: boolean;
  sport: string;
  games: LiveGame[];
  last_updated: string;
}

export interface PerformanceOverview {
  success: boolean;
  sport: string;
  overall: {
    total_predictions: number;
    total_graded: number;
    accuracy: number;
    hit_count: number;
    over_accuracy: number;
    over_total: number;
    under_accuracy: number;
    under_total: number;
  };
  by_prop_type: Record<string, { accuracy: number; total: number; hits: number }>;
  by_tier: Record<string, { accuracy: number; total: number; hits: number }>;
  trending: Array<{ date: string; accuracy: number; total: number; hits: number }>;
}

export interface PlayerSearchResult {
  player_name: string;
  sport: string;
  total_predictions: number;
  accuracy: number;
  last_game_date: string;
}

export interface PlayerSearchResponse {
  success: boolean;
  query: string;
  total_results: number;
  players: PlayerSearchResult[];
}

export interface PlayerHistory {
  player_name: string;
  sport: string;
  success: boolean;
  overall: {
    total_predictions: number;
    accuracy: number;
    hits: number;
  };
  by_prop_type: Record<string, { accuracy: number; total: number; hits: number }>;
  predictions: Array<{
    date: string;
    prop_type: string;
    line: number;
    prediction: string;
    actual_value?: number;
    outcome?: string;
  }>;
  model_signals?: Record<string, ModelSignals>;  // keyed by prop_type
  message?: string;
}

export interface ParlayCalculationResponse {
  success: boolean;
  pick_count: number;
  total_leg_value: number;
  combined_probability: number;
  combined_probability_pct: string;
  payout_multiplier: number;
  expected_value: number;
  ev_percentage: number;
  is_positive_ev: boolean;
  break_even_probability: number;
  edge: number;
  edge_pct: string;
  recommendation: string;
}

export interface AdminResponse {
  success: boolean;
  sport: string;
  message: string;
  details?: any;
}

export type SortOption = 'edge' | 'probability' | 'game_time' | 'team' | 'player' | 'tier';

// API Functions
/**
 * Fetch smart picks from Supabase daily_props directly.
 * Works anywhere (no local FastAPI server required).
 * Returns picks for today with the core SmartPick fields.
 */
async function fetchSmartPicksFromSupabase(
  sport: string,
  options: {
    minEdge?: number;
    minProb?: number;
    tier?: string;
    oddsType?: string;
    prediction?: string;
    team?: string;
    sortBy?: SortOption;
  } = {}
): Promise<SmartPicksResponse> {
  const sportUpper = sport.toUpperCase();
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;

  const LEG_VALUE: Record<string, number> = { goblin: 0.5, standard: 1.0, demon: 1.5 };

  let query = supabase
    .from('daily_props')
    .select(
      'player_name,team,opponent,prop_type,line,odds_type,game_time,matchup,' +
      'ai_prediction,ai_probability,ai_edge,ai_tier,ai_ev_2leg,ai_ev_3leg,ai_ev_4leg'
    )
    .eq('sport', sportUpper)
    .eq('game_date', todayStr)
    .eq('is_smart_pick', true)
    .order('ai_edge', { ascending: false })
    .limit(1000);

  if (options.minEdge) query = query.gte('ai_edge', options.minEdge);
  if (options.minProb) query = query.gte('ai_probability', options.minProb);
  if (options.tier) query = query.eq('ai_tier', options.tier);
  if (options.oddsType) query = query.eq('odds_type', options.oddsType);
  if (options.prediction) query = query.eq('ai_prediction', options.prediction);
  if (options.team) query = query.eq('team', options.team);

  const { data, error } = await query;
  if (error) throw error;

  const rows = data || [];

  // Map Supabase columns to SmartPick shape
  let picks: SmartPick[] = rows.map((r: any) => ({
    player_name: r.player_name,
    team: r.team,
    opponent: r.opponent,
    prop_type: r.prop_type,
    pp_line: r.line,
    pp_probability: r.ai_probability ?? 0,
    prediction: r.ai_prediction as 'OVER' | 'UNDER',
    edge: r.ai_edge ?? 0,
    tier: r.ai_tier ?? 'T4-LEAN',
    pp_odds_type: r.odds_type ?? 'standard',
    leg_value: LEG_VALUE[r.odds_type ?? 'standard'] ?? 1.0,
    our_line: r.line,          // best approximation — model line not stored in Supabase
    our_probability: r.ai_probability ?? 0,
    ev_2leg: r.ai_ev_2leg ?? 0,
    ev_3leg: r.ai_ev_3leg ?? 0,
    ev_4leg: r.ai_ev_4leg ?? 0,
    ev_5leg: 0,
    ev_6leg: 0,
    game_time: r.game_time ?? undefined,
    matchup: r.matchup ?? undefined,
    // Fields not in Supabase — default to 0
    sigma_distance: 0,
    parlay_score: 0,
    line_movement: 0,
    movement_agrees: false,
    calibration_correction: 0,
  }));

  // Client-side sort when sortBy differs from default edge sort
  if (options.sortBy && options.sortBy !== 'edge') {
    picks = picks.sort((a, b) => {
      if (options.sortBy === 'probability') return b.pp_probability - a.pp_probability;
      if (options.sortBy === 'player') return a.player_name.localeCompare(b.player_name);
      if (options.sortBy === 'team') return a.team.localeCompare(b.team);
      if (options.sortBy === 'tier') return a.tier.localeCompare(b.tier);
      return 0;
    });
  }

  const avgEdge = picks.length > 0 ? picks.reduce((s, p) => s + p.edge, 0) / picks.length : 0;
  const avgProb = picks.length > 0 ? picks.reduce((s, p) => s + p.pp_probability, 0) / picks.length : 0;
  const byTier: Record<string, number> = {};
  for (const p of picks) byTier[p.tier] = (byTier[p.tier] ?? 0) + 1;

  return {
    success: true,
    date: todayStr,
    sport: sportUpper,
    total_picks: picks.length,
    picks,
    summary: {
      avg_probability: Math.round(avgProb * 100) / 100,
      avg_edge: Math.round(avgEdge * 100) / 100,
      by_tier: byTier,
    },
  };
}

export async function fetchSmartPicks(
  sport: string,
  options: {
    minEdge?: number;
    minProb?: number;
    tier?: string;
    oddsType?: string;
    prediction?: string;
    team?: string;
    hideStarted?: boolean;
    sortBy?: SortOption;
    groupByGame?: boolean;
  } = {}
): Promise<SmartPicksResponse> {
  // Source priority:
  //   1. PEGASUS FastAPI (port 8600) — calibrated probs, situational flags, DK implied odds
  //   2. Local production FastAPI (port 8000) — raw smart picks
  //   3. Supabase daily_props — always works, no enrichment
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  // 1. Try PEGASUS first
  try {
    const { fetchSmartPicksFromPegasus } = await import('./pegasus');
    const picks = await fetchSmartPicksFromPegasus(sport, {
      minTier:   options.tier,
      direction: options.prediction,
      limit:     500,
    });

    if (picks.length > 0) {
      const avgEdge = picks.reduce((s, p) => s + p.edge, 0) / picks.length;
      const avgProb = picks.reduce((s, p) => s + p.pp_probability, 0) / picks.length;
      const byTier: Record<string, number> = {};
      for (const p of picks) byTier[p.tier] = (byTier[p.tier] ?? 0) + 1;

      return {
        success: true,
        date: todayStr,
        sport: sport.toUpperCase(),
        total_picks: picks.length,
        picks,
        summary: {
          avg_probability: Math.round(avgProb * 100) / 100,
          avg_edge: Math.round(avgEdge * 100) / 100,
          by_tier: byTier,
        },
      };
    }
  } catch (_pegasusErr) {
    // PEGASUS unreachable or no picks — continue to next source
  }

  // 2. Try local production FastAPI
  try {
    const response = await api.get<SmartPicksResponse>('/picks/today', {
      params: {
        sport,
        min_edge: options.minEdge ?? 0,
        min_prob: options.minProb ?? 0.5,
        tier: options.tier,
        odds_type: options.oddsType,
        prediction: options.prediction,
        team: options.team,
        hide_started: options.hideStarted ?? true,
        sort_by: options.sortBy ?? 'edge',
        group_by_game: options.groupByGame ?? false,
      },
      timeout: 5000,
    });
    return response.data;
  } catch (_localErr) {
    // Local FastAPI unreachable — fall through to Supabase
  }

  // 3. Supabase fallback
  return fetchSmartPicksFromSupabase(sport, options);
}

export async function fetchPicksByGame(sport: string): Promise<SmartPicksResponse> {
  const response = await api.get<SmartPicksResponse>('/picks/games', {
    params: { sport, hide_started: true },
  });
  return response.data;
}

export async function fetchLiveScores(sport: string): Promise<LiveScoresResponse> {
  const response = await api.get<LiveScoresResponse>('/scores/live', {
    params: { sport },
  });
  return response.data;
}

export async function fetchPerformance(
  sport: string,
  days: number = 14
): Promise<PerformanceOverview> {
  const response = await api.get<PerformanceOverview>('/performance/overview', {
    params: { sport, days },
  });
  return response.data;
}

export async function searchPlayers(
  query: string,
  sport?: string
): Promise<PlayerSearchResponse> {
  const response = await api.get<PlayerSearchResponse>('/players/search', {
    params: { query, sport },
  });
  return response.data;
}

export async function fetchPlayerHistory(
  playerName: string,
  sport?: string,
  ppLine?: number,
): Promise<PlayerHistory> {
  const sportUpper = (sport ?? 'NBA').toUpperCase();

  // 90-day window — enough for ~25 game dates per player
  const since = new Date();
  since.setDate(since.getDate() - 90);
  const sinceStr = `${since.getFullYear()}-${String(since.getMonth()+1).padStart(2,'0')}-${String(since.getDate()).padStart(2,'0')}`;

  // Fetch from Turso (cloud-hosted, works off home WiFi).
  // Falls back to Supabase daily_props if Turso credentials are not configured.
  let rows: Array<{
    game_date: string;
    prop_type: string;
    line: number;
    odds_type?: string;
    ai_prediction?: string;
    actual_value: number | null;
    opponent: string;
  }>;

  try {
    const tursoRows = await fetchPlayerHistoryFromTurso(playerName, sportUpper, sinceStr, ppLine);
    // Map Turso field names to the shape the rest of this function expects
    rows = tursoRows.map((r) => ({
      game_date: r.game_date,
      prop_type: r.prop_type,
      line: r.line,
      odds_type: 'standard',   // odds_type not in Turso predictions table; default to standard
      ai_prediction: r.prediction,
      actual_value: r.actual_value,
      opponent: r.opponent,
    }));
  } catch (_tursoErr) {
    // Turso unavailable (missing credentials or network) — fall back to Supabase
    let query = supabase
      .from('daily_props')
      .select('game_date,prop_type,line,odds_type,ai_prediction,actual_value,opponent')
      .eq('player_name', playerName)
      .eq('sport', sportUpper)
      .gte('game_date', sinceStr)
      .order('game_date', { ascending: false })
      .limit(500);

    if (ppLine != null) {
      query = query.gte('line', ppLine - 8).lte('line', ppLine + 8);
    } else {
      query = query.eq('is_smart_pick', true);
    }

    const { data, error } = await query;
    if (error) throw error;
    rows = data || [];
  }

  // Deduplicate: one entry per (game_date, prop_type) — actual_value is the same
  // across all line variants for the same game, so we prefer graded rows.
  const ODDS_RANK: Record<string, number> = { standard: 0, goblin: 1, demon: 2 };

  const seen = new Map<string, typeof rows[0]>();
  for (const row of rows) {
    const key = `${row.game_date}|${row.prop_type}`;
    const existing = seen.get(key);
    if (!existing) {
      seen.set(key, row);
    } else {
      // Prefer: graded > ungraded, then standard > goblin > demon
      const existingGraded = existing.actual_value != null;
      const rowGraded = row.actual_value != null;
      if (rowGraded && !existingGraded) {
        seen.set(key, row);
      } else if (existingGraded === rowGraded) {
        const existingRank = ODDS_RANK[existing.odds_type ?? 'standard'] ?? 0;
        const rowRank = ODDS_RANK[row.odds_type ?? 'standard'] ?? 0;
        if (rowRank < existingRank) seen.set(key, row);
      }
    }
  }
  const deduped = [...seen.values()].sort((a, b) =>
    b.game_date.localeCompare(a.game_date)
  );

  // Build predictions array
  const predictions = deduped.map((row) => {
    // Always compute from actual_value + ai_prediction — the stored `result` column
    // reflects the model's original prediction direction, which may differ from the
    // ai_prediction stored in daily_props (set by smart pick selector). Computing
    // directly avoids showing inverted outcomes.
    let outcome: string | undefined;
    if (row.actual_value != null && row.ai_prediction) {
      outcome = (row.ai_prediction === 'OVER' ? row.actual_value > row.line : row.actual_value < row.line)
        ? 'HIT' : 'MISS';
    }
    return {
      date: row.game_date,
      prop_type: row.prop_type,
      line: row.line,
      prediction: row.ai_prediction,
      actual_value: row.actual_value,
      outcome,
    };
  });

  const graded = predictions.filter((p) => p.outcome);
  const hits = graded.filter((p) => p.outcome === 'HIT').length;

  // by_prop_type accuracy
  const by_prop_type: Record<string, { accuracy: number; total: number; hits: number }> = {};
  for (const p of graded) {
    const pt = p.prop_type;
    if (!by_prop_type[pt]) by_prop_type[pt] = { accuracy: 0, total: 0, hits: 0 };
    by_prop_type[pt].total++;
    if (p.outcome === 'HIT') by_prop_type[pt].hits++;
  }
  for (const pt of Object.keys(by_prop_type)) {
    const s = by_prop_type[pt];
    s.accuracy = s.total > 0 ? (s.hits / s.total) * 100 : 0;
  }

  // model_signals per prop_type
  const model_signals: Record<string, ModelSignals> = {};
  const propTypes = [...new Set(graded.map((p) => p.prop_type))];

  for (const pt of propTypes) {
    const ptRows = graded.filter((p) => p.prop_type === pt);
    const l5 = ptRows.slice(0, 5);
    const l10 = ptRows.slice(0, 10);

    const avg = (arr: typeof ptRows) =>
      arr.length > 0 ? arr.reduce((s, p) => s + (p.actual_value ?? 0), 0) / arr.length : undefined;

    // Streak: consecutive HITs (positive) or MISSes (negative)
    let streak = 0;
    if (ptRows.length > 0) {
      const dir = ptRows[0].outcome;
      for (const p of ptRows) {
        if (p.outcome === dir) streak += dir === 'HIT' ? 1 : -1;
        else break;
      }
    }

    // Linear regression slope on last 10 actual values (oldest→newest)
    let trendSlope: number | undefined;
    const trendData = l10.filter((p) => p.actual_value != null).reverse();
    if (trendData.length >= 3) {
      const n = trendData.length;
      const ys = trendData.map((p) => p.actual_value!);
      const xMean = (n - 1) / 2;
      const yMean = ys.reduce((a, b) => a + b, 0) / n;
      const num = ys.reduce((s, y, i) => s + (i - xMean) * (y - yMean), 0);
      const den = ys.reduce((s, _, i) => s + (i - xMean) ** 2, 0);
      trendSlope = den > 0 ? num / den : 0;
    }

    model_signals[pt] = {
      l5_success_rate: l5.length > 0 ? l5.filter((p) => p.outcome === 'HIT').length / l5.length : undefined,
      l10_success_rate: l10.length > 0 ? l10.filter((p) => p.outcome === 'HIT').length / l10.length : undefined,
      season_success_rate: ptRows.length > 0 ? ptRows.filter((p) => p.outcome === 'HIT').length / ptRows.length : undefined,
      l5_avg: avg(l5),
      l10_avg: avg(l10),
      season_avg: avg(ptRows),
      current_streak: streak || undefined,
      trend_slope: trendSlope,
    };
  }

  return {
    player_name: playerName,
    sport: sportUpper,
    success: true,
    overall: {
      total_predictions: graded.length,
      accuracy: graded.length > 0 ? (hits / graded.length) * 100 : 0,
      hits,
    },
    by_prop_type,
    predictions,
    model_signals,
  };
}

export async function calculateParlay(
  picks: Array<{ probability: number; odds_type: string }>
): Promise<ParlayCalculationResponse> {
  const response = await api.post<ParlayCalculationResponse>('/parlays/calculate', {
    picks,
  });
  return response.data;
}

export async function quickParlay(
  probs: number[],
  types: string[]
): Promise<ParlayCalculationResponse> {
  const response = await api.get<ParlayCalculationResponse>('/parlays/quick', {
    params: {
      probs: probs.join(','),
      types: types.join(','),
    },
  });
  return response.data;
}

// Admin endpoints
export async function runPredictions(sport: string): Promise<AdminResponse> {
  const response = await api.post<AdminResponse>('/admin/run-predictions', null, {
    params: { sport },
    timeout: 300000, // 5 minute timeout for predictions
  });
  return response.data;
}

export async function refreshLines(sport: string = 'all'): Promise<AdminResponse> {
  const response = await api.post<AdminResponse>('/admin/refresh-lines', null, {
    params: { sport },
    timeout: 60000,
  });
  return response.data;
}

export async function getSystemStatus(): Promise<any> {
  const response = await api.get('/admin/status');
  return response.data;
}

export async function clearCache(): Promise<AdminResponse> {
  const response = await api.post<AdminResponse>('/admin/clear-cache');
  return response.data;
}

// PrizePicks cache status
export interface PrizePicksStatus {
  success: boolean;
  cached: boolean;
  date?: string;
  lines_count: number;
  last_fetched_at?: string;
  minutes_old?: number;
  is_stale?: boolean;
  by_sport?: Record<string, number>;
  by_prop_type?: Record<string, number>;
  message?: string;
}

export async function fetchPrizePicksStatus(sport?: string): Promise<PrizePicksStatus> {
  const response = await api.get<PrizePicksStatus>('/prizepicks/status', {
    params: sport ? { sport } : undefined,
  });
  return response.data;
}

export default api;
