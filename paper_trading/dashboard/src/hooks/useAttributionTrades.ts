import { useQuery } from '@tanstack/react-query'
import type { TradeAttributionRecord } from '../types/attribution'

interface AttributionFilter {
  limit?: number
  offset?: number
  archetype?: string
  regime?: string
  asset?: string
}

async function fetchAttributionTrades(params: AttributionFilter = {}): Promise<TradeAttributionRecord[]> {
  const qs = new URLSearchParams()
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.offset) qs.set('offset', String(params.offset))
  if (params.archetype) qs.set('archetype', params.archetype)
  if (params.regime) qs.set('regime', params.regime)
  if (params.asset) qs.set('asset', params.asset)
  const res = await fetch(`/attribution/trades.json?${qs}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function useAttributionTrades(limit = 50, offset = 0, filters?: { archetype?: string; regime?: string; asset?: string }) {
  return useQuery({
    queryKey: ['attributionTrades', limit, offset, filters],
    queryFn: () => fetchAttributionTrades({ limit, offset, ...filters }),
    refetchInterval: 60_000,
    staleTime: 50_000,
  })
}
