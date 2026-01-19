import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchLiveScores, LiveGame, LiveScoresResponse } from '../services/api';

interface UseLiveScoresResult {
  games: LiveGame[];
  lastUpdated: string | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function useLiveScores(sport: string, refreshInterval: number = 30000): UseLiveScoresResult {
  const [games, setGames] = useState<LiveGame[]>([]);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchLiveScores(sport);
      setGames(data.games);
      setLastUpdated(data.last_updated);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch scores');
      setGames([]);
    } finally {
      setLoading(false);
    }
  }, [sport]);

  useEffect(() => {
    fetchData();

    // Set up auto-refresh
    if (refreshInterval > 0) {
      intervalRef.current = setInterval(fetchData, refreshInterval);
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [fetchData, refreshInterval]);

  return { games, lastUpdated, loading, error, refetch: fetchData };
}
