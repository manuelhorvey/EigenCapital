import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import { addErrorBreadcrumb } from '../lib/errorReporting'
import { DeepDiveDataSchema } from '../lib/schemas'
import type { z } from 'zod'

export type DeepDiveData = z.infer<typeof DeepDiveDataSchema>
export type TradeEntry = DeepDiveData['trades'][number]
export type FeatureImportance = DeepDiveData['feature_importance'][number]

/** Fetches detailed asset-specific data including trades and feature importance. @returns {object} - React Query result with DeepDiveData */
export function useAssetDeepDive(name: string) {
  return useQuery({
    queryKey: ['assetDeepDive', name],
    queryFn: async () => {
      const json = await fetchApi<unknown>(`/asset/${name}.json`)
      const parsed = DeepDiveDataSchema.safeParse(json)
      if (!parsed.success) {
        console.error('[DeepDive] validation failed:', parsed.error.issues)
        addErrorBreadcrumb('DeepDive', `Validation failed for ${name}`)
        return { asset: name, feature_importance: [], trades: [], final_signal: null, sell_only: false, tripwire_active: false, last_signal: null, metrics: null }
      }
      return parsed.data
    },
    enabled: !!name,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  })
}
