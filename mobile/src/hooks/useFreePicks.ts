import { useEffect, useCallback } from 'react';
import { usePicksStore } from '../store/picksStore';
import { useAuthStore } from '../store/authStore';
import { supabase, getTodayDate } from '../services/supabase';

/**
 * Hook for FreePicks game logic.
 * Fetches today's props, manages user picks, subscribes to realtime updates.
 */
export function useFreePicks() {
  const {
    props, userPicks, sport, loading, error, todayStats, lastFetchedAt,
    setSport, fetchTodayProps, fetchUserPicks, makePick, refreshAll,
  } = usePicksStore();

  const { session, profile } = useAuthStore();

  // Initial fetch
  useEffect(() => {
    refreshAll();
  }, [sport, refreshAll]);

  // Subscribe to prop status changes (locking, grading)
  useEffect(() => {
    const today = getTodayDate();
    const channel = supabase
      .channel(`props-${sport}-${today}`)
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'daily_props',
          filter: `sport=eq.${sport}`,
        },
        () => {
          // Refresh when props are updated (locked, graded)
          fetchTodayProps();
        }
      )
      .subscribe();

    return () => {
      channel.unsubscribe();
    };
  }, [sport, fetchTodayProps]);

  // Subscribe to user pick grading
  useEffect(() => {
    if (!session?.user) return;

    const channel = supabase
      .channel(`picks-${session.user.id}`)
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'user_picks',
          filter: `user_id=eq.${session.user.id}`,
        },
        () => {
          fetchUserPicks();
        }
      )
      .subscribe();

    return () => {
      channel.unsubscribe();
    };
  }, [session, fetchUserPicks]);

  const handleMakePick = useCallback(async (propId: string, prediction: 'OVER' | 'UNDER') => {
    if (!session?.user) return;
    await makePick(propId, prediction);
  }, [session, makePick]);

  return {
    props,
    userPicks,
    sport,
    loading,
    error,
    todayStats,
    lastFetchedAt,
    isAuthenticated: !!session?.user,
    profile,
    setSport,
    makePick: handleMakePick,
    refresh: refreshAll,
  };
}
