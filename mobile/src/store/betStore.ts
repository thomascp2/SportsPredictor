import { create } from 'zustand';
import { supabase } from '../services/supabase';
import type { UserBet, BetLeg } from '../types/supabase';

interface BetStats {
  totalBets: number;
  wonBets: number;
  lostBets: number;
  pendingBets: number;
  totalStaked: number;
  totalPayout: number;
  netPL: number;
}

interface BetState {
  bets: UserBet[];
  stats: BetStats;
  loading: boolean;
  filter: 'all' | 'pending' | 'won' | 'lost';

  setFilter: (filter: BetState['filter']) => void;
  fetchBets: () => Promise<void>;
  addBet: (bet: {
    sport: string;
    sportsbook: string;
    bet_type: 'single' | 'parlay' | 'flex';
    stake: number;
    potential_payout: number;
    legs: BetLeg[];
    notes?: string;
  }) => Promise<void>;
  updateBetStatus: (betId: string, status: 'won' | 'lost' | 'push', actualPayout?: number) => Promise<void>;
  deleteBet: (betId: string) => Promise<void>;
}

function computeStats(bets: UserBet[]): BetStats {
  const totalBets = bets.length;
  const wonBets = bets.filter(b => b.status === 'won').length;
  const lostBets = bets.filter(b => b.status === 'lost').length;
  const pendingBets = bets.filter(b => b.status === 'pending').length;
  const totalStaked = bets.reduce((sum, b) => sum + (b.stake || 0), 0);
  const totalPayout = bets
    .filter(b => b.status === 'won')
    .reduce((sum, b) => sum + (b.actual_payout || b.potential_payout || 0), 0);
  const totalLost = bets
    .filter(b => b.status === 'lost')
    .reduce((sum, b) => sum + (b.stake || 0), 0);

  return {
    totalBets,
    wonBets,
    lostBets,
    pendingBets,
    totalStaked,
    totalPayout,
    netPL: totalPayout - totalLost,
  };
}

export const useBetStore = create<BetState>((set, get) => ({
  bets: [],
  stats: { totalBets: 0, wonBets: 0, lostBets: 0, pendingBets: 0, totalStaked: 0, totalPayout: 0, netPL: 0 },
  loading: false,
  filter: 'all',

  setFilter: (filter) => set({ filter }),

  fetchBets: async () => {
    set({ loading: true });
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.user) return;

      const { data, error } = await supabase
        .from('user_bets')
        .select('*')
        .eq('user_id', session.user.id)
        .order('placed_at', { ascending: false })
        .limit(100);

      if (error) throw error;

      const bets = (data || []) as UserBet[];
      set({ bets, stats: computeStats(bets) });
    } catch (error) {
      console.error('Fetch bets error:', error);
    } finally {
      set({ loading: false });
    }
  },

  addBet: async (bet) => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.user) throw new Error('Not authenticated');

      const { error } = await supabase
        .from('user_bets')
        .insert({
          user_id: session.user.id,
          ...bet,
        });

      if (error) throw error;
      await get().fetchBets();
    } catch (error) {
      console.error('Add bet error:', error);
      throw error;
    }
  },

  updateBetStatus: async (betId, status, actualPayout) => {
    try {
      const updateData: Record<string, unknown> = {
        status,
        settled_at: new Date().toISOString(),
      };
      if (actualPayout !== undefined) {
        updateData.actual_payout = actualPayout;
      }

      const { error } = await supabase
        .from('user_bets')
        .update(updateData)
        .eq('id', betId);

      if (error) throw error;
      await get().fetchBets();
    } catch (error) {
      console.error('Update bet error:', error);
      throw error;
    }
  },

  deleteBet: async (betId) => {
    try {
      const { error } = await supabase
        .from('user_bets')
        .delete()
        .eq('id', betId);

      if (error) throw error;
      await get().fetchBets();
    } catch (error) {
      console.error('Delete bet error:', error);
      throw error;
    }
  },
}));
