import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchSmartPicks, SmartPick, SmartPicksResponse, SortOption } from '../services/api';

const AUTO_REFRESH_MS = 5 * 60 * 1000; // 5 minutes

interface UseSmartPicksOptions {
  sortBy?: SortOption;
  tier?: string;
  prediction?: string;
  hideStarted?: boolean;
  /** Override auto-refresh interval in ms. Set 0 to disable. */
  refreshIntervalMs?: number;
}

interface UseSmartPicksResult {
  picks: SmartPick[];
  summary: SmartPicksResponse['summary'] | null;
  loading: boolean;
  error: string | null;
  lastFetchedAt: Date | null;
  minutesSinceRefresh: number | null;
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
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null);
  const [minutesSinceRefresh, setMinutesSinceRefresh] = useState<number | null>(null);

  // Tick timer to update "X min ago" display every 30s
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const intervalMs = options.refreshIntervalMs ?? AUTO_REFRESH_MS;

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
      const now = new Date();
      setLastFetchedAt(now);
      setMinutesSinceRefresh(0);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch picks');
      setPicks([]);
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [sport, options.sortBy, options.tier, options.prediction, options.hideStarted]);

  // Initial fetch + auto-refresh
  useEffect(() => {
    fetchData();

    if (intervalMs > 0) {
      const refreshTimer = setInterval(fetchData, intervalMs);
      return () => clearInterval(refreshTimer);
    }
  }, [fetchData, intervalMs]);

  // "X min ago" ticker — updates every 30 seconds
  useEffect(() => {
    if (!lastFetchedAt) return;

    const update = () => {
      const mins = (Date.now() - lastFetchedAt.getTime()) / 60000;
      setMinutesSinceRefresh(Math.floor(mins));
    };

    update();
    tickRef.current = setInterval(update, 30_000);
    return () => {
      if (tickRef.current) clearInterval(tickRef.current);
    };
  }, [lastFetchedAt]);

  return { picks, summary, loading, error, lastFetchedAt, minutesSinceRefresh, refetch: fetchData };
}
