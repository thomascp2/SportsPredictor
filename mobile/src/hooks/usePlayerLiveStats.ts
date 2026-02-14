import { useState, useEffect, useCallback, useMemo } from 'react';
import { supabase, getTodayDate } from '../services/supabase';
import type { DailyProp, DailyGame, WatchlistItem } from '../types/supabase';

interface PlayerLiveData {
  playerName: string;
  team: string;
  sport: string;
  game?: DailyGame;
  props: DailyProp[];
}

/**
 * Hook for fetching live stats and props for watched players.
 * Combines daily_games and daily_props data for the watchlist.
 */
export function usePlayerLiveStats(watchlistItems: WatchlistItem[], sport: string) {
  const [games, setGames] = useState<DailyGame[]>([]);
  const [allProps, setAllProps] = useState<DailyProp[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    if (watchlistItems.length === 0) {
      setLoading(false);
      return;
    }

    const today = getTodayDate();
    const sportUpper = sport.toUpperCase();

    try {
      const [gamesRes, propsRes] = await Promise.all([
        supabase
          .from('daily_games')
          .select('*')
          .eq('game_date', today)
          .eq('sport', sportUpper),
        supabase
          .from('daily_props')
          .select('*')
          .eq('game_date', today)
          .eq('sport', sportUpper)
          .in('player_name', watchlistItems.filter(w => w.sport.toUpperCase() === sportUpper).map(w => w.player_name)),
      ]);

      if (gamesRes.data) setGames(gamesRes.data as DailyGame[]);
      if (propsRes.data) setAllProps(propsRes.data as DailyProp[]);
    } catch (error) {
      console.error('usePlayerLiveStats fetch error:', error);
    } finally {
      setLoading(false);
    }
  }, [watchlistItems, sport]);

  useEffect(() => {
    fetchData();

    // Refresh every 60s during games
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Build player data map
  const playerData: PlayerLiveData[] = useMemo(() => {
    const sportUpper = sport.toUpperCase();
    return watchlistItems
      .filter(w => w.sport.toUpperCase() === sportUpper)
      .map(item => {
        const playerProps = allProps.filter(
          p => p.player_name === item.player_name
        );

        // Find game where player's team is playing
        const team = playerProps[0]?.team || '';
        const game = games.find(
          g => g.home_team === team || g.away_team === team
        );

        return {
          playerName: item.player_name,
          team,
          sport: item.sport,
          game,
          props: playerProps,
        };
      });
  }, [watchlistItems, allProps, games, sport]);

  return { playerData, loading, refresh: fetchData };
}
