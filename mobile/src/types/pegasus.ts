/**
 * PEGASUS pick data model — enriched player prop picks from PEGASUS FastAPI (port 8600).
 * Mobile reads from PEGASUS API instead of Supabase daily_props.
 *
 * Design spec: PEGASUS/docs/mobile-step10.md
 */

export interface PEGASUSPick {
  // Identity
  player_name:            string;
  team:                   string;
  sport:                  string;       // "nba" | "nhl" | "mlb"
  prop:                   string;       // "pts_asts" | "points" | "hits" | ...
  line:                   number;
  direction:              'OVER' | 'UNDER';
  odds_type:              'standard' | 'goblin' | 'demon';
  game_date:              string;       // "YYYY-MM-DD"

  // Model outputs
  raw_stat_probability:   number;       // raw stat model (0.0–1.0)
  ml_probability:         number | null; // ML blend component (null = stat-only)
  blended_probability:    number;       // after ML blend (= raw if no ML)
  calibrated_probability: number;       // DISPLAY THIS — corrected to actual hit rate

  // Edge
  break_even:             number;       // 0.5238 std / 0.7619 goblin / 0.4545 demon
  ai_edge:                number;       // (cal_prob - break_even) × 100 (ppt)
  vs_naive_edge:          number;       // vs always-UNDER baseline

  // Tier
  tier:                   string;       // "T1-ELITE" | "T2-STRONG" | "T3-GOOD" | "T4-LEAN"

  // Situational (advisory — display-only, never affects model output)
  situation_flag:         string;       // "NORMAL" | "HIGH_STAKES" | "DEAD_RUBBER" | "ELIMINATED" | "USAGE_BOOST"
  situation_modifier:     number;
  situation_notes:        string;       // "HIGH STAKES | LAC | 9-seed play-in | 22.0 GB"

  // Sportsbook (nullable — populated only when DK API has the line)
  implied_probability:    number | null;

  // Derived
  true_ev:                number;       // (cal_prob / break_even) - 1
  usage_boost:            boolean;
  model_version:          string;       // "statistical_v1" | "mlb_xgb_v1" | ...

  // Optional back-reference
  source_prediction_id?:  number | null;
}

export interface PEGASUSPicksResponse {
  game_date:    string;
  sport_filter: string | null;
  min_tier:     string | null;
  direction:    string | null;
  count:        number;
  picks:        PEGASUSPick[];
}

export interface PEGASUSHealthResponse {
  status:          string;
  api_version:     string;
  turso_client:    boolean;
  last_snapshot:   string | null;
  picks_by_sport:  Record<string, number>;
  server_time:     string;
}
