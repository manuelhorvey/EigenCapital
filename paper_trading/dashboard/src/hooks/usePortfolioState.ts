import { useQuery } from '@tanstack/react-query'
import type { EngineSnapshot } from '../types/portfolio'

async function fetchState(): Promise<EngineSnapshot> {
  const res = await fetch('/state.json')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  if (typeof json !== 'object' || json === null || !json.assets || typeof json.assets !== 'object') {
    console.error('[State] top-level validation failed: missing assets or invalid shape')
    throw new Error('Invalid state data from server')
  }
  return json as EngineSnapshot
}

export function usePortfolioState() {
  return useQuery({
    queryKey: ['portfolioState'],
    queryFn: fetchState,
    refetchInterval: (q) => {
      const d = q.state.data
      return d?.engine_status?.market_closed ? 120_000 : 30_000
    },
    staleTime: (q) => {
      const d = q.state.data
      return d?.engine_status?.market_closed ? 110_000 : 25_000
    },
  })
}
