import axios from 'axios';
import { API_BASE_URL } from '../utils/constants';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
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
}

export interface SmartPicksResponse {
  success: boolean;
  date: string;
  sport: string;
  total_picks: number;
  picks: SmartPick[];
  summary: {
    avg_probability: number;
    avg_edge: number;
    by_tier: Record<string, number>;
  };
}

export interface LiveGame {
  game_id: string;
  status: string;
  home_team: string;
  away_team: string;
  home_score: number;
  away_score: number;
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

// API Functions
export async function fetchSmartPicks(
  sport: string,
  minEdge: number = 0,
  minProb: number = 0.5
): Promise<SmartPicksResponse> {
  const response = await api.get<SmartPicksResponse>('/picks/today', {
    params: { sport, min_edge: minEdge, min_prob: minProb },
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

export default api;
