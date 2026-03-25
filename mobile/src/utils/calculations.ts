import { PAYOUTS, LEG_VALUES, BREAK_EVEN_RATES } from './constants';

export interface ParlayPick {
  id: string;
  playerName?: string;
  propType?: string;
  line?: number;
  prediction?: 'OVER' | 'UNDER';
  probability: number;
  oddsType: 'goblin' | 'standard' | 'demon';
}

export interface ParlayResult {
  totalLegValue: number;
  combinedProbability: number;
  combinedProbabilityPct: string;
  payoutMultiplier: number;
  expectedValue: number;
  evPercentage: number;
  isPositiveEV: boolean;
  breakEvenProbability: number;
  edge: number;
  edgePct: string;
  recommendation: string;
}

/**
 * Calculate total leg value for a parlay
 */
export function calculateTotalLegValue(picks: ParlayPick[]): number {
  return picks.reduce((total, pick) => {
    return total + (LEG_VALUES[pick.oddsType] || 1.0);
  }, 0);
}

/**
 * Calculate combined probability (multiply all individual probs)
 */
export function calculateCombinedProbability(picks: ParlayPick[]): number {
  return picks.reduce((prob, pick) => prob * pick.probability, 1);
}

/**
 * Interpolate payout for fractional leg values
 * e.g., 3.5 legs = halfway between 3-leg (5x) and 4-leg (10x) = 7.5x
 *
 * PrizePicks requires minimum 2 legs for a payout.
 * For < 2 legs, we interpolate down from 2-leg payout to 1x (no gain).
 */
export function interpolatePayout(totalLegValue: number): number {
  const legs = Array.from(Object.keys(PAYOUTS)).map(Number).sort((a, b) => a - b);
  const minLegs = legs[0]; // 2

  // For < 2 legs, interpolate between 1x (at 0 legs) and 3x (at 2 legs)
  // This reflects that you don't get full payout for incomplete parlays
  if (totalLegValue < minLegs) {
    // Linear interpolation: 0 legs = 1x, 2 legs = 3x
    const fraction = totalLegValue / minLegs;
    return 1 + fraction * (PAYOUTS[minLegs] - 1);
  }

  if (totalLegValue >= legs[legs.length - 1]) return PAYOUTS[legs[legs.length - 1]];

  // Find surrounding legs
  let lowerLeg = legs[0];
  let upperLeg = legs[legs.length - 1];

  for (let i = 0; i < legs.length - 1; i++) {
    if (totalLegValue >= legs[i] && totalLegValue <= legs[i + 1]) {
      lowerLeg = legs[i];
      upperLeg = legs[i + 1];
      break;
    }
  }

  // Linear interpolation
  const fraction = (totalLegValue - lowerLeg) / (upperLeg - lowerLeg);
  return PAYOUTS[lowerLeg] + fraction * (PAYOUTS[upperLeg] - PAYOUTS[lowerLeg]);
}

/**
 * Get recommendation based on EV percentage
 */
export function getRecommendation(evPercentage: number): string {
  if (evPercentage >= 50) return 'EXCELLENT VALUE';
  if (evPercentage >= 30) return 'STRONG VALUE';
  if (evPercentage >= 10) return 'GOOD VALUE';
  if (evPercentage >= 0) return 'SLIGHT VALUE';
  if (evPercentage >= -10) return 'MARGINAL';
  return 'AVOID';
}

/**
 * Calculate full parlay details
 */
export function calculateParlay(picks: ParlayPick[]): ParlayResult {
  if (picks.length < 2) {
    return {
      totalLegValue: 0,
      combinedProbability: 0,
      combinedProbabilityPct: '0.00%',
      payoutMultiplier: 0,
      expectedValue: -1,
      evPercentage: -100,
      isPositiveEV: false,
      breakEvenProbability: 1,
      edge: -1,
      edgePct: '-100.00%',
      recommendation: 'Need at least 2 picks',
    };
  }

  const totalLegValue = calculateTotalLegValue(picks);
  const combinedProbability = calculateCombinedProbability(picks);
  const payoutMultiplier = interpolatePayout(totalLegValue);
  const expectedValue = (combinedProbability * payoutMultiplier) - 1;
  const evPercentage = expectedValue * 100;
  const breakEvenProbability = 1 / payoutMultiplier;
  const edge = combinedProbability - breakEvenProbability;

  return {
    totalLegValue: Math.round(totalLegValue * 10) / 10,
    combinedProbability,
    combinedProbabilityPct: `${(combinedProbability * 100).toFixed(2)}%`,
    payoutMultiplier: Math.round(payoutMultiplier * 10) / 10,
    expectedValue,
    evPercentage: Math.round(evPercentage * 10) / 10,
    isPositiveEV: expectedValue > 0,
    breakEvenProbability,
    edge,
    edgePct: `${(edge * 100).toFixed(2)}%`,
    recommendation: getRecommendation(evPercentage),
  };
}

/**
 * Calculate required probability for positive EV
 */
export function requiredProbabilityForPositiveEV(totalLegValue: number): number {
  const payout = interpolatePayout(totalLegValue);
  return 1 / payout;
}

/**
 * Format probability as percentage
 */
export function formatProbability(prob: number): string {
  return `${(prob * 100).toFixed(1)}%`;
}

/**
 * Format edge/EV with sign
 */
export function formatEV(ev: number): string {
  const sign = ev >= 0 ? '+' : '';
  return `${sign}${ev.toFixed(1)}%`;
}
