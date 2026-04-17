/**
 * PEGASUS FastAPI service (port 8600)
 *
 * Mobile reads from PEGASUS API — NOT from Supabase daily_props.
 * PEGASUS provides calibrated probabilities, edge-based tiers, situational flags,
 * and optional DraftKings implied probability.
 *
 * Data flow: PEGASUS/run_daily.py -> Turso pegasus_picks -> PEGASUS FastAPI -> here
 *
 * Design spec: PEGASUS/docs/mobile-step10.md
 */

import { PEGASUS_API_URL } from '../utils/constants';
import type { PEGASUSPick, PEGASUSPicksResponse, PEGASUSHealthResponse } from '../types/pegasus';
import type { SmartPick } from './api';

const PEGASUS_TIMEOUT_MS = 5_000;

const LEG_VALUE: Record<string, number> = {
  goblin: 0.5,
  standard: 1.0,
  demon: 1.5,
};

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function pegasusFetch<T>(path: string, signal?: AbortSignal): Promise<T> {
  const url = `${PEGASUS_API_URL}${path}`;
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`PEGASUS API ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface FetchPegasusPicksOptions {
  sport?:    string;       // "nba" | "nhl" | "mlb"
  minTier?:  string;       // "T1-ELITE" | "T2-STRONG" | "T3-GOOD" | "T4-LEAN"
  direction?: string;      // "OVER" | "UNDER"
  limit?:    number;       // max picks (default 200)
  date?:     string;       // "YYYY-MM-DD" — defaults to today
}

/**
 * Fetch PEGASUS enriched picks.
 * Returns the raw PEGASUSPick array on success, throws on failure.
 */
export async function fetchPegasusPicksRaw(
  options: FetchPegasusPicksOptions = {}
): Promise<PEGASUSPick[]> {
  const today = new Date();
  const date = options.date
    ?? `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  const params = new URLSearchParams();
  if (options.sport)     params.set('sport',     options.sport.toLowerCase());
  if (options.minTier)   params.set('min_tier',  options.minTier);
  if (options.direction) params.set('direction', options.direction.toUpperCase());
  if (options.limit)     params.set('limit',     String(options.limit));

  const query = params.toString() ? `?${params.toString()}` : '';

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PEGASUS_TIMEOUT_MS);

  try {
    const data = await pegasusFetch<PEGASUSPicksResponse>(
      `/picks/${date}${query}`,
      controller.signal
    );
    return data.picks ?? [];
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Fetch PEGASUS health endpoint.
 */
export async function fetchPegasusHealth(): Promise<PEGASUSHealthResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PEGASUS_TIMEOUT_MS);
  try {
    return await pegasusFetch<PEGASUSHealthResponse>('/health', controller.signal);
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// Adapter — PEGASUSPick → SmartPick
// ---------------------------------------------------------------------------

/**
 * Map a PEGASUSPick to the SmartPick shape used throughout the mobile app.
 *
 * PEGASUS fields are surfaced via optional extensions on SmartPick:
 *   calibrated_probability, implied_probability, situation_flag,
 *   situation_notes, true_ev, model_version, pegasus_source
 *
 * The existing UI components use these gracefully:
 *   - PickCard shows "CAL" label instead of "PROB" when pegasus_source=true
 *   - Situation pill appears when situation_flag != "NORMAL"
 *   - True EV row appears when true_ev is present
 *   - Book row appears when implied_probability is non-null
 */
export function adaptPegasusPickToSmartPick(p: PEGASUSPick): SmartPick {
  return {
    // Core identity
    player_name:  p.player_name,
    team:         p.team,
    opponent:     '',           // PEGASUS doesn't include opponent; matchup shows team
    prop_type:    p.prop,
    pp_line:      p.line,
    pp_odds_type: p.odds_type,
    leg_value:    LEG_VALUE[p.odds_type] ?? 1.0,
    our_line:     p.line,

    // Predictions — always use calibrated probability as primary display
    pp_probability:  p.calibrated_probability,
    our_probability: p.calibrated_probability,
    prediction:      p.direction,

    // Edge + tier
    edge: p.ai_edge,
    tier: p.tier,

    // EV (parlay EV fields not available from PEGASUS — default 0)
    ev_2leg: 0,
    ev_3leg: 0,
    ev_4leg: 0,
    ev_5leg: 0,
    ev_6leg: 0,

    // Game context (not in PEGASUS picks)
    game_time: undefined,
    game_state: undefined,
    matchup:   p.team,          // Show team as matchup label when no opponent

    // Profitability fields — not in PEGASUS
    sigma_distance:         0,
    parlay_score:           0,
    line_movement:          0,
    movement_agrees:        false,
    calibration_correction: 0,

    // PEGASUS enrichment — surfaced in PickCard when present
    calibrated_probability: p.calibrated_probability,
    implied_probability:    p.implied_probability,
    situation_flag:         p.situation_flag,
    situation_notes:        p.situation_notes,
    true_ev:                p.true_ev,
    model_version:          p.model_version,
    pegasus_source:         true,
  };
}

/**
 * Fetch PEGASUS picks and adapt to SmartPick format.
 * Throws on network failure or timeout — caller handles fallback.
 */
export async function fetchSmartPicksFromPegasus(
  sport: string,
  options: {
    minTier?:   string;
    direction?: string;
    limit?:     number;
    date?:      string;
  } = {}
): Promise<SmartPick[]> {
  const raw = await fetchPegasusPicksRaw({
    sport: sport.toLowerCase(),
    minTier:   options.minTier,
    direction: options.direction,
    limit:     options.limit ?? 200,
    date:      options.date,
  });
  return raw.map(adaptPegasusPickToSmartPick);
}
