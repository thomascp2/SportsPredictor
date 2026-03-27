import { create } from 'zustand';
import { ParlayPick, calculateParlay, ParlayResult } from '../utils/calculations';
import { SmartPick } from '../services/api';

interface ParlayState {
  picks: ParlayPick[];
  result: ParlayResult | null;
  stakeAmount: number;

  // Actions
  addPick: (pick: SmartPick) => void;
  removePick: (pickId: string) => void;
  clearPicks: () => void;
  updatePickOddsType: (pickId: string, oddsType: 'goblin' | 'standard' | 'demon') => void;
  setStakeAmount: (amount: number) => void;
}

function generatePickId(pick: SmartPick): string {
  return `${pick.player_name}-${pick.prop_type}-${pick.pp_line}`.replace(/\s+/g, '-').toLowerCase();
}

function smartPickToParlayPick(pick: SmartPick): ParlayPick {
  return {
    id: generatePickId(pick),
    playerName: pick.player_name,
    propType: pick.prop_type,
    line: pick.pp_line,
    prediction: pick.prediction,
    probability: pick.pp_probability,
    oddsType: (pick.pp_odds_type || 'standard') as 'goblin' | 'standard' | 'demon',
  };
}

export const useParlayStore = create<ParlayState>((set, get) => ({
  picks: [],
  result: null,
  stakeAmount: 10,

  addPick: (smartPick: SmartPick) => {
    const pick = smartPickToParlayPick(smartPick);
    const currentPicks = get().picks;

    // Check if already added
    if (currentPicks.some(p => p.id === pick.id)) {
      return;
    }

    const newPicks = [...currentPicks, pick];
    const result = newPicks.length >= 2 ? calculateParlay(newPicks) : null;

    set({ picks: newPicks, result });
  },

  removePick: (pickId: string) => {
    const newPicks = get().picks.filter(p => p.id !== pickId);
    const result = newPicks.length >= 2 ? calculateParlay(newPicks) : null;

    set({ picks: newPicks, result });
  },

  clearPicks: () => {
    set({ picks: [], result: null });
  },

  updatePickOddsType: (pickId: string, oddsType: 'goblin' | 'standard' | 'demon') => {
    const newPicks = get().picks.map(p =>
      p.id === pickId ? { ...p, oddsType } : p
    );
    const result = newPicks.length >= 2 ? calculateParlay(newPicks) : null;

    set({ picks: newPicks, result });
  },

  setStakeAmount: (amount: number) => {
    set({ stakeAmount: Math.max(1, amount) });
  },
}));
