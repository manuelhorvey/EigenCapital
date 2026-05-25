import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { EquityHistoryPointSchema } from '../lib/schemas'
import { useMarketClosed } from './useMarketClosed'

export type EquityHistoryPoint = z.infer<typeof EquityHistoryPointSchema>

async function fetchEquityHistory(): Promise<EquityHistoryPoint[]> {
  const res = await fetch('/equity_history.json')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  const parsed = z.array(EquityHistoryPointSchema).safeParse(json)
  if (!parsed.success) {
    console.error('[EquityHistory] validation failed:', parsed.error.issues)
    throw new Error('Invalid equity history data from server')
  }
  return parsed.data
}

export function useEquityHistory() {
  const closed = useMarketClosed()
  return useQuery({
    queryKey: ['equityHistory'],
    queryFn: fetchEquityHistory,
    refetchInterval: closed ? 300_000 : 60_000,
    staleTime: closed ? 290_000 : 50_000,
  })
}
