import { keepPreviousData } from '@tanstack/react-query'
import { z } from 'zod'
import { createApiQuery } from '../lib/api'
import { EquityHistoryPointSchema } from '../lib/schemas'

export type EquityHistoryPoint = z.infer<typeof EquityHistoryPointSchema>

const useEquityHistoryQuery = createApiQuery<EquityHistoryPoint[]>('/equity_history.json', z.array(EquityHistoryPointSchema), 'equityHistory')

/** Fetches equity history data points. */
export function useEquityHistory() {
  return useEquityHistoryQuery({
    refetchInterval: 60_000,
    staleTime: 50_000,
    placeholderData: keepPreviousData,
  })
}
