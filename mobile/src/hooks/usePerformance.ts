import { useState, useEffect, useCallback } from 'react';
import { fetchPerformance, PerformanceOverview } from '../services/api';

interface UsePerformanceResult {
  data: PerformanceOverview | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function usePerformance(sport: string, days: number = 14): UsePerformanceResult {
  const [data, setData] = useState<PerformanceOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await fetchPerformance(sport, days);
      setData(response);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch performance data');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [sport, days]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
}
