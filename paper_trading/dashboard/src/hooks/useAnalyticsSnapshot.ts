import { useQuery } from '@tanstack/react-query'

export interface AnalyticsSnapshot {
  overall: {
    n_trades: number
    avg_r: number
    win_rate: number
    tp_rate: number
    sl_rate: number
  }
  by_archetype: Record<string, {
    n: number
    avg_r: number
    win_rate: number
    tp_rate: number
    sl_rate: number
    avg_entry_slippage: number
    avg_mae: number
    avg_mfe: number
  }>
  by_regime: Record<string, {
    n: number
    avg_r: number
    win_rate: number
  }>
  shadow: {
    n: number
    divergence_rate: number
    avg_r_delta: number
  }
}

async function fetchAnalyticsSnapshot(): Promise<AnalyticsSnapshot> {
  const res = await fetch('/analytics/snapshot.json')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function useAnalyticsSnapshot() {
  return useQuery({
    queryKey: ['analyticsSnapshot'],
    queryFn: fetchAnalyticsSnapshot,
    refetchInterval: 30_000,
    staleTime: 25_000,
  })
}
