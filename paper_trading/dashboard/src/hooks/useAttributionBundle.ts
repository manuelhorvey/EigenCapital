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

export function useAttributionBundle() {
  return useQuery({
    queryKey: QUERY_KEYS.attribution,
    queryFn: async (): Promise<AttributionBundleData> => {
      const [quality, slippage, summary, waterfall] = await Promise.allSettled([
        fetchApi<ExecutionQualityResponse>('/execution/quality.json').catch(() => null),
        fetchApi<SlippageDistribution>('/execution/slippage.json').catch(() => null),
        fetchApi<AttributionSummary>('/attribution/summary.json').catch(() => null),
        fetchApi<AttributionWaterfall>('/attribution/waterfall.json').catch(() => null),
      ])

      return {
        executionQuality: quality.status === 'fulfilled' ? quality.value : null,
        executionSlippage: slippage.status === 'fulfilled' ? slippage.value : null,
        attributionSummary: summary.status === 'fulfilled' ? summary.value : null,
        attributionWaterfall: waterfall.status === 'fulfilled' ? waterfall.value : null,
      }
    },
    refetchInterval: 60_000,
    staleTime: 50_000,
    retry: 1,
  })
}
