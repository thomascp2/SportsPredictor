import { useState, useEffect, useCallback } from 'react';
import { supabase, getTodayDate } from '../services/supabase';
import type { DailyGame } from '../types/supabase';

/**
 * Hook for subscribing to live game scores via Supabase Realtime.
 * Falls back to polling if realtime not available.
 */
export function useSupabaseGames(sport: string, pollInterval = 30000) {
  const [games, setGames] = useState<DailyGame[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const fetchGames = useCallback(async () => {
    try {
      const today = getTodayDate();
      const { data, error: fetchError } = await supabase
        .from('daily_games')
        .select('*')
        .eq('game_date', today)
        .eq('sport', sport.toUpperCase())
        .order('start_time', { ascending: true });

      if (fetchError) throw fetchError;

      setGames((data || []) as DailyGame[]);
      setLastUpdated(new Date().toISOString());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [sport]);

  useEffect(() => {
    fetchGames();

    // Subscribe to realtime updates
    const today = getTodayDate();
    const channel = supabase
      .channel(`games-${sport}-${today}`)
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'daily_games',
          filter: `sport=eq.${sport.toUpperCase()}`,
        },
        (payload) => {
          const updated = payload.new as DailyGame;
          setGames(prev => {
            const idx = prev.findIndex(g => g.id === updated.id);
            if (idx >= 0) {
              const next = [...prev];
              next[idx] = updated;
              return next;
            }
            return [...prev, updated];
          });
          setLastUpdated(new Date().toISOString());
        }
      )
      .subscribe();

    // Also poll as fallback
    const interval = setInterval(fetchGames, pollInterval);

    return () => {
      channel.unsubscribe();
      clearInterval(interval);
    };
  }, [sport, pollInterval, fetchGames]);

  return { games, loading, error, lastUpdated, refetch: fetchGames };
}
