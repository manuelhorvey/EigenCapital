import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import { QUERY_KEYS } from '../lib/queryKeys'
import type { ExecutionQualityResponse, SlippageDistribution } from '../types/execution'
import type { AttributionSummary, AttributionWaterfall } from '../types/attribution'

export interface AttributionBundleData {
  executionQuality: ExecutionQualityResponse | null
  executionSlippage: SlippageDistribution | null
  attributionSummary: AttributionSummary | null
  attributionWaterfall: AttributionWaterfall | null
}

/** Fetches execution quality, slippage, and attribution summary/waterfall data in parallel. @returns {object} - React Query result with AttributionBundleData */
export function useAttributionBundle() {
  return useQuery({
    queryKey: QUERY_KEYS.attribution,
    queryFn: async (): Promise<AttributionBundleData> => {
      // Fetch all endpoints concurrently. If an endpoint fails, return null.
      // If ALL 4 fail, throw so React Query's retry logic handles the total failure.
      const fetchOrNull = <T>(url: string) =>
        fetchApi<T>(url).catch(() => null as T | null)

      const [quality, slippage, summary, waterfall] = await Promise.all([
        fetchOrNull<ExecutionQualityResponse>('/execution/quality.json'),
        fetchOrNull<SlippageDistribution>('/execution/slippage.json'),
        fetchOrNull<AttributionSummary>('/attribution/summary.json'),
        fetchOrNull<AttributionWaterfall>('/attribution/waterfall.json'),
      ])

      // If all 4 endpoints failed, throw so React Query's outer retry kicks in
      if (quality === null && slippage === null && summary === null && waterfall === null) {
        throw new Error('All attribution endpoints failed')
      }

      return {
        executionQuality: quality,
        executionSlippage: slippage,
        attributionSummary: summary,
        attributionWaterfall: waterfall,
      }
    },
    refetchInterval: 60_000,
    staleTime: 50_000,
    retry: 1,
  })
}
