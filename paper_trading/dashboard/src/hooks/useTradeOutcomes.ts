import { createApiQuery } from '../lib/api'
import { TradeOutcomesSchema } from '../lib/schemas'
import type { z } from 'zod'

export type TradeOutcomesData = z.infer<typeof TradeOutcomesSchema>

const useTradeOutcomesQuery = createApiQuery<TradeOutcomesData>('/trade-outcomes.json', TradeOutcomesSchema)

/** Fetches trade outcome summaries. @returns {{ outcomes: TradeOutcomesData | null, isPending: boolean, isError: boolean, refetch: () => void }} - Outcomes data and query state */
export function useTradeOutcomes() {
  const { data, isPending, isError, refetch } = useTradeOutcomesQuery({
    refetchInterval: 30_000,
    staleTime: 25_000,
  })
  return { outcomes: data ?? null, isPending, isError, refetch }
}
