import { useQuery } from '@tanstack/react-query'

export interface ArchetypeStats {
  by_archetype: Record<string, {
    n: number
    avg_r: number
    win_rate: number
    tp_rate: number
    sl_rate: number
    avg_mae: number
    avg_mfe: number
    avg_entry_slippage_bps: number
    avg_bars_held: number
  }>
}

async function fetchArchetypeStats(): Promise<ArchetypeStats> {
  const res = await fetch('/archetype/stats.json')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function useArchetypeStats() {
  return useQuery({
    queryKey: ['archetypeStats'],
    queryFn: fetchArchetypeStats,
    refetchInterval: 120_000,
    staleTime: 100_000,
  })
}
