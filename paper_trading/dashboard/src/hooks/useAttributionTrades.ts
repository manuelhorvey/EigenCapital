import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import type { TradeAttributionRecord } from '../types/attribution'

async function fetchAttributionTrades(
  limit: number,
  offset: number,
  filters?: { archetype?: string; regime?: string; asset?: string },
): Promise<TradeAttributionRecord[]> {
  const qs = new URLSearchParams()
  qs.set('limit', String(limit))
  qs.set('offset', String(offset))
  if (filters?.archetype) qs.set('archetype', filters.archetype)
  if (filters?.regime) qs.set('regime', filters.regime)
  if (filters?.asset) qs.set('asset', filters.asset)
  return fetchApi<TradeAttributionRecord[]>(`/attribution/trades.json?${qs}`)
}

/** Fetches paginated attribution trades with optional archetype/regime/asset filters. @returns {object} - React Query result with TradeAttributionRecord array */
export function useAttributionTrades(
  limit = 50,
  offset = 0,
  filters?: { archetype?: string; regime?: string; asset?: string },
) {
  return useQuery({
    queryKey: ['attributionTrades', limit, offset, filters],
    queryFn: () => fetchAttributionTrades(limit, offset, filters),
    refetchInterval: 60_000,
    staleTime: 50_000,
  })
}
