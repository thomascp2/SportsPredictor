import { create } from 'zustand';
import { supabase, getTodayDate } from '../services/supabase';
import type { DailyProp, UserPick } from '../types/supabase';
import type { Sport } from '../utils/constants';

interface PicksState {
  props: DailyProp[];
  userPicks: Record<string, UserPick>; // keyed by prop_id
  sport: Sport;
  loading: boolean;
  error: string | null;
  todayStats: { total: number; hits: number; pending: number };

  setSport: (sport: Sport) => void;
  fetchTodayProps: () => Promise<void>;
  fetchUserPicks: () => Promise<void>;
  makePick: (propId: string, prediction: 'OVER' | 'UNDER') => Promise<void>;
  refreshAll: () => Promise<void>;
}

export const usePicksStore = create<PicksState>((set, get) => ({
  props: [],
  userPicks: {},
  sport: 'NBA',
  loading: false,
  error: null,
  todayStats: { total: 0, hits: 0, pending: 0 },

  setSport: (sport: Sport) => {
    set({ sport });
    get().refreshAll();
  },

  fetchTodayProps: async () => {
    const { sport } = get();
    set({ loading: true, error: null });

    try {
      const today = getTodayDate();
      const { data, error } = await supabase
        .from('daily_props')
        .select('*')
        .eq('game_date', today)
        .eq('sport', sport)
        .order('ai_edge', { ascending: false, nullsFirst: false });

      if (error) throw error;
      set({ props: (data || []) as DailyProp[] });
    } catch (error) {
      set({ error: (error as Error).message });
    } finally {
      set({ loading: false });
    }
  },

  fetchUserPicks: async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.user) return;

      const today = getTodayDate();
      const { data, error } = await supabase
        .from('user_picks')
        .select('*, prop:daily_props(*)')
        .eq('user_id', session.user.id)
        .gte('picked_at', `${today}T00:00:00`);

      if (error) throw error;

      const picksMap: Record<string, UserPick> = {};
      let hits = 0;
      let pending = 0;
      for (const pick of (data || [])) {
        picksMap[pick.prop_id] = pick as UserPick;
        if (pick.outcome === 'HIT') hits++;
        if (!pick.outcome) pending++;
      }

      set({
        userPicks: picksMap,
        todayStats: { total: data?.length || 0, hits, pending },
      });
    } catch (error) {
      console.error('Fetch user picks error:', error);
    }
  },

  makePick: async (propId: string, prediction: 'OVER' | 'UNDER') => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.user) throw new Error('Not authenticated');

      // Check if prop is still open
      const { props } = get();
      const prop = props.find(p => p.id === propId);
      if (!prop || prop.status !== 'open') {
        throw new Error('This prop is no longer available for picks');
      }

      // Upsert the pick
      const { data, error } = await supabase
        .from('user_picks')
        .upsert({
          user_id: session.user.id,
          prop_id: propId,
          prediction,
          picked_at: new Date().toISOString(),
        }, { onConflict: 'user_id,prop_id' })
        .select()
        .single();

      if (error) throw error;

      // Update community vote count
      await supabase.rpc('increment_vote', {
        prop_id: propId,
        vote: prediction,
      });

      // Update local state
      const { userPicks } = get();
      set({
        userPicks: { ...userPicks, [propId]: data as UserPick },
      });

      // Refresh to get updated vote counts
      get().fetchTodayProps();
    } catch (error) {
      console.error('Make pick error:', error);
      throw error;
    }
  },

  refreshAll: async () => {
    await Promise.all([
      get().fetchTodayProps(),
      get().fetchUserPicks(),
    ]);
  },
}));
