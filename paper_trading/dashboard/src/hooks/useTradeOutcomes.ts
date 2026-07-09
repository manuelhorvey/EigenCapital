import { keepPreviousData } from '@tanstack/react-query'
import { createApiQuery } from '../lib/api'
import { TradeOutcomesSchema } from '../lib/schemas'
import type { z } from 'zod'

export type TradeOutcomesData = z.infer<typeof TradeOutcomesSchema>

const useTradeOutcomesQuery = createApiQuery<TradeOutcomesData>('/trade-outcomes.json', TradeOutcomesSchema)

/** Fetches trade outcome summaries. */
export function useTradeOutcomes() {
  const { data, isPending, isError, error, refetch } = useTradeOutcomesQuery({
    refetchInterval: 30_000,
    staleTime: 25_000,
    placeholderData: keepPreviousData,
  })
  return { outcomes: data ?? null, isPending, isError, error, refetch }
}
