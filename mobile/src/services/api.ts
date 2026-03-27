import axios from 'axios';
import { API_BASE_URL } from '../utils/constants';
import { supabase } from './supabase';

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
  });
  return response.data;
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

  let query = supabase
    .from('daily_props')
    .select('game_date,prop_type,line,odds_type,ai_prediction,actual_value,opponent')
    .eq('player_name', playerName)
    .eq('sport', sportUpper)
    .gte('game_date', sinceStr)
    .order('game_date', { ascending: false })
    .limit(500);

  // Filter to lines within ±8 of today's PP line to exclude junk model lines (e.g. U40.5 for bench players)
  // Fall back to is_smart_pick filter when line is unknown
  if (ppLine != null) {
    query = query.gte('line', ppLine - 8).lte('line', ppLine + 8);
  } else {
    query = query.eq('is_smart_pick', true);
  }

  const { data, error } = await query;

  if (error) throw error;

  const rows = data || [];

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
