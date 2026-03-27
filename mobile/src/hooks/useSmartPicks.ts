import { useState, useEffect, useCallback } from 'react';
import { fetchSmartPicks, SmartPick, SmartPicksResponse, SortOption } from '../services/api';

interface UseSmartPicksOptions {
  sortBy?: SortOption;
  tier?: string;
  prediction?: string;
  hideStarted?: boolean;
}

interface UseSmartPicksResult {
  picks: SmartPick[];
  summary: SmartPicksResponse['summary'] | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function useSmartPicks(
  sport: string,
  options: UseSmartPicksOptions = {}
): UseSmartPicksResult {
  const [picks, setPicks] = useState<SmartPick[]>([]);
  const [summary, setSummary] = useState<SmartPicksResponse['summary'] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchSmartPicks(sport, {
        sortBy: options.sortBy,
        tier: options.tier,
        prediction: options.prediction,
        hideStarted: options.hideStarted ?? true,
      });
      setPicks(data.picks || []);
      setSummary(data.summary);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch picks');
      setPicks([]);
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [sport, options.sortBy, options.tier, options.prediction, options.hideStarted]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { picks, summary, loading, error, refetch: fetchData };
}
