import { useQuery } from '@tanstack/react-query'
import type { ShadowTradeRecord } from '../types/shadow'

interface ShadowFilter {
  limit?: number
  offset?: number
  alt_label?: string
}

async function fetchShadowTrades(params: ShadowFilter = {}): Promise<ShadowTradeRecord[]> {
  const qs = new URLSearchParams()
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.offset) qs.set('offset', String(params.offset))
  if (params.alt_label) qs.set('alt_label', params.alt_label)
  const res = await fetch(`/shadow/trades.json?${qs}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function useShadowTrades(limit = 20, offset = 0, alt_label?: string) {
  return useQuery({
    queryKey: ['shadowTrades', limit, offset, alt_label],
    queryFn: () => fetchShadowTrades({ limit, offset, alt_label }),
    refetchInterval: 60_000,
    staleTime: 50_000,
  })
}
