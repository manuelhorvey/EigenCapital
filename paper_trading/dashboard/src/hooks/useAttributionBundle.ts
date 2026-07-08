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
      // fetch one endpoint with individual retry; reject only if ALL 4 fail
      // so React Query's outer retry is triggered only for total failures.
      async function fetchWithRetry<T>(url: string, retries = 2): Promise<T | null> {
        for (let i = 0; i <= retries; i++) {
          try {
            return await fetchApi<T>(url)
          } catch (err) {
            if (i < retries) continue
            console.warn(`[AttributionBundle] ${url} failed after ${retries + 1} attempts`)
            return null
          }
        }
        return null
      }

      const [quality, slippage, summary, waterfall] = await Promise.all([
        fetchWithRetry<ExecutionQualityResponse>('/execution/quality.json'),
        fetchWithRetry<SlippageDistribution>('/execution/slippage.json'),
        fetchWithRetry<AttributionSummary>('/attribution/summary.json'),
        fetchWithRetry<AttributionWaterfall>('/attribution/waterfall.json'),
      ])

      // If all 4 failed, throw so React Query's retry/gate logic can handle it
      if (quality === null && slippage === null && summary === null && waterfall === null) {
        throw new Error('All attribution endpoints failed')
      }

      return { executionQuality: quality, executionSlippage: slippage, attributionSummary: summary, attributionWaterfall: waterfall }
    },
    refetchInterval: 60_000,
    staleTime: 50_000,
    retry: 1,
  })
}
