import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { fetchApi } from '../lib/api'
import { QUERY_KEYS } from '../lib/queryKeys'
import { addErrorBreadcrumb } from '../lib/errorReporting'
import {
  ExecutionQualityResponseSchema,
  SlippageDistributionSchema,
  AttributionSummaryResponseSchema,
  AttributionWaterfallResponseSchema,
} from '../lib/schemas'
import type { ExecutionQualityResponse, SlippageDistribution } from '../types/execution'
import type { AttributionSummary, AttributionWaterfall } from '../types/attribution'

export interface AttributionBundleData {
  executionQuality: ExecutionQualityResponse | null
  executionSlippage: SlippageDistribution | null
  attributionSummary: AttributionSummary | null
  attributionWaterfall: AttributionWaterfall | null
}

async function fetchWithSchema<T>(url: string, schema: z.ZodType<T>): Promise<T | null> {
  try {
    const json = await fetchApi<unknown>(url)
    const parsed = schema.safeParse(json)
    if (!parsed.success) {
      console.error(`[${url}] validation failed:`, parsed.error.issues)
      addErrorBreadcrumb('AttributionBundle', `Validation failed for ${url}`)
      return null
    }
    return parsed.data
  } catch {
    console.error(`[${url}] fetch failed — network error`)
    addErrorBreadcrumb('AttributionBundle', `Fetch failed: ${url}`)
    return null
  }
}

/** Fetches execution quality, slippage, and attribution summary/waterfall data in parallel with Zod validation. @returns {object} - React Query result with AttributionBundleData */
export function useAttributionBundle() {
  return useQuery({
    queryKey: QUERY_KEYS.attribution,
    queryFn: async (): Promise<AttributionBundleData> => {
      const [quality, slippage, summary, waterfall] = await Promise.all([
        fetchWithSchema('/execution/quality.json', ExecutionQualityResponseSchema),
        fetchWithSchema('/execution/slippage.json', SlippageDistributionSchema),
        fetchWithSchema('/attribution/summary.json', AttributionSummaryResponseSchema),
        fetchWithSchema('/attribution/waterfall.json', AttributionWaterfallResponseSchema),
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
