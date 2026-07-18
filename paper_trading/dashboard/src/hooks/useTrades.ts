import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { z } from 'zod'
import { fetchApi } from '../lib/api'
import { addErrorBreadcrumb } from '../lib/errorReporting'
import { TradeEntrySchema } from '../lib/schemas'

export type TradeEntry = z.infer<typeof TradeEntrySchema>

async function fetchTrades(limit: number, offset: number): Promise<TradeEntry[]> {
  const qs = new URLSearchParams()
  if (limit) qs.set('limit', String(limit))
  if (offset) qs.set('offset', String(offset))
  const json = await fetchApi<unknown>(`/trades.json?${qs}`)
  const parsed = z.array(TradeEntrySchema).safeParse(json)
  if (!parsed.success) {
    console.error('[Trades] validation failed:', parsed.error.issues)
    addErrorBreadcrumb('Trades', 'Validation failed')
    throw new Error('Invalid trades data from server')
  }
  return parsed.data
}

// createApiQuery not used here because query params (limit, offset) are dynamic
// and the factory hardcodes a single queryKey — pagination requires
// ['trades', limit, offset] to cache each page independently.

/** Fetches paginated trade entries. @returns {object} - React Query result with TradeEntry array */
export function useTrades(limit = 10, offset = 0) {
  return useQuery({
    queryKey: ['trades', limit, offset],
    queryFn: () => fetchTrades(limit, offset),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
    staleTime: 50_000,
  })
}
