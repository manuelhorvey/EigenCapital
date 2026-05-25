import { useQueryClient } from '@tanstack/react-query'
import { isMarketOpen, useSessionClock } from './useSessionClock'
import type { EngineSnapshot } from '../types/portfolio'

export function useMarketClosed(): boolean {
  const queryClient = useQueryClient()
  const data = queryClient.getQueryData<EngineSnapshot>(['portfolioState'])
  const { day, hour } = useSessionClock()

  const serverClosed = data?.engine_status?.market_closed
  if (serverClosed !== undefined) return serverClosed
  return !isMarketOpen(day, hour)
}
