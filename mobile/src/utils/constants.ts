// API Configuration
// For local development (emulator): 'http://localhost:8000/api'
// For physical device: use your PC's IP address
export const API_BASE_URL = 'http://192.168.1.70:8000/api';

// Parlay Payout Multipliers by total leg value
export const PAYOUTS: Record<number, number> = {
  2: 3.0,
  3: 5.0,
  4: 10.0,
  5: 20.0,
  6: 25.0,
};

// How much each odds type counts toward total legs
export const LEG_VALUES: Record<string, number> = {
  goblin: 0.5,
  standard: 1.0,
  demon: 1.5,
};

// Break-even win rates per pick type
export const BREAK_EVEN_RATES: Record<string, number> = {
  goblin: 0.76,
  standard: 0.56,
  demon: 0.45,
};

// Tier colors for display
export const TIER_COLORS: Record<string, string> = {
  'T1-ELITE': '#FFD700',     // Gold
  'T2-STRONG': '#00FF00',    // Green
  'T3-GOOD': '#00BFFF',      // Light Blue
  'T4-LEAN': '#FFA500',      // Orange
  'T5-FADE': '#FF4444',      // Red
};

// EV color thresholds
export const EV_COLORS = {
  positive: '#00FF00',   // Green for +EV
  neutral: '#FFD700',    // Gold for neutral
  negative: '#FF4444',   // Red for -EV
};

// Sports
export const SPORTS = ['NBA', 'NHL'] as const;
export type Sport = typeof SPORTS[number];
