import { create } from 'zustand';
import { supabase } from '../services/supabase';
import type { WatchlistItem } from '../types/supabase';

const MAX_WATCHLIST = 10;

interface WatchlistState {
  items: WatchlistItem[];
  loading: boolean;

  fetchWatchlist: () => Promise<void>;
  addPlayer: (playerName: string, sport: string) => Promise<void>;
  removePlayer: (id: string) => Promise<void>;
  reorder: (items: WatchlistItem[]) => Promise<void>;
  isWatched: (playerName: string, sport: string) => boolean;
  canAdd: () => boolean;
}

export const useWatchlistStore = create<WatchlistState>((set, get) => ({
  items: [],
  loading: false,

  fetchWatchlist: async () => {
    set({ loading: true });
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.user) return;

      const { data, error } = await supabase
        .from('watchlist')
        .select('*')
        .eq('user_id', session.user.id)
        .order('position', { ascending: true });

      if (error) throw error;
      set({ items: (data || []) as WatchlistItem[] });
    } catch (error) {
      console.error('Fetch watchlist error:', error);
    } finally {
      set({ loading: false });
    }
  },

  addPlayer: async (playerName: string, sport: string) => {
    const { items } = get();
    if (items.length >= MAX_WATCHLIST) {
      throw new Error(`Watchlist is full (max ${MAX_WATCHLIST} players)`);
    }

    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.user) throw new Error('Not authenticated');

      const { error } = await supabase
        .from('watchlist')
        .insert({
          user_id: session.user.id,
          player_name: playerName,
          sport: sport.toUpperCase(),
          position: items.length,
        });

      if (error) throw error;
      await get().fetchWatchlist();
    } catch (error) {
      console.error('Add to watchlist error:', error);
      throw error;
    }
  },

  removePlayer: async (id: string) => {
    try {
      const { error } = await supabase
        .from('watchlist')
        .delete()
        .eq('id', id);

      if (error) throw error;
      await get().fetchWatchlist();
    } catch (error) {
      console.error('Remove from watchlist error:', error);
      throw error;
    }
  },

  reorder: async (items: WatchlistItem[]) => {
    set({ items });
    // Update positions in background
    for (let i = 0; i < items.length; i++) {
      await supabase
        .from('watchlist')
        .update({ position: i })
        .eq('id', items[i].id);
    }
  },

  isWatched: (playerName: string, sport: string) => {
    const { items } = get();
    return items.some(
      i => i.player_name.toLowerCase() === playerName.toLowerCase() &&
           i.sport.toUpperCase() === sport.toUpperCase()
    );
  },

  canAdd: () => get().items.length < MAX_WATCHLIST,
}));
