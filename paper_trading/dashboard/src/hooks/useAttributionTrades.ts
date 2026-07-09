import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { z } from 'zod'
import { fetchApi } from '../lib/api'
import { addErrorBreadcrumb } from '../lib/errorReporting'
import { TradeAttributionRecordSchema } from '../lib/schemas'

export type TradeAttributionRecord = z.infer<typeof TradeAttributionRecordSchema>

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
  const json = await fetchApi<unknown>(`/attribution/trades.json?${qs}`)
  const parsed = z.array(TradeAttributionRecordSchema).safeParse(json)
  if (!parsed.success) {
    console.error('[AttributionTrades] validation failed:', parsed.error.issues)
    addErrorBreadcrumb('AttributionTrades', 'Validation failed')
    throw new Error('Invalid attribution trade data from server')
  }
  return parsed.data
}

/** Fetches paginated attribution trades with optional archetype/regime/asset filters. */
export function useAttributionTrades(
  limit = 50,
  offset = 0,
  filters?: { archetype?: string; regime?: string; asset?: string },
) {
  return useQuery({
    queryKey: ['attributionTrades', limit, offset, filters],
    queryFn: () => fetchAttributionTrades(limit, offset, filters),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
    staleTime: 50_000,
  })
}