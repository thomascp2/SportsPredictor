import axios from 'axios';
import { API_BASE_URL } from '../utils/constants';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Types
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
  // New fields for game time
  game_time?: string;
  game_time_utc?: string;
  has_started?: boolean;
  game_state?: string;
  matchup?: string;
  venue?: string;
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
  total_predictions: number;
  graded_predictions: number;
  accuracy: number;
  recent_predictions: Array<{
    date: string;
    prop_type: string;
    line: number;
    prediction: string;
    outcome?: string;
  }>;
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
  sport?: string
): Promise<PlayerHistory> {
  const response = await api.get<PlayerHistory>(`/players/${encodeURIComponent(playerName)}/history`, {
    params: { sport },
  });
  return response.data;
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

export default api;
