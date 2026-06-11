import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import { EngineSnapshotSchema } from '../lib/schemas'
import type { EngineSnapshot } from '../types/portfolio'

export function usePortfolioState() {
  return useQuery({
    queryKey: ['portfolioState'],
    queryFn: async () => {
      const json = await fetchApi<unknown>('/state.json')
      const parsed = EngineSnapshotSchema.safeParse(json)
      if (!parsed.success) {
        console.error('[State] validation failed:', parsed.error.issues)
        throw new Error('Invalid state data from server')
      }
      return parsed.data as EngineSnapshot
    },
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
