// TypeScript types for all Supabase tables

export interface Profile {
  id: string;
  username: string | null;
  display_name: string | null;
  avatar_url: string | null;
  points: number;
  streak: number;
  best_streak: number;
  tier: 'rookie' | 'pro' | 'elite' | 'legend';
  total_picks: number;
  total_hits: number;
  premium: boolean;
  premium_until: string | null;
  push_token: string | null;
  created_at: string;
  updated_at: string;
}

export interface DailyProp {
  id: string;
  game_date: string;
  sport: 'NBA' | 'NHL';
  player_name: string;
  team: string;
  opponent: string;
  prop_type: string;
  line: number;
  odds_type: 'standard' | 'goblin' | 'demon';
  game_time: string | null;
  matchup: string | null;
  // AI data
  ai_prediction: 'OVER' | 'UNDER' | null;
  ai_probability: number | null;
  ai_edge: number | null;
  ai_tier: string | null;
  ai_ev_2leg: number | null;
  ai_ev_3leg: number | null;
  ai_ev_4leg: number | null;
  // Grading
  actual_value: number | null;
  result: 'HIT' | 'MISS' | 'PUSH' | null;
  graded_at: string | null;
  // Community
  over_count: number;
  under_count: number;
  // Status
  status: 'open' | 'locked' | 'graded';
  created_at: string;
}

export interface UserPick {
  id: string;
  user_id: string;
  prop_id: string;
  prediction: 'OVER' | 'UNDER';
  outcome: 'HIT' | 'MISS' | null;
  points_earned: number;
  picked_at: string;
  graded_at: string | null;
  // Joined data
  prop?: DailyProp;
}

export interface BetLeg {
  player: string;
  prop_type: string;
  line: number;
  prediction: 'OVER' | 'UNDER';
  outcome?: 'HIT' | 'MISS' | null;
}

export interface UserBet {
  id: string;
  user_id: string;
  sport: string;
  sportsbook: string | null;
  bet_type: 'single' | 'parlay' | 'flex';
  stake: number | null;
  potential_payout: number | null;
  actual_payout: number | null;
  status: 'pending' | 'won' | 'lost' | 'push';
  legs: BetLeg[];
  notes: string | null;
  placed_at: string;
  settled_at: string | null;
}

export interface PointTransaction {
  id: string;
  user_id: string;
  amount: number;
  reason: string;
  reference_id: string | null;
  balance_after: number;
  created_at: string;
}

export interface DailyGame {
  id: string;
  game_date: string;
  sport: string;
  game_id: string;
  home_team: string;
  away_team: string;
  home_score: number;
  away_score: number;
  status: 'scheduled' | 'live' | 'final';
  period: string | null;
  clock: string | null;
  start_time: string | null;
  broadcast: string | null;
  updated_at: string;
}

export interface ModelPerformance {
  id: string;
  game_date: string;
  sport: string;
  total_predictions: number;
  total_graded: number;
  hits: number;
  accuracy: number | null;
  over_accuracy: number | null;
  under_accuracy: number | null;
  by_prop: Record<string, { total: number; hits: number; accuracy: number }> | null;
  by_tier: Record<string, { total: number; hits: number; accuracy: number }> | null;
  created_at: string;
}

export interface WatchlistItem {
  id: string;
  user_id: string;
  player_name: string;
  sport: string;
  position: number;
  added_at: string;
}

// Supabase Database type helper
export interface Database {
  public: {
    Tables: {
      profiles: { Row: Profile; Insert: Partial<Profile>; Update: Partial<Profile> };
      daily_props: { Row: DailyProp; Insert: Partial<DailyProp>; Update: Partial<DailyProp> };
      user_picks: { Row: UserPick; Insert: Partial<UserPick>; Update: Partial<UserPick> };
      user_bets: { Row: UserBet; Insert: Partial<UserBet>; Update: Partial<UserBet> };
      point_transactions: { Row: PointTransaction; Insert: Partial<PointTransaction>; Update: Partial<PointTransaction> };
      daily_games: { Row: DailyGame; Insert: Partial<DailyGame>; Update: Partial<DailyGame> };
      model_performance: { Row: ModelPerformance; Insert: Partial<ModelPerformance>; Update: Partial<ModelPerformance> };
      watchlist: { Row: WatchlistItem; Insert: Partial<WatchlistItem>; Update: Partial<WatchlistItem> };
    };
  };
}
